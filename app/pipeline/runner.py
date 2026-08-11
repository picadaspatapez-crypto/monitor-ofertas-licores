from __future__ import annotations

import hashlib
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.analyzers import analyze_catalog, analyze_cross_store_prices
from app.collectors.base import Collector, CollectorPausedError
from app.collectors.registry import enabled_collectors
from app.config import Settings
from app.database import Base, create_database
from app.deadlines import collector_budget
from app.favorites import deliver_pending_favorite_alerts, evaluate_favorite_alerts
from app.intelligence import (
    persist_opportunity_snapshots,
    reconcile_store_availability,
    refresh_price_statistics,
    refresh_personal_opportunities,
)
from app.models import ScrapeRun, Store
from app.notifications import (
    ComparisonAlertContext,
    NotificationBundle,
    SmartAlertContext,
    build_comparison_notification_bundles,
    build_smart_notification_bundles,
)
from app.performance import PerformanceSettings
from app.repositories import (
    count_missing_products,
    finish_scrape_run,
    get_or_create_store,
    latest_sent_alert,
    previous_health_status,
    previous_successful_product_count,
    reconcile_cross_store_matches,
    save_product,
    start_scrape_run,
    synchronize_active_stores,
)
from app.services import (
    deliver_notification_bundles,
    failure_notification_bundle,
    send_message,
)
from app.reports.global_summary import build_global_run_summary
from app.reports.health import build_weekly_health_report
from app.search.catalog import refresh_search_catalog
from app.version import RELEASE_NAME, __version__
from sqlalchemy import select


@dataclass(frozen=True)
class CollectorExecution:
    key: str
    store_name: str
    success: bool
    duration_ms: int
    products_found: int = 0
    error_message: str | None = None
    store_id: int | None = None
    run_id: int | None = None
    health_status: str | None = None
    new_products: int = 0
    price_drops: int = 0
    price_increases: int = 0
    sections_failed: int = 0
    execution_state: str = "UPDATED"
    detail: str | None = None
    last_real_run_at: datetime | None = None
    next_due_at: datetime | None = None
    source: str | None = None
    marked_unavailable: int = 0
    reactivated: int = 0
    diagnostic_mode: bool = False




@dataclass(frozen=True)
class RunSnapshot:
    run_id: int
    store_id: int
    products_found: int
    health_status: str
    finished_at: datetime
    source: str | None = None


def _latest_finished_run(session, store_id: int, *, exclude_run_id: int | None = None):
    query = select(ScrapeRun).where(
        ScrapeRun.store_id == store_id,
        ScrapeRun.finished_at.is_not(None),
    )
    if exclude_run_id is not None:
        query = query.where(ScrapeRun.id != exclude_run_id)
    return session.scalar(
        query.order_by(ScrapeRun.finished_at.desc(), ScrapeRun.id.desc()).limit(1)
    )


def _latest_healthy_snapshot(
    session, store_id: int, *, exclude_run_id: int | None = None
) -> RunSnapshot | None:
    query = select(ScrapeRun).where(
        ScrapeRun.store_id == store_id,
        ScrapeRun.status == "success",
        ScrapeRun.health_status == "HEALTHY",
        ScrapeRun.products_found > 0,
        ScrapeRun.finished_at.is_not(None),
    )
    if exclude_run_id is not None:
        query = query.where(ScrapeRun.id != exclude_run_id)
    run = session.scalar(
        query.order_by(ScrapeRun.finished_at.desc(), ScrapeRun.id.desc()).limit(1)
    )
    if run is None or run.finished_at is None:
        return None
    finished_at = run.finished_at
    if finished_at.tzinfo is None:
        finished_at = finished_at.replace(tzinfo=timezone.utc)
    return RunSnapshot(
        run_id=int(run.id),
        store_id=int(run.store_id),
        products_found=int(run.products_found or 0),
        health_status=str(run.health_status or "HEALTHY"),
        finished_at=finished_at,
        source=(run.metrics_json or {}).get("discovery_source") if isinstance(run.metrics_json, dict) else None,
    )


def _format_schedule_time(value: datetime, timezone_name: str) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    try:
        local = value.astimezone(ZoneInfo(timezone_name))
    except Exception:
        local = value.astimezone(timezone.utc)
    return local.strftime("%d-%m-%Y %H:%M:%S %Z")


def _scheduled_execution_or_none(
    *,
    collector: Collector,
    SessionLocal,
    performance: PerformanceSettings,
) -> CollectorExecution | None:
    interval_hours: int | None = None
    if collector.key == "elmundodelvino":
        interval_hours = performance.el_mundo_interval_hours
    if interval_hours is None:
        return None

    with SessionLocal() as session:
        store = get_or_create_store(session, **collector.metadata.repository_kwargs())
        session.flush()
        latest = _latest_finished_run(session, store.id)
        snapshot = _latest_healthy_snapshot(session, store.id)
        session.commit()

    if latest is None or latest.finished_at is None:
        return None
    last_finished = latest.finished_at
    if last_finished.tzinfo is None:
        last_finished = last_finished.replace(tzinfo=timezone.utc)
    due_at = last_finished + timedelta(hours=interval_hours)
    now = datetime.now(timezone.utc)
    grace = timedelta(minutes=performance.scheduler_grace_minutes)

    # La tolerancia evita perder una revisión completa porque Railway inició el
    # cron algunos segundos antes de la hora exacta.
    if now + grace >= due_at:
        return None
    if snapshot is None:
        return None

    remaining_seconds = max(0, int((due_at - now).total_seconds()))
    hours, remainder = divmod(remaining_seconds, 3600)
    minutes = remainder // 60
    remaining_text = f"{hours} h {minutes} min" if hours else f"{minutes} min"
    return CollectorExecution(
        key=collector.key,
        store_name=collector.store_name,
        success=True,
        duration_ms=0,
        products_found=snapshot.products_found,
        store_id=snapshot.store_id,
        run_id=snapshot.run_id,
        health_status=snapshot.health_status,
        execution_state="DUE_SOON",
        detail=(
            f"Catálogo vigente reutilizado; faltan {remaining_text}. "
            f"Próxima revisión real: "
            f"{_format_schedule_time(due_at, performance.app_timezone)}."
        ),
        last_real_run_at=snapshot.finished_at,
        next_due_at=due_at,
        source=snapshot.source,
    )


