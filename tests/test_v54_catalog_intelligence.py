from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.collectors.base import StoreMetadata
from app.database import Base
from app.domain import CollectedProduct
from app.intelligence.availability import reconcile_store_availability
from app.intelligence.history import refresh_price_statistics
from app.intelligence.opportunity import (
    OpportunityComponents,
    classify_opportunity,
    opportunity_score,
    persist_opportunity_snapshots,
)
from app.matching import MatchingPlan, build_matching_plan
from app.matching.rules import add_matching_rule
from app.models import (
    MasterPriceStatistic,
    MasterProduct,
    OpportunitySnapshot,
    PriceObservation,
    Product,
    ScrapeRun,
    Store,
)
from app.performance import PerformanceSettings
from app.pipeline.runner import _scheduled_execution_or_none
from app.repositories.matching import _augmented_candidates
from app.repositories.products import save_product
from app.repositories.runs import finish_scrape_run
from app.repositories.common import utcnow
from app.telegram_bot.commands import parse_command


def _session_factory():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)


def _store(session, *, key="test", name="Test"):
    store = Store(
        name=name,
        slug=key,
        base_url=f"https://{key}.example",
        connector_key=key,
        is_active=True,
        requires_browser=False,
    )
    session.add(store)
    session.flush()
    return store



def test_donde_la_negra_store_api_preserves_sku():
    from app.collectors.dondelanegra import _parse_store_api_products

    products = _parse_store_api_products(
        [
            {
                "name": "Whisky Ejemplo 750 ml",
                "permalink": "https://dondelanegra.cl/producto/whisky-ejemplo/",
                "sku": "DLN-7788",
                "categories": [{"name": "Whisky"}],
                "prices": {
                    "currency_minor_unit": 0,
                    "price": "19990",
                    "regular_price": "24990",
                    "sale_price": "19990",
                },
            }
        ]
    )
    item = next(iter(products.values()))
    assert item.sku == "DLN-7788"


def test_availability_requires_two_healthy_absences_and_reactivates():
    engine, SessionLocal = _session_factory()
    with SessionLocal() as session:
        store = _store(session)
        product = Product(
            store=store.name,
            store_id=store.id,
            name="Producto 750 ml",
            url="https://test.example/p",
            current_price=10_000,
            is_available=True,
            missing_streak=0,
        )
        session.add(product)
        session.flush()

        run1 = ScrapeRun(store_id=store.id, status="running")
        session.add(run1)
        session.flush()
        summary1 = reconcile_store_availability(
            session,
            store=store,
            scrape_run=run1,
            catalog_is_healthy=True,
            missing_threshold=2,
        )
        assert summary1.marked_unavailable == 0
        assert product.is_available is True
        assert product.missing_streak == 1

        run2 = ScrapeRun(store_id=store.id, status="running")
        session.add(run2)
        session.flush()
        summary2 = reconcile_store_availability(
            session,
            store=store,
            scrape_run=run2,
            catalog_is_healthy=True,
            missing_threshold=2,
        )
        assert summary2.marked_unavailable == 1
        assert product.is_available is False

        run3 = ScrapeRun(store_id=store.id, status="running")
        session.add(run3)
        session.flush()
        session.add(
            PriceObservation(
                product_id=product.id,
                scrape_run_id=run3.id,
                price=10_000,
                discount_pct=0,
            )
        )
        session.flush()
        summary3 = reconcile_store_availability(
            session,
            store=store,
            scrape_run=run3,
            catalog_is_healthy=True,
            missing_threshold=2,
        )
        assert summary3.reactivated == 1
        assert product.is_available is True
        assert product.missing_streak == 0
    engine.dispose()


def test_degraded_catalog_does_not_increase_missing_streak():
    engine, SessionLocal = _session_factory()
    with SessionLocal() as session:
        store = _store(session)
        product = Product(
            store=store.name,
            store_id=store.id,
            name="Producto",
            url="https://test.example/p",
            current_price=1000,
            missing_streak=1,
            is_available=True,
        )
        run = ScrapeRun(store_id=store.id, status="running")
        session.add_all([product, run])
        session.flush()
        reconcile_store_availability(
            session,
            store=store,
            scrape_run=run,
            catalog_is_healthy=False,
            missing_threshold=2,
        )
        assert product.missing_streak == 1
        assert product.is_available is True
    engine.dispose()


def test_save_product_persists_sku_and_ean():
    engine, SessionLocal = _session_factory()
    with SessionLocal() as session:
        store = _store(session)
        run = ScrapeRun(store_id=store.id, status="running")
        session.add(run)
        session.flush()
        saved = save_product(
            session,
            CollectedProduct(
                store=store.name,
                name="Whisky Ejemplo 750 ml",
                url="https://test.example/whisky",
                current_price=12_990,
                regular_price=15_990,
                discount_pct=0.18,
                sku="SKU-123",
                ean="7801234567890",
            ),
            store,
            run,
        )
        assert saved.product.sku == "SKU-123"
        assert saved.product.ean == "7801234567890"
        assert saved.product.master_product.ean == "7801234567890"
    engine.dispose()


