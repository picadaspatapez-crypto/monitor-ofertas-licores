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


def test_global_summary_distinguishes_stale_and_paused():
    executions = [
        CollectorExecution(
            key="elmundodelvino", store_name="El Mundo del Vino",
            success=True, duration_ms=0, products_found=834,
            health_status="STALE", execution_state="STALE",
            detail="Próxima revisión en 6 h.", run_id=10, store_id=2,
        ),
        CollectorExecution(
            key="labarra", store_name="La Barra", success=False,
            duration_ms=0, health_status="PAUSED", execution_state="PAUSED",
            detail="Próximo preflight semanal.",
        ),
        CollectorExecution(
            key="liquidos", store_name="Líquidos", success=True,
            duration_ms=1000, products_found=900, health_status="HEALTHY",
        ),
    ]
    message = build_global_run_summary(executions, wall_duration_ms=1000)
    assert "Tiendas actualizadas: 1" in message
    assert "Tiendas con datos vigentes: 2" in message
    assert "Tiendas pausadas: 1" in message
    assert "último snapshot confiable" in message
    assert "Collector pausado temporalmente" in message
