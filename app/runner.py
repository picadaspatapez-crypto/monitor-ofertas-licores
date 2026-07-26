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


def _offer_items(items: list[SavedProduct]) -> list[SavedProduct]:
    """Devuelve las ofertas con descuento informado, ordenadas de mayor a menor."""
    offers = [
        saved
        for saved in items
        if saved.item.regular_price is not None
        and saved.item.regular_price > saved.item.current_price
        and saved.item.discount_pct > 0
    ]

    return sorted(
        offers,
        key=lambda saved: (
            saved.item.discount_pct,
            saved.item.regular_price - saved.item.current_price,
        ),
        reverse=True,
    )


def _status_label(saved: SavedProduct) -> str:
    if saved.is_new:
        return "🆕 Nuevo"
    if saved.price_dropped:
        return "📉 Bajó de precio"
    return "Sin cambio"


def build_messages(
    saved_products: list[SavedProduct],
    total_products: int,
) -> list[str]:
    offers = _offer_items(saved_products)
    selected = offers[:REPORT_LIMIT]

    summary = [
        "📊 Monitor Licor3B actualizado",
        "",
        f"Productos revisados: {total_products}",
        f"Productos con descuento informado: {len(offers)}",
        f"Ofertas mostradas: {len(selected)}",
        "",
        "ℹ️ El porcentaje corresponde al descuento declarado por Licor3B.",
        "Aún no representa una comparación real con otras tiendas.",
    ]

    if not selected:
        summary.extend(
            [
                "",
                "No se encontraron productos con precio normal y precio oferta.",
                "Los precios igualmente quedaron guardados en PostgreSQL.",
            ]
        )
        return ["\n".join(summary)]

    messages = ["\n".join(summary)]

    for start in range(0, len(selected), ITEMS_PER_MESSAGE):
        group = selected[start : start + ITEMS_PER_MESSAGE]
        lines = [
            f"🏷️ Ofertas Licor3B {start + 1}-{start + len(group)}",
            "",
        ]

        for position, saved in enumerate(group, start=start + 1):
            item = saved.item
            saving = (
                item.regular_price - item.current_price
                if item.regular_price is not None
                else 0
            )

            lines.extend(
                [
                    f"{position}. {item.name}",
                    f"Precio oferta: {clp(item.current_price)}",
                    f"Precio normal informado: {clp(item.regular_price)}",
                    f"Descuento informado: {item.discount_pct:.0%}",
                    f"Ahorro informado: {clp(saving)}",
                    f"Estado: {_status_label(saved)}",
                    item.url,
                    "",
                ]
            )

        messages.append("\n".join(lines).rstrip())

    return messages


def run() -> int:
    settings = None
    engine = None
    SessionLocal = None
    scrape_run_id = None

    try:
        settings = Settings.from_env()
        engine, SessionLocal = create_database(settings.database_url)

        # Compatibilidad de arranque. Alembic continúa siendo la fuente
        # de verdad para la evolución del esquema.
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
                    session,
                    item,
                    store,
                    scrape_run,
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

        offers_count = len(_offer_items(saved_products))

        print(
            "Proceso completado. "
            f"Productos procesados: {len(scraped)}. "
            f"Ofertas con descuento informado: {offers_count}. "
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
