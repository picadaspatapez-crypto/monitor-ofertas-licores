from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import PriceObservation, Product, ScrapeRun, Store
from app.repositories.common import utcnow


@dataclass(frozen=True)
class AvailabilitySummary:
    observed: int = 0
    missing: int = 0
    marked_unavailable: int = 0
    reactivated: int = 0


def reconcile_store_availability(
    session: Session,
    *,
    store: Store,
    scrape_run: ScrapeRun,
    catalog_is_healthy: bool,
    missing_threshold: int = 2,
) -> AvailabilitySummary:
    """Actualiza disponibilidad solo a partir de catálogos HEALTHY completos.

    Un producto observado se confirma inmediatamente. Un producto ausente solo se
    desactiva después de ``missing_threshold`` catálogos HEALTHY consecutivos.
    Capturas DEGRADED, STALE o fallidas nunca aumentan el contador de ausencia.
    """

    threshold = max(1, int(missing_threshold))
    observed_ids = set(
        int(value)
        for value in session.scalars(
            select(PriceObservation.product_id).where(
                PriceObservation.scrape_run_id == scrape_run.id
            )
        )
    )
    products = list(
        session.scalars(
            select(Product).where(Product.store_id == store.id).order_by(Product.id)
        )
    )
    now = utcnow()
    reactivated = 0
    marked_unavailable = 0
    missing = 0

    for product in products:
        if int(product.id) in observed_ids:
            if not bool(product.is_available):
                reactivated += 1
                product.reactivated_at = now
            product.is_available = True
            product.missing_streak = 0
            product.last_available_at = now
            product.unavailable_since = None
            product.last_confirmed_run_id = scrape_run.id
            continue

        missing += 1
        if not catalog_is_healthy:
            continue
        product.missing_streak = int(product.missing_streak or 0) + 1
        if product.is_available and product.missing_streak >= threshold:
            product.is_available = False
            product.unavailable_since = now
            marked_unavailable += 1

    session.flush()
    return AvailabilitySummary(
        observed=len(observed_ids),
        missing=missing,
        marked_unavailable=marked_unavailable,
        reactivated=reactivated,
    )
