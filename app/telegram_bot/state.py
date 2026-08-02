from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.models import TelegramBotState


_OFFSET_KEY = "telegram_search_next_update_id"


def load_next_update_id(session: Session) -> int | None:
    state = session.get(TelegramBotState, _OFFSET_KEY)
    if state is None:
        return None
    try:
        return int(state.value)
    except (TypeError, ValueError):
        return None


def save_next_update_id(session: Session, value: int) -> None:
    state = session.get(TelegramBotState, _OFFSET_KEY)
    if state is None:
        session.add(TelegramBotState(key=_OFFSET_KEY, value=str(int(value))))
    else:
        state.value = str(int(value))


def _search_key(chat_id: int) -> str:
    return f"telegram_search_page:{int(chat_id)}"


def save_search_page(session: Session, *, chat_id: int, query: str, offset: int) -> None:
    key = _search_key(chat_id)
    payload = json.dumps({"query": query[:120], "offset": max(0, int(offset))})
    state = session.get(TelegramBotState, key)
    if state is None:
        session.add(TelegramBotState(key=key, value=payload))
    else:
        state.value = payload


def load_search_page(session: Session, *, chat_id: int) -> tuple[str, int] | None:
    state = session.get(TelegramBotState, _search_key(chat_id))
    if state is None:
        return None
    try:
        payload = json.loads(state.value)
        query = str(payload.get("query") or "").strip()
        offset = int(payload.get("offset") or 0)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return (query, max(0, offset)) if query else None
