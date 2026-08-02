from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import (
    MasterPriceStatistic,
    MasterProduct,
    OpportunitySnapshot,
    Product,
    Store,
)


@dataclass(frozen=True)
class OpportunityView:
    master_product_id: int
    canonical_name: str
    score: float
    classification: str
    winner_store: str
    winner_price: int
    saving_clp: int
    saving_pct: float
    confidence: float
    min_90d: int | None
    avg_90d: float | None
    historical_min: int | None
    url: str
    calculated_at: datetime


def top_opportunities(
    session: Session,
    *,
    limit: int = 20,
    minimum_score: float = 0.0,
    order: str = "score",
) -> list[OpportunityView]:
    ordering = (
        (desc(OpportunitySnapshot.saving_pct), desc(OpportunitySnapshot.saving_clp))
        if order == "saving"
        else (desc(OpportunitySnapshot.score), desc(OpportunitySnapshot.saving_pct))
    )
    statement = (
        select(
            OpportunitySnapshot,
            MasterProduct,
            Product,
            Store,
            MasterPriceStatistic,
        )
        .join(MasterProduct, MasterProduct.id == OpportunitySnapshot.master_product_id)
        .join(Product, Product.id == OpportunitySnapshot.winner_product_id)
        .join(Store, Store.id == OpportunitySnapshot.winner_store_id)
        .outerjoin(
            MasterPriceStatistic,
            MasterPriceStatistic.master_product_id == OpportunitySnapshot.master_product_id,
        )
        .where(
            OpportunitySnapshot.score >= minimum_score,
            Product.is_available.is_(True),
            Store.is_active.is_(True),
        )
        .order_by(*ordering, MasterProduct.canonical_name)
        .limit(max(1, min(int(limit), 30)))
    )
    views: list[OpportunityView] = []
    for snapshot, master, product, store, stats in session.execute(statement):
        views.append(
            OpportunityView(
                master_product_id=int(master.id),
                canonical_name=master.canonical_name,
                score=float(snapshot.score),
                classification=snapshot.classification,
                winner_store=store.name,
                winner_price=int(snapshot.winner_price or product.current_price),
                saving_clp=int(snapshot.saving_clp or 0),
                saving_pct=float(snapshot.saving_pct or 0.0),
                confidence=float(snapshot.match_confidence or 0.0),
                min_90d=(int(stats.min_90d) if stats and stats.min_90d is not None else None),
                avg_90d=(float(stats.avg_90d) if stats and stats.avg_90d is not None else None),
                historical_min=(
                    int(stats.historical_min)
                    if stats and stats.historical_min is not None
                    else None
                ),
                url=product.url,
                calculated_at=snapshot.calculated_at,
            )
        )
    return views