def _mark_run_special(
    *,
    SessionLocal,
    run_id: int | None,
    status: str,
    health_status: str,
    health_score: int,
    error_message: str | None = None,
    products_found: int = 0,
) -> None:
    if run_id is None:
        return
    with SessionLocal() as session:
        run = session.get(ScrapeRun, run_id)
        if run is None or run.status != "running":
            return
        finish_scrape_run(
            run,
            status=status,
            products_found=products_found,
            error_message=error_message,
            metrics={
                "health_status": health_status,
                "health_score": health_score,
                "sections_discovered": 0,
                "sections_visited": 0,
                "sections_succeeded": 0,
                "sections_failed": 0,
                "pages_visited": 0,
                "cards_seen": 0,
                "duplicates_removed": 0,
                "structural_warnings": 0,
            },
        )
        session.commit()

def _metrics_dict(stats, previous_count: int | None) -> dict:
    return {
        "sections_discovered": stats.sections_discovered,
        "sections_visited": stats.sections_visited,
        "sections_succeeded": stats.sections_succeeded,
        "sections_failed": stats.sections_failed,
        "pages_visited": stats.pages_visited,
        "cards_seen": stats.cards_seen,
        "duplicates_removed": stats.duplicates_removed,
        "structural_warnings": stats.structural_warnings,
        "discovery_source": stats.discovery_source,
        "health_status": stats.health_status,
        "health_score": stats.health_score,
        "previous_products_found": previous_count,
        "performance_ms": dict(stats.performance_ms),
        "sections": [
            {
                "key": section.key,
                "name": section.name,
                "url": section.url,
                "status": section.status,
                "pages_visited": section.pages_visited,
                "cards_seen": section.cards_seen,
                "unique_products": section.unique_products,
                "duplicates_removed": section.duplicates_removed,
                "duration_ms": section.duration_ms,
                "structural_warning": section.structural_warning,
                "error_message": section.error_message,
                "performance_ms": dict(section.performance_ms),
            }
            for section in stats.section_stats
        ],
    }


def _apply_historical_health(stats, previous_count: int | None):
    if not previous_count or previous_count <= 0:
        return stats
    ratio = stats.unique_products / previous_count
    status, score = stats.health_status, stats.health_score
    if ratio < 0.40:
        # A collector-specific DEGRADED result can still be a trustworthy
        # partial capture (for example, several Shopify collections obtained
        # before a 429). Preserve that classification instead of discarding
        # the whole batch solely because the previous run was larger.
        if status == "HEALTHY":
            status, score = "BROKEN", min(score, 25)
        elif status == "DEGRADED":
            score = min(score, 45)
    elif ratio < 0.70 and status == "HEALTHY":
        status, score = "DEGRADED", min(score, 60)
    return replace(stats, health_status=status, health_score=score)


def _print_summary(*, name: str, analysis) -> None:
    stats = analysis.collection_stats
    icon = {"HEALTHY": "🟢", "DEGRADED": "🟡", "BROKEN": "🔴"}.get(
        stats.health_status, "⚪"
    )
    print("=" * 58, flush=True)
    print(f"RESUMEN DE EJECUCIÓN · {name}", flush=True)
    print(f"Duración...............: {analysis.duration_ms / 1000:.1f} s", flush=True)
    print(f"Categorías descubiertas: {stats.sections_discovered}", flush=True)
    print(f"Categorías correctas...: {stats.sections_succeeded}", flush=True)
    print(f"Categorías fallidas....: {stats.sections_failed}", flush=True)
    print(f"Alertas estructurales..: {stats.structural_warnings}", flush=True)
    print(f"Páginas................: {stats.pages_visited}", flush=True)
    print(f"Tarjetas...............: {stats.cards_seen}", flush=True)
    print(f"Duplicados eliminados..: {stats.duplicates_removed}", flush=True)
    print(f"Productos..............: {analysis.total}", flush=True)
    print(f"Nuevos.................: {analysis.new_products}", flush=True)
    print(f"Actualizados...........: {analysis.total - analysis.new_products}", flush=True)
    print(f"Bajaron................: {analysis.price_drops}", flush=True)
    print(f"Subieron...............: {analysis.price_increases}", flush=True)
    print(f"Sin cambios............: {analysis.unchanged}", flush=True)
    print(f"No observados..........: {analysis.missing_products}", flush=True)
    print(
        f"Salud collector........: {icon} {stats.health_status} "
        f"({stats.health_score}/100)",
        flush=True,
    )
    if stats.performance_ms:
        print(
            "Performance............: "
            + ", ".join(
                f"{name}={value / 1000:.1f}s"
                if name != "blocked_requests"
                else f"{name}={value}"
                for name, value in stats.performance_ms.items()
            ),
            flush=True,
        )
    print("=" * 58, flush=True)


