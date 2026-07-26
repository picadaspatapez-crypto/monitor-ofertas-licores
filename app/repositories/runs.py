from sqlalchemy.orm import Session

from app.models import ScrapeRun, Store
from app.repositories.common import utcnow


def start_scrape_run(session: Session, store: Store) -> ScrapeRun:
    run = ScrapeRun(store_id=store.id, status="running")
    session.add(run)
    session.flush()
    return run


def finish_scrape_run(
    run: ScrapeRun,
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
    run.status = status
    run.finished_at = finished_at
    run.duration_ms = int((finished_at - run.started_at).total_seconds() * 1000)
    run.products_found = products_found
    run.products_created = products_created
    run.products_updated = products_updated
    run.products_failed = products_failed
    run.price_changes = price_changes
    run.error_message = error_message
