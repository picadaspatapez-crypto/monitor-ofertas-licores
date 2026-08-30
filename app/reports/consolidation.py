from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from statistics import median

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models import (
    MasterProduct,
    MatchingReview,
    PriceObservation,
    Product,
    ProductMatch,
    ScrapeRun,
    Store,
)
from app.repositories.common import utcnow


EXPANSION_CONNECTOR_KEYS: tuple[str, ...] = (
    "lakoka",
    "elbrindis",
    "ranchowines",
    "licorescl",
    "centralvinos",
    "vinoslareina",
)


@dataclass(frozen=True)
class StoreConsolidationView:
    connector_key: str
    store_name: str
    registered: bool
    runs_considered: int
    healthy_runs: int
    degraded_runs: int
    failed_runs: int
    latest_health: str | None
    latest_products: int
    successful_counts: tuple[int, ...]
    product_spread_pct: float | None
    average_duration_ms: int
    near_timeout_runs: int
    active_products: int
    canonicalized_products: int
    quality_warnings: int
    quality_blocked: int
    unavailable_products: int
    accepted_near_threshold: int
    pending_match_reviews: int
    source: str | None
    verdict: str


@dataclass(frozen=True)
class ExpansionConsolidationAudit:
    verdict: str
    enough_history: bool
    stores: tuple[StoreConsolidationView, ...]
    extreme_price_gaps: tuple[tuple[str, int, int, float], ...]
    observations_last_7d: int
    observations_previous_7d: int
    database_size_mb: float | None

    @property
    def stable(self) -> bool:
        return self.verdict == "STABLE"


def _product_spread_pct(counts: list[int]) -> float | None:
    values = [int(value) for value in counts if int(value) > 0]
    if len(values) < 2:
        return None
    center = float(median(values))
    if center <= 0:
        return None
    return ((max(values) - min(values)) / center) * 100.0


def _source(run: ScrapeRun | None) -> str | None:
    if run is None or not isinstance(run.metrics_json, dict):
        return None
    value = run.metrics_json.get("discovery_source")
    return str(value) if value else None


def _store_verdict(
    *,
    registered: bool,
    runs_considered: int,
    required_runs: int,
    latest_health: str | None,
    healthy_runs: int,
    degraded_runs: int,
    failed_runs: int,
    spread_pct: float | None,
    active_products: int,
    canonicalized_products: int,
    quality_blocked: int,
) -> str:
    if not registered or runs_considered < required_runs:
        return "NOT_READY"
    if latest_health in {None, "BROKEN", "PAUSED"} or failed_runs:
        return "WATCH"
    canonical_ratio = (
        canonicalized_products / active_products if active_products > 0 else 0.0
    )
    blocked_ratio = quality_blocked / active_products if active_products > 0 else 1.0
    stable_spread = spread_pct is not None and spread_pct <= 12.0
    if (
        healthy_runs == runs_considered
        and degraded_runs == 0
        and stable_spread
        and canonical_ratio >= 0.98
        and blocked_ratio <= 0.01
    ):
        return "STABLE"
    return "WATCH"


def _database_size_mb(session: Session) -> float | None:
    bind = session.get_bind()
    if bind.dialect.name != "postgresql":
        return None
    try:
        size_bytes = session.scalar(text("SELECT pg_database_size(current_database())"))
        return round(float(size_bytes or 0) / (1024.0 * 1024.0), 1)
    except Exception:
        # El reporte nunca debe hacer fallar el pipeline por falta de permisos.
        return None