def _send_store_notifications(
    *,
    SessionLocal,
    settings: Settings,
    store_id: int,
    run_id: int,
    store_name: str,
    saved,
    analysis,
    previous_health: str | None,
    previous_count: int | None,
) -> None:
    with SessionLocal() as session:
        last_ranking_alert = latest_sent_alert(
            session,
            store_id=store_id,
            alert_type="ranking_digest",
        )
        last_incident_alert = latest_sent_alert(
            session,
            store_id=store_id,
            alert_type="collector_incident",
        )
        if last_ranking_alert is not None:
            session.expunge(last_ranking_alert)
        if last_incident_alert is not None:
            session.expunge(last_incident_alert)

    context = SmartAlertContext(
        store_id=store_id,
        run_id=run_id,
        store_name=store_name,
        previous_health_status=previous_health,
        previous_product_count=previous_count,
        min_drop_pct=settings.alert_min_drop_pct,
        min_drop_amount=settings.alert_min_drop_amount,
        digest_interval_hours=settings.telegram_digest_interval_hours,
        alert_new_products=settings.alert_new_products,
        alert_price_increases=settings.alert_price_increases,
        max_change_items=settings.telegram_change_limit,
        report_limit=settings.telegram_report_limit,
        last_ranking_alert=last_ranking_alert,
        last_incident_alert=last_incident_alert,
    )
    bundles = build_smart_notification_bundles(
        items=saved,
        analysis=analysis,
        context=context,
    )
    if not bundles:
        print(
            f"Telegram {store_name}: sin cambios relevantes; 0 mensajes.",
            flush=True,
        )
        return

    sent, skipped, failed = deliver_notification_bundles(
        SessionLocal=SessionLocal,
        bundles=bundles,
        telegram_bot_token=settings.telegram_bot_token,
        telegram_chat_id=settings.telegram_chat_id,
        send_message_fn=send_message,
    )
    print(
        f"Telegram {store_name}: bundles enviados={sent}, "
        f"omitidos={skipped}, fallidos={failed}.",
        flush=True,
    )


def _track_failed_run(
    *,
    SessionLocal,
    run_id: int | None,
    store_id: int | None,
    error: Exception,
) -> int | None:
    if run_id is None:
        return store_id
    try:
        with SessionLocal() as session:
            run = session.get(ScrapeRun, run_id)
            if run is not None and run.status == "running":
                finish_scrape_run(
                    run,
                    status="failed",
                    error_message=str(error)[:2000],
                )
                store = session.get(Store, run.store_id)
                if store is not None:
                    store.last_error_at = run.finished_at
                    store_id = store.id
                session.commit()
    except Exception as tracking_error:
        print(
            f"No se pudo registrar el error: {tracking_error}",
            file=sys.stderr,
            flush=True,
        )
    return store_id


def _notify_failed_run(
    *,
    SessionLocal,
    settings: Settings,
    store_id: int | None,
    run_id: int | None,
    store_name: str,
    error: Exception,
) -> None:
    if store_id is None or run_id is None:
        return
    try:
        bundle = failure_notification_bundle(
            SessionLocal=SessionLocal,
            store_id=store_id,
            run_id=run_id,
            store_name=store_name,
            error=error,
        )
        if bundle is not None:
            deliver_notification_bundles(
                SessionLocal=SessionLocal,
                bundles=[bundle],
                telegram_bot_token=settings.telegram_bot_token,
                telegram_chat_id=settings.telegram_chat_id,
                send_message_fn=send_message,
            )
    except Exception as notification_error:
        print(
            f"No se pudo notificar el fallo: {notification_error}",
            file=sys.stderr,
            flush=True,
        )


