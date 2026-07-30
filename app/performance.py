from __future__ import annotations

import os
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterator

from playwright.sync_api import BrowserContext, Page, TimeoutError as PlaywrightTimeoutError, Route


BLOCKED_RESOURCE_TYPES = frozenset({"image", "media", "font"})
TRACKER_URL_PARTS = (
    "google-analytics.com",
    "googletagmanager.com",
    "doubleclick.net",
    "connect.facebook.net",
    "facebook.com/tr",
    "hotjar.com",
    "clarity.ms",
    "tiktok.com/i18n/pixel",
    "criteo.com",
    "newrelic.com",
    "nr-data.net",
    "sentry.io",
)


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().casefold() in {"1", "true", "yes", "si", "sí", "on"}


def _positive_int(name: str, default: int, *, minimum: int = 1, maximum: int | None = None) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise RuntimeError(f"{name} debe ser un número entero.") from exc
    if value < minimum:
        raise RuntimeError(f"{name} debe ser mayor o igual a {minimum}.")
    if maximum is not None and value > maximum:
        raise RuntimeError(f"{name} debe ser menor o igual a {maximum}.")
    return value


@dataclass(frozen=True)
class PerformanceSettings:
    collector_workers: int = 4
    block_browser_resources: bool = True
    product_wait_timeout_ms: int = 8_000
    dom_growth_timeout_ms: int = 4_500
    quick_settle_ms: int = 250
    collector_timeout_minutes: int = 25
    el_mundo_interval_hours: int = 12

    @classmethod
    def from_env(cls) -> "PerformanceSettings":
        return cls(
            collector_workers=_positive_int("COLLECTOR_WORKERS", 4, maximum=4),
            block_browser_resources=_bool_env("BLOCK_BROWSER_RESOURCES", True),
            product_wait_timeout_ms=_positive_int(
                "PRODUCT_WAIT_TIMEOUT_MS", 8_000, minimum=1_000, maximum=30_000
            ),
            dom_growth_timeout_ms=_positive_int(
                "DOM_GROWTH_TIMEOUT_MS", 4_500, minimum=500, maximum=20_000
            ),
            quick_settle_ms=_positive_int(
                "QUICK_SETTLE_MS", 250, minimum=0, maximum=2_000
            ),
            collector_timeout_minutes=_positive_int(
                "COLLECTOR_TIMEOUT_MINUTES", 25, minimum=1, maximum=120
            ),
            el_mundo_interval_hours=_positive_int(
                "EL_MUNDO_INTERVAL_HOURS", 12, minimum=1, maximum=168
            ),
        )


@dataclass
class PhaseMetrics:
    values_ms: dict[str, int] = field(default_factory=dict)

    @contextmanager
    def measure(self, name: str) -> Iterator[None]:
        started = time.monotonic()
        try:
            yield
        finally:
            elapsed_ms = int((time.monotonic() - started) * 1_000)
            self.values_ms[name] = self.values_ms.get(name, 0) + elapsed_ms

    def add(self, name: str, elapsed_ms: int) -> None:
        self.values_ms[name] = self.values_ms.get(name, 0) + max(0, int(elapsed_ms))

    def merge(self, other: "PhaseMetrics") -> None:
        """Acumula las fases de otra medición sin compartir su diccionario interno."""
        for name, elapsed_ms in other.values_ms.items():
            self.add(name, elapsed_ms)

    def as_dict(self) -> dict[str, int]:
        return dict(self.values_ms)


@dataclass
class ResourceBlockStats:
    blocked_requests: int = 0
    continued_requests: int = 0


def install_resource_blocking(
    context: BrowserContext,
    *,
    enabled: bool = True,
    stats: ResourceBlockStats | None = None,
) -> ResourceBlockStats:
    """Bloquea recursos visuales y trackers sin impedir HTML, CSS ni JS funcional."""

    stats = stats or ResourceBlockStats()
    if not enabled:
        return stats

    def handle(route: Route) -> None:
        request = route.request
        url = request.url.casefold()
        should_block = (
            request.resource_type in BLOCKED_RESOURCE_TYPES
            or any(part in url for part in TRACKER_URL_PARTS)
        )
        if should_block:
            stats.blocked_requests += 1
            route.abort()
        else:
            stats.continued_requests += 1
            route.continue_()

    context.route("**/*", handle)
    return stats


def wait_for_any_selector(
    page: Page,
    selector: str,
    *,
    timeout_ms: int,
    settle_ms: int = 0,
) -> bool:
    """Espera contenido útil, no el fin total del tráfico de red."""

    try:
        page.locator(selector).first.wait_for(state="attached", timeout=timeout_ms)
        if settle_ms:
            page.wait_for_timeout(settle_ms)
        return True
    except PlaywrightTimeoutError:
        return False


def wait_for_product_count_growth(
    page: Page,
    selector: str,
    previous_count: int,
    *,
    timeout_ms: int,
) -> bool:
    try:
        page.wait_for_function(
            "([selector, previous]) => document.querySelectorAll(selector).length > previous",
            arg=[selector, previous_count],
            timeout=timeout_ms,
        )
        return True
    except PlaywrightTimeoutError:
        return False


def wait_for_signature_change(
    page: Page,
    selector: str,
    previous_signature: str,
    *,
    timeout_ms: int,
) -> bool:
    try:
        page.wait_for_function(
            "([selector, previous]) => Array.from(document.querySelectorAll(selector))"
            ".map(el => el.href || '').filter(Boolean).sort().join('|') !== previous",
            arg=[selector, previous_signature],
            timeout=timeout_ms,
        )
        return True
    except PlaywrightTimeoutError:
        return False
