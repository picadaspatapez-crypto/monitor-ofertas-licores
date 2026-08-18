from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.intelligence.opportunity import OpportunityComponents, classify_opportunity, opportunity_score
from app.models import (
    MasterProduct,
    PersonalOpportunitySnapshot,
    PriceContextStatistic,
    Product,
    ProductMatch,
    ProductPriceQuote,
    Store,
)
from app.repositories.common import utcnow


def _normalized_audiences(values) -> set[str]:
    return {str(value).strip().casefold() for value in values or () if str(value).strip()}


def _quote_allowed(quote: ProductPriceQuote, eligible_audiences: set[str]) -> bool:
    if not quote.is_active or quote.price <= 0:
        return False
    if not quote.eligibility_required:
        return True
    return quote.audience_key.casefold() in eligible_audiences


def _best_quote(
    rows: list[ProductPriceQuote], *, eligible_audiences: set[str]
) -> ProductPriceQuote | None:
    allowed = [row for row in rows if _quote_allowed(row, eligible_audiences)]
    if not allowed:
        return None
    priority = {"MEMBER": 0, "SALE": 1, "PUBLIC": 2, "CARD_PROMO": 3, "COUPON": 4}
    return min(
        allowed,
        key=lambda row: (
            int(row.price),
            priority.get(row.price_type, 9),
            row.audience_key.casefold(),
        ),
    )


def _history_position(current: int, stats: PriceContextStatistic | None) -> float:
    if stats is None or not stats.avg_90d or stats.avg_90d <= 0:
        return 0.5
    average = float(stats.avg_90d)
    delta = (average - current) / average
    score = 0.5 + delta / 0.30
    if stats.min_90d and current <= stats.min_90d:
        score = max(score, 1.0)
    return max(0.0, min(1.0, score))


def _freshness(product: Product, now: datetime) -> float:
    seen = product.last_seen_at
    if seen is None:
        return 0.0
    if seen.tzinfo is None:
        seen = seen.replace(tzinfo=timezone.utc)
    age_h = max(0.0, (now - seen).total_seconds() / 3600)
    if age_h <= 6:
        return 1.0
    if age_h <= 24:
        return 0.9
    if age_h <= 72:
        return 0.7
    return 0.4


def refresh_personal_opportunities(
    session: Session,
    *,
    eligible_audiences: tuple[str, ...] | list[str] | set[str] = ("cav_member",),
) -> int:
    """Calcula el comparador personal sin modificar el mercado público.

    Las tiendas públicas siempre participan. Fuentes como CAV participan cuando
    ``personal_comparison_enabled`` está activo. Los precios que requieren
    elegibilidad solo se usan si su ``audience_key`` está configurado para el
    perfil personal.
    """
    eligible = _normalized_audiences(eligible_audiences)
    rows = session.execute(
        select(Product, Store, ProductMatch, ProductPriceQuote)
        .join(Store, Store.id == Product.store_id)
        .outerjoin(ProductMatch, ProductMatch.store_product_id == Product.id)
        .join(ProductPriceQuote, ProductPriceQuote.product_id == Product.id)
        .where(
            Store.is_active.is_(True),
            Product.is_available.is_(True),
            Product.excluded_from_comparison.is_(False),
            Product.package_quantity == 1,
            Product.master_product_id.is_not(None),
            ProductPriceQuote.is_active.is_(True),
        )
    )
    grouped: dict[int, dict[int, tuple[Product, Store, ProductMatch | None, list[ProductPriceQuote]]]] = defaultdict(dict)
    for product, store, match, quote in rows:
        if not (store.comparison_enabled or store.personal_comparison_enabled):
            continue
        master_id = int(product.master_product_id)
        pid = int(product.id)
        if pid not in grouped[master_id]:
            grouped[master_id][pid] = (product, store, match, [])
        grouped[master_id][pid][3].append(quote)

    stat_rows = list(session.scalars(select(PriceContextStatistic)))
    stats = {
        (int(row.product_id), row.price_type, row.audience_key): row
        for row in stat_rows
    }

    now = utcnow()
    active_ids: set[int] = set()
    updated = 0
    for master_id, by_product in grouped.items():
        offers = []
        for product, store, match, quotes in by_product.values():
            quote = _best_quote(quotes, eligible_audiences=eligible)
            if quote is None:
                continue
            confidence = float(match.confidence) if match is not None else 1.0
            offers.append((int(quote.price), product, store, quote, confidence))
        if len(offers) < 2:
            continue

        offers.sort(key=lambda item: (item[0], item[2].name.casefold()))
        winner = offers[0]
        runner = offers[1]
        saving = max(0, runner[0] - winner[0])
        saving_pct = saving / runner[0] if runner[0] else 0.0

        public_prices: list[int] = []
        for product, store, _match, quotes in by_product.values():
            if not store.comparison_enabled:
                continue
            public_quotes = [
                quote for quote in quotes
                if quote.is_active
                and int(quote.price or 0) > 0
                and not quote.eligibility_required
                and str(quote.price_type or "").upper() in {"PUBLIC", "SALE"}
            ]
            if public_quotes:
                public_prices.append(min(int(quote.price) for quote in public_quotes))
            elif not store.personal_comparison_enabled and int(product.current_price or 0) > 0:
                public_prices.append(int(product.current_price))
        public_reference = min(public_prices, default=None)
        advantage = max(0, (public_reference or winner[0]) - winner[0]) if public_reference else 0
        advantage_pct = advantage / public_reference if public_reference else 0.0

        winner_stats = stats.get((int(winner[1].id), winner[3].price_type, winner[3].audience_key))
        history = _history_position(winner[0], winner_stats)
        confidence = min(winner[4], runner[4])
        freshness = min(_freshness(winner[1], now), _freshness(runner[1], now))
        scarcity = max(0.0, min(1.0, (7 - len(offers)) / 5))
        score = opportunity_score(
            OpportunityComponents(
                market_saving=min(1.0, saving_pct / 0.30),
                history_position=history,
                match_confidence=confidence,
                freshness=freshness,
                scarcity=scarcity,
            )
        )

        row = session.get(PersonalOpportunitySnapshot, master_id)
        if row is None:
            row = PersonalOpportunitySnapshot(
                master_product_id=master_id,
                score=score,
                classification=classify_opportunity(score),
            )
            session.add(row)
        row.score = score
        row.classification = classify_opportunity(score)
        row.winner_product_id = int(winner[1].id)
        row.winner_store_id = int(winner[2].id)
        row.winner_price = winner[0]
        row.winner_price_type = winner[3].price_type
        row.winner_audience_key = winner[3].audience_key
        row.saving_clp = saving
        row.saving_pct = saving_pct
        row.public_reference_price = public_reference
        row.personal_advantage_clp = advantage
        row.personal_advantage_pct = advantage_pct
        row.history_position = history
        row.match_confidence = confidence
        row.freshness_score = freshness
        row.scarcity_score = scarcity
        row.calculated_at = now
        active_ids.add(master_id)
        updated += 1

    if active_ids:
        session.execute(
            delete(PersonalOpportunitySnapshot).where(
                PersonalOpportunitySnapshot.master_product_id.not_in(active_ids)
            )
        )
    else:
        session.execute(delete(PersonalOpportunitySnapshot))
    session.flush()
    return updated