def _run_collector(
    *,
    collector: Collector,
    SessionLocal,
    settings: Settings,
    timeout_minutes: int,
) -> CollectorExecution:
    started = time.monotonic()
    run_id: int | None = None
    store_id: int | None = None
    meta = collector.metadata.repository_kwargs()

    print(f"▶ Iniciando collector paralelo: {collector.store_name}", flush=True)
    try:
        with SessionLocal() as session:
            store = get_or_create_store(session, **meta)
            run = start_scrape_run(session, store)
            run_id = run.id
            store_id = store.id
            session.commit()

        collect_started = time.monotonic()
        with collector_budget(
            store_name=collector.store_name,
            seconds=timeout_minutes * 60,
        ):
            batch = collector.collect()
        collect_ms = int((time.monotonic() - collect_started) * 1000)
        collected = batch.products
        saved = []
        created = updated = price_changes = 0

        persistence_started = time.monotonic()
        with SessionLocal() as session:
            store = get_or_create_store(session, **meta)
            run = session.get(ScrapeRun, run_id)
            if run is None:
                raise RuntimeError("No se pudo recuperar la ejecución activa.")
            previous_count = previous_successful_product_count(session, store, run.id)
            previous_health = previous_health_status(session, store, run.id)
            healthy_snapshot = _latest_healthy_snapshot(
                session, store.id, exclude_run_id=run.id
            )
            final_stats = _apply_historical_health(batch.stats, previous_count)

            # El Mundo del Vino usa el último snapshot HEALTHY cuando la captura
            # actual quedó parcial. Así una página 429 no mezcla un catálogo
            # incompleto con observaciones confiables anteriores.
            if (
                collector.key == "elmundodelvino"
                and final_stats.health_status == "DEGRADED"
                and healthy_snapshot is not None
            ):
                performance_ms = dict(final_stats.performance_ms)
                performance_ms["collect"] = collect_ms
                final_stats = replace(final_stats, performance_ms=performance_ms)
                stale_metrics = _metrics_dict(final_stats, previous_count)
                stale_metrics["health_status"] = "STALE"
                stale_metrics["health_score"] = 70
                finish_scrape_run(
                    run,
                    status="stale",
                    products_found=len(collected),
                    error_message=(
                        "Captura parcial descartada; se reutiliza el último "
                        "snapshot HEALTHY."
                    ),
                    metrics=stale_metrics,
                )
                session.commit()
                total_ms = int((time.monotonic() - started) * 1000)
                print(
                    f"🟠 El Mundo del Vino: captura parcial de {len(collected)} productos "
                    f"no persistida; se reutiliza snapshot HEALTHY de "
                    f"{healthy_snapshot.products_found} productos.",
                    flush=True,
                )
                return CollectorExecution(
                    key=collector.key,
                    store_name=collector.store_name,
                    success=True,
                    duration_ms=total_ms,
                    products_found=healthy_snapshot.products_found,
                    store_id=healthy_snapshot.store_id,
                    run_id=healthy_snapshot.run_id,
                    health_status="STALE",
                    execution_state="STALE",
                    detail=(
                        "La captura actual fue parcial; se conserva el último "
                        "catálogo confiable."
                    ),
                    sections_failed=final_stats.sections_failed,
                )

            if final_stats.health_status == "BROKEN":
                raise RuntimeError(
                    f"{collector.store_name} entregó una cobertura no confiable "
                    f"({len(collected)} productos; salud BROKEN). "
                    "Se conservan los datos históricos y no se persiste esta captura parcial."
                )

            for item in collected:
                result = save_product(session, item, store, run)
                saved.append(result)
                created += int(result.is_new)
                updated += int(not result.is_new)
                price_changes += int(result.price_changed)

            session.flush()
            availability = reconcile_store_availability(
                session,
                store=store,
                scrape_run=run,
                catalog_is_healthy=final_stats.health_status == "HEALTHY",
                missing_threshold=settings.availability_missing_threshold,
            )
            missing_products = availability.missing
            persistence_ms = int((time.monotonic() - persistence_started) * 1000)
            performance_ms = dict(final_stats.performance_ms)
            performance_ms["collect"] = collect_ms
            performance_ms["persistence"] = persistence_ms
            final_stats = replace(final_stats, performance_ms=performance_ms)
            metrics = _metrics_dict(final_stats, previous_count)
            finish_scrape_run(
                run,
                status=(
                    "success" if final_stats.health_status != "BROKEN" else "degraded"
                ),
                products_found=len(collected),
                products_created=created,
                products_updated=updated,
                price_changes=price_changes,
                metrics=metrics,
            )
            store.last_success_at = run.finished_at
            duration_ms = run.duration_ms or 0
            store_id = store.id
            session.commit()

        analysis = analyze_catalog(
            saved,
            missing_products=missing_products,
            duration_ms=duration_ms,
            collection_stats=final_stats,
        )
        _print_summary(name=collector.store_name, analysis=analysis)

        notification_started = time.monotonic()
        _send_store_notifications(
            SessionLocal=SessionLocal,
            settings=settings,
            store_id=store_id,
            run_id=run_id,
            store_name=collector.store_name,
            saved=saved,
            analysis=analysis,
            previous_health=previous_health,
            previous_count=previous_count,
        )
        notification_ms = int((time.monotonic() - notification_started) * 1000)
        total_ms = int((time.monotonic() - started) * 1000)
        print(
            f"✓ Pipeline {collector.key} completado: productos={len(collected)}, "
            f"collect={collect_ms / 1000:.1f}s, persist={persistence_ms / 1000:.1f}s, "
            f"notify={notification_ms / 1000:.1f}s, total={total_ms / 1000:.1f}s.",
            flush=True,
        )
        collector_success = final_stats.health_status != "BROKEN"
        return CollectorExecution(
            key=collector.key,
            store_name=collector.store_name,
            success=collector_success,
            duration_ms=total_ms,
            products_found=len(collected),
            error_message=(
                None
                if collector_success
                else "Collector finalizó con salud BROKEN; los datos incompletos no participan en comparaciones."
            ),
            store_id=store_id,
            run_id=run_id,
            health_status=final_stats.health_status,
            new_products=analysis.new_products,
            price_drops=analysis.price_drops,
            price_increases=analysis.price_increases,
            sections_failed=final_stats.sections_failed,
            last_real_run_at=run.finished_at,
            source=final_stats.discovery_source,
            marked_unavailable=availability.marked_unavailable,
            diagnostic_mode=collector.metadata.diagnostic_mode,
            reactivated=availability.reactivated,
        )

    except CollectorPausedError as exc:
        _mark_run_special(
            SessionLocal=SessionLocal,
            run_id=run_id,
            status="paused",
            health_status="PAUSED",
            health_score=0,
            error_message=str(exc)[:2000],
        )
        total_ms = int((time.monotonic() - started) * 1000)
        print(
            f"⏸ Collector {collector.key} pausado tras {total_ms / 1000:.1f}s: {exc}",
            flush=True,
        )
        return CollectorExecution(
            key=collector.key,
            store_name=collector.store_name,
            success=False,
            duration_ms=total_ms,
            error_message=None,
            store_id=store_id,
            run_id=None,
            health_status="PAUSED",
            execution_state="PAUSED",
            detail=str(exc)[:500],
        )

    except Exception as exc:
        # El Mundo del Vino mantiene el último snapshot HEALTHY si el intento
        # actual falla por 429, timeout u otra inestabilidad de red.
        if collector.key == "elmundodelvino" and store_id is not None:
            try:
                with SessionLocal() as session:
                    snapshot = _latest_healthy_snapshot(
                        session, store_id, exclude_run_id=run_id
                    )
                if snapshot is not None:
                    _mark_run_special(
                        SessionLocal=SessionLocal,
                        run_id=run_id,
                        status="stale",
                        health_status="STALE",
                        health_score=70,
                        error_message=f"{type(exc).__name__}: {exc}"[:2000],
                    )
                    total_ms = int((time.monotonic() - started) * 1000)
                    print(
                        f"🟠 El Mundo del Vino quedó STALE tras {type(exc).__name__}; "
                        f"se reutiliza snapshot HEALTHY de {snapshot.products_found} productos.",
                        flush=True,
                    )
                    return CollectorExecution(
                        key=collector.key,
                        store_name=collector.store_name,
                        success=True,
                        duration_ms=total_ms,
                        products_found=snapshot.products_found,
                        store_id=snapshot.store_id,
                        run_id=snapshot.run_id,
                        health_status="STALE",
                        execution_state="STALE",
                        detail=(
                            f"Intento actual limitado ({type(exc).__name__}); "
                            "se conserva el último catálogo confiable."
                        ),
                    )
            except Exception as stale_error:
                print(
                    f"⚠ No se pudo reutilizar snapshot de El Mundo del Vino: {stale_error}",
                    file=sys.stderr,
                    flush=True,
                )

        store_id = _track_failed_run(
            SessionLocal=SessionLocal,
            run_id=run_id,
            store_id=store_id,
            error=exc,
        )
        _notify_failed_run(
            SessionLocal=SessionLocal,
            settings=settings,
            store_id=store_id,
            run_id=run_id,
            store_name=collector.store_name,
            error=exc,
        )
        total_ms = int((time.monotonic() - started) * 1000)
        print(
            f"✖ Error en collector {collector.key} tras {total_ms / 1000:.1f}s: {exc}",
            file=sys.stderr,
            flush=True,
        )
        return CollectorExecution(
            key=collector.key,
            store_name=collector.store_name,
            success=False,
            duration_ms=total_ms,
            error_message=f"{type(exc).__name__}: {exc}"[:1000],
            store_id=store_id,
            run_id=run_id,
            sections_failed=1,
            execution_state="FAILED",
            diagnostic_mode=collector.metadata.diagnostic_mode,
        )


