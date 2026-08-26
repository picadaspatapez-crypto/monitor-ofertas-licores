from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.intelligence.opportunity import persist_opportunity_snapshots
from app.intelligence.queries import top_opportunities
from app.intelligence.title_guard import repair_licor3b_title_integrity, safe_licor3b_display_name
from app.models import MasterProduct, OpportunitySnapshot, Product, Store


POLLUTED = (
    "3 Vinos Montes Alpha Cabernet Sauvignon 3 Vinos "
    "Marques De Casa Concha Cabernet Sauvignon 750 ml"
)
CLEAN = "vino marques de casa concha cabernet sauvignon 750 ml"
URL = "https://licor3b.cl/product/vino-marques-de-casa-concha-cabernet-sauvignon-750-ml/"


def _db():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return engine


def _store(session):
    store = Store(
        name="Licor3B", slug="licor3b", base_url="https://licor3b.cl",
        connector_key="licor3b", is_active=True, comparison_enabled=True,
    )
    session.add(store)
    session.flush()
    return store


def test_read_time_name_guard_prefers_clean_licor3b_product_identity():
    assert safe_licor3b_display_name(
        canonical_name=POLLUTED, product_name=CLEAN, url=URL
    ) == CLEAN


def test_repairs_polluted_master_even_when_product_name_is_already_clean():
    engine = _db()
    with Session(engine) as session:
        store = _store(session)
        master = MasterProduct(
            canonical_name=POLLUTED, normalized_key="legacy-polluted-master", package_quantity=1,
        )
        session.add(master)
        session.flush()
        product = Product(
            store="Licor3B", store_id=store.id, master_product_id=master.id,
            name=CLEAN, url=URL, current_price=12990, regular_price=14990,
            package_quantity=1, data_quality_score=100, data_quality_status="CLEAN",
            excluded_from_comparison=False, is_available=True,
        )
        session.add(product)
        session.commit()

        summary = repair_licor3b_title_integrity(session)
        session.commit()

        assert summary.products_repaired == 0
        assert summary.masters_repaired == 1
        assert "montes alpha" not in master.canonical_name.casefold()
        assert "marques de casa concha" in master.canonical_name.casefold()


def test_radar_query_excludes_snapshot_if_winner_was_relinked_to_another_master():
    engine = _db()
    with Session(engine) as session:
        store = _store(session)
        stale = MasterProduct(canonical_name=POLLUTED, normalized_key="stale", package_quantity=1)
        clean = MasterProduct(canonical_name=CLEAN, normalized_key="clean", package_quantity=1)
        session.add_all([stale, clean])
        session.flush()
        product = Product(
            store="Licor3B", store_id=store.id, master_product_id=clean.id,
            name=CLEAN, url=URL, current_price=12990, regular_price=14990,
            package_quantity=1, data_quality_score=100, data_quality_status="CLEAN",
            excluded_from_comparison=False, is_available=True,
        )
        session.add(product)
        session.flush()
        session.add(OpportunitySnapshot(
            master_product_id=stale.id, score=97, classification="Excelente",
            winner_product_id=product.id, winner_store_id=store.id, winner_price=12990,
            saving_clp=1000, saving_pct=0.1, match_confidence=0.97,
        ))
        session.commit()

        assert top_opportunities(session, limit=10) == []

        summary = repair_licor3b_title_integrity(session)
        session.commit()
        assert summary.snapshots_purged >= 1
        assert session.get(OpportunitySnapshot, stale.id) is None


def test_radar_query_excludes_merged_master_even_when_product_link_matches():
    engine = _db()
    with Session(engine) as session:
        store = _store(session)
        master = MasterProduct(
            canonical_name=CLEAN, normalized_key="merged", package_quantity=1, status="merged"
        )
        session.add(master)
        session.flush()
        product = Product(
            store="Licor3B", store_id=store.id, master_product_id=master.id,
            name=CLEAN, url=URL, current_price=12990,
            package_quantity=1, data_quality_score=100, data_quality_status="CLEAN",
            excluded_from_comparison=False, is_available=True,
        )
        session.add(product)
        session.flush()
        session.add(OpportunitySnapshot(
            master_product_id=master.id, score=97, classification="Excelente",
            winner_product_id=product.id, winner_store_id=store.id, winner_price=12990,
            saving_clp=1000, saving_pct=0.1, match_confidence=0.97,
        ))
        session.commit()
        assert top_opportunities(session, limit=10) == []


def test_snapshot_persistence_refuses_master_winner_mismatch():
    engine = _db()
    with Session(engine) as session:
        store = _store(session)
        stale = MasterProduct(canonical_name=POLLUTED, normalized_key="stale2", package_quantity=1)
        clean = MasterProduct(canonical_name=CLEAN, normalized_key="clean2", package_quantity=1)
        session.add_all([stale, clean])
        session.flush()
        product = Product(
            store="Licor3B", store_id=store.id, master_product_id=clean.id,
            name=CLEAN, url=URL, current_price=12990,
            package_quantity=1, data_quality_score=100, data_quality_status="CLEAN",
            excluded_from_comparison=False, is_available=True,
        )
        session.add(product)
        session.flush()
        winner = SimpleNamespace(
            product_id=product.id, store_id=store.id, price=12990
        )
        comparison = SimpleNamespace(
            winner=winner, master_product_id=stale.id, opportunity_score=97.0,
            opportunity_classification="Excelente", saving_clp=1000, saving_pct=0.1,
            confidence=0.97, history_position=0.8, freshness_score=1.0,
            scarcity_score=0.5, score_version="v2", rarity_score=0.2,
            rarity_frequency_90d=0.1, history_observations_90d=10,
            previous_historical_min=13990, price_event="MARKET_LEADER",
            historical_gap_clp=0, historical_gap_pct=0.0, intelligence_reason="test",
        )
        assert persist_opportunity_snapshots(session, [comparison]) == 0
        session.commit()
        assert session.get(OpportunitySnapshot, stale.id) is None


def test_radar_sanitizes_polluted_master_even_when_winner_is_another_store():
    engine = _db()
    with Session(engine) as session:
        licor = _store(session)
        other = Store(
            name="Socomep", slug="socomep", base_url="https://example.com",
            connector_key="socomep", is_active=True, comparison_enabled=True,
        )
        session.add(other)
        master = MasterProduct(canonical_name=POLLUTED, normalized_key="shared-polluted", package_quantity=1)
        session.add(master)
        session.flush()
        licor_product = Product(
            store="Licor3B", store_id=licor.id, master_product_id=master.id,
            name=CLEAN, url=URL, current_price=12990, package_quantity=1,
            data_quality_score=100, data_quality_status="CLEAN",
            excluded_from_comparison=False, is_available=True,
        )
        winner = Product(
            store="Socomep", store_id=other.id, master_product_id=master.id,
            name="Vino Marques de Casa Concha Cabernet Sauvignon 750 ml",
            url="https://example.com/marques", current_price=11990, package_quantity=1,
            data_quality_score=100, data_quality_status="CLEAN",
            excluded_from_comparison=False, is_available=True,
        )
        session.add_all([licor_product, winner])
        session.flush()
        session.add(OpportunitySnapshot(
            master_product_id=master.id, score=90, classification="Excelente",
            winner_product_id=winner.id, winner_store_id=other.id, winner_price=11990,
            saving_clp=1000, saving_pct=0.08, match_confidence=0.95,
        ))
        session.commit()

        rows = top_opportunities(session, limit=10)
        assert len(rows) == 1
        assert "Montes Alpha" not in rows[0].canonical_name
        assert "marques de casa concha" in rows[0].canonical_name.casefold()
