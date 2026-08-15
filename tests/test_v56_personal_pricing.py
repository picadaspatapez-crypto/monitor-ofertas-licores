from __future__ import annotations

from datetime import timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.domain import CollectedPriceQuote, CollectedProduct
from app.intelligence.context_history import refresh_context_price_statistics
from app.intelligence.personal import refresh_personal_opportunities
from app.models import (
    PersonalOpportunitySnapshot,
    PriceContextStatistic,
    PriceQuoteObservation,
    Product,
    ScrapeRun,
    Store,
)
from app.notifications.personal import build_personal_price_notification_bundles
from app.repositories.common import utcnow
from app.repositories.products import save_product
from app.search.engine import search_products
from app.search.web import CatalogPulse, _search_html
from app.telegram_bot.commands import parse_command


def _session_factory():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)


def _store(
    session,
    *,
    name: str,
    key: str,
    comparison_enabled: bool = True,
    personal_comparison_enabled: bool = False,
):
    row = Store(
        name=name,
        slug=key,
        base_url=f"https://{key}.example",
        connector_key=key,
        is_active=True,
        requires_browser=False,
        comparison_enabled=comparison_enabled,
        diagnostic_mode=False,
        personal_comparison_enabled=personal_comparison_enabled,
    )
    session.add(row)
    session.flush()
    return row


def _save_pair(session):
    public = _store(session, name="La Vinoteca", key="lavinoteca")
    cav = _store(
        session,
        name="CAV",
        key="cav",
        comparison_enabled=True,
        personal_comparison_enabled=True,
    )
    run_public = ScrapeRun(store_id=public.id, status="running")
    run_cav = ScrapeRun(store_id=cav.id, status="running")
    session.add_all([run_public, run_cav])
    session.flush()
    public_saved = save_product(
        session,
        CollectedProduct(
            store="La Vinoteca",
            name="Whisky Demo 750 ml",
            url="https://lavinoteca.example/demo",
            current_price=24000,
            regular_price=27000,
            discount_pct=3000 / 27000,
        ),
        public,
        run_public,
    )
    cav_saved = save_product(
        session,
        CollectedProduct(
            store="CAV",
            name="Whisky Demo 750 ml",
            url="https://cav.example/demo",
            current_price=26000,
            regular_price=None,
            discount_pct=0,
            price_quotes=(
                CollectedPriceQuote(26000, "PUBLIC", audience_key="public"),
                CollectedPriceQuote(
                    21000,
                    "MEMBER",
                    regular_price=26000,
                    audience_key="cav_member",
                    eligibility_required=True,
                ),
            ),
        ),
        cav,
        run_cav,
    )
    assert public_saved.product.master_product_id == cav_saved.product.master_product_id
    return public, cav, public_saved.product, cav_saved.product


def test_cav_is_hybrid_public_and_personal_source():
    from app.collectors.cav import CAVCollector

    assert CAVCollector.metadata.comparison_enabled is True
    assert CAVCollector.metadata.personal_comparison_enabled is True
    assert CAVCollector.metadata.diagnostic_mode is False


def test_context_history_keeps_member_and_public_prices_separate():
    engine, SessionLocal = _session_factory()
    with SessionLocal() as session:
        _, _, _, cav_product = _save_pair(session)
        session.flush()
        result = refresh_context_price_statistics(session)
        session.flush()
        rows = list(
            session.scalars(
                select(PriceContextStatistic)
                .where(PriceContextStatistic.product_id == cav_product.id)
                .order_by(PriceContextStatistic.price_type)
            )
        )
        assert result.rows_updated >= 3
        values = {(row.price_type, row.audience_key): row.current_price for row in rows}
        assert values[("MEMBER", "cav_member")] == 21000
        assert values[("PUBLIC", "public")] == 26000
    engine.dispose()


