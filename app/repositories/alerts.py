from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Alert
from app.repositories.common import utcnow


RETRY_PENDING_AFTER = timedelta(minutes=30)


def latest_sent_alert(
    session: Session,
    *,
    store_id: int | None,
    alert_type: str,
) -> Alert | None:
    return session.scalar(
        select(Alert)
        .where(
            Alert.store_id == store_id,
            Alert.alert_type == alert_type,
            Alert.status == "sent",
        )
        .order_by(Alert.sent_at.desc(), Alert.id.desc())
        .limit(1)
    )


def reserve_alert(
    session: Session,
    *,
    store_id: int | None,
    scrape_run_id: int | None,
    product_id: int | None,
    alert_type: str,
    price: int | None,
    reason: str,
    deduplication_key: str,
    payload_hash: str | None,
) -> Alert | None:
    """Reserva una notificación antes de enviarla.

    Una clave ya enviada no se repite. Una reserva fallida o pendiente por más
    de 30 minutos puede reintentarse para no perder avisos después de un corte.
    """
    existing = session.scalar(
        select(Alert).where(Alert.deduplication_key == deduplication_key)
    )
    now = utcnow()
    if existing is not None:
        if existing.status == "sent":
            return None
        created_at = existing.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=now.tzinfo)
        if existing.status == "pending" and now - created_at < RETRY_PENDING_AFTER:
            return None
        existing.status = "pending"
        existing.failed_at = None
        existing.error_message = None
        existing.created_at = now
        existing.reason = reason
        existing.payload_hash = payload_hash
        existing.price = price
        existing.product_id = product_id
        existing.store_id = store_id
        existing.scrape_run_id = scrape_run_id
        session.flush()
        return existing

    alert = Alert(
        product_id=product_id,
        store_id=store_id,
        scrape_run_id=scrape_run_id,
        alert_type=alert_type,
        status="pending",
        channel="telegram",
        price=price,
        reason=reason,
        deduplication_key=deduplication_key,
        payload_hash=payload_hash,
    )
    session.add(alert)
    try:
        session.flush()
    except IntegrityError:
        # Defensa ante dos ejecuciones concurrentes. La restricción única es la
        # fuente final de verdad y evita el doble envío.
        session.rollback()
        return None
    return alert


def mark_alert_sent(alert: Alert) -> None:
    alert.status = "sent"
    alert.sent_at = utcnow()
    alert.failed_at = None
    alert.error_message = None


def mark_alert_failed(alert: Alert, error: Exception | str) -> None:
    alert.status = "failed"
    alert.failed_at = utcnow()
    alert.error_message = str(error)[:2000]
