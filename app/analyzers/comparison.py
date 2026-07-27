from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.matching import build_product_signature, compare_signatures
from app.models import MasterProduct, PriceObservation, Product, ProductMatch, Store
from app.repositories.matching import products_observed_in_runs


@dataclass(frozen=True)
class StoreOffer:
    product_id: int
    store_id: int
    store_name: str
    product_name: str
    price: int
    regular_price: int | None
    discount_pct: float
    url: str


@dataclass(frozen=True)
class PriceComparison:
    master_product_id: int
    canonical_name: str
    volume_ml: int | None
    offers: tuple[StoreOffer, ...]
    winner: StoreOffer | None
    runner_up: StoreOffer | None
    saving_clp: int
    saving_pct: float
    confidence: float
    previous_winner_store_id: int | None
    previous_winner_store_name: str | None
    winner_changed: bool
    is_tie: bool


@dataclass(frozen=True)
class ComparisonAnalysis:
    current_products: int
    master_groups: int
    verified_matches: int
    opportunities: tuple[PriceComparison, ...]
    winner_changes: tuple[PriceComparison, ...]
    ties: int
    unverified_groups: int


def _previous_prices(
    session: Session,
    *,
    product_ids: list[int],
    current_run_ids: list[int],
) -> dict[int, int]:
    if not product_ids:
        return {}
    statement = (
        select(PriceObservation)
        .where(PriceObservation.product_id.in_(product_ids))
        .where(
            PriceObservation.scrape_run_id.is_(None)
            | PriceObservation.scrape_run_id.not_in(current_run_ids)
        )
        .order_by(
            PriceObservation.product_id,
            PriceObservation.observed_at.desc(),
            PriceObservation.id.desc(),
        )
    )
    result: dict[int, int] = {}
    for observation in session.scalars(statement):
        result.setdefault(int(observation.product_id), int(observation.price))
    return result


def analyze_cross_store_prices(
    session: Session,
    *,
    run_ids: list[int],
    minimum_confidence: float = 0.86,
) -> ComparisonAnalysis:
    products = products_observed_in_runs(session, run_ids)
    if not products:
        return ComparisonAnalysis(0, 0, 0, (), (), 0, 0)

    product_ids = [int(product.id) for product in products]
    stores = {
        int(store.id): store
        for store in session.scalars(
            select(Store).where(Store.id.in_({product.store_id for product in products if product.store_id}))
        )
    }
    masters = {
        int(master.id): master
        for master in session.scalars(
            select(MasterProduct).where(
                MasterProduct.id.in_(
                    {
                        product.master_product_id
                        for product in products
                        if product.master_product_id is not None
                    }
                )
            )
        )
    }
    matches = {
        int(match.store_product_id): match
        for match in session.scalars(
            select(ProductMatch).where(ProductMatch.store_product_id.in_(product_ids))
        )
    }
    previous_prices = _previous_prices(
        session,
        product_ids=product_ids,
        current_run_ids=run_ids,
    )

    by_master: dict[int, list[Product]] = {}
    for product in products:
        if product.master_product_id is None or product.store_id is None:
            continue
        by_master.setdefault(int(product.master_product_id), []).append(product)

    comparisons: list[PriceComparison] = []
    unverified_groups = 0
    ties = 0
    verified_matches = 0

    for master_id, group_products in by_master.items():
        cheapest_by_store: dict[int, Product] = {}
        for product in group_products:
            store_id = int(product.store_id)
            current = cheapest_by_store.get(store_id)
            if current is None or product.current_price < current.current_price:
                cheapest_by_store[store_id] = product
        if len(cheapest_by_store) < 2:
            continue

        selected = list(cheapest_by_store.values())
        pair_confidences: list[float] = []
        verified = True
        for left_index in range(len(selected)):
            for right_index in range(left_index + 1, len(selected)):
                left = selected[left_index]
                right = selected[right_index]
                score = compare_signatures(
                    build_product_signature(left.name),
                    build_product_signature(right.name),
                    minimum_confidence=minimum_confidence,
                )
                if not score.accepted:
                    verified = False
                    break
                stored_confidence = min(
                    float(matches.get(int(left.id)).confidence) if matches.get(int(left.id)) else score.confidence,
                    float(matches.get(int(right.id)).confidence) if matches.get(int(right.id)) else score.confidence,
                )
                pair_confidences.append(min(score.confidence, stored_confidence))
            if not verified:
                break
        if not verified:
            unverified_groups += 1
            continue

        offers = tuple(
            sorted(
                (
                    StoreOffer(
                        product_id=int(product.id),
                        store_id=int(product.store_id),
                        store_name=stores[int(product.store_id)].name,
                        product_name=product.name,
                        price=int(product.current_price),
                        regular_price=(
                            int(product.regular_price)
                            if product.regular_price is not None
                            else None
                        ),
                        discount_pct=float(product.discount_pct or 0.0),
                        url=product.url,
                    )
                    for product in selected
                ),
                key=lambda offer: (offer.price, offer.store_name.casefold()),
            )
        )
        verified_matches += 1
        is_tie = len(offers) > 1 and offers[0].price == offers[1].price
        if is_tie:
            winner = runner_up = None
            saving_clp = 0
            saving_pct = 0.0
            ties += 1
        else:
            winner, runner_up = offers[0], offers[1]
            saving_clp = runner_up.price - winner.price
            saving_pct = saving_clp / runner_up.price if runner_up.price > 0 else 0.0

        previous_offers = [
            (previous_prices.get(offer.product_id), offer)
            for offer in offers
            if previous_prices.get(offer.product_id) is not None
        ]
        previous_winner_store_id = None
        previous_winner_store_name = None
        if len(previous_offers) >= 2:
            previous_offers.sort(key=lambda item: (int(item[0]), item[1].store_name.casefold()))
            if int(previous_offers[0][0]) < int(previous_offers[1][0]):
                previous_winner_store_id = previous_offers[0][1].store_id
                previous_winner_store_name = previous_offers[0][1].store_name

        winner_changed = bool(
            winner is not None
            and previous_winner_store_id is not None
            and winner.store_id != previous_winner_store_id
        )
        master = masters.get(master_id)
        canonical_name = (
            master.canonical_name if master is not None else offers[0].product_name
        )
        volume_ml = master.volume_ml if master is not None else build_product_signature(offers[0].product_name).volume_ml
        comparisons.append(
            PriceComparison(
                master_product_id=master_id,
                canonical_name=canonical_name,
                volume_ml=volume_ml,
                offers=offers,
                winner=winner,
                runner_up=runner_up,
                saving_clp=saving_clp,
                saving_pct=saving_pct,
                confidence=min(pair_confidences) if pair_confidences else 1.0,
                previous_winner_store_id=previous_winner_store_id,
                previous_winner_store_name=previous_winner_store_name,
                winner_changed=winner_changed,
                is_tie=is_tie,
            )
        )

    opportunities = tuple(
        sorted(
            (comparison for comparison in comparisons if not comparison.is_tie and comparison.saving_clp > 0),
            key=lambda comparison: (
                -comparison.saving_pct,
                -comparison.saving_clp,
                comparison.canonical_name.casefold(),
            ),
        )
    )
    winner_changes = tuple(
        sorted(
            (comparison for comparison in opportunities if comparison.winner_changed),
            key=lambda comparison: (-comparison.saving_pct, -comparison.saving_clp),
        )
    )
    return ComparisonAnalysis(
        current_products=len(products),
        master_groups=len(by_master),
        verified_matches=verified_matches,
        opportunities=opportunities,
        winner_changes=winner_changes,
        ties=ties,
        unverified_groups=unverified_groups,
    )
