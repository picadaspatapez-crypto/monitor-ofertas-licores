from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.domain import CollectedProduct
from app.models import MasterProduct, ScrapeRun, Store
from app.repositories import save_product


def _session_factory():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def test_same_normalized_product_reuses_one_master_row():
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        store_a = Store(
            name="A",
            slug="a",
            base_url="https://a.example",
            connector_key="a",
        )
        store_b = Store(
            name="B",
            slug="b",
            base_url="https://b.example",
            connector_key="b",
        )
        session.add_all([store_a, store_b])
        session.flush()
        run_a = ScrapeRun(store=store_a, status="running")
        run_b = ScrapeRun(store=store_b, status="running")
        session.add_all([run_a, run_b])
        session.flush()

        first = save_product(
            session,
            CollectedProduct(
                store="A",
                name="Malfy Originale 41 750 ml",
                url="https://a.example/malfy",
                current_price=24990,
                regular_price=None,
                discount_pct=0,
            ),
            store_a,
            run_a,
        )
        second = save_product(
            session,
            CollectedProduct(
                store="B",
                name="Malfy Originale 41° 750 cc",
                url="https://b.example/malfy",
                current_price=23990,
                regular_price=None,
                discount_pct=0,
            ),
            store_b,
            run_b,
        )
        session.flush()

        assert first.product.master_product_id == second.product.master_product_id
        assert session.scalar(select(func.count(MasterProduct.id))) == 1
