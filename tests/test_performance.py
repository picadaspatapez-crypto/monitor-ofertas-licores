from __future__ import annotations

import time

import pytest

from app.domain import CollectionStats, SectionStats
from app.performance import PerformanceSettings, PhaseMetrics


def _clear_performance_env(monkeypatch):
    for name in (
        "COLLECTOR_WORKERS",
        "BLOCK_BROWSER_RESOURCES",
        "PRODUCT_WAIT_TIMEOUT_MS",
        "DOM_GROWTH_TIMEOUT_MS",
        "QUICK_SETTLE_MS",
    ):
        monkeypatch.delenv(name, raising=False)


def test_performance_settings_defaults_to_two_workers(monkeypatch):
    _clear_performance_env(monkeypatch)
    settings = PerformanceSettings.from_env()
    assert settings.collector_workers == 2
    assert settings.block_browser_resources is True
    assert settings.product_wait_timeout_ms == 8_000


def test_performance_settings_accepts_safe_tuning(monkeypatch):
    _clear_performance_env(monkeypatch)
    monkeypatch.setenv("COLLECTOR_WORKERS", "1")
    monkeypatch.setenv("BLOCK_BROWSER_RESOURCES", "false")
    monkeypatch.setenv("PRODUCT_WAIT_TIMEOUT_MS", "12000")
    monkeypatch.setenv("DOM_GROWTH_TIMEOUT_MS", "6000")
    monkeypatch.setenv("QUICK_SETTLE_MS", "0")
    settings = PerformanceSettings.from_env()
    assert settings.collector_workers == 1
    assert settings.block_browser_resources is False
    assert settings.product_wait_timeout_ms == 12_000
    assert settings.dom_growth_timeout_ms == 6_000
    assert settings.quick_settle_ms == 0


def test_performance_settings_rejects_more_than_two_workers(monkeypatch):
    _clear_performance_env(monkeypatch)
    monkeypatch.setenv("COLLECTOR_WORKERS", "3")
    with pytest.raises(RuntimeError, match="menor o igual a 2"):
        PerformanceSettings.from_env()


def test_phase_metrics_accumulates_repeated_phase():
    metrics = PhaseMetrics()
    with metrics.measure("parse"):
        time.sleep(0.002)
    first = metrics.as_dict()["parse"]
    with metrics.measure("parse"):
        time.sleep(0.002)
    assert metrics.as_dict()["parse"] >= first


def test_performance_dict_defaults_are_not_shared():
    section_a = SectionStats(key="a", name="A", url="https://example.com/a")
    section_b = SectionStats(key="b", name="B", url="https://example.com/b")
    collection_a = CollectionStats()
    collection_b = CollectionStats()
    section_a.performance_ms["parse"] = 1
    collection_a.performance_ms["collect"] = 2
    assert section_b.performance_ms == {}
    assert collection_b.performance_ms == {}

class _KeywordOnlyWaitPage:
    """Replica la firma Python de Playwright: arg es keyword-only."""

    def __init__(self):
        self.calls = []

    def wait_for_function(self, expression, *, arg=None, timeout=None, polling=None):
        self.calls.append(
            {
                "expression": expression,
                "arg": arg,
                "timeout": timeout,
                "polling": polling,
            }
        )
        return object()


def test_wait_for_product_count_growth_passes_arg_as_keyword():
    from app.performance import wait_for_product_count_growth

    page = _KeywordOnlyWaitPage()
    assert wait_for_product_count_growth(page, ".product", 12, timeout_ms=4_500)
    assert page.calls[0]["arg"] == [".product", 12]
    assert page.calls[0]["timeout"] == 4_500


def test_wait_for_signature_change_passes_arg_as_keyword():
    from app.performance import wait_for_signature_change

    page = _KeywordOnlyWaitPage()
    assert wait_for_signature_change(page, "a[href]", "old", timeout_ms=4_500)
    assert page.calls[0]["arg"] == ["a[href]", "old"]
    assert page.calls[0]["timeout"] == 4_500