def _run_cross_store_stage(*, SessionLocal, settings: Settings, results: list[CollectorExecution]) -> None:
    successful = [
        result
        for result in results
        if result.success
        and result.run_id is not None
        and result.store_id is not None
        and result.products_found > 0
    ]
    if len(successful) < 2:
        print(
            "Comparador multi-tienda: omitido; se requieren al menos dos collectors correctos con productos.",
            flush=True,
        )
        return

    run_ids = sorted(int(result.run_id) for result in successful if result.run_id is not None)
    stage_started = time.monotonic()
    try:
        with SessionLocal() as session:
            matching = reconcile_cross_store_matches(
                session,
                run_ids=run_ids,
                minimum_confidence=settings.cross_store_match_min_confidence,
            )
            session.flush()
            historical = refresh_price_statistics(session)
            comparison = analyze_cross_store_prices(
                session,
                run_ids=run_ids,
                minimum_confidence=settings.cross_store_match_min_confidence,
            )
            opportunity_rows = persist_opportunity_snapshots(
                session, comparison.opportunities
            )
            personal_rows = refresh_personal_opportunities(session)
            session.commit()

        print("=" * 64, flush=True)
        print("MATCHING Y COMPARACIÓN ENTRE TIENDAS", flush=True)
        print(f"Productos actuales........: {matching.total_products}", flush=True)
        print(f"Elegibles.................: {matching.eligible_products}", flush=True)
        print(f"Packs excluidos...........: {matching.skipped_packs}", flush=True)
        print(f"Volumen desconocido.......: {matching.skipped_unknown_volume}", flush=True)
        print(f"Pares evaluados...........: {matching.candidate_pairs}", flush=True)
        print(f"Pares ambiguos............: {matching.ambiguous_products}", flush=True)
        print(f"Matches aceptados.........: {matching.matched_pairs}", flush=True)
        print(f"Matches exactos...........: {matching.exact_matches}", flush=True)
        print(f"Matches difusos...........: {matching.fuzzy_matches}", flush=True)
        print(f"Productos reagrupados.....: {matching.products_relinked}", flush=True)
        print(f"Maestros fusionados.......: {matching.masters_merged}", flush=True)
        print(f"Equivalencias verificadas.: {comparison.verified_matches}", flush=True)
        print(f"Estadísticas históricas...: {historical.rows_updated}", flush=True)
        print(f"Oportunidades de precio...: {len(comparison.opportunities)}", flush=True)
        print(f"Opportunity Scores guardados: {opportunity_rows}", flush=True)
        print(f"Opportunity Scores personales (preview): {personal_rows}", flush=True)
        print(f"Cambios de ganador........: {len(comparison.winner_changes)}", flush=True)
        print(f"Empates...................: {comparison.ties}", flush=True)
        print(f"Grupos no verificados.....: {comparison.unverified_groups}", flush=True)
        print("=" * 64, flush=True)

        with SessionLocal() as session:
            last_digest = latest_sent_alert(
                session,
                store_id=None,
                alert_type="cross_store_digest",
            )
            if last_digest is not None:
                session.expunge(last_digest)

        bundles = build_comparison_notification_bundles(
            analysis=comparison,
            context=ComparisonAlertContext(
                run_ids=tuple(run_ids),
                digest_interval_hours=settings.telegram_digest_interval_hours,
                report_limit=settings.telegram_comparison_limit,
                winner_change_limit=settings.telegram_winner_change_limit,
                last_digest_alert=last_digest,
            ),
        )
        if bundles:
            sent, skipped, failed = deliver_notification_bundles(
                SessionLocal=SessionLocal,
                bundles=bundles,
                telegram_bot_token=settings.telegram_bot_token,
                telegram_chat_id=settings.telegram_chat_id,
                send_message_fn=send_message,
            )
            print(
                f"Telegram comparador: bundles enviados={sent}, omitidos={skipped}, fallidos={failed}.",
                flush=True,
            )
        else:
            print("Telegram comparador: ranking sin cambios; 0 mensajes.", flush=True)

        elapsed_ms = int((time.monotonic() - stage_started) * 1000)
        print(f"✓ Etapa cross-store completada en {elapsed_ms / 1000:.1f}s.", flush=True)
    except Exception as exc:
        print(
            f"✖ Etapa cross-store omitida por error: {type(exc).__name__}: {exc}",
            file=sys.stderr,
            flush=True,
        )


