from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.models import (
    PriceContextStatistic,
    PriceQuoteObservation,
    Product,
    ProductPriceQuote,
    Store,
)
from app.repositories.common import utcnow


@dataclass(frozen=True)
class ContextStatisticsRefresh:
    contexts_seen: int
    rows_updated: int


def _eligible_store_filter():
    return or_(
        Store.comparison_enabled.is_(True),
        Store.personal_comparison_enabled.is_(True),
    )


def _aggregate_period(session: Session, *, cutoff) -> dict[tuple[int, str, str], dict]:
    statement = (
        select(
            PriceQuoteObservation.product_id,
            PriceQuoteObservation.price_type,
            PriceQuoteObservation.audience_key,
            func.min(PriceQuoteObservation.price).label("minimum"),
            func.avg(PriceQuoteObservation.price).label("average"),
            func.count(PriceQuoteObservation.id).label("observations"),
        )
        .join(Product, Product.id == PriceQuoteObservation.product_id)
        .join(Store, Store.id == Product.store_id)
        .where(
            Store.is_active.is_(True),
            _eligible_store_filter(),
            PriceQuoteObservation.price > 0,
            PriceQuoteObservation.observed_at >= cutoff,
        )
        .group_by(
            PriceQuoteObservation.product_id,
            PriceQuoteObservation.price_type,
            PriceQuoteObservation.audience_key,
        )
    )
    return {
        (int(row.product_id), str(row.price_type), str(row.audience_key)): {
            "minimum": int(row.minimum) if row.minimum is not None else None,
            "average": float(row.average) if row.average is not None else None,
            "observations": int(row.observations or 0),
        }
        for row in session.execute(statement)
    }


def refresh_context_price_statistics(session: Session) -> ContextStatisticsRefresh:
    """Actualiza historia separada por PUBLIC/SALE/MEMBER y audiencia.

    Esta tabla nunca reemplaza ``MasterPriceStatistic``. La estadística maestra
    continúa representando el mercado público; esta vista conserva el historial
    del precio contextual exacto que usa la comparación personal.
    """
    now = utcnow()
    stats_30 = _aggregate_period(session, cutoff=now - timedelta(days=30))
    stats_90 = _aggregate_period(session, cutoff=now - timedelta(days=90))

    historical = {
        (int(pid), str(ptype), str(audience)): int(minimum)
        for pid, ptype, audience, minimum in session.execute(
            select(
                PriceQuoteObservation.product_id,
                PriceQuoteObservation.price_type,
                PriceQuoteObservation.audience_key,
                func.min(PriceQuoteObservation.price),
            )
            .join(Product, Product.id == PriceQuoteObservation.product_id)
            .join(Store, Store.id == Product.store_id)
            .where(
                Store.is_active.is_(True),
                _eligible_store_filter(),
                PriceQuoteObservation.price > 0,
            )
            .group_by(
                PriceQuoteObservation.product_id,
                PriceQuoteObservation.price_type,
                PriceQuoteObservation.audience_key,
            )
        )
        if minimum is not None
    }
    totals = {
        (int(pid), str(ptype), str(audience)): int(total or 0)
        for pid, ptype, audience, total in session.execute(
            select(
                PriceQuoteObservation.product_id,
                PriceQuoteObservation.price_type,
                PriceQuoteObservation.audience_key,
                func.count(PriceQuoteObservation.id),
            )
            .join(Product, Product.id == PriceQuoteObservation.product_id)
            .join(Store, Store.id == Product.store_id)
            .where(
                Store.is_active.is_(True),
                _eligible_store_filter(),
                PriceQuoteObservation.price > 0,
            )
            .group_by(
                PriceQuoteObservation.product_id,
                PriceQuoteObservation.price_type,
                PriceQuoteObservation.audience_key,
            )
        )
    }
    current = {
        (int(quote.product_id), str(quote.price_type), str(quote.audience_key)): int(quote.price)
        for quote in session.scalars(
            select(ProductPriceQuote)
            .join(Product, Product.id == ProductPriceQuote.product_id)
            .join(Store, Store.id == Product.store_id)
            .where(
                Store.is_active.is_(True),
                _eligible_store_filter(),
                Product.is_available.is_(True),
                ProductPriceQuote.is_active.is_(True),
                ProductPriceQuote.price > 0,
            )
        )
    }

    same_price_join = and_(
        ProductPriceQuote.product_id == PriceQuoteObservation.product_id,
        ProductPriceQuote.price_type == PriceQuoteObservation.price_type,
        ProductPriceQuote.audience_key == PriceQuoteObservation.audience_key,
        ProductPriceQuote.price == PriceQuoteObservation.price,
        ProductPriceQuote.is_active.is_(True),
    )
    current_since = {
        (int(pid), str(ptype), str(audience)): observed_at
        for pid, ptype, audience, observed_at in session.execute(
            select(
                PriceQuoteObservation.product_id,
                PriceQuoteObservation.price_type,
                PriceQuoteObservation.audience_key,
                func.min(PriceQuoteObservation.observed_at),
            )
            .join(ProductPriceQuote, same_price_join)
            .join(Product, Product.id == PriceQuoteObservation.product_id)
            .join(Store, Store.id == Product.store_id)
            .where(
                Store.is_active.is_(True),
                _eligible_store_filter(),
                Product.is_available.is_(True),
                PriceQuoteObservation.observed_at >= now - timedelta(days=90),
            )
            .group_by(
                PriceQuoteObservation.product_id,
                PriceQuoteObservation.price_type,
                PriceQuoteObservation.audience_key,
            )
        )
    }

    keys = set(stats_30) | set(stats_90) | set(historical) | set(current)
    updated = 0
    for key in keys:
        product_id, price_type, audience_key = key
        row = session.scalar(
            select(PriceContextStatistic).where(
                PriceContextStatistic.product_id == product_id,
                PriceContextStatistic.price_type == price_type,
                PriceContextStatistic.audience_key == audience_key,
            )
        )
        if row is None:
            row = PriceContextStatistic(
                product_id=product_id,
                price_type=price_type,
                audience_key=audience_key,
            )
            session.add(row)
        p30 = stats_30.get(key, {})
        p90 = stats_90.get(key, {})
        since = current_since.get(key)
        if since is not None and since.tzinfo is None:
            since = since.replace(tzinfo=now.tzinfo)
        row.current_price = current.get(key)
        row.min_30d = p30.get("minimum")
        row.avg_30d = p30.get("average")
        row.min_90d = p90.get("minimum")
        row.avg_90d = p90.get("average")
        row.historical_min = historical.get(key)
        row.observations_30d = int(p30.get("observations", 0))
        row.observations_90d = int(p90.get("observations", 0))
        row.observations_total = int(totals.get(key, 0))
        row.days_at_current_price = (
            max(0, int((now - since).total_seconds() // 86400)) if since is not None else 0
        )
        row.updated_at = now
        updated += 1

    session.flush()
    return ContextStatisticsRefresh(contexts_seen=len(keys), rows_updated=updated)
