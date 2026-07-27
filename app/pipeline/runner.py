from __future__ import annotations

import sys
from dataclasses import replace

from app.analyzers import analyze_catalog
from app.collectors.registry import enabled_collectors
from app.config import Settings
from app.database import Base, create_database
from app.models import ScrapeRun, Store
from app.reports import build_telegram_messages
from app.repositories import (
    count_missing_products,
    finish_scrape_run,
    get_or_create_store,
    previous_successful_product_count,
    save_product,
    start_scrape_run,
)
from app.services.telegram import send_message


def _store_metadata(collector_key: str) -> dict[str, object]:
    if collector_key == "licor3b":
        return {
            "name": "Licor3B", "slug": "licor3b", "base_url": "https://licor3b.cl/",
            "connector_key": "licor3b", "requires_browser": True,
        }
    raise RuntimeError(f"Collector sin metadatos: {collector_key}")


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
        status, score = "BROKEN", min(score, 25)
    elif ratio < 0.70 and status == "HEALTHY":
        status, score = "DEGRADED", min(score, 60)
    return replace(stats, health_status=status, health_score=score)


def _print_summary(*, name: str, analysis) -> None:
    stats = analysis.collection_stats
    icon = {"HEALTHY": "🟢", "DEGRADED": "🟡", "BROKEN": "🔴"}.get(stats.health_status, "⚪")
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
    print(f"Salud collector........: {icon} {stats.health_status} ({stats.health_score}/100)", flush=True)
    print("=" * 58, flush=True)


def run_pipeline() -> int:
    settings = Settings.from_env()
    engine, SessionLocal = create_database(settings.database_url)
    Base.metadata.create_all(engine)
    failures = 0

    for collector in enabled_collectors():
        run_id = None
        meta = _store_metadata(collector.key)
        try:
            with SessionLocal() as session:
                store = get_or_create_store(session, **meta)
                run = start_scrape_run(session, store)
                run_id = run.id
                session.commit()

            batch = collector.collect()
            collected = batch.products
            saved = []
            created = updated = price_changes = 0

            with SessionLocal() as session:
                store = get_or_create_store(session, **meta)
                run = session.get(ScrapeRun, run_id)
                if run is None:
                    raise RuntimeError("No se pudo recuperar la ejecución activa.")
                previous_count = previous_successful_product_count(session, store, run.id)
                final_stats = _apply_historical_health(batch.stats, previous_count)

                for item in collected:
                    result = save_product(session, item, store, run)
                    saved.append(result)
                    created += int(result.is_new)
                    updated += int(not result.is_new)
                    price_changes += int(result.price_changed)

                session.flush()
                missing_products = count_missing_products(session, store, run)
                metrics = _metrics_dict(final_stats, previous_count)
                finish_scrape_run(
                    run,
                    status="success" if final_stats.health_status != "BROKEN" else "degraded",
                    products_found=len(collected),
                    products_created=created,
                    products_updated=updated,
                    price_changes=price_changes,
                    metrics=metrics,
                )
                store.last_success_at = run.finished_at
                duration_ms = run.duration_ms or 0
                session.commit()

            analysis = analyze_catalog(
                saved,
                missing_products=missing_products,
                duration_ms=duration_ms,
                collection_stats=final_stats,
            )
            _print_summary(name=collector.store_name, analysis=analysis)
            for message in build_telegram_messages(
                store_name=collector.store_name,
                items=saved,
                analysis=analysis,
            ):
                send_message(settings.telegram_bot_token, settings.telegram_chat_id, message)
            print(f"Pipeline {collector.key} completado. Productos: {len(collected)}.", flush=True)

        except Exception as exc:
            failures += 1
            if run_id is not None:
                try:
                    with SessionLocal() as session:
                        run = session.get(ScrapeRun, run_id)
                        if run is not None and run.status == "running":
                            finish_scrape_run(run, status="failed", error_message=str(exc)[:2000])
                            store = session.get(Store, run.store_id)
                            if store is not None:
                                store.last_error_at = run.finished_at
                            session.commit()
                except Exception as tracking_error:
                    print(f"No se pudo registrar el error: {tracking_error}", file=sys.stderr)
            print(f"Error en collector {collector.key}: {exc}", file=sys.stderr)

    return 1 if failures else 0
