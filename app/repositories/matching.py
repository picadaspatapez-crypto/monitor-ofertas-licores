from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.matching import build_matching_plan, build_product_signature, normalize_product_name
from app.models import MasterProduct, PriceObservation, Product, ProductMatch


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


def products_observed_in_runs(session: Session, run_ids: list[int]) -> list[Product]:
    if not run_ids:
        return []
    statement = (
        select(Product)
        .join(PriceObservation, PriceObservation.product_id == Product.id)
        .where(PriceObservation.scrape_run_id.in_(run_ids))
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


def reconcile_cross_store_matches(
    session: Session,
    *,
    run_ids: list[int],
    minimum_confidence: float = 0.86,
) -> ReconciliationSummary:
    products = products_observed_in_runs(session, run_ids)
    plan = build_matching_plan(products, minimum_confidence=minimum_confidence)
    if not plan.candidates:
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
        )

    products_by_id = {int(product.id): product for product in products}
    union = _UnionFind(list(products_by_id))
    edge_by_pair = {}
    for candidate in plan.candidates:
        union.union(candidate.left_id, candidate.right_id)
        edge_by_pair[tuple(sorted((candidate.left_id, candidate.right_id)))] = candidate

    groups: dict[int, list[int]] = {}
    for product_id in products_by_id:
        groups.setdefault(union.find(product_id), []).append(product_id)

    products_relinked = 0
    merged_master_ids: set[int] = set()
    exact_matches = sum(candidate.method == "alias_exact" for candidate in plan.candidates)
    fuzzy_matches = len(plan.candidates) - exact_matches

    for product_ids in groups.values():
        group_edges = [
            candidate
            for candidate in plan.candidates
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
                        review_status="automatic",
                    )
                )
            else:
                match.master_product_id = target_id
                match.confidence = confidence
                match.matching_method = method
                match.review_status = "automatic"

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
        matched_pairs=len(plan.candidates),
        exact_matches=exact_matches,
        fuzzy_matches=fuzzy_matches,
        products_relinked=products_relinked,
        masters_merged=masters_merged,
    )