def _refresh_search_catalog_stage(*, SessionLocal) -> None:
    started = time.monotonic()
    try:
        with SessionLocal() as session:
            summary = refresh_search_catalog(session)
            session.commit()
        duration_ms = int((time.monotonic() - started) * 1000)
        print(
            "ÍNDICE DE BÚSQUEDA · "
            f"maestros={summary.masters_seen}, "
            f"actualizados={summary.masters_updated}, "
            f"alias={summary.aliases_indexed}, "
            f"duración={duration_ms / 1000:.1f}s.",
            flush=True,
        )
    except Exception as exc:
        print(
            f"⚠ No se pudo actualizar el índice de búsqueda: {type(exc).__name__}: {exc}",
            file=sys.stderr,
            flush=True,
        )


def _run_favorite_alert_stage(
    *,
    SessionLocal,
    settings: Settings,
    results: list[CollectorExecution],
) -> None:
    relevant = [result for result in results if result.execution_state != "PAUSED" and not result.diagnostic_mode]
    complete = bool(relevant) and all(
        result.run_id is not None
        and result.products_found > 0
        and (
            (result.execution_state == "UPDATED" and result.health_status == "HEALTHY")
            or result.execution_state in {"STALE", "DUE_SOON"}
        )
        for result in relevant
    )
    if not complete:
        print(
            "Favoritos: evaluación omitida porque una tienda con datos activos falló "
            "o una actualización no quedó HEALTHY.",
            flush=True,
        )
        return

    run_ids = tuple(
        sorted(int(result.run_id) for result in relevant if result.run_id is not None)
    )
    started = time.monotonic()
    try:
        with SessionLocal() as session:
            evaluated, queued = evaluate_favorite_alerts(
                session,
                run_ids=run_ids,
                coverage_complete=True,
                minimum_drop_clp=settings.favorite_min_drop_clp,
            )
            session.commit()

        sent, failed = deliver_pending_favorite_alerts(
            SessionLocal=SessionLocal,
            telegram_bot_token=settings.telegram_bot_token,
            send_message_fn=send_message,
            limit=settings.favorite_alert_limit,
        )
        elapsed_ms = int((time.monotonic() - started) * 1000)
        print(
            "FAVORITOS PERSONALIZADOS · "
            f"evaluados={evaluated}, encolados={queued}, "
            f"enviados={sent}, fallidos={failed}, "
            f"duración={elapsed_ms / 1000:.1f}s.",
            flush=True,
        )
    except Exception as exc:
        print(
            f"⚠ Favoritos: no se pudo evaluar o enviar alertas: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
            flush=True,
        )