@dataclass(frozen=True)
class PersonalOpportunityView:
    master_product_id: int
    canonical_name: str
    score: float
    classification: str
    winner_store: str
    winner_price: int
    price_type: str
    audience_key: str
    saving_clp: int
    saving_pct: float
    public_reference_price: int | None
    personal_advantage_clp: int
    personal_advantage_pct: float
    history_position: float
    url: str


def top_personal_opportunities(
    session: Session,
    *,
    limit: int = 20,
    minimum_score: float = 0.0,
) -> list[PersonalOpportunityView]:
    statement = (
        select(PersonalOpportunitySnapshot, MasterProduct, Product, Store)
        .join(MasterProduct, MasterProduct.id == PersonalOpportunitySnapshot.master_product_id)
        .join(Product, Product.id == PersonalOpportunitySnapshot.winner_product_id)
        .join(Store, Store.id == PersonalOpportunitySnapshot.winner_store_id)
        .where(
            Product.is_available.is_(True),
            Product.excluded_from_comparison.is_(False),
            Product.package_quantity == 1,
            Store.is_active.is_(True),
            PersonalOpportunitySnapshot.score >= float(minimum_score),
        )
        .order_by(
            PersonalOpportunitySnapshot.score.desc(),
            PersonalOpportunitySnapshot.personal_advantage_pct.desc(),
            PersonalOpportunitySnapshot.saving_pct.desc(),
        )
        .limit(max(1, min(int(limit), 30)))
    )
    return [
        PersonalOpportunityView(
            master_product_id=int(master.id),
            canonical_name=master.canonical_name,
            score=float(snapshot.score),
            classification=snapshot.classification,
            winner_store=store.name,
            winner_price=int(snapshot.winner_price or product.current_price),
            price_type=snapshot.winner_price_type,
            audience_key=snapshot.winner_audience_key,
            saving_clp=int(snapshot.saving_clp or 0),
            saving_pct=float(snapshot.saving_pct or 0.0),
            public_reference_price=(
                int(snapshot.public_reference_price)
                if snapshot.public_reference_price is not None
                else None
            ),
            personal_advantage_clp=int(snapshot.personal_advantage_clp or 0),
            personal_advantage_pct=float(snapshot.personal_advantage_pct or 0.0),
            history_position=float(snapshot.history_position or 0.5),
            url=product.url,
        )
        for snapshot, master, product, store in session.execute(statement)
    ]
