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
    if saved.price_dropped:
        return "📉 Bajó de precio"
    if saved.is_new:
        return "🆕 Nuevo"
    return "Sin cambio"


def _reported_discount(saved: SavedProduct) -> bool:
    return (
        saved.item.regular_price is not None
        and saved.item.regular_price > saved.item.current_price
        and saved.item.discount_pct > 0
    )


def _ranked_items(items: list[SavedProduct]) -> list[SavedProduct]:
    """
    Orden de prioridad:
    1. Mayor descuento informado por la tienda.
    2. Productos que bajaron frente a la observación anterior.
    3. Productos nuevos.
    4. Nombre alfabético.

    El precio actual no se utiliza como criterio de orden.
    """
    return sorted(
        items,
        key=lambda saved: (
            0 if _reported_discount(saved) else 1,
            -saved.item.discount_pct if _reported_discount(saved) else 0,
            0 if saved.price_dropped else 1,
            0 if saved.is_new else 1,
            saved.item.name.casefold(),
        ),
    )


def build_messages(
    saved_products: list[SavedProduct],
    total_products: int,
) -> list[str]:
    selected = _ranked_items(saved_products)[:REPORT_LIMIT]

    reported_discount_count = sum(
        1 for saved in saved_products if _reported_discount(saved)
    )
    dropped_count = sum(
        1 for saved in saved_products if saved.price_dropped
    )
    new_count = sum(
        1 for saved in saved_products if saved.is_new
    )

    summary = [
        "📊 Monitor Licor3B actualizado",
        "",
        f"Productos revisados: {total_products}",
        f"Con descuento informado: {reported_discount_count}",
        f"Bajaron de precio: {dropped_count}",
        f"Productos nuevos: {new_count}",
        f"Productos mostrados: {len(selected)}",
        "",
        "ℹ️ Orden: descuento informado, bajas reales, nuevos y alfabético.",
        "El precio no se usa para seleccionar los productos mostrados.",
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
            f"🏷️ Productos destacados {start + 1}-{start + len(group)}",
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

            if _reported_discount(saved):
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
