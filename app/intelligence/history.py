from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta
from statistics import median

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models import MasterPriceStatistic, PriceObservation, Product, Store
from app.repositories.common import utcnow


@dataclass(frozen=True)
class PriceStatisticsRefresh:
    masters_seen: int
    rows_updated: int


def _aggregate_period(session: Session, *, cutoff, include_median: bool) -> dict[int, dict]:
    dialect = session.get_bind().dialect.name
    columns = [
        Product.master_product_id.label("master_id"),
        func.min(PriceObservation.price).label("minimum"),
        func.avg(PriceObservation.price).label("average"),
        func.count(PriceObservation.id).label("observations"),
        func.avg(case((PriceObservation.discount_pct > 0, 1.0), else_=0.0)).label(
            "discount_frequency"
        ),
    ]
    if include_median and dialect == "postgresql":
        columns.append(
            func.percentile_cont(0.5)
            .within_group(PriceObservation.price)
            .label("median_value")
        )
    statement = (
        select(*columns)
        .join(Product, Product.id == PriceObservation.product_id)
        .join(Store, Store.id == Product.store_id)
        .where(
            Product.master_product_id.is_not(None),
            Store.is_active.is_(True),
            Store.comparison_enabled.is_(True),
            PriceObservation.observed_at >= cutoff,
            PriceObservation.price > 0,
        )
        .group_by(Product.master_product_id)
    )
    result: dict[int, dict] = {}
    for row in session.execute(statement):
        item = {
            "minimum": int(row.minimum) if row.minimum is not None else None,
            "average": float(row.average) if row.average is not None else None,
            "observations": int(row.observations or 0),
            "discount_frequency": float(row.discount_frequency or 0.0),
            "median": (
                float(getattr(row, "median_value", 0.0))
                if getattr(row, "median_value", None) is not None
                else None
            ),
        }
        result[int(row.master_id)] = item

    # SQLite is used by the test suite. Production PostgreSQL computes the median
    # in SQL and never loads the complete 90-day history into Python.
    if include_median and dialect != "postgresql" and result:
        values: dict[int, list[int]] = defaultdict(list)
        rows = session.execute(
            select(Product.master_product_id, PriceObservation.price)
            .join(Product, Product.id == PriceObservation.product_id)
            .join(Store, Store.id == Product.store_id)
            .where(
                Product.master_product_id.in_(result),
                Store.is_active.is_(True),
            Store.comparison_enabled.is_(True),
                PriceObservation.observed_at >= cutoff,
                PriceObservation.price > 0,
            )
        )
        for master_id, price in rows:
            values[int(master_id)].append(int(price))
        for master_id, prices in values.items():
            result[master_id]["median"] = float(median(prices)) if prices else None
    return result


def refresh_price_statistics(session: Session) -> PriceStatisticsRefresh:
    now = utcnow()
    stats_30 = _aggregate_period(session, cutoff=now - timedelta(days=30), include_median=True)
    stats_90 = _aggregate_period(session, cutoff=now - timedelta(days=90), include_median=True)

    historical = {
        int(master_id): (int(value) if value is not None else None)
        for master_id, value in session.execute(
            select(Product.master_product_id, func.min(PriceObservation.price))
            .join(PriceObservation, PriceObservation.product_id == Product.id)
            .join(Store, Store.id == Product.store_id)
            .where(
                Product.master_product_id.is_not(None),
                Store.is_active.is_(True),
            Store.comparison_enabled.is_(True),
                PriceObservation.price > 0,
            )
            .group_by(Product.master_product_id)
        )
    }
    totals = {
        int(master_id): int(value or 0)
        for master_id, value in session.execute(
            select(Product.master_product_id, func.count(PriceObservation.id))
            .join(PriceObservation, PriceObservation.product_id == Product.id)
            .join(Store, Store.id == Product.store_id)
            .where(
                Product.master_product_id.is_not(None),
                Store.is_active.is_(True),
            Store.comparison_enabled.is_(True),
                PriceObservation.price > 0,
            )
            .group_by(Product.master_product_id)
        )
    }
    current = {
        int(master_id): int(value)
        for master_id, value in session.execute(
            select(Product.master_product_id, func.min(Product.current_price))
            .join(Store, Store.id == Product.store_id)
            .where(
                Product.master_product_id.is_not(None),
                Product.is_available.is_(True),
                Product.excluded_from_comparison.is_(False),
                Product.current_price > 0,
                Store.is_active.is_(True),
            Store.comparison_enabled.is_(True),
            )
            .group_by(Product.master_product_id)
        )
    }
    current_since = {
        int(master_id): observed_at
        for master_id, observed_at in session.execute(
            select(Product.master_product_id, func.min(PriceObservation.observed_at))
            .join(PriceObservation, PriceObservation.product_id == Product.id)
            .join(Store, Store.id == Product.store_id)
            .where(
                Product.master_product_id.is_not(None),
                Product.is_available.is_(True),
                Store.is_active.is_(True),
            Store.comparison_enabled.is_(True),
                PriceObservation.price == Product.current_price,
                PriceObservation.observed_at >= now - timedelta(days=90),
            )
            .group_by(Product.master_product_id)
        )
    }

    master_ids = set(stats_30) | set(stats_90) | set(historical) | set(current)
    updated = 0
    for master_id in master_ids:
        row = session.get(MasterPriceStatistic, master_id)
        if row is None:
            row = MasterPriceStatistic(master_product_id=master_id)
            session.add(row)
        period_30 = stats_30.get(master_id, {})
        period_90 = stats_90.get(master_id, {})
        since = current_since.get(master_id)
        if since is not None and since.tzinfo is None:
            since = since.replace(tzinfo=now.tzinfo)
        row.current_best_price = current.get(master_id)
        row.min_30d = period_30.get("minimum")
        row.avg_30d = period_30.get("average")
        row.median_30d = period_30.get("median")
        row.min_90d = period_90.get("minimum")
        row.avg_90d = period_90.get("average")
        row.median_90d = period_90.get("median")
        row.historical_min = historical.get(master_id)
        row.observations_30d = int(period_30.get("observations", 0))
        row.observations_90d = int(period_90.get("observations", 0))
        row.observations_total = max(row.observations_90d, totals.get(master_id, 0))
        row.discount_frequency_90d = float(period_90.get("discount_frequency", 0.0))
        row.days_at_current_price = (
            max(0, int((now - since).total_seconds() // 86400)) if since is not None else 0
        )
        row.updated_at = now
        updated += 1

    session.flush()
    return PriceStatisticsRefresh(masters_seen=len(master_ids), rows_updated=updated)
