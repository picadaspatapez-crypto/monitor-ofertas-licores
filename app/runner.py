import sys
from dataclasses import dataclass

from app.config import Settings
from app.database import Base, create_database
from app.models import Alert, Product, ScrapeRun
from app.repository import (
    finish_scrape_run,
    get_or_create_store,
    mark_alerts_failed,
    mark_alerts_sent,
    reserve_alert,
    save_product,
    start_scrape_run,
)
from app.scrapers.licor3b import ScrapedProduct, scrape
from app.services.telegram import send_message


@dataclass
class Candidate:
    item: ScrapedProduct
    product: Product
    alert: Alert


def clp(value: int) -> str:
    return "$" + f"{value:,}".replace(",", ".")


def qualifies(item: ScrapedProduct, settings: Settings) -> bool:
    return (
        item.current_price <= settings.max_product_price
        and item.discount_pct >= settings.min_target_margin
    )


def build_message(
    new_candidates: list[Candidate],
    dropped_candidates: list[Candidate],
    total: int,
    settings: Settings,
) -> str:
    lines = [
        "📊 Monitor Licor3B actualizado",
        "",
        f"Productos revisados: {total}",
        f"Nuevas oportunidades: {len(new_candidates)}",
        f"Bajas de precio: {len(dropped_candidates)}",
    ]

    selected = new_candidates[:5] + dropped_candidates[:5]

    if not selected:
        lines.extend(
            [
                "",
                "No hay alertas nuevas que cumplan los filtros.",
                "Los precios quedaron guardados en PostgreSQL.",
            ]
        )
        return "\n".join(lines)

    lines.append("")
    for candidate in selected:
        item = candidate.item
        units = min(
            settings.max_units_per_product,
            settings.total_budget // item.current_price,
        )
        lines.extend(
            [
                f"• {item.name}",
                f"  Precio: {clp(item.current_price)}",
                f"  Descuento: {item.discount_pct:.0%}",
                f"  Compra posible: {units} unidad(es)",
                f"  {item.url}",
                "",
            ]
        )

    return "\n".join(lines)


def run() -> int:
    settings = None
    engine = None
    SessionLocal = None
    scrape_run_id = None

    try:
        settings = Settings.from_env()
        engine, SessionLocal = create_database(settings.database_url)
        # Compatibilidad de arranque. Alembic será la fuente de verdad del esquema.
        Base.metadata.create_all(engine)

        with SessionLocal() as session:
            store = get_or_create_store(session)
            scrape_run = start_scrape_run(session, store)
            scrape_run_id = scrape_run.id
            session.commit()

        scraped = scrape()
        new_candidates: list[Candidate] = []
        dropped_candidates: list[Candidate] = []
        created = 0
        updated = 0
        price_changes = 0

        with SessionLocal() as session:
            store = get_or_create_store(session)
            scrape_run = session.get(ScrapeRun, scrape_run_id)
            if scrape_run is None:
                raise RuntimeError("No se pudo recuperar la ejecución activa.")

            for item in scraped:
                product, is_new, price_dropped = save_product(
                    session, item, store, scrape_run
                )
                created += int(is_new)
                updated += int(not is_new)
                price_changes += int(price_dropped)

                if not qualifies(item, settings):
                    continue

                alert_type = "new_opportunity" if is_new else "price_drop"
                if not (is_new or price_dropped):
                    continue

                alert = reserve_alert(
                    session,
                    product,
                    alert_type=alert_type,
                    reason=(
                        "Producto nuevo que cumple los filtros"
                        if is_new
                        else "Baja de precio que cumple los filtros"
                    ),
                )
                if alert is None:
                    continue

                candidate = Candidate(item=item, product=product, alert=alert)
                if is_new:
                    new_candidates.append(candidate)
                else:
                    dropped_candidates.append(candidate)

            finish_scrape_run(
                scrape_run,
                status="success",
                products_found=len(scraped),
                products_created=created,
                products_updated=updated,
                price_changes=price_changes,
            )
            store.last_success_at = scrape_run.finished_at
            session.commit()

        selected = new_candidates[:5] + dropped_candidates[:5]
        message = build_message(
            new_candidates,
            dropped_candidates,
            len(scraped),
            settings,
        )

        try:
            send_message(
                settings.telegram_bot_token,
                settings.telegram_chat_id,
                message,
            )
        except Exception as telegram_error:
            if selected:
                with SessionLocal() as session:
                    alerts = [session.get(Alert, c.alert.id) for c in selected]
                    valid_alerts = [a for a in alerts if a is not None]
                    mark_alerts_failed(valid_alerts, str(telegram_error))
                    session.commit()
            raise

        if selected:
            with SessionLocal() as session:
                alerts = [session.get(Alert, c.alert.id) for c in selected]
                valid_alerts = [a for a in alerts if a is not None]
                mark_alerts_sent(valid_alerts)
                session.commit()

        print(f"Proceso completado. Productos procesados: {len(scraped)}")
        return 0

    except Exception as exc:
        if SessionLocal is not None and scrape_run_id is not None:
            try:
                from app.models import ScrapeRun, Store

                with SessionLocal() as session:
                    scrape_run = session.get(ScrapeRun, scrape_run_id)
                    if scrape_run is not None and scrape_run.status == "running":
                        finish_scrape_run(
                            scrape_run,
                            status="failed",
                            error_message=str(exc)[:2000],
                        )
                        store = session.get(Store, scrape_run.store_id)
                        if store is not None:
                            store.last_error_at = scrape_run.finished_at
                        session.commit()
            except Exception as tracking_error:
                print(
                    f"No se pudo registrar el error de ejecución: {tracking_error}",
                    file=sys.stderr,
                )

        print(f"Error: {exc}", file=sys.stderr)
        return 1
