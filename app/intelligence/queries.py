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
    score_version: str = "v2"
    rarity_score: float = 0.0
    rarity_frequency_90d: float | None = None
    history_observations_90d: int = 0
    previous_historical_min: int | None = None
    price_event: str = "NORMAL"
    historical_gap_clp: int = 0
    historical_gap_pct: float = 0.0
    intelligence_reason: str | None = None


def _statement(*, minimum_score: float, events: tuple[str, ...] | None, order: str):
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
            Product.excluded_from_comparison.is_(False),
            Store.is_active.is_(True),
        )
        .order_by(*ordering, MasterProduct.canonical_name)
    )
    if events:
        statement = statement.where(OpportunitySnapshot.price_event.in_(events))
    return statement


def _views(session: Session, statement, *, limit: int) -> list[OpportunityView]:
    views: list[OpportunityView] = []
    for snapshot, master, product, store, stats in session.execute(
        statement.limit(max(1, min(int(limit), 30)))
    ):
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
                score_version=str(getattr(snapshot, "score_version", "v2") or "v2"),
                rarity_score=float(getattr(snapshot, "rarity_score", 0.0) or 0.0),
                rarity_frequency_90d=getattr(snapshot, "rarity_frequency_90d", None),
                history_observations_90d=int(getattr(snapshot, "history_observations_90d", 0) or 0),
                previous_historical_min=getattr(snapshot, "previous_historical_min", None),
                price_event=str(getattr(snapshot, "price_event", "NORMAL") or "NORMAL"),
                historical_gap_clp=int(getattr(snapshot, "historical_gap_clp", 0) or 0),
                historical_gap_pct=float(getattr(snapshot, "historical_gap_pct", 0.0) or 0.0),
                intelligence_reason=getattr(snapshot, "intelligence_reason", None),
            )
        )
    return views


def top_opportunities(
    session: Session,
    *,
    limit: int = 20,
    minimum_score: float = 0.0,
    order: str = "score",
) -> list[OpportunityView]:
    return _views(
        session,
        _statement(minimum_score=minimum_score, events=None, order=order),
        limit=limit,
    )


def commercial_radar(
    session: Session,
    *,
    limit: int = 10,
    minimum_score: float = 70.0,
) -> list[OpportunityView]:
    events = (
        "NEW_HISTORICAL_MIN",
        "RARE_OFFER",
        "AT_HISTORICAL_MIN",
        "NEAR_HISTORICAL_MIN",
        "MARKET_LEADER",
    )
    return _views(
        session,
        _statement(minimum_score=minimum_score, events=events, order="score"),
        limit=limit,
    )


def historical_floor_opportunities(
    session: Session,
    *,
    limit: int = 10,
) -> list[OpportunityView]:
    events = ("NEW_HISTORICAL_MIN", "AT_HISTORICAL_MIN", "NEAR_HISTORICAL_MIN")
    statement = _statement(minimum_score=0.0, events=events, order="score").order_by(None).order_by(
        desc(OpportunitySnapshot.historical_gap_pct),
        desc(OpportunitySnapshot.score),
        MasterProduct.canonical_name,
    )
    return _views(session, statement, limit=limit)
