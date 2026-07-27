from __future__ import annotations

import os
from dataclasses import dataclass


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().casefold()
    if value in {"1", "true", "yes", "si", "sí", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"Valor inválido para {name}: {raw!r}. Usa true/false.")


def _positive_int(
    name: str,
    default: int,
    *,
    minimum: int = 1,
    maximum: int | None = None,
) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise RuntimeError(f"{name} debe ser un número entero.") from exc
    if value < minimum:
        raise RuntimeError(f"{name} debe ser mayor o igual a {minimum}.")
    if maximum is not None:
        value = min(value, maximum)
    return value


def _chat_ids() -> frozenset[int]:
    raw = os.getenv("TELEGRAM_ALLOWED_CHAT_IDS", "").strip()
    if not raw:
        raw = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not raw:
        return frozenset()

    values: set[int] = set()
    for part in raw.replace(";", ",").split(","):
        clean = part.strip()
        if not clean:
            continue
        try:
            values.add(int(clean))
        except ValueError as exc:
            raise RuntimeError(
                "TELEGRAM_ALLOWED_CHAT_IDS debe contener IDs numéricos separados por comas."
            ) from exc
    return frozenset(values)


@dataclass(frozen=True)
class TelegramBotSettings:
    enabled: bool
    token: str
    allowed_chat_ids: frozenset[int]
    result_limit: int
    max_age_hours: int
    poll_timeout_seconds: int
    retry_seconds: int

    @classmethod
    def from_env(cls) -> "TelegramBotSettings":
        token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        enabled = _bool_env("TELEGRAM_SEARCH_BOT_ENABLED", True) and bool(token)
        return cls(
            enabled=enabled,
            token=token,
            allowed_chat_ids=_chat_ids(),
            result_limit=_positive_int(
                "TELEGRAM_SEARCH_RESULT_LIMIT", 5, maximum=8
            ),
            max_age_hours=_positive_int(
                "SEARCH_MAX_AGE_HOURS", 72, maximum=24 * 30
            ),
            poll_timeout_seconds=_positive_int(
                "TELEGRAM_POLL_TIMEOUT_SECONDS", 25, maximum=50
            ),
            retry_seconds=_positive_int(
                "TELEGRAM_POLL_RETRY_SECONDS", 5, maximum=60
            ),
        )
