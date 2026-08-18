from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.matching import MatchCandidate, build_matching_plan, build_product_signature, compare_signatures, normalize_product_name
from app.matching.rules import rule_key
from app.models import MatchingReview, MatchingRule, MasterProduct, PriceObservation, Product, ProductMatch


@dataclass(frozen=True)
class ReconciliationSummary:
    total_products: int
    eligible_products: int
    skipped_packs: int
    skipped_unknown_volume: int
    candidate_pairs: int
    ambiguous_products: int
    matched_pairs: int
    exact_matches: int
    fuzzy_matches: int
    products_relinked: int
    masters_merged: int
    review_candidates: int = 0
    review_pending: int = 0


def products_observed_in_runs(session: Session, run_ids: list[int]) -> list[Product]:
    if not run_ids:
        return []
    statement = (
        select(Product)
        .join(PriceObservation, PriceObservation.product_id == Product.id)
        .where(PriceObservation.scrape_run_id.in_(run_ids))
        .where(Product.excluded_from_comparison.is_(False))
        .distinct()
        .order_by(Product.id)
    )
    return list(session.scalars(statement).unique())


class _UnionFind:
    def __init__(self, values: list[int]):
        self.parent = {value: value for value in values}

    def find(self, value: int) -> int:
        parent = self.parent[value]
        if parent != value:
            self.parent[value] = self.find(parent)
        return self.parent[value]

    def union(self, left: int, right: int) -> None:
        left_root, right_root = self.find(left), self.find(right)
        if left_root != right_root:
            self.parent[max(left_root, right_root)] = min(left_root, right_root)


def _get_match(session: Session, product_id: int) -> ProductMatch | None:
    return session.scalar(
        select(ProductMatch).where(ProductMatch.store_product_id == product_id)
    )


def _augmented_candidates(session: Session, products: list[Product], plan) -> tuple[MatchCandidate, ...]:
    products_by_id = {int(product.id): product for product in products}
    candidates: dict[tuple[int, int], MatchCandidate] = {
        tuple(sorted((item.left_id, item.right_id))): item for item in plan.candidates
    }

    def add_pair(left: Product, right: Product, *, confidence: float, method: str) -> None:
        if left.store_id is None or right.store_id is None or left.store_id == right.store_id:
            return
        pair = tuple(sorted((int(left.id), int(right.id))))
        current = candidates.get(pair)
        candidate = MatchCandidate(pair[0], pair[1], confidence, method)
        if current is None or candidate.confidence > current.confidence:
            candidates[pair] = candidate

    # EAN is globally meaningful. SKU is accepted only when brand and volume also agree.
    by_ean: dict[str, list[Product]] = {}
    by_sku: dict[str, list[Product]] = {}
    signatures = {int(product.id): build_product_signature(product.name) for product in products}
    for product in products:
        if product.ean:
            by_ean.setdefault(product.ean.strip(), []).append(product)
        if product.sku:
            by_sku.setdefault(product.sku.strip().casefold(), []).append(product)
    for group in by_ean.values():
        for index, left in enumerate(group):
            for right in group[index + 1 :]:
                left_sig, right_sig = signatures[int(left.id)], signatures[int(right.id)]
                # EAN is the strongest identifier, but impossible structural conflicts
                # still win over a dirty/reused barcode.
                structural = compare_signatures(left_sig, right_sig, minimum_confidence=0.0)
                if structural.method in {"volume_conflict", "vintage_conflict", "abv_conflict", "excluded_pack"}:
                    continue
                add_pair(left, right, confidence=1.0, method="ean_exact")
    for group in by_sku.values():
        for index, left in enumerate(group):
            for right in group[index + 1 :]:
                left_sig, right_sig = signatures[int(left.id)], signatures[int(right.id)]
                # SKU is store-scoped in many commerces. It is only a secondary
                # signal when the independent identity evidence is already strong.
                score = compare_signatures(left_sig, right_sig, minimum_confidence=0.92)
                if score.accepted and left_sig.brand and left_sig.brand == right_sig.brand:
                    add_pair(left, right, confidence=max(0.97, score.confidence), method="sku_secondary_verified")

    active_rules = list(
        session.scalars(select(MatchingRule).where(MatchingRule.is_active.is_(True)))
    )
    keys = {int(product.id): rule_key(product.name) for product in products}
    exclusions = {
        tuple(sorted((rule.left_key, rule.right_key)))
        for rule in active_rules
        if rule.rule_type == "exclusion"
    }
    equivalences = {
        tuple(sorted((rule.left_key, rule.right_key)))
        for rule in active_rules
        if rule.rule_type == "equivalence"
    }
    for pair in list(candidates):
        left_key, right_key = keys[pair[0]], keys[pair[1]]
        if tuple(sorted((left_key, right_key))) in exclusions:
            candidates.pop(pair, None)
    for index, left in enumerate(products):
        for right in products[index + 1 :]:
            key_pair = tuple(sorted((keys[int(left.id)], keys[int(right.id)])))
            if key_pair in equivalences:
                # Una regla manual puede corregir aliases/nombres, pero nunca debe
                # convertir un pack en botella individual. La identidad estructural
                # tiene precedencia sobre cualquier equivalencia persistida.
                left_sig = signatures[int(left.id)]
                right_sig = signatures[int(right.id)]
                if left_sig.is_pack or right_sig.is_pack:
                    continue
                structural = compare_signatures(left_sig, right_sig, minimum_confidence=0.0)
                if structural.method in {"volume_conflict", "vintage_conflict", "abv_conflict", "excluded_pack"}:
                    continue
                add_pair(left, right, confidence=1.0, method="manual_equivalence")

    return tuple(sorted(candidates.values(), key=lambda item: (item.left_id, item.right_id)))


