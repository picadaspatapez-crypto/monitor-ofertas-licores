from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.analyzers.comparison import analyze_cross_store_prices
from app.database import Base
from app.intelligence.pack_guard import repair_pack_identity
from app.intelligence.queries import commercial_radar
from app.models import (
    MasterProduct,
    OpportunitySnapshot,
    PriceObservation,
    Product,
    ProductMatch,
    ScrapeRun,
    Store,
)


def _session_factory():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)


def test_radar_hides_pack_canonical_even_if_winner_product_is_single():
    engine, SessionLocal = _session_factory()
    with SessionLocal() as session:
        store = Store(name="A", slug="a", base_url="https://a.example", connector_key="a")
        master = MasterProduct(
            canonical_name="Casas Patronales Gran Reserva Carmenere X6 750 ml",
            normalized_key="casas-patronales-x6|750",
            package_quantity=1,
        )
        session.add_all([store, master]); session.flush()
        bottle = Product(
            store="A", store_id=store.id, master_product_id=master.id,
            name="Casas Patronales Gran Reserva Carmenere 750 ml",
            url="https://a.example/bottle", current_price=6990, package_quantity=1,
        )
        session.add(bottle); session.flush()
        session.add(OpportunitySnapshot(
            master_product_id=master.id, winner_product_id=bottle.id,
            winner_store_id=store.id, winner_price=6990,
            score=99.0, classification="Excelente", saving_clp=37410,
            saving_pct=0.843, match_confidence=0.95, price_event="MARKET_LEADER",
        ))
        session.flush()
        assert commercial_radar(session, limit=10) == []
    engine.dispose()


def test_pack_repair_splits_mixed_legacy_master_and_repairs_single_identity():
    engine, SessionLocal = _session_factory()
    with SessionLocal() as session:
        a = Store(name="A", slug="a", base_url="https://a.example", connector_key="a")
        b = Store(name="B", slug="b", base_url="https://b.example", connector_key="b")
        master = MasterProduct(
            canonical_name="Vino Demo X6 750 ml",
            normalized_key="demo x6|750",
            package_quantity=1,
        )
        session.add_all([a, b, master]); session.flush()
        pack = Product(
            store="A", store_id=a.id, master_product_id=master.id,
            name="Vino Demo X6 750 ml", url="https://a.example/pack",
            current_price=39990, package_quantity=1,
        )
        bottle = Product(
            store="B", store_id=b.id, master_product_id=master.id,
            name="Vino Demo 750 ml", url="https://b.example/bottle",
            current_price=6990, package_quantity=1,
        )
        session.add_all([pack, bottle]); session.flush()
        session.add_all([
            ProductMatch(store_product_id=pack.id, master_product_id=master.id, confidence=1.0, matching_method="exact_normalized"),
            ProductMatch(store_product_id=bottle.id, master_product_id=master.id, confidence=1.0, matching_method="manual_equivalence"),
        ])
        session.flush()

        summary = repair_pack_identity(session)
        session.flush()
        assert summary.mixed_masters_found == 1
        assert summary.products_relinked >= 1
        assert pack.package_quantity == 6
        assert bottle.package_quantity == 1
        assert pack.master_product_id != bottle.master_product_id

        bottle_master = session.get(MasterProduct, bottle.master_product_id)
        assert bottle_master is not None
        assert bottle_master.package_quantity == 1
        assert "X6" not in bottle_master.canonical_name.upper()
    engine.dispose()


def _comparison_fixture(*, shared_ean: bool):
    engine, SessionLocal = _session_factory()
    session = SessionLocal()
    a = Store(name="A", slug="a", base_url="https://a.example", connector_key="a")
    b = Store(name="B", slug="b", base_url="https://b.example", connector_key="b")
    master = MasterProduct(canonical_name="Whisky Demo 750 ml", normalized_key="demo|750", package_quantity=1)
    session.add_all([a, b, master]); session.flush()
    ean = "7800000000001" if shared_ean else None
    cheap = Product(
        store="A", store_id=a.id, master_product_id=master.id,
        name="Whisky Demo 750 ml", url="https://a.example/cheap",
        current_price=6990, package_quantity=1, ean=ean,
    )
    expensive = Product(
        store="B", store_id=b.id, master_product_id=master.id,
        name="Whisky Demo 750 ml", url="https://b.example/expensive",
        current_price=39990, package_quantity=1, ean=ean,
    )
    session.add_all([cheap, expensive]); session.flush()
    session.add_all([
        ProductMatch(store_product_id=cheap.id, master_product_id=master.id, confidence=1.0, matching_method="ean_exact" if shared_ean else "alias_exact"),
        ProductMatch(store_product_id=expensive.id, master_product_id=master.id, confidence=1.0, matching_method="ean_exact" if shared_ean else "alias_exact"),
    ])
    run_a = ScrapeRun(store_id=a.id, status="success", health_status="HEALTHY")
    run_b = ScrapeRun(store_id=b.id, status="success", health_status="HEALTHY")
    session.add_all([run_a, run_b]); session.flush()
    session.add_all([
        PriceObservation(product_id=cheap.id, scrape_run_id=run_a.id, price=6990, discount_pct=0),
        PriceObservation(product_id=expensive.id, scrape_run_id=run_b.id, price=39990, discount_pct=0),
    ])
    session.flush()
    return engine, session, [run_a.id, run_b.id]


def test_extreme_price_ratio_is_quarantined_without_shared_ean():
    engine, session, run_ids = _comparison_fixture(shared_ean=False)
    try:
        analysis = analyze_cross_store_prices(session, run_ids=run_ids)
        assert analysis.opportunities == ()
        assert analysis.unverified_groups >= 1
    finally:
        session.close(); engine.dispose()


def test_extreme_price_ratio_can_survive_exact_shared_ean():
    engine, session, run_ids = _comparison_fixture(shared_ean=True)
    try:
        analysis = analyze_cross_store_prices(session, run_ids=run_ids)
        assert len(analysis.opportunities) == 1
        assert analysis.opportunities[0].saving_pct > 0.80
    finally:
        session.close(); engine.dispose()
