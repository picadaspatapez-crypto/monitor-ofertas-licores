from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.models import OpportunitySnapshot
from app.repositories.common import utcnow


@dataclass(frozen=True)
class OpportunityComponents:
    market_saving: float
    history_position: float
    match_confidence: float
    freshness: float
    scarcity: float


def _unit(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def classify_opportunity(score: float) -> str:
    if score >= 90:
        return "Excelente"
    if score >= 80:
        return "Muy buena"
    if score >= 70:
        return "Buena"
    if score >= 55:
        return "Normal"
    return "No destacada"


def opportunity_score(components: OpportunityComponents) -> float:
    value = 100.0 * (
        0.35 * _unit(components.market_saving)
        + 0.30 * _unit(components.history_position)
        + 0.15 * _unit(components.match_confidence)
        + 0.10 * _unit(components.freshness)
        + 0.10 * _unit(components.scarcity)
    )
    return round(value, 1)


def persist_opportunity_snapshots(session: Session, comparisons) -> int:
    now = utcnow()
    updated = 0
    active_ids: set[int] = set()
    for item in comparisons:
        if item.winner is None:
            continue
        master_id = int(item.master_product_id)
        active_ids.add(master_id)
        row = session.get(OpportunitySnapshot, master_id)
        if row is None:
            row = OpportunitySnapshot(
                master_product_id=master_id,
                score=float(item.opportunity_score),
                classification=item.opportunity_classification,
            )
            session.add(row)
        row.score = float(item.opportunity_score)
        row.classification = item.opportunity_classification
        row.winner_product_id = item.winner.product_id
        row.winner_store_id = item.winner.store_id
        row.winner_price = item.winner.price
        row.saving_clp = item.saving_clp
        row.saving_pct = item.saving_pct
        row.match_confidence = item.confidence
        row.history_position = item.history_position
        row.freshness_score = item.freshness_score
        row.scarcity_score = item.scarcity_score
        row.calculated_at = now
        updated += 1
    if active_ids:
        session.execute(
            delete(OpportunitySnapshot).where(
                OpportunitySnapshot.master_product_id.not_in(active_ids)
            )
        )
    else:
        session.execute(delete(OpportunitySnapshot))
    session.flush()
    return updated
