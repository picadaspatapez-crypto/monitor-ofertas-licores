from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Float, cast, desc, func, select
from sqlalchemy.orm import Session

from app.matching import build_product_signature
from app.models import (
    MasterPriceStatistic,
    MasterProduct,
    OpportunitySnapshot,
    Product,
    Store,
)


@dataclass(frozen=True)
class OpportunityView:
    master_product_id: int
    canonical_name: str
    score: float
    classification: str
    winner_store: str
    winner_price: int
    saving_clp: int
    saving_pct: float
    confidence: float
    min_90d: int | None
    avg_90d: float | None
    historical_min: int | None
    url: str
    calculated_at: datetime
    score_version: str = "v2"
    rarity_score: float = 0.0
    rarity_frequency_90d: float | None = None
    history_observations_90d: int = 0
    previous_historical_min: int | None = None
    price_event: str = "NORMAL"
    historical_gap_clp: int = 0
    historical_gap_pct: float = 0.0
    intelligence_reason: str | None = None


def _statement(*, minimum_score: float, events: tuple[str, ...] | None, order: str):
    ordering = (
        (desc(OpportunitySnapshot.saving_pct), desc(OpportunitySnapshot.saving_clp))
        if order == "saving"
        else (desc(OpportunitySnapshot.score), desc(OpportunitySnapshot.saving_pct))
    )
    statement = (
        select(
            OpportunitySnapshot,
            MasterProduct,
            Product,
            Store,
            MasterPriceStatistic,
        )
        .join(MasterProduct, MasterProduct.id == OpportunitySnapshot.master_product_id)
        .join(Product, Product.id == OpportunitySnapshot.winner_product_id)
        .join(Store, Store.id == OpportunitySnapshot.winner_store_id)
        .outerjoin(
            MasterPriceStatistic,
            MasterPriceStatistic.master_product_id == OpportunitySnapshot.master_product_id,
        )
        .where(
            OpportunitySnapshot.score >= minimum_score,
            Product.is_available.is_(True),
            Product.excluded_from_comparison.is_(False),
            Product.package_quantity == 1,
            MasterProduct.package_quantity == 1,
            Store.is_active.is_(True),
        )
        .order_by(*ordering, MasterProduct.canonical_name)
    )
    if events:
        statement = statement.where(OpportunitySnapshot.price_event.in_(events))
    return statement


def _views(session: Session, statement, *, limit: int) -> list[OpportunityView]:
    views: list[OpportunityView] = []
    fetch_limit = max(1, min(int(limit), 30)) * 5
    for snapshot, master, product, store, stats in session.execute(
        statement.limit(fetch_limit)
    ):
        # Independent presentation guard: a stale canonical name containing X6/X24
        # must never surface in /radar or /minimos even if an older snapshot survived
        # an interrupted run.
        if build_product_signature(master.canonical_name or "").is_pack:
            continue
        if build_product_signature(product.name or "").is_pack:
            continue
        views.append(
            OpportunityView(
                master_product_id=int(master.id),
                canonical_name=master.canonical_name,
                score=float(snapshot.score),
                classification=snapshot.classification,
                winner_store=store.name,
                winner_price=int(snapshot.winner_price or product.current_price),
                saving_clp=int(snapshot.saving_clp or 0),
                saving_pct=float(snapshot.saving_pct or 0.0),
                confidence=float(snapshot.match_confidence or 0.0),
                min_90d=(int(stats.min_90d) if stats and stats.min_90d is not None else None),
                avg_90d=(float(stats.avg_90d) if stats and stats.avg_90d is not None else None),
                historical_min=(
                    int(stats.historical_min)
                    if stats and stats.historical_min is not None
                    else None
                ),
                url=product.url,
                calculated_at=snapshot.calculated_at,
                score_version=str(getattr(snapshot, "score_version", "v2") or "v2"),
                rarity_score=float(getattr(snapshot, "rarity_score", 0.0) or 0.0),
                rarity_frequency_90d=getattr(snapshot, "rarity_frequency_90d", None),
                history_observations_90d=int(getattr(snapshot, "history_observations_90d", 0) or 0),
                previous_historical_min=getattr(snapshot, "previous_historical_min", None),
                price_event=str(getattr(snapshot, "price_event", "NORMAL") or "NORMAL"),
                historical_gap_clp=int(getattr(snapshot, "historical_gap_clp", 0) or 0),
                historical_gap_pct=float(getattr(snapshot, "historical_gap_pct", 0.0) or 0.0),
                intelligence_reason=getattr(snapshot, "intelligence_reason", None),
            )
        )
        if len(views) >= max(1, min(int(limit), 30)):
            break
    return views