def _persist_review_candidates(session: Session, plan) -> tuple[int, int]:
    created_or_refreshed = 0
    for candidate in plan.review_candidates[:500]:
        left_id, right_id = sorted((int(candidate.left_id), int(candidate.right_id)))
        row = session.scalar(
            select(MatchingReview).where(
                MatchingReview.left_product_id == left_id,
                MatchingReview.right_product_id == right_id,
            )
        )
        if row is None:
            row = MatchingReview(
                left_product_id=left_id, right_product_id=right_id,
                confidence=float(candidate.confidence), proposed_method=candidate.method,
                reason=candidate.reason, status="pending",
            )
            session.add(row)
            created_or_refreshed += 1
        elif row.status == "pending":
            row.confidence = float(candidate.confidence)
            row.proposed_method = candidate.method
            row.reason = candidate.reason
            created_or_refreshed += 1
    session.flush()
    pending = int(session.scalar(select(func.count(MatchingReview.id)).where(MatchingReview.status == "pending")) or 0)
    return created_or_refreshed, pending


def _close_auto_resolved_reviews(session: Session, candidates: tuple[MatchCandidate, ...]) -> None:
    if not candidates:
        return
    accepted_pairs = {tuple(sorted((int(item.left_id), int(item.right_id)))) for item in candidates}
    pending = list(session.scalars(select(MatchingReview).where(MatchingReview.status == "pending")))
    for row in pending:
        pair = tuple(sorted((int(row.left_product_id), int(row.right_product_id))))
        if pair in accepted_pairs:
            row.status = "auto_resolved"
            row.resolution_notes = "El par superó el umbral automático en una revisión posterior."
            from datetime import datetime, timezone
            row.resolved_at = datetime.now(timezone.utc)