def _extreme_price_gaps(
    session: Session,
    *,
    expansion_store_ids: set[int],
    ratio_threshold: float = 2.5,
    limit: int = 5,
) -> tuple[tuple[str, int, int, float], ...]:
    rows = session.execute(
        select(
            Product.master_product_id,
            Product.store_id,
            Product.current_price,
            MasterProduct.canonical_name,
        )
        .join(Store, Store.id == Product.store_id)
        .join(MasterProduct, MasterProduct.id == Product.master_product_id)
        .where(
            Product.master_product_id.is_not(None),
            Product.current_price > 0,
            Product.is_available.is_(True),
            Product.excluded_from_comparison.is_(False),
            Store.is_active.is_(True),
            Store.comparison_enabled.is_(True),
        )
    ).all()
    grouped: dict[int, list[tuple[int, int, str]]] = {}
    for master_id, store_id, price, canonical_name in rows:
        if master_id is None or store_id is None:
            continue
        grouped.setdefault(int(master_id), []).append(
            (int(store_id), int(price), str(canonical_name))
        )

    anomalies: list[tuple[str, int, int, float]] = []
    for values in grouped.values():
        store_ids = {item[0] for item in values}
        if len(store_ids) < 2 or not (store_ids & expansion_store_ids):
            continue
        prices = [item[1] for item in values if item[1] >= 1000]
        if len(prices) < 2:
            continue
        low, high = min(prices), max(prices)
        ratio = high / low if low > 0 else 0.0
        if ratio >= ratio_threshold:
            anomalies.append((values[0][2], low, high, ratio))

    anomalies.sort(key=lambda item: (-item[3], item[0].casefold()))
    return tuple(anomalies[: max(1, limit)])


