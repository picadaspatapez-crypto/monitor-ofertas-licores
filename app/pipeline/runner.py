from __future__ import annotations

import sys

from app.analyzers import analyze_catalog
from app.collectors.registry import enabled_collectors
from app.config import Settings
from app.database import Base, create_database
from app.models import ScrapeRun, Store
from app.reports import build_telegram_messages
from app.repositories import finish_scrape_run, get_or_create_store, save_product, start_scrape_run
from app.services.telegram import send_message


def _store_metadata(collector_key: str) -> dict[str, object]:
    if collector_key == "licor3b":
        return {
            "name": "Licor3B", "slug": "licor3b", "base_url": "https://licor3b.cl/",
            "connector_key": "licor3b", "requires_browser": True,
        }
    raise RuntimeError(f"Collector sin metadatos: {collector_key}")


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

            collected = collector.collect()
            saved = []
            created = updated = price_changes = 0

            with SessionLocal() as session:
                store = get_or_create_store(session, **meta)
                run = session.get(ScrapeRun, run_id)
                if run is None:
                    raise RuntimeError("No se pudo recuperar la ejecución activa.")
                for item in collected:
                    result = save_product(session, item, store, run)
                    saved.append(result)
                    created += int(result.is_new)
                    updated += int(not result.is_new)
                    price_changes += int(result.price_dropped)
                finish_scrape_run(run, status="success", products_found=len(collected),
                    products_created=created, products_updated=updated, price_changes=price_changes)
                store.last_success_at = run.finished_at
                session.commit()

            analysis = analyze_catalog(saved)
            for message in build_telegram_messages(store_name=collector.store_name, items=saved, analysis=analysis):
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