def _send_global_run_summary(
    *,
    SessionLocal,
    settings: Settings,
    results: list[CollectorExecution],
    wall_duration_ms: int,
) -> None:
    if not results:
        return
    try:
        message = build_global_run_summary(
            results,
            wall_duration_ms=wall_duration_ms,
        )
        payload_hash = hashlib.sha256(message.encode("utf-8")).hexdigest()
        run_token = "-".join(
            str(result.run_id) if result.run_id is not None else f"{result.key}-failed"
            for result in sorted(results, key=lambda item: item.key)
        )
        bundle = NotificationBundle(
            store_id=None,
            run_id=None,
            alert_type="global_run_summary",
            deduplication_key=f"global-run-summary:{run_token}",
            payload_hash=payload_hash,
            reason="resumen compacto de todos los collectors",
            messages=(message,),
        )
        sent, skipped, failed = deliver_notification_bundles(
            SessionLocal=SessionLocal,
            bundles=[bundle],
            telegram_bot_token=settings.telegram_bot_token,
            telegram_chat_id=settings.telegram_chat_id,
            send_message_fn=send_message,
        )
        print(
            f"Telegram resumen global: enviados={sent}, omitidos={skipped}, fallidos={failed}.",
            flush=True,
        )
    except Exception as exc:
        print(
            f"⚠ No se pudo enviar el resumen global: {type(exc).__name__}: {exc}",
            file=sys.stderr,
            flush=True,
        )



def _run_weekly_health_stage(
    *,
    SessionLocal,
    settings: Settings,
    timeout_minutes: int,
) -> None:
    if not settings.weekly_health_report:
        return
    now = datetime.now(timezone.utc)
    try:
        with SessionLocal() as session:
            last = latest_sent_alert(
                session, store_id=None, alert_type="weekly_health_report"
            )
            if last is not None and last.sent_at is not None:
                sent_at = last.sent_at
                if sent_at.tzinfo is None:
                    sent_at = sent_at.replace(tzinfo=timezone.utc)
                if now - sent_at < timedelta(hours=settings.weekly_health_interval_hours):
                    print("Reporte semanal de salud: todavía no corresponde.", flush=True)
                    return
            message = build_weekly_health_report(
                session, days=7, timeout_minutes=timeout_minutes
            )
        payload_hash = hashlib.sha256(message.encode("utf-8")).hexdigest()
        week_token = now.strftime("%G-W%V")
        bundle = NotificationBundle(
            store_id=None,
            run_id=None,
            alert_type="weekly_health_report",
            deduplication_key=f"weekly-health:{week_token}:{payload_hash[:12]}",
            payload_hash=payload_hash,
            reason="reporte semanal de salud de collectors",
            messages=(message,),
        )
        sent, skipped, failed = deliver_notification_bundles(
            SessionLocal=SessionLocal,
            bundles=[bundle],
            telegram_bot_token=settings.telegram_bot_token,
            telegram_chat_id=settings.telegram_chat_id,
            send_message_fn=send_message,
        )
        print(
            f"Reporte semanal de salud: enviados={sent}, omitidos={skipped}, fallidos={failed}.",
            flush=True,
        )
    except Exception as exc:
        print(
            f"⚠ No se pudo generar el reporte semanal: {type(exc).__name__}: {exc}",
            file=sys.stderr,
            flush=True,
        )


def _pipeline_exit_code(results: list[CollectorExecution]) -> int:
    """Una ejecución es operativa si existe al menos un catálogo actualizado o vigente."""

    return 0 if any(
        result.execution_state in {"UPDATED", "STALE", "DUE_SOON"}
        and result.success
        and not result.diagnostic_mode
        for result in results
    ) else 1


