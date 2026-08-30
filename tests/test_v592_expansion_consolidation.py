from __future__ import annotations

from datetime import timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import MasterProduct, Product, ProductMatch, ScrapeRun, Store
from app.repositories.common import utcnow
from app.reports.consolidation import (
    EXPANSION_CONNECTOR_KEYS,
    build_expansion_consolidation_audit,
    format_expansion_consolidation_report,
)
from app.telegram_bot.commands import parse_command


def _session_factory():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)


def _seed_stable_expansion(session):
    now = utcnow()
    for index, key in enumerate(EXPANSION_CONNECTOR_KEYS, start=1):
        store = Store(
            name=f"Store {index}",
            slug=key,
            base_url=f"https://{key}.example",
            connector_key=key,
            is_active=True,
            comparison_enabled=True,
        )
        session.add(store)
        session.flush()
        master = MasterProduct(
            canonical_name=f"Producto {index} 750 ml",
            normalized_key=f"producto-{index}|750",
            volume_ml=750,
            package_quantity=1,
            status="active",
        )
        session.add(master)
        session.flush()
        product = Product(
            store=store.name,
            store_id=store.id,
            master_product_id=master.id,
            name=master.canonical_name,
            url=f"https://{key}.example/p/{index}",
            current_price=10_000 + index * 100,
            regular_price=12_000 + index * 100,
            data_quality_status="CLEAN",
            is_available=True,
            package_quantity=1,
        )
        session.add(product)
        session.flush()
        session.add(
            ProductMatch(
                store_product_id=product.id,
                master_product_id=master.id,
                confidence=0.95,
                matching_method="exact_normalized",
            )
        )
        for offset, count in enumerate((100, 102, 101)):
            finished = now - timedelta(hours=(3 - offset) * 6)
            session.add(
                ScrapeRun(
                    store_id=store.id,
                    status="success",
                    health_status="HEALTHY",
                    products_found=count + index,
                    duration_ms=30_000 + index * 100,
                    started_at=finished - timedelta(seconds=30),
                    finished_at=finished,
                    metrics_json={"discovery_source": "test_http"},
                )
            )
    session.flush()


def test_audit_command_aliases_are_available():
    assert parse_command("/auditoria").name == "expansion_audit"
    assert parse_command("/consolidacion").name == "expansion_audit"
    assert parse_command("/expansión").name == "expansion_audit"


def test_expansion_audit_marks_three_stable_cycles_as_stable():
    engine, SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_stable_expansion(session)
        audit = build_expansion_consolidation_audit(session, runs_per_store=3)
        assert audit.enough_history is True
        assert audit.verdict == "STABLE"
        assert len(audit.stores) == 6
        assert all(view.verdict == "STABLE" for view in audit.stores)
        report = format_expansion_consolidation_report(audit, runs_per_store=3)
        assert "expansión consolidada" in report
        assert "cerrar v5.9" in report
        assert len(report) <= 4000
    engine.dispose()


def test_expansion_audit_keeps_broken_recent_store_on_watch():
    engine, SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_stable_expansion(session)
        store = session.query(Store).filter(Store.connector_key == "licorescl").one()
        latest = utcnow()
        session.add(
            ScrapeRun(
                store_id=store.id,
                status="failed",
                health_status="BROKEN",
                products_found=1,
                duration_ms=500,
                started_at=latest - timedelta(seconds=1),
                finished_at=latest,
                error_message="coverage guard",
            )
        )
        session.flush()
        audit = build_expansion_consolidation_audit(session, runs_per_store=3)
        target = next(view for view in audit.stores if view.connector_key == "licorescl")
        assert target.verdict == "WATCH"
        assert audit.verdict == "WATCH"
    engine.dispose()


def test_expansion_audit_waits_until_all_six_have_enough_runs():
    engine, SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_stable_expansion(session)
        store = session.query(Store).filter(Store.connector_key == "vinoslareina").one()
        runs = (
            session.query(ScrapeRun)
            .filter(ScrapeRun.store_id == store.id)
            .order_by(ScrapeRun.id)
            .all()
        )
        session.delete(runs[0])
        session.flush()
        audit = build_expansion_consolidation_audit(session, runs_per_store=3)
        assert audit.enough_history is False
        assert audit.verdict == "NOT_READY"
    engine.dispose()