def build_expansion_consolidation_audit(
    session: Session,
    *,
    runs_per_store: int = 3,
    timeout_minutes: int = 25,
    match_threshold: float = 0.86,
) -> ExpansionConsolidationAudit:
    required_runs = max(2, int(runs_per_store))
    timeout_ms = max(1, int(timeout_minutes)) * 60 * 1000
    store_rows = list(
        session.scalars(
            select(Store)
            .where(Store.connector_key.in_(EXPANSION_CONNECTOR_KEYS))
            .order_by(Store.name)
        )
    )
    by_key = {store.connector_key: store for store in store_rows}
    views: list[StoreConsolidationView] = []
    expansion_store_ids: set[int] = {int(store.id) for store in store_rows}

    for key in EXPANSION_CONNECTOR_KEYS:
        store = by_key.get(key)
        if store is None:
            views.append(
                StoreConsolidationView(
                    connector_key=key,
                    store_name=key,
                    registered=False,
                    runs_considered=0,
                    healthy_runs=0,
                    degraded_runs=0,
                    failed_runs=0,
                    latest_health=None,
                    latest_products=0,
                    successful_counts=(),
                    product_spread_pct=None,
                    average_duration_ms=0,
                    near_timeout_runs=0,
                    active_products=0,
                    canonicalized_products=0,
                    quality_warnings=0,
                    quality_blocked=0,
                    unavailable_products=0,
                    accepted_near_threshold=0,
                    pending_match_reviews=0,
                    source=None,
                    verdict="NOT_READY",
                )
            )
            continue

        runs = list(
            session.scalars(
                select(ScrapeRun)
                .where(
                    ScrapeRun.store_id == store.id,
                    ScrapeRun.finished_at.is_not(None),
                )
                .order_by(ScrapeRun.finished_at.desc(), ScrapeRun.id.desc())
                .limit(required_runs)
            )
        )
        latest = runs[0] if runs else None
        healthy_runs = sum(
            run.status == "success" and run.health_status == "HEALTHY" for run in runs
        )
        degraded_runs = sum(
            run.status == "success" and run.health_status in {"DEGRADED", "STALE"}
            for run in runs
        )
        failed_runs = sum(
            run.status == "failed" or run.health_status == "BROKEN" for run in runs
        )
        successful_counts = [
            int(run.products_found or 0)
            for run in runs
            if run.status == "success"
            and run.health_status in {"HEALTHY", "DEGRADED"}
            and int(run.products_found or 0) > 0
        ]
        spread_pct = _product_spread_pct(successful_counts)
        durations = [int(run.duration_ms or 0) for run in runs if run.duration_ms is not None]
        average_duration_ms = round(sum(durations) / len(durations)) if durations else 0
        near_timeout_runs = sum(duration >= int(timeout_ms * 0.80) for duration in durations)

        active_products = int(
            session.scalar(
                select(func.count(Product.id)).where(
                    Product.store_id == store.id,
                    Product.is_available.is_(True),
                )
            )
            or 0
        )
        canonicalized_products = int(
            session.scalar(
                select(func.count(Product.id)).where(
                    Product.store_id == store.id,
                    Product.is_available.is_(True),
                    Product.master_product_id.is_not(None),
                )
            )
            or 0
        )
        quality_warnings = int(
            session.scalar(
                select(func.count(Product.id)).where(
                    Product.store_id == store.id,
                    Product.is_available.is_(True),
                    Product.data_quality_status.in_(("WARNING", "WARN")),
                )
            )
            or 0
        )
        quality_blocked = int(
            session.scalar(
                select(func.count(Product.id)).where(
                    Product.store_id == store.id,
                    Product.is_available.is_(True),
                    Product.data_quality_status == "BLOCKED",
                )
            )
            or 0
        )
        unavailable_products = int(
            session.scalar(
                select(func.count(Product.id)).where(
                    Product.store_id == store.id,
                    Product.is_available.is_(False),
                )
            )
            or 0
        )
        accepted_near_threshold = int(
            session.scalar(
                select(func.count(ProductMatch.id))
                .join(Product, Product.id == ProductMatch.store_product_id)
                .where(
                    Product.store_id == store.id,
                    ProductMatch.confidence >= float(match_threshold),
                    ProductMatch.confidence < min(1.0, float(match_threshold) + 0.04),
                )
            )
            or 0
        )
        product_ids = set(
            int(value)
            for value in session.scalars(
                select(Product.id).where(Product.store_id == store.id)
            )
        )
        pending_match_reviews = 0
        if product_ids:
            pending_match_reviews = int(
                session.scalar(
                    select(func.count(MatchingReview.id)).where(
                        MatchingReview.status == "pending",
                        (
                            MatchingReview.left_product_id.in_(product_ids)
                            | MatchingReview.right_product_id.in_(product_ids)
                        ),
                    )
                )
                or 0
            )

        latest_health = str(latest.health_status or latest.status).upper() if latest else None
        verdict = _store_verdict(
            registered=True,
            runs_considered=len(runs),
            required_runs=required_runs,
            latest_health=latest_health,
            healthy_runs=healthy_runs,
            degraded_runs=degraded_runs,
            failed_runs=failed_runs,
            spread_pct=spread_pct,
            active_products=active_products,
            canonicalized_products=canonicalized_products,
            quality_blocked=quality_blocked,
        )
        views.append(
            StoreConsolidationView(
                connector_key=key,
                store_name=store.name,
                registered=True,
                runs_considered=len(runs),
                healthy_runs=healthy_runs,
                degraded_runs=degraded_runs,
                failed_runs=failed_runs,
                latest_health=latest_health,
                latest_products=int(latest.products_found or 0) if latest else 0,
                successful_counts=tuple(successful_counts),
                product_spread_pct=spread_pct,
                average_duration_ms=average_duration_ms,
                near_timeout_runs=near_timeout_runs,
                active_products=active_products,
                canonicalized_products=canonicalized_products,
                quality_warnings=quality_warnings,
                quality_blocked=quality_blocked,
                unavailable_products=unavailable_products,
                accepted_near_threshold=accepted_near_threshold,
                pending_match_reviews=pending_match_reviews,
                source=_source(latest),
                verdict=verdict,
            )
        )

    now = utcnow()
    last_7d = now - timedelta(days=7)
    previous_7d = now - timedelta(days=14)
    observations_last_7d = int(
        session.scalar(
            select(func.count(PriceObservation.id)).where(
                PriceObservation.observed_at >= last_7d
            )
        )
        or 0
    )
    observations_previous_7d = int(
        session.scalar(
            select(func.count(PriceObservation.id)).where(
                PriceObservation.observed_at >= previous_7d,
                PriceObservation.observed_at < last_7d,
            )
        )
        or 0
    )

    enough_history = all(view.runs_considered >= required_runs for view in views)
    if not enough_history:
        verdict = "NOT_READY"
    elif all(view.verdict == "STABLE" for view in views):
        verdict = "STABLE"
    else:
        verdict = "WATCH"

    return ExpansionConsolidationAudit(
        verdict=verdict,
        enough_history=enough_history,
        stores=tuple(views),
        extreme_price_gaps=_extreme_price_gaps(
            session, expansion_store_ids=expansion_store_ids
        ),
        observations_last_7d=observations_last_7d,
        observations_previous_7d=observations_previous_7d,
        database_size_mb=_database_size_mb(session),
    )


def _duration(milliseconds: int) -> str:
    seconds = max(0, int(milliseconds)) // 1000
    minutes, seconds = divmod(seconds, 60)
    return f"{minutes}m {seconds:02d}s" if minutes else f"{seconds}s"


