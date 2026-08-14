from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    MasterPriceStatistic,
    MasterProduct,
    OpportunitySnapshot,
    PersonalOpportunitySnapshot,
    PriceContextStatistic,
    Product,
    ProductPriceQuote,
)
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
    price_type: str = "PUBLIC"
    audience_key: str = "public"
    eligibility_required: bool = False
    is_public_market: bool = True


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
    min_30d: int | None = None
    avg_30d: float | None = None
    min_90d: int | None = None
    avg_90d: float | None = None
    historical_min: int | None = None
    days_at_current_price: int = 0
    opportunity_score: float | None = None
    opportunity_classification: str | None = None
    price_mode: str = "public"
    public_reference_price: int | None = None
    personal_advantage_clp: int = 0
    personal_advantage_pct: float = 0.0


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
    price_mode: str = "public",
) -> list[Product]:
    result: list[Product] = []
    for product in products:
        store = product.store_record
        if store is not None:
            if not store.is_active:
                continue
            if price_mode == "personal":
                if not (
                    getattr(store, "comparison_enabled", True)
                    or getattr(store, "personal_comparison_enabled", False)
                ):
                    continue
            elif not getattr(store, "comparison_enabled", True):
                continue
        if not bool(getattr(product, "is_available", True)):
            continue
        if bool(getattr(product, "excluded_from_comparison", False)):
            continue
        seen_at = product.last_seen_at
        if seen_at is None:
            continue
        if seen_at.tzinfo is None:
            seen_at = seen_at.replace(tzinfo=timezone.utc)
        if seen_at >= cutoff and product.current_price > 0:
            result.append(product)
    return result


def _quote_allowed(quote: ProductPriceQuote, eligible_audiences: set[str]) -> bool:
    if not quote.is_active or quote.price <= 0:
        return False
    if not quote.eligibility_required:
        return True
    return quote.audience_key.casefold() in eligible_audiences


def _offer_from_product(product: Product) -> SearchOffer:
    regular = int(product.regular_price) if product.regular_price is not None else None
    ptype = "SALE" if regular and regular > product.current_price else "PUBLIC"
    seen = product.last_seen_at
    if seen.tzinfo is None:
        seen = seen.replace(tzinfo=timezone.utc)
    return SearchOffer(
        product_id=int(product.id),
        store_name=product.store_record.name if product.store_record is not None else product.store,
        product_name=product.name,
        price=int(product.current_price),
        regular_price=regular,
        discount_pct=float(product.discount_pct or 0.0),
        url=product.url,
        last_seen_at=seen,
        price_type=ptype,
        audience_key="public",
        eligibility_required=False,
        is_public_market=bool(product.store_record.comparison_enabled) if product.store_record is not None else True,
    )


def _personal_offer_from_product(
    product: Product,
    quotes: list[ProductPriceQuote],
    *,
    eligible_audiences: set[str],
) -> SearchOffer | None:
    allowed = [quote for quote in quotes if _quote_allowed(quote, eligible_audiences)]
    if not allowed:
        # Una tienda pública puede seguir participando aun cuando su backfill de
        # quote todavía no exista. Una fuente exclusivamente personal no hace
        # fallback para evitar usar accidentalmente un precio no elegible.
        if product.store_record is None or product.store_record.comparison_enabled:
            return _offer_from_product(product)
        return None
    priority = {"MEMBER": 0, "SALE": 1, "PUBLIC": 2, "CARD_PROMO": 3, "COUPON": 4}
    quote = min(
        allowed,
        key=lambda row: (int(row.price), priority.get(row.price_type, 9), row.audience_key.casefold()),
    )
    seen = product.last_seen_at
    if seen.tzinfo is None:
        seen = seen.replace(tzinfo=timezone.utc)
    regular = int(quote.regular_price) if quote.regular_price is not None else None
    discount = ((regular - quote.price) / regular) if regular and regular > quote.price else 0.0
    return SearchOffer(
        product_id=int(product.id),
        store_name=product.store_record.name if product.store_record is not None else product.store,
        product_name=product.name,
        price=int(quote.price),
        regular_price=regular,
        discount_pct=float(discount),
        url=product.url,
        last_seen_at=seen,
        price_type=quote.price_type,
        audience_key=quote.audience_key,
        eligibility_required=bool(quote.eligibility_required),
        is_public_market=bool(product.store_record.comparison_enabled) if product.store_record is not None else True,
    )