def top_opportunities(
    session: Session,
    *,
    limit: int = 20,
    minimum_score: float = 0.0,
    order: str = "score",
) -> list[OpportunityView]:
    return _views(
        session,
        _statement(minimum_score=minimum_score, events=None, order=order),
        limit=limit,
    )


def commercial_radar(
    session: Session,
    *,
    limit: int = 10,
    minimum_score: float = 70.0,
) -> list[OpportunityView]:
    """Radar comercial con degradación útil cuando no hay señales excepcionales.

    v5.8.0 exigía simultáneamente una señal comercial especial y score >= 70.
    Ese filtro era correcto para alertas automáticas, pero demasiado estricto para
    un comando interactivo: en mercados estables podía devolver cero filas aunque
    existieran comparaciones verificadas.

    La consulta interactiva conserva primero el criterio estricto. Si no hay
    resultados, muestra oportunidades verificadas con score >= 55 y, como último
    recurso, las mejores comparaciones disponibles. Las alertas automáticas NO usan
    este fallback y mantienen sus umbrales originales.
    """
    events = (
        "NEW_HISTORICAL_MIN",
        "RARE_OFFER",
        "AT_HISTORICAL_MIN",
        "NEAR_HISTORICAL_MIN",
        "MARKET_LEADER",
    )
    strict = _views(
        session,
        _statement(minimum_score=minimum_score, events=events, order="score"),
        limit=limit,
    )
    if strict:
        return strict

    useful = top_opportunities(session, limit=limit, minimum_score=55.0, order="score")
    if useful:
        return useful
    return top_opportunities(session, limit=limit, minimum_score=0.0, order="score")


def historical_floor_opportunities(
    session: Session,
    *,
    limit: int = 10,
) -> list[OpportunityView]:
    """Productos en el piso histórico o, si no hay ninguno, los más cercanos.

    El modo estricto conserva NEW/AT/NEAR_HISTORICAL_MIN. Cuando el mercado está
    estable y ninguno cae dentro del 3 %, el comando sigue siendo útil ordenando
    las comparaciones por distancia absoluta al mínimo histórico.
    """
    events = ("NEW_HISTORICAL_MIN", "AT_HISTORICAL_MIN", "NEAR_HISTORICAL_MIN")
    statement = _statement(minimum_score=0.0, events=events, order="score").order_by(None).order_by(
        desc(OpportunitySnapshot.historical_gap_pct),
        desc(OpportunitySnapshot.score),
        MasterProduct.canonical_name,
    )
    strict = _views(session, statement, limit=limit)
    if strict:
        return strict

    distance = func.abs(
        (
            cast(OpportunitySnapshot.winner_price, Float)
            - cast(MasterPriceStatistic.historical_min, Float)
        )
        / cast(MasterPriceStatistic.historical_min, Float)
    )
    nearest = (
        _statement(minimum_score=0.0, events=None, order="score")
        .where(
            OpportunitySnapshot.winner_price.is_not(None),
            MasterPriceStatistic.historical_min.is_not(None),
            MasterPriceStatistic.historical_min > 0,
            MasterPriceStatistic.observations_total >= 2,
        )
        .order_by(None)
        .order_by(
            distance,
            desc(OpportunitySnapshot.score),
            MasterProduct.canonical_name,
        )
    )
    return _views(session, nearest, limit=limit)