def format_expansion_consolidation_report(
    audit: ExpansionConsolidationAudit,
    *,
    runs_per_store: int = 3,
) -> str:
    verdict_icon = {"STABLE": "✅", "WATCH": "🟡", "NOT_READY": "🕒"}.get(
        audit.verdict, "⚪"
    )
    verdict_text = {
        "STABLE": "expansión consolidada",
        "WATCH": "requiere observación",
        "NOT_READY": "faltan ciclos para consolidar",
    }.get(audit.verdict, audit.verdict)
    lines = [
        "🧭 Auditoría v5.9 · expansión de tiendas",
        "",
        f"{verdict_icon} Veredicto: {verdict_text}",
        f"Ventana: últimas {max(2, int(runs_per_store))} ejecuciones por tienda",
        "",
    ]
    icons = {"STABLE": "🟢", "WATCH": "🟡", "NOT_READY": "🕒"}
    for view in audit.stores:
        icon = icons.get(view.verdict, "⚪")
        if not view.registered:
            lines.extend([f"{icon} {view.store_name}", "   no registrada", ""])
            continue
        spread = (
            f"{view.product_spread_pct:.1f}%"
            if view.product_spread_pct is not None
            else "sin base"
        )
        canonical_pct = (
            view.canonicalized_products / view.active_products * 100.0
            if view.active_products
            else 0.0
        )
        lines.append(f"{icon} {view.store_name}")
        lines.append(
            f"   HEALTHY {view.healthy_runs}/{view.runs_considered} · "
            f"último {view.latest_products} prod. · variación {spread}"
        )
        lines.append(
            f"   Canónico {canonical_pct:.1f}% · DQ warn/block "
            f"{view.quality_warnings}/{view.quality_blocked} · {_duration(view.average_duration_ms)}"
        )
        if view.accepted_near_threshold or view.pending_match_reviews:
            lines.append(
                f"   Matching: {view.accepted_near_threshold} aceptados cerca de 86% · "
                f"{view.pending_match_reviews} pendientes"
            )
        if view.unavailable_products:
            lines.append(f"   No disponibles confirmados: {view.unavailable_products}")
        if view.near_timeout_runs:
            lines.append(f"   ⚠ Cerca del timeout: {view.near_timeout_runs} ejecución(es)")
        if view.source:
            lines.append(f"   Fuente: {view.source}")
        lines.append("")

    if audit.extreme_price_gaps:
        lines.append("⚠ Brechas de precio a revisar (>=2,5x)")
        for name, low, high, ratio in audit.extreme_price_gaps[:3]:
            lines.append(
                f"   {name[:55]}: ${low:,} → ${high:,} ({ratio:.1f}x)".replace(",", ".")
            )
        lines.append("")
    else:
        lines.extend(["✅ Sin brechas extremas >=2,5x en comparables activos.", ""])

    if audit.observations_previous_7d > 0:
        delta = (
            (audit.observations_last_7d - audit.observations_previous_7d)
            / audit.observations_previous_7d
            * 100.0
        )
        lines.append(
            f"Historial: {audit.observations_last_7d:,} observaciones/7d "
            f"({delta:+.1f}% vs 7d previos)".replace(",", ".")
        )
    else:
        lines.append(
            f"Historial: {audit.observations_last_7d:,} observaciones en 7 días".replace(",", ".")
        )
    if audit.database_size_mb is not None:
        lines.append(f"PostgreSQL: {audit.database_size_mb:.1f} MB")

    if audit.verdict == "STABLE":
        lines.extend(["", "✅ Criterio cumplido para cerrar v5.9 y avanzar a v6.0."])
    elif audit.verdict == "WATCH":
        lines.extend(["", "🟡 Mantener v5.9 en observación; no hace falta agregar tiendas."])
    else:
        lines.extend(["", "🕒 Esperar los ciclos restantes antes de cerrar v5.9."])
    return "\n".join(lines).strip()[:4000]


def build_expansion_consolidation_report(
    session: Session,
    *,
    runs_per_store: int = 3,
    timeout_minutes: int = 25,
    match_threshold: float = 0.86,
) -> str:
    audit = build_expansion_consolidation_audit(
        session,
        runs_per_store=runs_per_store,
        timeout_minutes=timeout_minutes,
        match_threshold=match_threshold,
    )
    return format_expansion_consolidation_report(audit, runs_per_store=runs_per_store)
