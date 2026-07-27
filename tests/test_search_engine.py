from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import MasterProduct, Product, Store
from app.search.catalog import refresh_search_catalog
from app.search.engine import search_products
from app.search.normalization import parse_search_query


def _session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)()


def test_query_understands_alias_and_naked_volume():
    query = parse_search_query("jw black 750")
    assert query.volume_ml == 750
    assert "johnnie" in query.tokens
    assert "walker" in query.tokens


def test_search_groups_store_offers_and_returns_cheapest():
    engine, session = _session()
    try:
        licor3b = Store(
            name="Licor3B",
            slug="licor3b",
            base_url="https://licor3b.cl/",
            connector_key="licor3b",
        )
        liquidos = Store(
            name="Líquidos",
            slug="liquidos",
            base_url="https://www.liquidos.cl/",
            connector_key="liquidos",
        )
        master = MasterProduct(
            canonical_name="Johnnie Walker Black Label 750 ml",
            normalized_key="johnnie walker black label|750",
            volume_ml=750,
            status="active",
        )
        session.add_all([licor3b, liquidos, master])
        session.flush()
        now = datetime.now(timezone.utc)
        session.add_all(
            [
                Product(
                    store="Licor3B",
                    store_id=licor3b.id,
                    master_product_id=master.id,
                    name="Whisky Johnnie Walker Black Label 750 cc",
                    url="https://licor3b.cl/black",
                    current_price=24990,
                    regular_price=29990,
                    discount_pct=0.1667,
                    last_seen_at=now,
                ),
                Product(
                    store="Líquidos",
                    store_id=liquidos.id,
                    master_product_id=master.id,
                    name="Johnnie Walker Etiqueta Negra 75 cl",
                    url="https://liquidos.cl/black",
                    current_price=21990,
                    regular_price=25990,
                    discount_pct=0.1539,
                    last_seen_at=now,
                ),
            ]
        )
        session.flush()
        summary = refresh_search_catalog(session)
        session.commit()

        assert summary.masters_seen == 1
        results = search_products(session, "jw black 750", limit=5)
        assert len(results) == 1
        result = results[0]
        assert result.winner.store_name == "Líquidos"
        assert result.saving_clp == 3000
        assert len(result.offers) == 2
        assert result.score >= 0.8
    finally:
        session.close()
        engine.dispose()


def test_explicit_different_volume_is_not_returned():
    engine, session = _session()
    try:
        store = Store(
            name="Licor3B",
            slug="licor3b",
            base_url="https://licor3b.cl/",
            connector_key="licor3b",
        )
        master = MasterProduct(
            canonical_name="Johnnie Walker Black Label 750 ml",
            normalized_key="johnnie walker black label|750",
            volume_ml=750,
            search_text="johnnie walker black label 750 ml",
            aliases=[],
            package_quantity=1,
            status="active",
        )
        session.add_all([store, master])
        session.flush()
        session.add(
            Product(
                store="Licor3B",
                store_id=store.id,
                master_product_id=master.id,
                name="Johnnie Walker Black 750 ml",
                url="https://licor3b.cl/black",
                current_price=24990,
                last_seen_at=datetime.now(timezone.utc),
            )
        )
        session.commit()
        assert search_products(session, "johnnie black 1000") == []
    finally:
        session.close()
        engine.dispose()
