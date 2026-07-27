from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.repositories import mark_alert_failed, mark_alert_sent, reserve_alert


def _session_factory():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def test_sent_deduplication_key_is_not_reserved_twice():
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        alert = reserve_alert(
            session,
            store_id=None,
            scrape_run_id=None,
            product_id=None,
            alert_type="test",
            price=None,
            reason="test",
            deduplication_key="same-key",
            payload_hash="abc",
        )
        assert alert is not None
        mark_alert_sent(alert)
        session.commit()

    with SessionLocal() as session:
        duplicate = reserve_alert(
            session,
            store_id=None,
            scrape_run_id=None,
            product_id=None,
            alert_type="test",
            price=None,
            reason="test",
            deduplication_key="same-key",
            payload_hash="abc",
        )
        assert duplicate is None


def test_failed_alert_can_be_reserved_for_retry():
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        alert = reserve_alert(
            session,
            store_id=None,
            scrape_run_id=None,
            product_id=None,
            alert_type="test",
            price=None,
            reason="test",
            deduplication_key="retry-key",
            payload_hash="abc",
        )
        assert alert is not None
        mark_alert_failed(alert, "network")
        session.commit()

    with SessionLocal() as session:
        retried = reserve_alert(
            session,
            store_id=None,
            scrape_run_id=None,
            product_id=None,
            alert_type="test",
            price=None,
            reason="retry",
            deduplication_key="retry-key",
            payload_hash="abc",
        )
        assert retried is not None
        assert retried.status == "pending"
