from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Alert, PriceObservation, Product, ScrapeRun, Store
from app.scrapers.licor3b import ScrapedProduct


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def get_or_create_store(session: Session) -> Store:
    store = session.scalar(select(Store).where(Store.slug == "licor3b"))
    if store is not None:
        return store

    store = Store(
        name="Licor3B",
        slug="licor3b",
        base_url="https://licor3b.cl/",
        connector_key="licor3b",
        is_active=True,
        requires_browser=False,
        country_code="CL",
        currency_code="CLP",
    )
    session.add(store)
    session.flush()
    return store


def start_scrape_run(session: Session, store: Store) -> ScrapeRun:
    scrape_run = ScrapeRun(store_id=store.id, status="running")
    session.add(scrape_run)
    session.flush()
    return scrape_run


def finish_scrape_run(
    scrape_run: ScrapeRun,
    *,
    status: str,
    products_found: int = 0,
    products_created: int = 0,
    products_updated: int = 0,
    products_failed: int = 0,
    price_changes: int = 0,
    error_message: str | None = None,
) -> None:
    finished_at = utcnow()
    scrape_run.status = status
    scrape_run.finished_at = finished_at
    scrape_run.duration_ms = int(
        (finished_at - scrape_run.started_at).total_seconds() * 1000
    )
    scrape_run.products_found = products_found
    scrape_run.products_created = products_created
    scrape_run.products_updated = products_updated
    scrape_run.products_failed = products_failed
    scrape_run.price_changes = price_changes
    scrape_run.error_message = error_message


def save_product(
    session: Session,
    item: ScrapedProduct,
    store: Store,
    scrape_run: ScrapeRun,
) -> tuple[Product, bool, bool]:
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
            store_id=store.id,
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
        existing.store_id = store.id
        existing.name = item.name
        existing.current_price = item.current_price
        existing.regular_price = item.regular_price
        existing.discount_pct = item.discount_pct
        existing.last_seen_at = utcnow()

    session.add(
        PriceObservation(
            product=existing,
            scrape_run_id=scrape_run.id,
            price=item.current_price,
            regular_price=item.regular_price,
            discount_pct=item.discount_pct,
        )
    )

    return existing, is_new, price_dropped


def reserve_alert(
    session: Session,
    product: Product,
    *,
    alert_type: str,
    reason: str,
) -> Alert | None:
    key = f"{product.id}:{alert_type}:{product.current_price}"
    existing = session.scalar(
        select(Alert).where(Alert.deduplication_key == key)
    )
    if existing is not None:
        return None

    alert = Alert(
        product_id=product.id,
        alert_type=alert_type,
        status="pending",
        channel="telegram",
        price=product.current_price,
        reason=reason,
        deduplication_key=key,
    )
    session.add(alert)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        return None
    return alert


def mark_alerts_sent(alerts: list[Alert]) -> None:
    sent_at = utcnow()
    for alert in alerts:
        alert.status = "sent"
        alert.sent_at = sent_at


def mark_alerts_failed(alerts: list[Alert], error: str) -> None:
    failed_at = utcnow()
    for alert in alerts:
        alert.status = "failed"
        alert.failed_at = failed_at
        alert.error_message = error[:2000]