def test_history_statistics_30_90_and_historical():
    engine, SessionLocal = _session_factory()
    now = utcnow()
    with SessionLocal() as session:
        store = _store(session)
        master = MasterProduct(canonical_name="Producto", normalized_key="producto")
        session.add(master)
        session.flush()
        product = Product(
            store=store.name,
            store_id=store.id,
            master_product_id=master.id,
            name="Producto 750 ml",
            url="https://test.example/p",
            current_price=8000,
            is_available=True,
        )
        session.add(product)
        session.flush()
        session.add_all(
            [
                PriceObservation(product_id=product.id, price=10_000, discount_pct=0, observed_at=now - timedelta(days=80)),
                PriceObservation(product_id=product.id, price=9_000, discount_pct=0.1, observed_at=now - timedelta(days=20)),
                PriceObservation(product_id=product.id, price=8_000, discount_pct=0.2, observed_at=now - timedelta(days=1)),
                PriceObservation(product_id=product.id, price=7_000, discount_pct=0.3, observed_at=now - timedelta(days=120)),
            ]
        )
        session.flush()
        summary = refresh_price_statistics(session)
        stats = session.get(MasterPriceStatistic, master.id)
        assert summary.rows_updated == 1
        assert stats.min_30d == 8000
        assert round(stats.avg_30d) == 8500
        assert stats.min_90d == 8000
        assert stats.historical_min == 7000
        assert stats.current_best_price == 8000
    engine.dispose()


def test_opportunity_score_classification():
    score = opportunity_score(
        OpportunityComponents(1.0, 1.0, 1.0, 1.0, 1.0)
    )
    assert score == 100.0
    assert classify_opportunity(score) == "Excelente"
    assert classify_opportunity(84.9) == "Muy buena"
    assert classify_opportunity(72) == "Buena"


def test_ean_exact_augments_unrelated_names():
    engine, SessionLocal = _session_factory()
    with SessionLocal() as session:
        left_store = _store(session, key="left", name="Left")
        right_store = _store(session, key="right", name="Right")
        left = Product(
            store="Left", store_id=left_store.id, name="Nombre A 750 ml",
            url="https://left.example/a", current_price=1000, ean="780000000001"
        )
        right = Product(
            store="Right", store_id=right_store.id, name="Texto totalmente distinto 750 ml",
            url="https://right.example/b", current_price=1200, ean="780000000001"
        )
        session.add_all([left, right])
        session.flush()
        plan = build_matching_plan([left, right])
        candidates = _augmented_candidates(session, [left, right], plan)
        assert len(candidates) == 1
        assert candidates[0].method == "ean_exact"
    engine.dispose()


def test_manual_exclusion_removes_automatic_candidate():
    engine, SessionLocal = _session_factory()
    with SessionLocal() as session:
        left_store = _store(session, key="left", name="Left")
        right_store = _store(session, key="right", name="Right")
        left = Product(
            store="Left", store_id=left_store.id, name="Johnnie Walker Black 750 ml",
            url="https://left.example/a", current_price=1000
        )
        right = Product(
            store="Right", store_id=right_store.id, name="Whisky Johnnie Walker Black 750 cc",
            url="https://right.example/b", current_price=1200
        )
        session.add_all([left, right])
        session.flush()
        plan = build_matching_plan([left, right])
        assert plan.candidates
        add_matching_rule(
            session,
            rule_type="exclusion",
            left=left.name,
            right=right.name,
            notes="Test",
        )
        candidates = _augmented_candidates(session, [left, right], plan)
        assert candidates == ()
    engine.dispose()


def test_scheduler_grace_executes_before_exact_due_time():
    engine, SessionLocal = _session_factory()
    now = utcnow()
    with SessionLocal() as session:
        store = _store(session, key="elmundodelvino", name="El Mundo del Vino")
        run = ScrapeRun(
            store_id=store.id,
            status="success",
            health_status="HEALTHY",
            products_found=835,
            started_at=now - timedelta(hours=12),
            finished_at=now - timedelta(hours=11, minutes=50),
            metrics_json={"discovery_source": "shopify_storefront_graphql"},
        )
        session.add(run)
        session.commit()
    collector = SimpleNamespace(
        key="elmundodelvino",
        store_name="El Mundo del Vino",
        metadata=StoreMetadata(
            name="El Mundo del Vino",
            slug="elmundodelvino",
            base_url="https://elmundodelvino.cl",
            connector_key="elmundodelvino",
            requires_browser=False,
        ),
    )
    performance = PerformanceSettings(scheduler_grace_minutes=15)
    assert _scheduled_execution_or_none(
        collector=collector, SessionLocal=SessionLocal, performance=performance
    ) is None
    engine.dispose()


def test_scheduler_reports_due_soon_with_exact_time():
    engine, SessionLocal = _session_factory()
    now = utcnow()
    with SessionLocal() as session:
        store = _store(session, key="elmundodelvino", name="El Mundo del Vino")
        run = ScrapeRun(
            store_id=store.id,
            status="success",
            health_status="HEALTHY",
            products_found=835,
            started_at=now - timedelta(hours=12),
            finished_at=now - timedelta(hours=11, minutes=30),
            metrics_json={"discovery_source": "shopify_storefront_graphql"},
        )
        session.add(run)
        session.commit()
    collector = SimpleNamespace(
        key="elmundodelvino",
        store_name="El Mundo del Vino",
        metadata=StoreMetadata(
            name="El Mundo del Vino",
            slug="elmundodelvino",
            base_url="https://elmundodelvino.cl",
            connector_key="elmundodelvino",
            requires_browser=False,
        ),
    )
    result = _scheduled_execution_or_none(
        collector=collector,
        SessionLocal=SessionLocal,
        performance=PerformanceSettings(scheduler_grace_minutes=15),
    )
    assert result is not None
    assert result.execution_state == "DUE_SOON"
    assert result.products_found == 835
    assert "Próxima revisión real" in (result.detail or "")
    assert result.source == "shopify_storefront_graphql"
    engine.dispose()


def test_new_telegram_commands_parse():
    assert parse_command("/mas").name == "search_more"
    assert parse_command("/historial jack honey").name == "history"
    assert parse_command("/oportunidades").name == "opportunities"
    assert parse_command("/mejores").name == "best_prices"