def test_public_search_uses_cav_public_price_and_personal_search_uses_member_price():
    engine, SessionLocal = _session_factory()
    with SessionLocal() as session:
        _save_pair(session)
        refresh_context_price_statistics(session)
        refresh_personal_opportunities(session, eligible_audiences=("cav_member",))
        public = search_products(session, "whisky demo 750", price_mode="public")
        personal = search_products(
            session,
            "whisky demo 750",
            price_mode="personal",
            eligible_audiences=("cav_member",),
        )
        assert public
        assert [offer.store_name for offer in public[0].offers] == ["La Vinoteca", "CAV"]
        cav_public = next(offer for offer in public[0].offers if offer.store_name == "CAV")
        assert cav_public.price == 26000
        assert cav_public.price_type == "PUBLIC"
        assert personal
        assert personal[0].winner.store_name == "CAV"
        assert personal[0].winner.price == 21000
        assert personal[0].winner.price_type == "MEMBER"
        assert personal[0].public_reference_price == 24000
        assert personal[0].personal_advantage_clp == 3000
        assert personal[0].personal_advantage_pct == 3000 / 24000
    engine.dispose()


def test_personal_opportunity_persists_public_reference_and_history_signal():
    engine, SessionLocal = _session_factory()
    with SessionLocal() as session:
        _, _, public_product, cav_product = _save_pair(session)
        # Segunda observación MEMBER más baja para que exista historia real.
        now = utcnow()
        session.add(
            PriceQuoteObservation(
                product_id=cav_product.id,
                scrape_run_id=None,
                price=23000,
                regular_price=26000,
                price_type="MEMBER",
                audience_key="cav_member",
                eligibility_required=True,
                observed_at=now - timedelta(days=2),
            )
        )
        session.flush()
        refresh_context_price_statistics(session)
        count = refresh_personal_opportunities(session, eligible_audiences=("cav_member",))
        session.flush()
        snapshot = session.scalar(select(PersonalOpportunitySnapshot))
        assert count == 1
        assert snapshot is not None
        assert snapshot.winner_product_id == cav_product.id
        assert snapshot.public_reference_price == public_product.current_price
        assert snapshot.personal_advantage_clp == 3000
        assert snapshot.history_position >= 0.5
    engine.dispose()


def test_personal_alerts_include_member_drop_and_advantage_digest():
    engine, SessionLocal = _session_factory()
    with SessionLocal() as session:
        _, _, _, cav_product = _save_pair(session)
        now = utcnow()
        # save_product ya escribió la observación actual 21.000; agregamos una
        # observación previa más cara con fecha anterior.
        session.add(
            PriceQuoteObservation(
                product_id=cav_product.id,
                scrape_run_id=None,
                price=23000,
                regular_price=26000,
                price_type="MEMBER",
                audience_key="cav_member",
                eligibility_required=True,
                observed_at=now - timedelta(days=1),
            )
        )
        session.flush()
        refresh_context_price_statistics(session)
        refresh_personal_opportunities(session, eligible_audiences=("cav_member",))
        session.flush()
        bundles = build_personal_price_notification_bundles(
            session,
            eligible_audiences=("cav_member",),
            min_drop_pct=0.05,
            min_drop_amount=1000,
            min_advantage_clp=1000,
            limit=10,
        )
        types = {bundle.alert_type for bundle in bundles}
        assert "personal_member_price_drop" in types
        assert "personal_member_advantage_digest" in types
    engine.dispose()


def test_web_ui_has_public_personal_switch_and_member_badge():
    engine, SessionLocal = _session_factory()
    with SessionLocal() as session:
        _save_pair(session)
        refresh_context_price_statistics(session)
        refresh_personal_opportunities(session, eligible_audiences=("cav_member",))
        result = search_products(
            session,
            "whisky demo 750",
            price_mode="personal",
            eligible_audiences=("cav_member",),
        )[0]
    page = _search_html(
        query="whisky demo 750",
        results=[result],
        max_age_hours=72,
        pulse=CatalogPulse(public_stores=8, personal_sources=1),
        price_mode="personal",
    ).decode("utf-8")
    assert "Con membresía CAV" in page
    assert "Precio socio" in page
    assert "Mejor precio para ti" in page
    assert "Ahorro por membresía" in page
    engine.dispose()


def test_personal_telegram_commands_are_explicit():
    assert parse_command("/personal").name == "personal_opportunities"
    command = parse_command("/miprecio johnnie black 750")
    assert command.name == "personal_search"
    assert command.query == "johnnie black 750"
    history = parse_command("/historialsocio johnnie black 750")
    assert history.name == "personal_history"
