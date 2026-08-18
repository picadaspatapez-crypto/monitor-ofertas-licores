from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.analyzers.comparison import analyze_cross_store_prices
from app.database import Base
from app.intelligence.commercial import (
    CommercialComponents,
    classify_commercial_signal,
    commercial_opportunity_score,
)
from app.intelligence.history import refresh_price_statistics
from app.models import MasterProduct, PriceObservation, Product, ProductMatch, ScrapeRun, Store
from app.notifications.commercial import CommercialAlertContext, build_commercial_notification_bundles
from app.repositories.common import utcnow
from app.telegram_bot.commands import parse_command


def _session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)


def test_score_v2_reaches_100_with_all_components_maxed():
    score = commercial_opportunity_score(
        CommercialComponents(1, 1, 1, 1, 1, 1)
    )
    assert score == 100.0


def test_new_historical_min_has_priority_over_rare_offer():
    signal = classify_commercial_signal(
        current_price=19990,
        previous_historical_min=22990,
        historical_min=19990,
        observations_90d=20,
        rarity_frequency_90d=0.05,
        rarity_score_value=0.95,
        saving_pct=0.20,
    )
    assert signal.event == "NEW_HISTORICAL_MIN"
    assert signal.historical_gap_clp == 3000


def test_rare_offer_requires_enough_history():
    signal = classify_commercial_signal(
        current_price=19990,
        previous_historical_min=19000,
        historical_min=19000,
        observations_90d=3,
        rarity_frequency_90d=0.0,
        rarity_score_value=1.0,
        saving_pct=0.20,
        minimum_observations=6,
    )
    assert signal.event != "RARE_OFFER"


def test_history_refresh_calculates_floor_frequency_90d():
    engine, SessionLocal = _session_factory()
    with SessionLocal() as session:
        store = Store(name="A", slug="a", base_url="https://a.example", connector_key="a")
        master = MasterProduct(canonical_name="Whisky Demo 750 ml", normalized_key="whisky-demo|750")
        session.add_all([store, master]); session.flush()
        product = Product(
            store="A", store_id=store.id, master_product_id=master.id,
            name="Whisky Demo 750 ml", url="https://a.example/p", current_price=10000,
        )
        session.add(product); session.flush()
        now = utcnow()
        for idx, price in enumerate((10000, 10400, 12000, 13000)):
            session.add(PriceObservation(
                product_id=product.id, price=price, discount_pct=0.0,
                observed_at=now - timedelta(days=idx + 1),
            ))
        session.flush()
        refresh_price_statistics(session)
        stat = master.id and session.get(__import__('app.models', fromlist=['MasterPriceStatistic']).MasterPriceStatistic, master.id)
        assert stat is not None
        assert stat.min_90d == 10000
        assert stat.low_price_frequency_90d == pytest.approx(0.5)
    engine.dispose()


def test_cross_store_detects_new_historical_min_and_alert_bundle():
    engine, SessionLocal = _session_factory()
    with SessionLocal() as session:
        a = Store(name="A", slug="a", base_url="https://a.example", connector_key="a")
        b = Store(name="B", slug="b", base_url="https://b.example", connector_key="b")
        master = MasterProduct(canonical_name="Whisky Demo 750 ml", normalized_key="whisky-demo|750")
        session.add_all([a, b, master]); session.flush()
        pa = Product(store="A", store_id=a.id, master_product_id=master.id, name="Whisky Demo 750 ml", url="https://a.example/p", current_price=8000)
        pb = Product(store="B", store_id=b.id, master_product_id=master.id, name="Whisky Demo 750 ml", url="https://b.example/p", current_price=10000)
        session.add_all([pa, pb]); session.flush()
        session.add_all([
            ProductMatch(store_product_id=pa.id, master_product_id=master.id, confidence=1.0, matching_method="manual_equivalence"),
            ProductMatch(store_product_id=pb.id, master_product_id=master.id, confidence=1.0, matching_method="manual_equivalence"),
        ])
        old_a = ScrapeRun(store_id=a.id, status="success", health_status="HEALTHY")
        old_b = ScrapeRun(store_id=b.id, status="success", health_status="HEALTHY")
        session.add_all([old_a, old_b]); session.flush()
        old_time = utcnow() - timedelta(days=3)
        session.add_all([
            PriceObservation(product_id=pa.id, scrape_run_id=old_a.id, price=9000, discount_pct=0, observed_at=old_time),
            PriceObservation(product_id=pb.id, scrape_run_id=old_b.id, price=11000, discount_pct=0, observed_at=old_time),
        ])
        run_a = ScrapeRun(store_id=a.id, status="success", health_status="HEALTHY")
        run_b = ScrapeRun(store_id=b.id, status="success", health_status="HEALTHY")
        session.add_all([run_a, run_b]); session.flush()
        session.add_all([
            PriceObservation(product_id=pa.id, scrape_run_id=run_a.id, price=8000, discount_pct=0, observed_at=utcnow()),
            PriceObservation(product_id=pb.id, scrape_run_id=run_b.id, price=10000, discount_pct=0, observed_at=utcnow()),
        ])
        session.flush()
        refresh_price_statistics(session)
        analysis = analyze_cross_store_prices(
            session,
            run_ids=[run_a.id, run_b.id],
            current_observation_run_ids=[run_a.id, run_b.id],
            minimum_confidence=0.80,
            commercial_min_history_observations=1,
        )
        assert analysis.opportunities
        item = analysis.opportunities[0]
        assert item.price_event == "NEW_HISTORICAL_MIN"
        assert item.previous_historical_min == 9000
        assert item.historical_gap_clp == 1000
        bundles = build_commercial_notification_bundles(
            analysis,
            context=CommercialAlertContext(minimum_history_observations=1),
        )
        assert len(bundles) == 1
        assert bundles[0].alert_type == "commercial_new_historical_min"
        assert bundles[0].deduplication_key.endswith(f":{master.id}:8000")
    engine.dispose()