def run_pipeline() -> int:
    settings = Settings.from_env()
    performance = PerformanceSettings.from_env()
    engine, SessionLocal = create_database(settings.database_url)
    Base.metadata.create_all(engine)
    collectors = enabled_collectors()
    with SessionLocal() as session:
        changed_store_states = synchronize_active_stores(
            session, {collector.key for collector in collectors}
        )
        session.commit()
    pipeline_started = time.monotonic()

    print(f"Monitor de Licores v{__version__} · {RELEASE_NAME}", flush=True)
    print(
        f"Collectors habilitados: {', '.join(item.key for item in collectors)}",
        flush=True,
    )
    if changed_store_states:
        print(
            f"Tiendas activas sincronizadas: {changed_store_states} estado(s) actualizado(s).",
            flush=True,
        )
    print(
        f"Ejecución paralela: workers={min(performance.collector_workers, len(collectors))}; "
        f"bloqueo_recursos={'sí' if performance.block_browser_resources else 'no'}; "
        f"espera_producto={performance.product_wait_timeout_ms} ms; "
        f"límite_por_tienda={performance.collector_timeout_minutes} min.",
        flush=True,
    )
    print(
        "Alertas inteligentes: "
        f"baja ≥ {settings.alert_min_drop_pct:.1%} o "
        f"≥ ${settings.alert_min_drop_amount:,}; "
        f"digest cada {settings.telegram_digest_interval_hours} h."
        .replace(",", "."),
        flush=True,
    )
    print(
        "Comparador cross-store: "
        f"confianza ≥ {settings.cross_store_match_min_confidence:.0%}; "
        f"top={settings.telegram_comparison_limit}; packs excluidos.",
        flush=True,
    )
    print(
        "Favoritos personalizados: "
        f"baja mínima=${settings.favorite_min_drop_clp:,}; "
        f"máximo={settings.favorite_alert_limit} avisos por ejecución."
        .replace(",", "."),
        flush=True,
    )
    print(
        "Resiliencia de tiendas: "
        f"El Mundo del Vino cada {performance.el_mundo_interval_hours} h "
        f"(tolerancia {performance.scheduler_grace_minutes} min); "
        "La Barra deshabilitada; La Vinoteca activa; CAV en diagnóstico sin afectar comparador público.",
        flush=True,
    )

    results: list[CollectorExecution] = []
    due_collectors: list[Collector] = []
    for collector in collectors:
        scheduled = _scheduled_execution_or_none(
            collector=collector,
            SessionLocal=SessionLocal,
            performance=performance,
        )
        if scheduled is None:
            due_collectors.append(collector)
            continue
        results.append(scheduled)
        if scheduled.execution_state == "DUE_SOON":
            print(
                f"🕒 {collector.store_name}: revisión programada aún no vencida; "
                f"{scheduled.detail}",
                flush=True,
            )
        elif scheduled.execution_state == "STALE":
            print(
                f"🟠 {collector.store_name}: {scheduled.detail}",
                flush=True,
            )
        elif scheduled.execution_state == "PAUSED":
            print(f"⏸ {collector.store_name}: {scheduled.detail}", flush=True)

    worker_count = min(performance.collector_workers, len(due_collectors))
    if due_collectors:
        with ThreadPoolExecutor(
            max_workers=worker_count,
            thread_name_prefix="store-collector",
        ) as executor:
            futures = {
                executor.submit(
                    _run_collector,
                    collector=collector,
                    SessionLocal=SessionLocal,
                    settings=settings,
                    timeout_minutes=performance.collector_timeout_minutes,
                ): collector
                for collector in due_collectors
            }
            for future in as_completed(futures):
                collector = futures[future]
                try:
                    results.append(future.result())
                except Exception as exc:  # Defensa adicional fuera del worker.
                    results.append(
                        CollectorExecution(
                            key=collector.key,
                            store_name=collector.store_name,
                            success=False,
                            duration_ms=0,
                            error_message=f"{type(exc).__name__}: {exc}"[:1000],
                            execution_state="FAILED",
                        )
                    )
                    print(
                        f"✖ Fallo no controlado en {collector.key}: {exc}",
                        file=sys.stderr,
                        flush=True,
                    )
    else:
        print("No hay collectors con revisión vencida en este ciclo.", flush=True)

    # Confirmar inmediatamente en Telegram qué collectors terminaron, antes de
    # ejecutar matching, reindexación y favoritos. Así una etapa posterior lenta
    # no oculta tiendas correctas como Comercial JP.
    collector_wall_ms = int((time.monotonic() - pipeline_started) * 1000)
    _send_global_run_summary(
        SessionLocal=SessionLocal,
        settings=settings,
        results=results,
        wall_duration_ms=collector_wall_ms,
    )

    _run_cross_store_stage(SessionLocal=SessionLocal, settings=settings, results=results)
    _refresh_search_catalog_stage(SessionLocal=SessionLocal)
    _run_favorite_alert_stage(
        SessionLocal=SessionLocal,
        settings=settings,
        results=results,
    )
    _run_weekly_health_stage(
        SessionLocal=SessionLocal,
        settings=settings,
        timeout_minutes=performance.collector_timeout_minutes,
    )

    total_collectors = len(collectors)
    updated_count = sum(
        result.execution_state == "UPDATED" and result.success for result in results
    )
    stale_count = sum(result.execution_state == "STALE" for result in results)
    due_soon_count = sum(result.execution_state == "DUE_SOON" for result in results)
    paused_count = sum(result.execution_state == "PAUSED" for result in results)
    failed_count = sum(result.execution_state == "FAILED" for result in results)
    wall_ms = int((time.monotonic() - pipeline_started) * 1000)
    sequential_ms = sum(result.duration_ms for result in results)
    saved_ms = max(0, sequential_ms - wall_ms)

    print("=" * 64, flush=True)
    print("RESUMEN GLOBAL MULTI-TIENDA · PERFORMANCE", flush=True)
    print(f"Collectors registrados...: {total_collectors}", flush=True)
    print(f"Actualizados...............: {updated_count}", flush=True)
    print(f"Snapshots STALE...........: {stale_count}", flush=True)
    print(f"Programados DUE SOON......: {due_soon_count}", flush=True)
    print(f"Collectors pausados.......: {paused_count}", flush=True)
    print(f"Collectors fallidos.......: {failed_count}", flush=True)
    print(f"Duración de pared.........: {wall_ms / 1000:.1f} s", flush=True)
    print(f"Tiempo secuencial estimado: {sequential_ms / 1000:.1f} s", flush=True)
    print(f"Tiempo ahorrado paralelo..: {saved_ms / 1000:.1f} s", flush=True)
    labels = {
        "UPDATED": "OK",
        "STALE": "STALE",
        "DUE_SOON": "DUE",
        "PAUSED": "PAUSE",
        "FAILED": "ERROR",
    }
    for result in sorted(results, key=lambda item: item.key):
        status = labels.get(result.execution_state, "ERROR")
        print(
            f"{result.store_name:<20} {status:<5} "
            f"{result.duration_ms / 1000:>8.1f}s · productos={result.products_found}",
            flush=True,
        )
    print("=" * 64, flush=True)

    exit_code = _pipeline_exit_code(results)
    engine.dispose()
    # Una tienda caída no invalida los datos obtenidos correctamente por las demás.
    # Railway solo marcará el cron como fallido cuando ninguna tienda termine bien.
    return exit_code
