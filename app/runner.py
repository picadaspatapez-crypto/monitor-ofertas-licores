import sys

from app.config import Settings
from app.database import Base, create_database
from app.repository import save_product
from app.scrapers.licor3b import ScrapedProduct, scrape
from app.services.telegram import send_message


def clp(value: int) -> str:
    return "$" + f"{value:,}".replace(",", ".")


def qualifies(item: ScrapedProduct, settings: Settings) -> bool:
    return (
        item.current_price <= settings.max_product_price
        and item.discount_pct >= settings.min_target_margin
    )


def build_message(
    new_candidates: list[ScrapedProduct],
    dropped_candidates: list[ScrapedProduct],
    total: int,
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
                "No hay oportunidades nuevas ni bajas de precio que cumplan los filtros.",
                "Los precios quedaron guardados en PostgreSQL.",
            ]
        )
        return "\n".join(lines)

    lines.append("")
    for item in selected:
        units = min(3, 100000 // item.current_price)
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
    try:
        settings = Settings.from_env()
        engine, SessionLocal = create_database(settings.database_url)
        Base.metadata.create_all(engine)

        scraped = scrape()
        new_candidates: list[ScrapedProduct] = []
        dropped_candidates: list[ScrapedProduct] = []

        with SessionLocal() as session:
            for item in scraped:
                _, is_new, price_dropped = save_product(session, item)

                if qualifies(item, settings):
                    if is_new:
                        new_candidates.append(item)
                    elif price_dropped:
                        dropped_candidates.append(item)

            session.commit()

        message = build_message(
            new_candidates=new_candidates,
            dropped_candidates=dropped_candidates,
            total=len(scraped),
        )
        send_message(
            settings.telegram_bot_token,
            settings.telegram_chat_id,
            message,
        )

        print(f"Proceso completado. Productos procesados: {len(scraped)}")
        return 0

    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