def test_new_telegram_commands_are_recognized():
    assert parse_command("/radar").name == "commercial_radar"
    assert parse_command("/inteligencia").name == "commercial_radar"
    assert parse_command("/minimos").name == "historical_floors"


def _rare_analysis(*, previous_price: int | None) -> __import__('app.analyzers.comparison', fromlist=['ComparisonAnalysis']).ComparisonAnalysis:
    from app.analyzers.comparison import ComparisonAnalysis, PriceComparison, StoreOffer

    winner = StoreOffer(
        product_id=1,
        store_id=1,
        store_name="A",
        product_name="Whisky Demo 750 ml",
        price=10000,
        regular_price=13000,
        discount_pct=0.23,
        url="https://a.example/p",
    )
    runner = StoreOffer(
        product_id=2,
        store_id=2,
        store_name="B",
        product_name="Whisky Demo 750 ml",
        price=12500,
        regular_price=None,
        discount_pct=0.0,
        url="https://b.example/p",
    )
    comparison = PriceComparison(
        master_product_id=10,
        canonical_name="Whisky Demo 750 ml",
        volume_ml=750,
        offers=(winner, runner),
        winner=winner,
        runner_up=runner,
        saving_clp=2500,
        saving_pct=0.20,
        confidence=0.99,
        previous_winner_store_id=1,
        previous_winner_store_name="A",
        winner_changed=False,
        is_tie=False,
        winner_previous_price=previous_price,
        history_observations_90d=20,
        opportunity_score=92.0,
        opportunity_classification="Excelente",
        rarity_score=0.90,
        rarity_frequency_90d=0.10,
        price_event="RARE_OFFER",
        intelligence_reason="oferta poco frecuente",
    )
    return ComparisonAnalysis(2, 1, 1, (comparison,), (), 0, 0)


def test_rare_offer_does_not_alert_only_because_v58_was_deployed():
    bundles = build_commercial_notification_bundles(
        _rare_analysis(previous_price=10000),
        context=CommercialAlertContext(),
    )
    assert bundles == []


def test_rare_offer_alerts_after_real_price_drop():
    bundles = build_commercial_notification_bundles(
        _rare_analysis(previous_price=11000),
        context=CommercialAlertContext(),
    )
    assert len(bundles) == 1
    assert bundles[0].alert_type == "commercial_rare_offer"
    assert bundles[0].deduplication_key == "commercial:rare-offer:10:10000"


def _seed_snapshot(session, *, score: float = 60.0, event: str = "NORMAL", winner_price: int = 10500, historical_min: int = 10000):
    from app.models import MasterPriceStatistic, OpportunitySnapshot

    store = Store(
        name="Fallback Store",
        slug="fallback-store",
        base_url="https://fallback.example",
        connector_key="fallback-store",
        is_active=True,
        comparison_enabled=True,
    )
    master = MasterProduct(
        canonical_name="Whisky Fallback 750 ml",
        normalized_key="whisky-fallback|750",
    )
    session.add_all([store, master])
    session.flush()
    product = Product(
        store="Fallback Store",
        store_id=store.id,
        master_product_id=master.id,
        name="Whisky Fallback 750 ml",
        url="https://fallback.example/p",
        current_price=winner_price,
        is_available=True,
        excluded_from_comparison=False,
    )
    session.add(product)
    session.flush()
    session.add(
        MasterPriceStatistic(
            master_product_id=master.id,
            current_best_price=winner_price,
            min_90d=historical_min,
            avg_90d=float(historical_min + 1000),
            historical_min=historical_min,
            observations_total=20,
            observations_90d=20,
        )
    )
    session.add(
        OpportunitySnapshot(
            master_product_id=master.id,
            score=score,
            classification="Normal",
            winner_product_id=product.id,
            winner_store_id=store.id,
            winner_price=winner_price,
            saving_clp=500,
            saving_pct=0.05,
            match_confidence=0.95,
            price_event=event,
            calculated_at=utcnow(),
        )
    )
    session.flush()
    return master, product


def test_radar_interactive_falls_back_when_no_exceptional_signal():
    from app.intelligence.queries import commercial_radar

    engine, SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_snapshot(session, score=60.0, event="NORMAL")
        rows = commercial_radar(session, limit=10, minimum_score=70.0)
        assert len(rows) == 1
        assert rows[0].canonical_name == "Whisky Fallback 750 ml"
        assert rows[0].price_event == "NORMAL"
    engine.dispose()


def test_minimos_interactive_falls_back_to_closest_historical_floor():
    from app.intelligence.queries import historical_floor_opportunities

    engine, SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_snapshot(
            session,
            score=58.0,
            event="NORMAL",
            winner_price=10500,
            historical_min=10000,
        )
        rows = historical_floor_opportunities(session, limit=10)
        assert len(rows) == 1
        assert rows[0].historical_min == 10000
        assert rows[0].winner_price == 10500
    engine.dispose()


def test_opportunity_format_displays_historical_distance_for_fallback():
    from app.intelligence.queries import historical_floor_opportunities
    from app.telegram_bot.formatting import format_opportunities

    engine, SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_snapshot(
            session,
            score=58.0,
            event="NORMAL",
            winner_price=10500,
            historical_min=10000,
        )
        rows = historical_floor_opportunities(session, limit=10)
        text, _ = format_opportunities(rows, title="Precios más cercanos a su mínimo histórico")
        assert "Mínimo histórico" in text
        assert "Distancia al mínimo" in text
        assert "+5.0%" in text
    engine.dispose()
