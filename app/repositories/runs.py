from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ScrapeRun, Store
from app.repositories.common import utcnow


def start_scrape_run(session: Session, store: Store) -> ScrapeRun:
    run = ScrapeRun(store_id=store.id, status="running")
    session.add(run)
    session.flush()
    return run


def previous_successful_product_count(session: Session, store: Store, current_run_id: int) -> int | None:
    value = session.scalar(
        select(ScrapeRun.products_found)
        .where(
            ScrapeRun.store_id == store.id,
            ScrapeRun.status == "success",
            ScrapeRun.id != current_run_id,
        )
        .order_by(ScrapeRun.finished_at.desc())
        .limit(1)
    )
    return int(value) if value is not None else None


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
    metrics: dict | None = None,
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

    if metrics:
        run.sections_discovered = int(metrics.get("sections_discovered", 0))
        run.sections_visited = int(metrics.get("sections_visited", 0))
        run.sections_succeeded = int(metrics.get("sections_succeeded", 0))
        run.sections_failed = int(metrics.get("sections_failed", 0))
        run.pages_visited = int(metrics.get("pages_visited", 0))
        run.cards_seen = int(metrics.get("cards_seen", 0))
        run.duplicates_removed = int(metrics.get("duplicates_removed", 0))
        run.structural_warnings = int(metrics.get("structural_warnings", 0))
        run.health_status = metrics.get("health_status")
        run.health_score = metrics.get("health_score")
        run.metrics_json = metrics
