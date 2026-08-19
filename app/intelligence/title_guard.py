from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.collectors.licor3b import _name_from_product_url, _safe_product_name
from app.matching import normalize_product_name
from app.models import MasterProduct, OpportunitySnapshot, PersonalOpportunitySnapshot, Product


@dataclass(frozen=True)
class TitleIntegrityRepairSummary:
    products_scanned: int
    products_repaired: int
    masters_repaired: int
    snapshots_purged: int


def repair_licor3b_title_integrity(session: Session) -> TitleIntegrityRepairSummary:
    """Repair persisted Licor3B titles polluted by category-card DOM text.

    Only rows whose URL belongs to Licor3B and whose visible name strongly conflicts
    with the stable product slug are changed. Historical price observations are not
    deleted; only display identity and derived opportunity snapshots are repaired.
    """
    products = list(
        session.scalars(
            select(Product)
            .where(Product.store == "Licor3B")
            .order_by(Product.id)
        )
    )
    affected_master_ids: set[int] = set()
    repaired = 0
    for product in products:
        url_name = _name_from_product_url(product.url or "")
        if not url_name:
            continue
        safe = _safe_product_name(product.name or "", product.url or "")
        if not safe or safe == product.name:
            continue
        product.name = safe
        repaired += 1
        if product.master_product_id is not None:
            affected_master_ids.add(int(product.master_product_id))

    session.flush()

    masters_repaired = 0
    for master_id in sorted(affected_master_ids):
        master = session.get(MasterProduct, master_id)
        if master is None:
            continue
        attached = list(
            session.scalars(
                select(Product)
                .where(Product.master_product_id == master_id)
                .where(Product.excluded_from_comparison.is_(False))
                .order_by(Product.data_quality_score.desc(), Product.id)
            )
        )
        singles = [p for p in attached if int(p.package_quantity or 1) == 1]
        if not singles:
            continue
        best = max(singles, key=lambda p: (int(p.data_quality_score or 0), -len(p.name or "")))
        normalized = normalize_product_name(best.name or "")
        if master.canonical_name != normalized.canonical_name:
            master.canonical_name = normalized.canonical_name
            masters_repaired += 1

    snapshots_purged = 0
    if affected_master_ids:
        result = session.execute(
            delete(OpportunitySnapshot).where(OpportunitySnapshot.master_product_id.in_(affected_master_ids))
        )
        snapshots_purged += int(result.rowcount or 0)
        result = session.execute(
            delete(PersonalOpportunitySnapshot).where(PersonalOpportunitySnapshot.master_product_id.in_(affected_master_ids))
        )
        snapshots_purged += int(result.rowcount or 0)

    session.flush()
    return TitleIntegrityRepairSummary(
        products_scanned=len(products),
        products_repaired=repaired,
        masters_repaired=masters_repaired,
        snapshots_purged=snapshots_purged,
    )
