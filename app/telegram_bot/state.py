from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import TelegramBotState


_OFFSET_KEY = "telegram_search_next_update_id"


def load_next_update_id(session: Session) -> int | None:
    row = session.scalar(
        select(TelegramBotState).where(TelegramBotState.key == _OFFSET_KEY)
    )
    if row is None or not row.value:
        return None
    try:
        return int(row.value)
    except ValueError:
        return None


def save_next_update_id(session: Session, value: int) -> None:
    row = session.scalar(
        select(TelegramBotState).where(TelegramBotState.key == _OFFSET_KEY)
    )
    if row is None:
        session.add(TelegramBotState(key=_OFFSET_KEY, value=str(int(value))))
    else:
        row.value = str(int(value))
    session.flush()
