from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain import CollectedProduct, SavedProduct
from app.matching import normalize_product_name
from app.models import MasterProduct, PriceObservation, Product, ProductMatch, ScrapeRun, Store
from app.repositories.common import utcnow


def _get_or_create_master_product(session: Session, source_name: str) -> MasterProduct:
    normalized = normalize_product_name(source_name)
    master = session.scalar(
        select(MasterProduct).where(MasterProduct.normalized_key == normalized.normalized_key)
    )
    if master is not None:
        return master

    master = MasterProduct(
        canonical_name=normalized.canonical_name,
        normalized_key=normalized.normalized_key,
        volume_ml=normalized.volume_ml,
        status="active",
    )
    session.add(master)
    session.flush()
    return master


def _link_master_product(session: Session, product: Product, master: MasterProduct) -> None:
    product.master_product_id = master.id
    match = session.scalar(
        select(ProductMatch).where(ProductMatch.store_product_id == product.id)
    )
    if match is None:
        session.add(ProductMatch(
            store_product_id=product.id,
            master_product_id=master.id,
            confidence=1.0,
            matching_method="exact_normalized",
            review_status="automatic",
        ))
    else:
        match.master_product_id = master.id
        match.confidence = 1.0
        match.matching_method = "exact_normalized"


def save_product(
    session: Session,
    item: CollectedProduct,
    store: Store,
    scrape_run: ScrapeRun,
) -> SavedProduct:
    product = session.scalar(select(Product).where(Product.store == item.store, Product.url == item.url))
    is_new = product is None
    previous_price = None if product is None else product.current_price

    if product is None:
        product = Product(
            store=item.store, store_id=store.id, name=item.name, url=item.url,
            current_price=item.current_price, regular_price=item.regular_price,
            discount_pct=item.discount_pct,
        )
        session.add(product)
        session.flush()
    else:
        product.store_id = store.id
        product.name = item.name
        product.current_price = item.current_price
        product.regular_price = item.regular_price
        product.discount_pct = item.discount_pct
        product.last_seen_at = utcnow()

    master = _get_or_create_master_product(session, item.name)
    _link_master_product(session, product, master)
    session.add(PriceObservation(
        product=product, scrape_run_id=scrape_run.id, price=item.current_price,
        regular_price=item.regular_price, discount_pct=item.discount_pct,
    ))
    return SavedProduct(
        item=item,
        product=product,
        is_new=is_new,
        previous_price=previous_price,
    )


def count_missing_products(session: Session, store: Store, scrape_run: ScrapeRun) -> int:
    """Productos conocidos que no fueron observados durante la ejecución actual."""
    observed_ids = select(PriceObservation.product_id).where(
        PriceObservation.scrape_run_id == scrape_run.id
    )
    return int(session.scalar(
        select(func.count(Product.id)).where(
            Product.store_id == store.id,
            Product.id.not_in(observed_ids),
        )
    ) or 0)
