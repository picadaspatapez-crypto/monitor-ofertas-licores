import sys
from dataclasses import dataclass

from app.config import Settings
from app.database import Base, create_database
from app.models import Product, ScrapeRun, Store
from app.repository import (
    finish_scrape_run,
    get_or_create_store,
    save_product,
    start_scrape_run,
)
from app.scrapers.licor3b import ScrapedProduct, scrape
from app.services.telegram import send_message


REPORT_LIMIT = 20
ITEMS_PER_MESSAGE = 10


@dataclass
class SavedProduct:
    item: ScrapedProduct
    product: Product
    is_new: bool
    price_dropped: bool


def clp(value: int) -> str:
    return "$" + f"{value:,}".replace(",", ".")


def _status_label(saved: SavedProduct) -> str:
    if saved.is_new:
        return "🆕 Nuevo"
    if saved.price_dropped:
        return "📉 Bajó de precio"
    return "Sin cambio"


def _ranked_items(items: list[SavedProduct]) -> list[SavedProduct]:
    """
    Prioridad:
    1. Descuento informado disponible.
    2. Productos que bajaron de precio.
    3. Productos nuevos.
    4. Menor precio actual.
    """
    return sorted(
        items,
        key=lambda saved: (
            saved.item.regular_price is not None
            and saved.item.discount_pct > 0,
            saved.item.discount_pct,
            saved.price_dropped,
            saved.is_new,
            -saved.item.current_price,
        ),
        reverse=True,
    )


def build_messages(
    saved_products: list[SavedProduct],
    total_products: int,
) -> list[str]:
    selected = _ranked_items(saved_products)[:REPORT_LIMIT]
    with_reported_discount = sum(
        1
        for saved in saved_products
        if saved.item.regular_price is not None
        and saved.item.discount_pct > 0
    )

    summary = [
        "📊 Monitor Licor3B actualizado",
        "",
        f"Productos revisados: {total_products}",
        f"Con descuento informado: {with_reported_discount}",
        f"Productos mostrados: {len(selected)}",
        "",
        "ℹ️ Todos pertenecen a la categoría Ofertas de Licor3B.",
        "El descuento informado solo aparece cuando la tienda publica",
        "precio normal y precio actual.",
    ]

    if not selected:
        summary.extend(
            [
                "",
                "No fue posible obtener productos para mostrar.",
                "Revisa los logs de Railway.",
            ]
        )
        return ["\n".join(summary)]

    messages = ["\n".join(summary)]

    for start in range(0, len(selected), ITEMS_PER_MESSAGE):
        group = selected[start : start + ITEMS_PER_MESSAGE]
        lines = [
            f"🏷️ Productos en oferta {start + 1}-{start + len(group)}",
            "",
        ]

        for position, saved in enumerate(group, start=start + 1):
            item = saved.item

            lines.extend(
                [
                    f"{position}. {item.name}",
                    f"Precio actual: {clp(item.current_price)}",
                ]
            )

            if item.regular_price is not None and item.discount_pct > 0:
                saving = item.regular_price - item.current_price
                lines.extend(
                    [
                        f"Precio normal informado: {clp(item.regular_price)}",
                        f"Descuento informado: {item.discount_pct:.0%}",
                        f"Ahorro informado: {clp(saving)}",
                    ]
                )
            else:
                lines.append("Descuento informado: no disponible")

            lines.extend(
                [
                    f"Estado: {_status_label(saved)}",
                    item.url,
                    "",
                ]
            )

        messages.append("\n".join(lines).rstrip())

    return messages


def run() -> int:
    settings = None
    SessionLocal = None
    scrape_run_id = None

    try:
        settings = Settings.from_env()
        engine, SessionLocal = create_database(settings.database_url)
        Base.metadata.create_all(engine)

        with SessionLocal() as session:
            store = get_or_create_store(session)
            scrape_run = start_scrape_run(session, store)
            scrape_run_id = scrape_run.id
            session.commit()

        scraped = scrape()
        saved_products: list[SavedProduct] = []
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

                saved_products.append(
                    SavedProduct(
                        item=item,
                        product=product,
                        is_new=is_new,
                        price_dropped=price_dropped,
                    )
                )

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

        messages = build_messages(saved_products, len(scraped))

        for message in messages:
            send_message(
                settings.telegram_bot_token,
                settings.telegram_chat_id,
                message,
            )

        print(
            "Proceso completado. "
            f"Productos procesados: {len(scraped)}. "
            f"Mensajes Telegram: {len(messages)}"
        )
        return 0

    except Exception as exc:
        if SessionLocal is not None and scrape_run_id is not None:
            try:
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
                    "No se pudo registrar el error de ejecución: "
                    f"{tracking_error}",
                    file=sys.stderr,
                )

        print(f"Error: {exc}", file=sys.stderr)
        return 1
