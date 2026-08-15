from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.domain import CollectedPriceQuote, CollectedProduct
from app.models import MasterPriceStatistic, Product, ScrapeRun, Store
from app.repositories.products import save_product
from app.search.engine import search_products
from app.analyzers.comparison import analyze_cross_store_prices
from app.intelligence.history import refresh_price_statistics
from app.telegram_bot.commands import parse_command
from app.telegram_bot.formatting import quality_message


def _session_factory():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)


def test_quality_command_is_recognized_in_telegram():
    assert parse_command("/quality").name == "quality"
    assert parse_command("/calidad").name == "quality"


def test_quality_message_formats_incidents():
    row = Product(store="Líquidos", name="Null", url="https://example.com/null", current_price=2600)
    row.data_quality_status = "BLOCKED"
    row.data_quality_score = 15
    row.data_quality_issues = ["invalid_name", "suspicious_discount"]
    text = quality_message([row], blocked=1, warnings=0)
    assert "Calidad de datos" in text
    assert "Bloqueadas" in text
    assert "Null" in text
    assert "$2.600" in text


def test_cav_public_search_uses_public_quote_not_member_quote():
    engine, SessionLocal = _session_factory()
    with SessionLocal() as session:
        public = Store(name="Otra", slug="otra", base_url="https://otra.example", connector_key="otra", is_active=True, comparison_enabled=True)
        cav = Store(name="CAV", slug="cav", base_url="https://cav.example", connector_key="cav", is_active=True, comparison_enabled=True, personal_comparison_enabled=True)
        session.add_all([public, cav]); session.flush()
        run_a = ScrapeRun(store_id=public.id, status="running")
        run_c = ScrapeRun(store_id=cav.id, status="running")
        session.add_all([run_a, run_c]); session.flush()
        save_product(session, CollectedProduct(store="Otra", name="Gin Demo 700 ml", url="https://otra.example/gin", current_price=24000, regular_price=None, discount_pct=0), public, run_a)
        save_product(session, CollectedProduct(store="CAV", name="Gin Demo 700 ml", url="https://cav.example/gin", current_price=23000, regular_price=26000, discount_pct=3000/26000, price_quotes=(
            CollectedPriceQuote(23000, "SALE", 26000, "public_offer", False),
            CollectedPriceQuote(20000, "MEMBER", 26000, "cav_member", True),
        )), cav, run_c)
        session.commit()
        public_results = search_products(session, "gin demo 700", price_mode="public")
        personal_results = search_products(session, "gin demo 700", price_mode="personal", eligible_audiences=("cav_member",))
        assert public_results
        cav_public = next(o for o in public_results[0].offers if o.store_name == "CAV")
        assert cav_public.price == 23000
        assert cav_public.price_type == "SALE"
        assert personal_results[0].winner.store_name == "CAV"
        assert personal_results[0].winner.price == 20000
        assert personal_results[0].winner.price_type == "MEMBER"
    engine.dispose()


def test_cav_member_only_product_is_not_exposed_in_public_search():
    engine, SessionLocal = _session_factory()
    with SessionLocal() as session:
        cav = Store(name="CAV", slug="cav", base_url="https://cav.example", connector_key="cav", is_active=True, comparison_enabled=True, personal_comparison_enabled=True)
        session.add(cav); session.flush()
        run = ScrapeRun(store_id=cav.id, status="running")
        session.add(run); session.flush()
        save_product(session, CollectedProduct(store="CAV", name="Whisky Member Only 750 ml", url="https://cav.example/member", current_price=19000, regular_price=None, discount_pct=0, price_quotes=(
            CollectedPriceQuote(19000, "MEMBER", 25000, "cav_member", True),
        )), cav, run)
        session.commit()
        assert search_products(session, "whisky member only 750", price_mode="public") == []
        personal = search_products(session, "whisky member only 750", price_mode="personal", eligible_audiences=("cav_member",))
        assert personal and personal[0].winner.price == 19000
    engine.dispose()


def test_cross_store_analyzer_uses_cav_public_quote_even_if_raw_current_is_lower():
    engine, SessionLocal = _session_factory()
    with SessionLocal() as session:
        other = Store(name="Otra", slug="otra", base_url="https://otra.example", connector_key="otra", is_active=True, comparison_enabled=True)
        cav = Store(name="CAV", slug="cav", base_url="https://cav.example", connector_key="cav", is_active=True, comparison_enabled=True, personal_comparison_enabled=True)
        session.add_all([other, cav]); session.flush()
        run_o = ScrapeRun(store_id=other.id, status="running")
        run_c = ScrapeRun(store_id=cav.id, status="running")
        session.add_all([run_o, run_c]); session.flush()
        save_product(session, CollectedProduct(store="Otra", name="Whisky Demo 750 ml", url="https://otra.example/w", current_price=25000, regular_price=None, discount_pct=0), other, run_o)
        cav_saved = save_product(session, CollectedProduct(store="CAV", name="Whisky Demo 750 ml", url="https://cav.example/w", current_price=20000, regular_price=26000, discount_pct=0, price_quotes=(
            CollectedPriceQuote(23000, "SALE", 26000, "public_offer", False),
            CollectedPriceQuote(20000, "MEMBER", 26000, "cav_member", True),
        )), cav, run_c)
        session.flush()
        analysis = analyze_cross_store_prices(session, run_ids=[run_o.id, run_c.id], minimum_confidence=0.80)
        assert analysis.opportunities
        comparison = analysis.opportunities[0]
        cav_offer = next(o for o in comparison.offers if o.store_name == "CAV")
        assert cav_offer.price == 23000
        assert comparison.winner is not None and comparison.winner.store_name == "CAV"
    engine.dispose()


def test_public_history_excludes_hybrid_member_only_observation():
    engine, SessionLocal = _session_factory()
    with SessionLocal() as session:
        cav = Store(name="CAV", slug="cav", base_url="https://cav.example", connector_key="cav", is_active=True, comparison_enabled=True, personal_comparison_enabled=True)
        session.add(cav); session.flush()
        run = ScrapeRun(store_id=cav.id, status="running")
        session.add(run); session.flush()
        saved = save_product(session, CollectedProduct(store="CAV", name="Rum Member Only 750 ml", url="https://cav.example/r", current_price=15000, regular_price=None, discount_pct=0, price_quotes=(
            CollectedPriceQuote(15000, "MEMBER", 22000, "cav_member", True),
        )), cav, run)
        session.flush()
        refresh_price_statistics(session)
        stat = session.get(MasterPriceStatistic, saved.product.master_product_id)
        assert stat is None or stat.current_best_price is None
    engine.dispose()
