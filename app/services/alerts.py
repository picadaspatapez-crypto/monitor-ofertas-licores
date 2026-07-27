from __future__ import annotations

import hashlib
from datetime import timedelta, timezone
from typing import Callable

from sqlalchemy.orm import sessionmaker

from app.models import Alert
from app.notifications import NotificationBundle
from app.repositories import (
    latest_sent_alert,
    mark_alert_failed,
    mark_alert_sent,
    reserve_alert,
)
from app.repositories.common import utcnow


SendMessage = Callable[[str, str, str], None]


def deliver_notification_bundles(
    *,
    SessionLocal: sessionmaker,
    bundles: list[NotificationBundle],
    telegram_bot_token: str,
    telegram_chat_id: str,
    send_message_fn: SendMessage,
) -> tuple[int, int, int]:
    """Envía bundles reservándolos en PostgreSQL para evitar duplicados.

    Retorna ``(sent, skipped, failed)``. Un fallo de Telegram no invalida el
    scraping ni el historial de precios; queda registrado para reintento.
    """
    sent = skipped = failed = 0
    for bundle in bundles:
        with SessionLocal() as session:
            alert = reserve_alert(
                session,
                store_id=bundle.store_id,
                scrape_run_id=bundle.run_id,
                product_id=bundle.product_id,
                alert_type=bundle.alert_type,
                price=bundle.price,
                reason=bundle.reason,
                deduplication_key=bundle.deduplication_key,
                payload_hash=bundle.payload_hash,
            )
            if alert is None:
                skipped += 1
                continue
            alert_id = alert.id
            session.commit()

        try:
            for message in bundle.messages:
                send_message_fn(telegram_bot_token, telegram_chat_id, message)
        except Exception as exc:
            with SessionLocal() as session:
                alert = session.get(Alert, alert_id)
                if alert is not None:
                    mark_alert_failed(alert, exc)
                    session.commit()
            failed += 1
            print(
                f"Telegram: falló {bundle.alert_type}: {exc}",
                flush=True,
            )
            continue

        with SessionLocal() as session:
            alert = session.get(Alert, alert_id)
            if alert is not None:
                mark_alert_sent(alert)
                session.commit()
        sent += 1
    return sent, skipped, failed


def _alert_age(alert: Alert | None):
    if alert is None or alert.sent_at is None:
        return None
    sent_at = alert.sent_at
    now = utcnow()
    if sent_at.tzinfo is None:
        sent_at = sent_at.replace(tzinfo=timezone.utc)
    return now - sent_at


def failure_notification_bundle(
    *,
    SessionLocal: sessionmaker,
    store_id: int,
    run_id: int,
    store_name: str,
    error: Exception,
) -> NotificationBundle | None:
    normalized_error = f"{type(error).__name__}: {str(error)[:1000]}"
    payload_hash = hashlib.sha256(normalized_error.encode("utf-8")).hexdigest()
    with SessionLocal() as session:
        last = latest_sent_alert(
            session,
            store_id=store_id,
            alert_type="collector_failure",
        )
        age = _alert_age(last)
        if (
            last is not None
            and last.payload_hash == payload_hash
            and age is not None
            and age < timedelta(hours=24)
        ):
            return None

    message = "\n".join(
        [
            f"🔴 Falló el collector · {store_name}",
            "",
            normalized_error,
            "",
            "No se repite el mismo error durante 24 horas, pero la ejecución queda registrada.",
        ]
    )
    return NotificationBundle(
        store_id=store_id,
        run_id=run_id,
        alert_type="collector_failure",
        deduplication_key=f"collector-failure:{store_id}:{run_id}:{payload_hash[:20]}",
        payload_hash=payload_hash,
        reason=normalized_error,
        messages=(message,),
    )
