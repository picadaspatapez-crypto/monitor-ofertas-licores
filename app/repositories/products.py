from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain import CollectedProduct, SavedProduct
from app.intelligence.quality import apply_quality_assessment
from app.matching import normalize_product_name
from app.models import (MasterProduct, PriceObservation, PriceQuoteObservation, Product, ProductMatch, ProductPriceQuote, ScrapeRun, Store)
from app.repositories.common import utcnow


def _new_master_values(source_name: str) -> tuple[object, dict]:
    """Return normalized product data and the values used for a master row."""
    normalized = normalize_product_name(source_name)
    values = {
        "canonical_name": normalized.canonical_name,
        "normalized_key": normalized.normalized_key,
        "volume_ml": normalized.volume_ml,
        "status": "active",
    }
    return normalized, values


def _postgresql_get_or_create_master_id(session: Session, values: dict) -> int:
    """Create/reuse a master product in a short independent transaction.

    Store collectors persist in parallel and each uses its own long-running session.
    Creating master rows inside those sessions can race on ``normalized_key`` and can
    also keep unique-index locks until the whole store commits.  The short transaction
    below makes the operation atomic and releases its lock immediately.
    """
    bind = session.get_bind()
    engine = getattr(bind, "engine", bind)

    statement = (
        postgresql_insert(MasterProduct)
        .values(**values)
        .on_conflict_do_nothing(index_elements=[MasterProduct.normalized_key])
        .returning(MasterProduct.id)
    )

    with engine.begin() as connection:
        master_id = connection.scalar(statement)
        if master_id is None:
            master_id = connection.scalar(
                select(MasterProduct.id).where(
                    MasterProduct.normalized_key == values["normalized_key"]
                )
            )

    if master_id is None:
        raise RuntimeError(
            "No se pudo crear ni recuperar el producto maestro para "
            f"normalized_key={values['normalized_key']!r}."
        )
    return int(master_id)


def _get_or_create_master_product(session: Session, source_name: str) -> MasterProduct:
    normalized, values = _new_master_values(source_name)
    master = session.scalar(
        select(MasterProduct).where(
            MasterProduct.normalized_key == normalized.normalized_key
        )
    )
    if master is not None:
        return master

    dialect_name = session.get_bind().dialect.name
    if dialect_name == "postgresql":
        master_id = _postgresql_get_or_create_master_id(session, values)
        master = session.get(MasterProduct, master_id)
        if master is None:
            # READ COMMITTED sees the independently committed row on this statement.
            master = session.scalar(
                select(MasterProduct).where(
                    MasterProduct.normalized_key == normalized.normalized_key
                )
            )
        if master is None:
            raise RuntimeError(
                "El producto maestro fue confirmado en PostgreSQL, pero no pudo "
                "recuperarse desde la sesión de persistencia."
            )
        return master

    # Portable fallback for tests and non-PostgreSQL installations.  A savepoint
    # prevents a concurrent unique violation from invalidating the outer transaction.
    try:
        with session.begin_nested():
            master = MasterProduct(**values)
            session.add(master)
            session.flush()
        return master
    except IntegrityError:
        master = session.scalar(
            select(MasterProduct).where(
                MasterProduct.normalized_key == normalized.normalized_key
            )
        )
        if master is None:
            raise
        return master


def _link_master_product(session: Session, product: Product, master: MasterProduct) -> None:
    product.master_product_id = master.id
    match = session.scalar(
        select(ProductMatch).where(ProductMatch.store_product_id == product.id)
    )
    if match is None:
        session.add(
            ProductMatch(
                store_product_id=product.id,
                master_product_id=master.id,
                confidence=1.0,
                matching_method="exact_normalized",
                review_status="automatic",
            )
        )
    else:
        match.master_product_id = master.id
        match.confidence = 1.0
        match.matching_method = "exact_normalized"



def _persist_price_quotes(session: Session, item: CollectedProduct, product: Product, scrape_run: ScrapeRun) -> None:
    quotes = item.price_quotes
    if not quotes:
        from app.domain import CollectedPriceQuote
        quotes = (CollectedPriceQuote(
            price=item.current_price, regular_price=item.regular_price,
            price_type="PUBLIC", audience_key="public", eligibility_required=False,
        ),)

    active_contexts: set[tuple[str, str]] = set()
    now = utcnow()
    for quote in quotes:
        if int(quote.price) <= 0:
            continue
        price_type = (quote.price_type or "PUBLIC").strip().upper()[:30]
        audience_key = (quote.audience_key or "public").strip().casefold()[:80]
        key = (price_type, audience_key)
        active_contexts.add(key)
        row = session.scalar(
            select(ProductPriceQuote).where(
                ProductPriceQuote.product_id == product.id,
                ProductPriceQuote.price_type == price_type,
                ProductPriceQuote.audience_key == audience_key,
            )
        )
        if row is None:
            row = ProductPriceQuote(
                product_id=product.id, price_type=price_type, audience_key=audience_key
            )
            session.add(row)
        row.price = int(quote.price)
        row.regular_price = quote.regular_price
        row.eligibility_required = bool(quote.eligibility_required)
        row.is_active = True
        row.observed_at = now
        session.add(PriceQuoteObservation(
            product_id=product.id, scrape_run_id=scrape_run.id,
            price=int(quote.price), regular_price=quote.regular_price,
            price_type=price_type, audience_key=audience_key,
            eligibility_required=bool(quote.eligibility_required), observed_at=now,
        ))

    if active_contexts:
        for row in session.scalars(select(ProductPriceQuote).where(ProductPriceQuote.product_id == product.id)):
            if (row.price_type, row.audience_key) not in active_contexts:
                row.is_active = False


def save_product(
    session: Session,
    item: CollectedProduct,
    store: Store,
    scrape_run: ScrapeRun,
) -> SavedProduct:
    product = session.scalar(
        select(Product).where(Product.store == item.store, Product.url == item.url)
    )
    is_new = product is None
    previous_price = None if product is None else product.current_price

    if product is None:
        product = Product(
            store=item.store,
            store_id=store.id,
            name=item.name,
            url=item.url,
            current_price=item.current_price,
            regular_price=item.regular_price,
            discount_pct=item.discount_pct,
            sku=item.sku,
            ean=item.ean,
            is_available=True,
            missing_streak=0,
            last_available_at=utcnow(),
            last_confirmed_run_id=scrape_run.id,
        )
        session.add(product)
        session.flush()
    else:
        product.store_id = store.id
        product.name = item.name
        product.current_price = item.current_price
        product.regular_price = item.regular_price
        product.discount_pct = item.discount_pct
        product.sku = item.sku or product.sku
        product.ean = item.ean or product.ean
        product.last_seen_at = utcnow()

    master = _get_or_create_master_product(session, item.name)
    if item.ean and not master.ean:
        master.ean = item.ean
    _link_master_product(session, product, master)
    apply_quality_assessment(
        session, product=product, scrape_run=scrape_run, previous_price=previous_price
    )
    _persist_price_quotes(session, item, product, scrape_run)
    session.add(
        PriceObservation(
            product=product,
            scrape_run_id=scrape_run.id,
            price=item.current_price,
            regular_price=item.regular_price,
            discount_pct=item.discount_pct,
        )
    )
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
    return int(
        session.scalar(
            select(func.count(Product.id)).where(
                Product.store_id == store.id,
                Product.id.not_in(observed_ids),
            )
        )
        or 0
    )
