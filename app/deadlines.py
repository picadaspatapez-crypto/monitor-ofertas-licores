from __future__ import annotations

import time
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator


class CollectorBudgetExceeded(RuntimeError):
    """Raised when a collector exceeds its configured wall-clock budget."""


_deadline: ContextVar[float | None] = ContextVar("collector_deadline", default=None)
_store_name: ContextVar[str] = ContextVar("collector_store_name", default="Collector")


@contextmanager
def collector_budget(*, store_name: str, seconds: int) -> Iterator[None]:
    deadline_token = _deadline.set(time.monotonic() + max(1, int(seconds)))
    store_token = _store_name.set(store_name)
    try:
        yield
    finally:
        _deadline.reset(deadline_token)
        _store_name.reset(store_token)


def remaining_seconds(*, fallback: float | None = None) -> float | None:
    deadline = _deadline.get()
    if deadline is None:
        return fallback
    return max(0.0, deadline - time.monotonic())


def ensure_budget(context: str | None = None) -> None:
    remaining = remaining_seconds()
    if remaining is None or remaining > 0:
        return
    suffix = f" durante {context}" if context else ""
    raise CollectorBudgetExceeded(
        f"{_store_name.get()} superó el límite máximo de ejecución{suffix}."
    )


def bounded_request_timeout(
    default: tuple[float, float],
    *,
    minimum: float = 1.0,
) -> tuple[float, float]:
    """Clamp requests' connect/read timeout to the collector time remaining."""

    ensure_budget("una solicitud HTTP")
    remaining = remaining_seconds()
    if remaining is None:
        return default
    available = max(minimum, remaining - 0.25)
    connect = max(minimum, min(float(default[0]), available))
    read = max(minimum, min(float(default[1]), available))
    return connect, read


def bounded_timeout_ms(default_ms: int, *, minimum_ms: int = 250) -> int:
    """Clamp a Playwright timeout to the collector time remaining."""

    ensure_budget("una operación de navegador")
    remaining = remaining_seconds()
    if remaining is None:
        return int(default_ms)
    available_ms = max(minimum_ms, int((remaining - 0.25) * 1000))
    return max(minimum_ms, min(int(default_ms), available_ms))
