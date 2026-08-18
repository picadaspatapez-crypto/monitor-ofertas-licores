from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.matching import build_product_signature, normalize_product_name
from app.models import (
    MasterProduct,
    MatchingReview,
    OpportunitySnapshot,
    PersonalOpportunitySnapshot,
    Product,
    ProductMatch,
)


@dataclass(frozen=True)
class PackIdentityRepairSummary:
    products_scanned: int
    quantities_reclassified: int
    mixed_masters_found: int
    products_relinked: int
    masters_repaired: int
    snapshots_purged: int
    reviews_closed: int


def _get_or_create_exact_master(session: Session, product: Product) -> MasterProduct:
    """Return the exact-name master for a product during identity repair.

    Cross-store reconciliation can later merge compatible single-bottle masters.
    During pack repair we intentionally prefer the exact normalized identity so a
    multipack and a single bottle cannot remain attached to the same canonical row.
    """
    normalized = normalize_product_name(product.name)
    master = session.scalar(
        select(MasterProduct).where(MasterProduct.normalized_key == normalized.normalized_key)
    )
    if master is None:
        signature = build_product_signature(product.name)
        master = MasterProduct(
            canonical_name=normalized.canonical_name,
            normalized_key=normalized.normalized_key,
            volume_ml=normalized.volume_ml,
            package_quantity=int(signature.pack_count or 1),
            brand=signature.brand,
            abv_pct=signature.abv_pct,
            vintage_year=signature.vintage_year,
            status="active",
            identity_confidence=1.0,
        )
        session.add(master)
        session.flush()
    return master


def _relink_product(session: Session, product: Product, target: MasterProduct) -> None:
    product.master_product_id = int(target.id)
    match = session.scalar(
        select(ProductMatch).where(ProductMatch.store_product_id == int(product.id))
    )
    if match is None:
        match = ProductMatch(
            store_product_id=int(product.id),
            master_product_id=int(target.id),
            confidence=1.0,
            matching_method="identity_repair_exact",
            review_status="automatic",
            evidence_json={"reason": "package_identity_split_v5.8.3"},
        )
        session.add(match)
    else:
        match.master_product_id = int(target.id)
        match.confidence = 1.0
        match.matching_method = "identity_repair_exact"
        match.review_status = "automatic"
        match.evidence_json = {"reason": "package_identity_split_v5.8.3"}


