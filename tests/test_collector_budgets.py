import pytest

from app.deadlines import CollectorBudgetExceeded, collector_budget, ensure_budget
from app.performance import PerformanceSettings
from app.pipeline.runner import CollectorExecution, _pipeline_exit_code


def test_performance_default_budget_is_25_minutes(monkeypatch):
    monkeypatch.delenv("COLLECTOR_TIMEOUT_MINUTES", raising=False)
    assert PerformanceSettings.from_env().collector_timeout_minutes == 25


def test_performance_budget_can_be_configured(monkeypatch):
    monkeypatch.setenv("COLLECTOR_TIMEOUT_MINUTES", "30")
    assert PerformanceSettings.from_env().collector_timeout_minutes == 30


def test_expired_collector_budget_raises(monkeypatch):
    import app.deadlines as deadlines

    ticks = iter([100.0, 102.0])
    monkeypatch.setattr(deadlines.time, "monotonic", lambda: next(ticks))
    with collector_budget(store_name="Tienda", seconds=1):
        with pytest.raises(CollectorBudgetExceeded, match="Tienda"):
            ensure_budget("prueba")


def test_partial_multistore_run_returns_success():
    results = [
        CollectorExecution("a", "A", True, 10),
        CollectorExecution("b", "B", False, 10),
    ]
    assert _pipeline_exit_code(results) == 0


def test_all_collectors_failed_returns_error():
    results = [
        CollectorExecution("a", "A", False, 10),
        CollectorExecution("b", "B", False, 10),
    ]
    assert _pipeline_exit_code(results) == 1
