from __future__ import annotations

from collections import defaultdict

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.intelligence.opportunity import OpportunityComponents, classify_opportunity, opportunity_score
from app.models import PersonalOpportunitySnapshot, Product, ProductMatch, ProductPriceQuote, Store
from app.repositories.common import utcnow


def _best_quote(rows: list[ProductPriceQuote]) -> ProductPriceQuote | None:
    active = [row for row in rows if row.is_active and row.price > 0]
    if not active:
        return None
    # Para el perfil personal se admiten MEMBER y promociones públicas. CARD_PROMO
    # y COUPON quedan modelados, pero no se activan sin una elegibilidad configurada.
    allowed = [row for row in active if row.price_type in {"PUBLIC", "SALE", "MEMBER"}]
    return min(allowed, key=lambda row: (row.price, row.eligibility_required, row.price_type)) if allowed else None


def refresh_personal_opportunities(session: Session) -> int:
    """Vista personal separada; nunca modifica el comparador público ni sus alertas."""
    rows = session.execute(
        select(Product, Store, ProductMatch, ProductPriceQuote)
        .join(Store, Store.id == Product.store_id)
        .outerjoin(ProductMatch, ProductMatch.store_product_id == Product.id)
        .join(ProductPriceQuote, ProductPriceQuote.product_id == Product.id)
        .where(
            Store.is_active.is_(True),
            Product.is_available.is_(True),
            Product.master_product_id.is_not(None),
            ProductPriceQuote.is_active.is_(True),
        )
    )
    grouped: dict[int, dict[int, tuple[Product, Store, ProductMatch | None, list[ProductPriceQuote]]]] = defaultdict(dict)
    for product, store, match, quote in rows:
        master_id = int(product.master_product_id)
        pid = int(product.id)
        if pid not in grouped[master_id]:
            grouped[master_id][pid] = (product, store, match, [])
        grouped[master_id][pid][3].append(quote)

    now = utcnow()
    active_ids: set[int] = set()
    updated = 0
    for master_id, by_product in grouped.items():
        offers = []
        for product, store, match, quotes in by_product.values():
            quote = _best_quote(quotes)
            if quote is None:
                continue
            # Tiendas diagnósticas solo pueden entrar mediante un precio MEMBER;
            # su precio normal no altera esta vista ni el comparador público.
            if store.diagnostic_mode and quote.price_type != "MEMBER":
                member_quotes = [q for q in quotes if q.is_active and q.price_type == "MEMBER" and q.price > 0]
                if not member_quotes:
                    continue
                quote = min(member_quotes, key=lambda q: q.price)
            confidence = float(match.confidence) if match is not None else 1.0
            offers.append((int(quote.price), product, store, quote, confidence))
        if len(offers) < 2:
            continue
        offers.sort(key=lambda item: (item[0], item[2].name.casefold()))
        winner, runner = offers[0], offers[1]
        saving = max(0, runner[0] - winner[0])
        saving_pct = saving / runner[0] if runner[0] else 0.0
        # Preview personal: usa señal de mercado, matching y disponibilidad; el
        # histórico público sigue siendo la referencia consolidada de v5.4.
        score = opportunity_score(OpportunityComponents(
            market_saving=min(1.0, saving_pct / 0.30),
            history_position=0.5,
            match_confidence=min(winner[4], runner[4]),
            freshness=1.0,
            scarcity=max(0.0, min(1.0, (7 - len(offers)) / 5)),
        ))
        row = session.get(PersonalOpportunitySnapshot, master_id)
        if row is None:
            row = PersonalOpportunitySnapshot(master_product_id=master_id, score=score, classification=classify_opportunity(score))
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
        row.calculated_at = now
        active_ids.add(master_id)
        updated += 1

    if active_ids:
        session.execute(delete(PersonalOpportunitySnapshot).where(PersonalOpportunitySnapshot.master_product_id.not_in(active_ids)))
    else:
        session.execute(delete(PersonalOpportunitySnapshot))
    session.flush()
    return updated

from dataclasses import dataclass
from app.models import MasterProduct


@dataclass(frozen=True)
class PersonalOpportunityView:
    canonical_name: str
    score: float
    classification: str
    winner_store: str
    winner_price: int
    price_type: str
    audience_key: str
    saving_clp: int
    saving_pct: float
    url: str


def top_personal_opportunities(session: Session, *, limit: int = 20) -> list[PersonalOpportunityView]:
    statement = (
        select(PersonalOpportunitySnapshot, MasterProduct, Product, Store)
        .join(MasterProduct, MasterProduct.id == PersonalOpportunitySnapshot.master_product_id)
        .join(Product, Product.id == PersonalOpportunitySnapshot.winner_product_id)
        .join(Store, Store.id == PersonalOpportunitySnapshot.winner_store_id)
        .where(Product.is_available.is_(True), Store.is_active.is_(True))
        .order_by(PersonalOpportunitySnapshot.score.desc(), PersonalOpportunitySnapshot.saving_pct.desc())
        .limit(max(1, min(int(limit), 30)))
    )
    return [
        PersonalOpportunityView(
            canonical_name=master.canonical_name,
            score=float(snapshot.score),
            classification=snapshot.classification,
            winner_store=store.name,
            winner_price=int(snapshot.winner_price or product.current_price),
            price_type=snapshot.winner_price_type,
            audience_key=snapshot.winner_audience_key,
            saving_clp=int(snapshot.saving_clp or 0),
            saving_pct=float(snapshot.saving_pct or 0.0),
            url=product.url,
        )
        for snapshot, master, product, store in session.execute(statement)
    ]
