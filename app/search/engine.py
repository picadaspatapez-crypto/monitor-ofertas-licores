from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import MasterProduct, Product
from app.search.normalization import SearchQuery, normalize_search_text, parse_search_query


@dataclass(frozen=True)
class SearchOffer:
    product_id: int
    store_name: str
    product_name: str
    price: int
    regular_price: int | None
    discount_pct: float
    url: str
    last_seen_at: datetime


@dataclass(frozen=True)
class SearchResult:
    master_product_id: int
    canonical_name: str
    brand: str | None
    variant: str | None
    volume_ml: int | None
    package_quantity: int
    score: float
    offers: tuple[SearchOffer, ...]
    winner: SearchOffer
    runner_up: SearchOffer | None
    saving_clp: int
    saving_pct: float


def _token_score(query_tokens: tuple[str, ...], candidate_tokens: set[str]) -> float:
    if not query_tokens:
        return 0.0
    matched = sum(token in candidate_tokens for token in query_tokens)
    return matched / len(query_tokens)


def _candidate_score(query: SearchQuery, master: MasterProduct) -> float:
    candidate = master.search_text or normalize_search_text(
        " ".join(
            [
                master.canonical_name,
                master.normalized_key,
                master.brand or "",
                master.variant or "",
                *list(master.aliases or []),
            ]
        )
    )
    if not candidate:
        return 0.0

    if query.volume_ml is not None and master.volume_ml is not None:
        if abs(query.volume_ml - master.volume_ml) > max(5, round(query.volume_ml * 0.01)):
            return 0.0
    if query.package_quantity is not None and master.package_quantity not in {
        query.package_quantity,
        None,
    }:
        return 0.0

    candidate_tokens = set(candidate.split())
    coverage = _token_score(query.tokens, candidate_tokens)
    phrase_ratio = SequenceMatcher(None, query.normalized, candidate).ratio()
    contains = bool(query.normalized and query.normalized in candidate)

    alias_ratios = [
        SequenceMatcher(None, query.normalized, normalize_search_text(alias)).ratio()
        for alias in list(master.aliases or [])
        if alias
    ]
    alias_ratio = max(alias_ratios, default=0.0)

    score = coverage * 0.58 + max(phrase_ratio, alias_ratio) * 0.32
    if contains:
        score += 0.12
    if coverage == 1.0:
        score += 0.08

    if query.volume_ml is not None and master.volume_ml == query.volume_ml:
        score += 0.08
    if query.brand and master.brand:
        query_brand = normalize_search_text(query.brand)
        master_brand = normalize_search_text(master.brand)
        if query_brand == master_brand:
            score += 0.08
        elif query_brand and master_brand and query_brand not in candidate:
            score -= 0.12

    return max(0.0, min(score, 1.0))


def _fresh_products(
    products: Iterable[Product],
    *,
    cutoff: datetime,
) -> list[Product]:
    result: list[Product] = []
    for product in products:
        seen_at = product.last_seen_at
        if seen_at is None:
            continue
        if seen_at.tzinfo is None:
            seen_at = seen_at.replace(tzinfo=timezone.utc)
        if seen_at >= cutoff and product.current_price > 0:
            result.append(product)
    return result


def search_products(
    session: Session,
    query: str,
    *,
    limit: int = 8,
    max_age_hours: int = 72,
    minimum_score: float = 0.34,
) -> list[SearchResult]:
    parsed = parse_search_query(query)
    if len(parsed.normalized) < 2:
        return []

    statement = (
        select(MasterProduct)
        .options(
            selectinload(MasterProduct.store_products).selectinload(Product.store_record)
        )
        .where(MasterProduct.status == "active")
        .order_by(MasterProduct.id)
    )
    masters = list(session.scalars(statement).unique())
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    scored: list[tuple[float, MasterProduct, list[Product]]] = []

    for master in masters:
        score = _candidate_score(parsed, master)
        if score < minimum_score:
            continue
        products = _fresh_products(master.store_products, cutoff=cutoff)
        if not products:
            continue
        scored.append((score, master, products))

    scored.sort(
        key=lambda item: (
            -item[0],
            min(product.current_price for product in item[2]),
            item[1].canonical_name.casefold(),
        )
    )

    results: list[SearchResult] = []
    for score, master, products in scored[: max(1, min(limit, 20))]:
        cheapest_by_store: dict[int | str, Product] = {}
        for product in products:
            store_key: int | str = product.store_id or product.store
            current = cheapest_by_store.get(store_key)
            if current is None or product.current_price < current.current_price:
                cheapest_by_store[store_key] = product

        offers = tuple(
            sorted(
                (
                    SearchOffer(
                        product_id=int(product.id),
                        store_name=(
                            product.store_record.name
                            if product.store_record is not None
                            else product.store
                        ),
                        product_name=product.name,
                        price=int(product.current_price),
                        regular_price=(
                            int(product.regular_price)
                            if product.regular_price is not None
                            else None
                        ),
                        discount_pct=float(product.discount_pct or 0.0),
                        url=product.url,
                        last_seen_at=(
                            product.last_seen_at
                            if product.last_seen_at.tzinfo is not None
                            else product.last_seen_at.replace(tzinfo=timezone.utc)
                        ),
                    )
                    for product in cheapest_by_store.values()
                ),
                key=lambda offer: (offer.price, offer.store_name.casefold()),
            )
        )
        if not offers:
            continue
        winner = offers[0]
        runner_up = offers[1] if len(offers) > 1 else None
        saving_clp = max(0, runner_up.price - winner.price) if runner_up else 0
        saving_pct = saving_clp / runner_up.price if runner_up and runner_up.price else 0.0
        results.append(
            SearchResult(
                master_product_id=int(master.id),
                canonical_name=master.canonical_name,
                brand=master.brand,
                variant=master.variant,
                volume_ml=master.volume_ml,
                package_quantity=int(master.package_quantity or 1),
                score=score,
                offers=offers,
                winner=winner,
                runner_up=runner_up,
                saving_clp=saving_clp,
                saving_pct=saving_pct,
            )
        )
    return results
