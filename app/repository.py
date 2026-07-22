from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import PriceObservation, Product
from app.scrapers.licor3b import ScrapedProduct


def save_product(session: Session, item: ScrapedProduct) -> tuple[Product, bool, bool]:
    existing = session.scalar(
        select(Product).where(
            Product.store == item.store,
            Product.url == item.url,
        )
    )

    is_new = existing is None
    price_dropped = False

    if existing is None:
        existing = Product(
            store=item.store,
            name=item.name,
            url=item.url,
            current_price=item.current_price,
            regular_price=item.regular_price,
            discount_pct=item.discount_pct,
        )
        session.add(existing)
        session.flush()
    else:
        price_dropped = item.current_price < existing.current_price
        existing.name = item.name
        existing.current_price = item.current_price
        existing.regular_price = item.regular_price
        existing.discount_pct = item.discount_pct
        existing.last_seen_at = datetime.utcnow()

    session.add(
        PriceObservation(
            product=existing,
            price=item.current_price,
            regular_price=item.regular_price,
            discount_pct=item.discount_pct,
        )
    )

    return existing, is_new, price_dropped
