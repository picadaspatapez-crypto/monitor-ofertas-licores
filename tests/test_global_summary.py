from app.pipeline.runner import CollectorExecution
from app.reports.global_summary import build_global_run_summary


def test_global_summary_always_lists_every_store():
    executions = [
        CollectorExecution(
            key="liquidos",
            store_name="Líquidos",
            success=True,
            duration_ms=120_000,
            products_found=700,
            health_status="HEALTHY",
        ),
        CollectorExecution(
            key="licor3b",
            store_name="Licor3B",
            success=True,
            duration_ms=180_000,
            products_found=550,
            health_status="HEALTHY",
            price_drops=2,
        ),
        CollectorExecution(
            key="tost",
            store_name="Tost",
            success=False,
            duration_ms=30_000,
            error_message="HTTP 503",
        ),
    ]
    message = build_global_run_summary(executions, wall_duration_ms=190_000)
    assert "Licor3B" in message
    assert "Líquidos" in message
    assert "Tost" in message
    assert "2 bajas" in message
    assert "Collector fallido" in message