def reconcile_cross_store_matches(
    session: Session,
    *,
    run_ids: list[int],
    minimum_confidence: float = 0.86,
) -> ReconciliationSummary:
    products = products_observed_in_runs(session, run_ids)
    plan = build_matching_plan(products, minimum_confidence=minimum_confidence)
    review_candidates, review_pending = _persist_review_candidates(session, plan)
    candidates = _augmented_candidates(session, products, plan)
    _close_auto_resolved_reviews(session, candidates)
    if not candidates:
        return ReconciliationSummary(
            total_products=plan.total_products,
            eligible_products=plan.eligible_products,
            skipped_packs=plan.skipped_packs,
            skipped_unknown_volume=plan.skipped_unknown_volume,
            candidate_pairs=plan.candidate_pairs,
            ambiguous_products=plan.ambiguous_products,
            matched_pairs=0,
            exact_matches=0,
            fuzzy_matches=0,
            products_relinked=0,
            masters_merged=0,
            review_candidates=review_candidates,
            review_pending=review_pending,
        )

    products_by_id = {int(product.id): product for product in products}
    union = _UnionFind(list(products_by_id))
    edge_by_pair = {}
    for candidate in candidates:
        union.union(candidate.left_id, candidate.right_id)
        edge_by_pair[tuple(sorted((candidate.left_id, candidate.right_id)))] = candidate

    groups: dict[int, list[int]] = {}
    for product_id in products_by_id:
        groups.setdefault(union.find(product_id), []).append(product_id)

    products_relinked = 0
    merged_master_ids: set[int] = set()
    exact_methods = {"alias_exact", "ean_exact", "sku_secondary_verified", "manual_equivalence"}
    exact_matches = sum(candidate.method in exact_methods for candidate in candidates)
    fuzzy_matches = len(candidates) - exact_matches

    for product_ids in groups.values():
        group_edges = [
            candidate
            for candidate in candidates
            if candidate.left_id in product_ids and candidate.right_id in product_ids
        ]
        if not group_edges:
            continue

        group_products = [products_by_id[product_id] for product_id in product_ids]
        master_ids = sorted(
            {
                int(product.master_product_id)
                for product in group_products
                if product.master_product_id is not None
            }
        )
        if not master_ids:
            continue

        target_id = master_ids[0]
        target = session.get(MasterProduct, target_id)
        if target is None:
            continue
        target.status = "active"
        target.identity_confidence = max(
            float(target.identity_confidence or 0.5),
            min((float(edge.confidence) for edge in group_edges), default=0.5),
        )

        signatures = [build_product_signature(product.name) for product in group_products]
        volumes = {signature.volume_ml for signature in signatures if signature.volume_ml is not None}
        brands = {signature.brand for signature in signatures if signature.brand}
        if len(volumes) == 1:
            target.volume_ml = next(iter(volumes))
        if len(brands) == 1:
            target.brand = next(iter(brands))

        best_name = max(
            (product.name for product in group_products),
            key=lambda value: (len(build_product_signature(value).core_tokens), len(value)),
        )
        target.canonical_name = normalize_product_name(best_name).canonical_name

        confidence_by_product: dict[int, float] = {}
        method_by_product: dict[int, str] = {}
        for edge in group_edges:
            for product_id in (edge.left_id, edge.right_id):
                current = confidence_by_product.get(product_id, 0.0)
                if edge.confidence >= current:
                    confidence_by_product[product_id] = edge.confidence
                    method_by_product[product_id] = edge.method

        for product in group_products:
            old_master_id = product.master_product_id
            if old_master_id != target_id:
                product.master_product_id = target_id
                products_relinked += 1
                if old_master_id is not None:
                    merged_master_ids.add(int(old_master_id))

            match = _get_match(session, int(product.id))
            confidence = confidence_by_product.get(int(product.id), 1.0)
            method = method_by_product.get(int(product.id), "exact_normalized")
            if match is None:
                session.add(
                    ProductMatch(
                        store_product_id=int(product.id),
                        master_product_id=target_id,
                        confidence=confidence,
                        matching_method=method,
                        review_status=("manual" if method == "manual_equivalence" else "automatic"),
                        evidence_json={"method": method, "confidence": round(float(confidence), 4)},
                    )
                )
            else:
                match.master_product_id = target_id
                match.confidence = confidence
                match.matching_method = method
                match.review_status = "manual" if method == "manual_equivalence" else "automatic"
                match.evidence_json = {"method": method, "confidence": round(float(confidence), 4)}

    session.flush()
    masters_merged = 0
    for master_id in sorted(merged_master_ids):
        remaining = int(
            session.scalar(
                select(func.count(Product.id)).where(Product.master_product_id == master_id)
            )
            or 0
        )
        if remaining == 0:
            master = session.get(MasterProduct, master_id)
            if master is not None and master.status != "merged":
                master.status = "merged"
                masters_merged += 1

    return ReconciliationSummary(
        total_products=plan.total_products,
        eligible_products=plan.eligible_products,
        skipped_packs=plan.skipped_packs,
        skipped_unknown_volume=plan.skipped_unknown_volume,
        candidate_pairs=plan.candidate_pairs,
        ambiguous_products=plan.ambiguous_products,
        matched_pairs=len(candidates),
        exact_matches=exact_matches,
        fuzzy_matches=fuzzy_matches,
        products_relinked=products_relinked,
        masters_merged=masters_merged,
        review_candidates=review_candidates,
        review_pending=review_pending,
    )