def repair_pack_identity(session: Session) -> PackIdentityRepairSummary:
    """Repair canonical groups that historically mixed packs and single bottles.

    v5.8.2 correctly classified titles such as ``X6 750 ml`` but an old
    ``master_product_id`` could still keep the canonical identity contaminated.
    That allowed a *single* winner to inherit a pack canonical name and, more
    importantly, preserved stale group membership created before the improved pack
    parser existed.

    This repair is intentionally conservative:
    * package quantity is recalculated from the live title for every product;
    * only masters containing both pack and single publications are split;
    * products moved out of a mixed master go to their exact normalized master;
    * stale opportunity snapshots for affected identities are removed and rebuilt
      later in the same cross-store stage;
    * pending review rows involving a pack are closed so they cannot be approved by
      accident after the repair.
    """
    products = list(session.scalars(select(Product).order_by(Product.id)))
    products_scanned = len(products)
    reclassified = 0

    by_master: dict[int, list[Product]] = {}
    signatures = {}
    for product in products:
        signature = build_product_signature(product.name or "")
        signatures[int(product.id)] = signature
        quantity = int(signature.pack_count or 1)
        if int(product.package_quantity or 1) != quantity:
            product.package_quantity = quantity
            reclassified += 1
        if product.master_product_id is not None:
            by_master.setdefault(int(product.master_product_id), []).append(product)

    mixed_master_ids: set[int] = set()
    affected_master_ids: set[int] = set()
    moved_product_ids: set[int] = set()
    products_relinked = 0
    masters_repaired = 0

    for master_id, group in by_master.items():
        pack_products = [p for p in group if signatures[int(p.id)].is_pack]
        single_products = [p for p in group if not signatures[int(p.id)].is_pack]
        master = session.get(MasterProduct, master_id)
        if master is None:
            continue

        # A stale canonical name may still say X6 even after every pack publication
        # was already separated. Repair the display/identity metadata from a live
        # single bottle whenever one exists.
        if single_products:
            best_single = max(
                single_products,
                key=lambda item: (int(item.data_quality_score or 0), len(item.name or "")),
            )
            best_sig = signatures[int(best_single.id)]
            normalized = normalize_product_name(best_single.name)
            changed = False
            for attr, value in (
                ("canonical_name", normalized.canonical_name),
                ("package_quantity", 1),
                ("volume_ml", best_sig.volume_ml),
                ("brand", best_sig.brand or master.brand),
                ("abv_pct", best_sig.abv_pct),
                ("vintage_year", best_sig.vintage_year),
            ):
                if value is not None and getattr(master, attr) != value:
                    setattr(master, attr, value)
                    changed = True
            if changed:
                masters_repaired += 1
                affected_master_ids.add(master_id)

        if not pack_products or not single_products:
            # Pure pack masters remain valid for store-local search/rankings; they
            # simply never enter cross-store intelligence.
            if pack_products and not single_products:
                counts = [int(signatures[int(p.id)].pack_count or p.package_quantity or 2) for p in pack_products]
                quantity = max(counts) if counts else 2
                if int(master.package_quantity or 1) != quantity:
                    master.package_quantity = quantity
                    masters_repaired += 1
            continue

        mixed_master_ids.add(master_id)
        affected_master_ids.add(master_id)
        canonical_is_pack = build_product_signature(master.canonical_name or "").is_pack
        keep_pack_side = canonical_is_pack
        movers = single_products if keep_pack_side else pack_products

        for product in movers:
            target = _get_or_create_exact_master(session, product)
            if int(target.id) == master_id:
                # This can only occur when the canonical row's normalized key is on
                # the side we intended to move. In that case invert the split and
                # move the opposite side instead.
                continue
            _relink_product(session, product, target)
            affected_master_ids.add(int(target.id))
            moved_product_ids.add(int(product.id))
            products_relinked += 1

        # If no row moved because the canonical key belonged to the chosen side,
        # move the opposite side. This keeps the operation deterministic without
        # mutating the unique normalized_key in-place.
        if not any(int(p.id) in moved_product_ids for p in movers):
            alternate = pack_products if keep_pack_side else single_products
            for product in alternate:
                target = _get_or_create_exact_master(session, product)
                if int(target.id) == master_id:
                    continue
                _relink_product(session, product, target)
                affected_master_ids.add(int(target.id))
                moved_product_ids.add(int(product.id))
                products_relinked += 1

    reviews_closed = 0
    if signatures:
        pack_ids = {pid for pid, sig in signatures.items() if sig.is_pack}
        if pack_ids:
            pending = list(
                session.scalars(
                    select(MatchingReview).where(MatchingReview.status == "pending")
                )
            )
            for row in pending:
                if int(row.left_product_id) in pack_ids or int(row.right_product_id) in pack_ids:
                    row.status = "rejected"
                    row.resolution_notes = "Cerrado automáticamente: el par incluye un multipack."
                    reviews_closed += 1

    session.flush()

    # Re-canonicalize every affected master after the split. Pure pack masters keep
    # a pack quantity; masters with singles use a single-bottle display name.
    for master_id in sorted(affected_master_ids):
        master = session.get(MasterProduct, master_id)
        if master is None:
            continue
        attached = list(
            session.scalars(
                select(Product)
                .where(Product.master_product_id == master_id)
                .order_by(Product.id)
            )
        )
        singles = [p for p in attached if not build_product_signature(p.name or "").is_pack]
        if singles:
            best = max(singles, key=lambda p: (int(p.data_quality_score or 0), len(p.name or "")))
            sig = build_product_signature(best.name)
            normalized = normalize_product_name(best.name)
            master.canonical_name = normalized.canonical_name
            master.package_quantity = 1
            if sig.volume_ml is not None:
                master.volume_ml = sig.volume_ml
            if sig.brand:
                master.brand = sig.brand
        elif attached:
            sig = build_product_signature(attached[0].name)
            normalized = normalize_product_name(attached[0].name)
            master.canonical_name = normalized.canonical_name
            master.package_quantity = int(sig.pack_count or attached[0].package_quantity or 2)
            if sig.volume_ml is not None:
                master.volume_ml = sig.volume_ml
            if sig.brand:
                master.brand = sig.brand

    snapshots_purged = 0
    if affected_master_ids:
        result = session.execute(
            delete(OpportunitySnapshot).where(
                OpportunitySnapshot.master_product_id.in_(affected_master_ids)
            )
        )
        snapshots_purged += int(result.rowcount or 0)
        result = session.execute(
            delete(PersonalOpportunitySnapshot).where(
                PersonalOpportunitySnapshot.master_product_id.in_(affected_master_ids)
            )
        )
        snapshots_purged += int(result.rowcount or 0)

    session.flush()
    return PackIdentityRepairSummary(
        products_scanned=products_scanned,
        quantities_reclassified=reclassified,
        mixed_masters_found=len(mixed_master_ids),
        products_relinked=products_relinked,
        masters_repaired=masters_repaired,
        snapshots_purged=snapshots_purged,
        reviews_closed=reviews_closed,
    )