def search_products(
    session: Session,
    query: str,
    *,
    limit: int = 8,
    offset: int = 0,
    max_age_hours: int = 72,
    minimum_score: float = 0.34,
    price_mode: str = "public",
    eligible_audiences: tuple[str, ...] | list[str] | set[str] = ("cav_member",),
) -> list[SearchResult]:
    price_mode = "personal" if str(price_mode).casefold() == "personal" else "public"
    eligible = {str(value).strip().casefold() for value in eligible_audiences if str(value).strip()}
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
        products = _fresh_products(master.store_products, cutoff=cutoff, price_mode=price_mode)
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

    page_limit = max(1, min(limit, 30))
    start = max(0, int(offset))
    selected_scored = scored[start : start + page_limit]
    selected_ids = [int(item[1].id) for item in selected_scored]
    selected_products = [product for _, _, products in selected_scored for product in products]
    product_ids = [int(product.id) for product in selected_products]

    master_stats = {
        int(item.master_product_id): item
        for item in session.scalars(
            select(MasterPriceStatistic).where(MasterPriceStatistic.master_product_id.in_(selected_ids))
        )
    } if selected_ids else {}
    public_opportunities = {
        int(item.master_product_id): item
        for item in session.scalars(
            select(OpportunitySnapshot).where(OpportunitySnapshot.master_product_id.in_(selected_ids))
        )
    } if selected_ids else {}
    personal_opportunities = {
        int(item.master_product_id): item
        for item in session.scalars(
            select(PersonalOpportunitySnapshot).where(PersonalOpportunitySnapshot.master_product_id.in_(selected_ids))
        )
    } if selected_ids and price_mode == "personal" else {}

    quotes_by_product: dict[int, list[ProductPriceQuote]] = {}
    context_stats: dict[tuple[int, str, str], PriceContextStatistic] = {}
    if price_mode == "personal" and product_ids:
        for quote in session.scalars(
            select(ProductPriceQuote).where(ProductPriceQuote.product_id.in_(product_ids))
        ):
            quotes_by_product.setdefault(int(quote.product_id), []).append(quote)
        context_stats = {
            (int(row.product_id), row.price_type, row.audience_key): row
            for row in session.scalars(
                select(PriceContextStatistic).where(PriceContextStatistic.product_id.in_(product_ids))
            )
        }

    results: list[SearchResult] = []
    for score, master, products in selected_scored:
        cheapest_by_store: dict[int | str, SearchOffer] = {}
        for product in products:
            if price_mode == "personal":
                offer = _personal_offer_from_product(
                    product,
                    quotes_by_product.get(int(product.id), []),
                    eligible_audiences=eligible,
                )
                if offer is None:
                    continue
            else:
                offer = _offer_from_product(product)
            store_key: int | str = product.store_id or product.store
            current = cheapest_by_store.get(store_key)
            if current is None or offer.price < current.price:
                cheapest_by_store[store_key] = offer

        offers = tuple(sorted(cheapest_by_store.values(), key=lambda offer: (offer.price, offer.store_name.casefold())))
        if not offers:
            continue
        winner = offers[0]
        runner_up = offers[1] if len(offers) > 1 else None
        saving_clp = max(0, runner_up.price - winner.price) if runner_up else 0
        saving_pct = saving_clp / runner_up.price if runner_up and runner_up.price else 0.0

        stat_min_30 = stat_avg_30 = stat_min_90 = stat_avg_90 = historical_min = None
        days_at_current = 0
        opportunity_score_value = None
        opportunity_classification = None
        public_reference_price = None
        personal_advantage_clp = 0
        personal_advantage_pct = 0.0

        if price_mode == "personal":
            contextual = context_stats.get((winner.product_id, winner.price_type, winner.audience_key))
            if contextual is not None:
                stat_min_30 = contextual.min_30d
                stat_avg_30 = contextual.avg_30d
                stat_min_90 = contextual.min_90d
                stat_avg_90 = contextual.avg_90d
                historical_min = contextual.historical_min
                days_at_current = int(contextual.days_at_current_price or 0)
            snap = personal_opportunities.get(int(master.id))
            if snap is not None:
                opportunity_score_value = float(snap.score)
                opportunity_classification = snap.classification
                public_reference_price = int(snap.public_reference_price) if snap.public_reference_price is not None else None
                personal_advantage_clp = int(snap.personal_advantage_clp or 0)
                personal_advantage_pct = float(snap.personal_advantage_pct or 0.0)
            if public_reference_price is None:
                public_prices = [offer.price for offer in offers if offer.is_public_market]
                public_reference_price = min(public_prices, default=None)
                if public_reference_price is not None:
                    personal_advantage_clp = max(0, public_reference_price - winner.price)
                    personal_advantage_pct = personal_advantage_clp / public_reference_price if public_reference_price else 0.0
        else:
            stats = master_stats.get(int(master.id))
            if stats is not None:
                stat_min_30 = stats.min_30d
                stat_avg_30 = stats.avg_30d
                stat_min_90 = stats.min_90d
                stat_avg_90 = stats.avg_90d
                historical_min = stats.historical_min
                days_at_current = int(stats.days_at_current_price or 0)
            snap = public_opportunities.get(int(master.id))
            if snap is not None:
                opportunity_score_value = float(snap.score)
                opportunity_classification = snap.classification

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
                min_30d=stat_min_30,
                avg_30d=stat_avg_30,
                min_90d=stat_min_90,
                avg_90d=stat_avg_90,
                historical_min=historical_min,
                days_at_current_price=days_at_current,
                opportunity_score=opportunity_score_value,
                opportunity_classification=opportunity_classification,
                price_mode=price_mode,
                public_reference_price=public_reference_price,
                personal_advantage_clp=personal_advantage_clp,
                personal_advantage_pct=personal_advantage_pct,
            )
        )
    return results
