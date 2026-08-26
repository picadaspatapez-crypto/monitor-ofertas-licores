from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, exists, func, select
from sqlalchemy.orm import Session

from app.collectors.licor3b import (
    _looks_like_contaminated_title,
    _name_from_product_url,
    _safe_product_name,
)
from app.matching import normalize_product_name
from app.models import MasterProduct, OpportunitySnapshot, PersonalOpportunitySnapshot, Product


@dataclass(frozen=True)
class TitleIntegrityRepairSummary:
    products_scanned: int
    products_repaired: int
    masters_repaired: int
    snapshots_purged: int
    orphan_masters_retired: int = 0
    inconsistent_snapshots_purged: int = 0


def _licor3b_authoritative_name(product: Product) -> str:
    """Best local identity for a Licor3B publication.

    The product URL is a much narrower identity signal than a category-card text
    node.  We still keep the visible title when it is coherent with the slug, but
    when the visible title has neighbouring-card contamination the slug-derived
    title wins.
    """
    return _safe_product_name(product.name or "", product.url or "").strip()


def safe_licor3b_display_name(*, canonical_name: str, product_name: str, url: str) -> str:
    """Return a presentation-safe name even if a legacy master stayed polluted.

    This is deliberately a read-time guard in addition to the database repair. It
    prevents Telegram/web output from surfacing a stale canonical title after a
    partial deployment or an interrupted reconciliation cycle.
    """
    canonical = " ".join((canonical_name or "").split()).strip()
    product = " ".join((product_name or "").split()).strip()
    safe_product = _safe_product_name(product, url or "").strip()
    url_name = _name_from_product_url(url or "").strip()

    if url_name and canonical and _looks_like_contaminated_title(canonical, url_name):
        return safe_product or url_name
    if safe_product and product and safe_product != product:
        return safe_product
    return canonical or safe_product or product


def _purge_inconsistent_snapshots(session: Session) -> int:
    """Delete derived snapshots whose winner no longer belongs to their master.

    A product can be relinked to a corrected master during the current run. A
    snapshot from an older run may still point to the old master while retaining
    that product as winner. Such a row is structurally invalid and must never be
    visible in /radar, /minimos or the personal comparison.
    """
    purged = 0
    for model in (OpportunitySnapshot, PersonalOpportunitySnapshot):
        rows = list(session.scalars(select(model)))
        for row in rows:
            master = session.get(MasterProduct, int(row.master_product_id))
            winner_id = getattr(row, "winner_product_id", None)
            winner = session.get(Product, int(winner_id)) if winner_id is not None else None
            invalid = (
                master is None
                or str(master.status or "").casefold() != "active"
                or winner is None
                or winner.master_product_id is None
                or int(winner.master_product_id) != int(row.master_product_id)
            )
            if invalid:
                session.delete(row)
                purged += 1
    session.flush()
    return purged


def repair_licor3b_title_integrity(session: Session) -> TitleIntegrityRepairSummary:
    """Repair Licor3B product/master titles and retire stale canonical identities.

    v5.8.4 repaired the visible Product.name only when it was still polluted. In
    production a collector run can already relink that cleaned product to a new
    master before this repair runs, leaving the *old* polluted master/snapshot
    behind. v5.8.5 therefore audits all Licor3B-linked masters, retires orphan
    masters and removes derived snapshots whose winner/master relationship is no
    longer valid.
    """
    products = list(
        session.scalars(
            select(Product)
            .where(func.lower(Product.store) == "licor3b")
            .order_by(Product.id)
        )
    )

    # Keep every currently referenced Licor3B master in the audit set, even when
    # Product.name is already clean. This is the key difference from v5.8.4.
    affected_master_ids: set[int] = {
        int(product.master_product_id)
        for product in products
        if product.master_product_id is not None
    }
    repaired = 0
    for product in products:
        safe = _licor3b_authoritative_name(product)
        if safe and safe != (product.name or ""):
            product.name = safe
            repaired += 1
            if product.master_product_id is not None:
                affected_master_ids.add(int(product.master_product_id))

    session.flush()

    masters_repaired = 0
    snapshots_purged = 0
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

        # If the canonical master is polluted relative to an attached Licor3B URL,
        # prefer that URL-derived identity explicitly. Otherwise use the strongest
        # current single-bottle product as before.
        preferred_name: str | None = None
        for product in singles:
            if (product.store or "").casefold() != "licor3b":
                continue
            url_name = _name_from_product_url(product.url or "").strip()
            if url_name and _looks_like_contaminated_title(master.canonical_name or "", url_name):
                preferred_name = _licor3b_authoritative_name(product) or url_name
                break

        if not preferred_name:
            best = max(
                singles,
                key=lambda p: (int(p.data_quality_score or 0), -len(p.name or "")),
            )
            preferred_name = best.name or ""

        normalized = normalize_product_name(preferred_name)
        if normalized.canonical_name and master.canonical_name != normalized.canonical_name:
            master.canonical_name = normalized.canonical_name
            masters_repaired += 1
            result = session.execute(
                delete(OpportunitySnapshot).where(OpportunitySnapshot.master_product_id == master_id)
            )
            snapshots_purged += int(result.rowcount or 0)
            result = session.execute(
                delete(PersonalOpportunitySnapshot).where(
                    PersonalOpportunitySnapshot.master_product_id == master_id
                )
            )
            snapshots_purged += int(result.rowcount or 0)

    # Retire masters that no longer own any product after save_product/reconciliation.
    # Keeping them active lets old derived rows leak into interactive reports.
    orphan_masters_retired = 0
    orphan_masters = list(
        session.scalars(
            select(MasterProduct)
            .where(MasterProduct.status == "active")
            .where(
                ~exists(
                    select(Product.id).where(Product.master_product_id == MasterProduct.id)
                )
            )
        )
    )
    for master in orphan_masters:
        master.status = "merged"
        orphan_masters_retired += 1
        result = session.execute(
            delete(OpportunitySnapshot).where(OpportunitySnapshot.master_product_id == master.id)
        )
        snapshots_purged += int(result.rowcount or 0)
        result = session.execute(
            delete(PersonalOpportunitySnapshot).where(
                PersonalOpportunitySnapshot.master_product_id == master.id
            )
        )
        snapshots_purged += int(result.rowcount or 0)

    inconsistent = _purge_inconsistent_snapshots(session)
    snapshots_purged += inconsistent

    session.flush()
    return TitleIntegrityRepairSummary(
        products_scanned=len(products),
        products_repaired=repaired,
        masters_repaired=masters_repaired,
        snapshots_purged=snapshots_purged,
        orphan_masters_retired=orphan_masters_retired,
        inconsistent_snapshots_purged=inconsistent,
    )
