from __future__ import annotations

from datetime import timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.analyzers.comparison import analyze_cross_store_prices
from app.database import Base
from app.intelligence.history import refresh_price_statistics
from app.intelligence.queries import commercial_radar
from app.matching import build_product_signature, extract_pack_count
from app.models import (
    MasterProduct,
    OpportunitySnapshot,
    PriceObservation,
    Product,
    ProductMatch,
    ScrapeRun,
    Store,
)
from app.repositories.common import utcnow


def _session_factory():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)


def test_x6_suffix_and_prefix_formats_are_detected_as_packs():
    examples = (
        "Casas Patronales Gran Reserva Cabernet Sauvignon X6 750 ml",
        "Casas Patronales Gran Reserva Carmenere x 6 750 ml",
        "Cocotel Secreto Peruano Sour X6 1000 ml",
        "Vodka Eristoff Botella 700cc x6",
        "Whisky Demo 6x750 ml",
    )
    for name in examples:
        signature = build_product_signature(name)
        assert signature.is_pack, name
        assert signature.pack_count == 6, name
        assert extract_pack_count(name) == 6


def test_normal_single_bottle_with_volume_is_not_pack():
    signature = build_product_signature("Casas Patronales Gran Reserva Carmenere 750 ml")
    assert not signature.is_pack
    assert signature.pack_count is None


def test_comparison_rejects_pack_even_with_stale_trusted_master_match():
    engine, SessionLocal = _session_factory()
    with SessionLocal() as session:
        a = Store(name="A", slug="a", base_url="https://a.example", connector_key="a")
        b = Store(name="B", slug="b", base_url="https://b.example", connector_key="b")
        master = MasterProduct(canonical_name="Vino Demo 750 ml", normalized_key="vino-demo|750")
        session.add_all([a, b, master]); session.flush()
        pack = Product(
            store="A", store_id=a.id, master_product_id=master.id,
            name="Vino Demo X6 750 ml", url="https://a.example/pack",
            current_price=6990, package_quantity=1,
        )
        bottle = Product(
            store="B", store_id=b.id, master_product_id=master.id,
            name="Vino Demo 750 ml", url="https://b.example/bottle",
            current_price=39990, package_quantity=1,
        )
        session.add_all([pack, bottle]); session.flush()
        session.add_all([
            ProductMatch(store_product_id=pack.id, master_product_id=master.id, confidence=1.0, matching_method="manual_equivalence"),
            ProductMatch(store_product_id=bottle.id, master_product_id=master.id, confidence=1.0, matching_method="manual_equivalence"),
        ])
        run_a = ScrapeRun(store_id=a.id, status="success", health_status="HEALTHY")
        run_b = ScrapeRun(store_id=b.id, status="success", health_status="HEALTHY")
        session.add_all([run_a, run_b]); session.flush()
        session.add_all([
            PriceObservation(product_id=pack.id, scrape_run_id=run_a.id, price=6990, discount_pct=0),
            PriceObservation(product_id=bottle.id, scrape_run_id=run_b.id, price=39990, discount_pct=0),
        ])
        session.flush()
        analysis = analyze_cross_store_prices(session, run_ids=[run_a.id, run_b.id])
        assert analysis.verified_matches == 0
        assert analysis.opportunities == ()
    engine.dispose()


def test_pack_price_does_not_pollute_bottle_history():
    engine, SessionLocal = _session_factory()
    with SessionLocal() as session:
        store = Store(name="A", slug="a", base_url="https://a.example", connector_key="a")
        master = MasterProduct(canonical_name="Vino Demo 750 ml", normalized_key="vino-demo|750")
        session.add_all([store, master]); session.flush()
        pack = Product(
            store="A", store_id=store.id, master_product_id=master.id,
            name="Vino Demo X6 750 ml", url="https://a.example/pack",
            current_price=6990, package_quantity=1,
        )
        bottle = Product(
            store="A", store_id=store.id, master_product_id=master.id,
            name="Vino Demo 750 ml", url="https://a.example/bottle",
            current_price=39990, package_quantity=1,
        )
        session.add_all([pack, bottle]); session.flush()
        now = utcnow()
        session.add_all([
            PriceObservation(product_id=pack.id, price=5990, discount_pct=0, observed_at=now - timedelta(days=2)),
            PriceObservation(product_id=bottle.id, price=39990, discount_pct=0, observed_at=now - timedelta(days=1)),
        ])
        session.flush()
        refresh_price_statistics(session)
        assert pack.package_quantity == 6
        from app.models import MasterPriceStatistic
        stat = session.get(MasterPriceStatistic, master.id)
        assert stat is not None
        assert stat.historical_min == 39990
        assert stat.min_90d == 39990
    engine.dispose()


def test_radar_hides_stale_snapshot_if_winner_is_pack():
    engine, SessionLocal = _session_factory()
    with SessionLocal() as session:
        store = Store(name="A", slug="a", base_url="https://a.example", connector_key="a")
        master = MasterProduct(canonical_name="Vino Demo X6 750 ml", normalized_key="vino-demo-x6|750")
        session.add_all([store, master]); session.flush()
        pack = Product(
            store="A", store_id=store.id, master_product_id=master.id,
            name="Vino Demo X6 750 ml", url="https://a.example/pack",
            current_price=6990, package_quantity=6,
        )
        session.add(pack); session.flush()
        session.add(OpportunitySnapshot(
            master_product_id=master.id, winner_product_id=pack.id, winner_store_id=store.id,
            winner_price=6990, score=99.0, classification="Excelente", saving_clp=30000,
            saving_pct=0.80, match_confidence=0.99, price_event="MARKET_LEADER",
        ))
        session.flush()
        assert commercial_radar(session, limit=10) == []
    engine.dispose()
