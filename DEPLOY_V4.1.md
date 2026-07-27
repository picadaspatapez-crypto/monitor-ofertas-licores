from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Alert, ScrapeRun, Store
from app.notifications import NotificationBundle
from app.services import deliver_notification_bundles


def _database():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    with SessionLocal() as session:
        store = Store(
            name="Test",
            slug="test",
            base_url="https://example.com",
            connector_key="test",
        )
        session.add(store)
        session.flush()
        run = ScrapeRun(store_id=store.id, status="success")
        session.add(run)
        session.commit()
        return SessionLocal, store.id, run.id


def _bundle(store_id: int, run_id: int) -> NotificationBundle:
    return NotificationBundle(
        store_id=store_id,
        run_id=run_id,
        alert_type="ranking_digest",
        deduplication_key=f"ranking-digest:{store_id}:{run_id}:abc",
        payload_hash="abc",
        reason="test",
        messages=("uno", "dos"),
    )


def test_delivery_marks_bundle_sent_and_skips_duplicate():
    SessionLocal, store_id, run_id = _database()
    sent_messages = []

    def fake_send(token, chat, message):
        sent_messages.append((token, chat, message))

    result = deliver_notification_bundles(
        SessionLocal=SessionLocal,
        bundles=[_bundle(store_id, run_id)],
        telegram_bot_token="token",
        telegram_chat_id="chat",
        send_message_fn=fake_send,
    )
    assert result == (1, 0, 0)
    assert [item[2] for item in sent_messages] == ["uno", "dos"]

    duplicate = deliver_notification_bundles(
        SessionLocal=SessionLocal,
        bundles=[_bundle(store_id, run_id)],
        telegram_bot_token="token",
        telegram_chat_id="chat",
        send_message_fn=fake_send,
    )
    assert duplicate == (0, 1, 0)

    with SessionLocal() as session:
        alert = session.scalar(select(Alert))
        assert alert.status == "sent"
        assert alert.sent_at is not None


def test_failed_delivery_is_recorded_and_can_retry():
    SessionLocal, store_id, run_id = _database()
    attempts = 0

    def failing_send(token, chat, message):
        nonlocal attempts
        attempts += 1
        raise RuntimeError("telegram down")

    first = deliver_notification_bundles(
        SessionLocal=SessionLocal,
        bundles=[_bundle(store_id, run_id)],
        telegram_bot_token="token",
        telegram_chat_id="chat",
        send_message_fn=failing_send,
    )
    assert first == (0, 0, 1)

    delivered = []

    def working_send(token, chat, message):
        delivered.append(message)

    retry = deliver_notification_bundles(
        SessionLocal=SessionLocal,
        bundles=[_bundle(store_id, run_id)],
        telegram_bot_token="token",
        telegram_chat_id="chat",
        send_message_fn=working_send,
    )
    assert retry == (1, 0, 0)
    assert delivered == ["uno", "dos"]
