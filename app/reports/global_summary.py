from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol


class ExecutionView(Protocol):
    key: str
    store_name: str
    success: bool
    duration_ms: int
    products_found: int
    health_status: str | None
    new_products: int
    price_drops: int
    price_increases: int
    sections_failed: int
    error_message: str | None
    execution_state: str
    detail: str | None
    source: str | None
    marked_unavailable: int
    reactivated: int
    diagnostic_mode: bool


def _duration(milliseconds: int) -> str:
    seconds = max(0, int(milliseconds)) // 1000
    minutes, seconds = divmod(seconds, 60)
    if minutes:
        return f"{minutes}m {seconds:02d}s"
    return f"{seconds}s"


def build_global_run_summary(
    executions: Iterable[ExecutionView],
    *,
    wall_duration_ms: int,
) -> str:
    ordered = sorted(executions, key=lambda item: item.store_name.casefold())
    public = [item for item in ordered if not getattr(item, "diagnostic_mode", False)]
    diagnostic = [item for item in ordered if getattr(item, "diagnostic_mode", False)]
    updated = sum(item.execution_state == "UPDATED" and item.success for item in public)
    stale = sum(item.execution_state == "STALE" and item.success for item in public)
    due_soon = sum(item.execution_state == "DUE_SOON" and item.success for item in public)
    paused = sum(item.execution_state == "PAUSED" for item in public)
    failed = sum(item.execution_state == "FAILED" or (
        not item.success and item.execution_state not in {"PAUSED"}
    ) for item in public)
    diagnostic_ok = sum(item.success for item in diagnostic)
    lines = [
        "📊 Revisión multi-tienda completada",
        "",
        f"Tiendas actualizadas: {updated}",
        f"Tiendas con datos vigentes: {updated + stale + due_soon}",
        f"Revisiones programadas pendientes: {due_soon}",
        f"Tiendas pausadas: {paused}",
        f"Tiendas fallidas: {failed}",
        f"Collectors diagnóstico OK: {diagnostic_ok}/{len(diagnostic)}" if diagnostic else "Collectors diagnóstico: 0",
        f"Duración collectors: {_duration(wall_duration_ms)}",
        "",
    ]
    icons = {
        "HEALTHY": "🟢",
        "DEGRADED": "🟡",
        "BROKEN": "🔴",
        "STALE": "🟠",
        "PAUSED": "⏸",
        "DUE_SOON": "🕒",
    }
    for item in ordered:
        state = item.execution_state
        if state == "DUE_SOON":
            lines.append(f"🕒 {item.store_name}")
            lines.append(f"   {item.products_found} productos · catálogo vigente")
            if item.source:
                lines.append(f"   Fuente: {item.source}")
            if item.detail:
                lines.append(f"   {item.detail[:220]}")
        elif state == "PAUSED":
            lines.append(f"⏸ {item.store_name}")
            lines.append("   Collector pausado temporalmente")
            if item.detail:
                lines.append(f"   {item.detail[:180]}")
        elif state == "STALE":
            lines.append(f"🟠 {item.store_name}")
            lines.append(
                f"   {item.products_found} productos · último snapshot confiable"
            )
            if item.detail:
                lines.append(f"   {item.detail[:180]}")
        elif item.success:
            health = item.health_status or "UNKNOWN"
            icon = icons.get(health, "⚪")
            prefix = "🧪" if getattr(item, "diagnostic_mode", False) else icon
            lines.append(f"{prefix} {item.store_name}")
            lines.append(
                f"   {item.products_found} productos · {health}{' · DIAGNÓSTICO' if getattr(item, 'diagnostic_mode', False) else ''} · {_duration(item.duration_ms)}"
            )
            changes = []
            if item.price_drops:
                changes.append(f"{item.price_drops} bajas")
            if item.price_increases:
                changes.append(f"{item.price_increases} alzas")
            if item.new_products:
                changes.append(f"{item.new_products} nuevos")
            if item.sections_failed:
                changes.append(f"{item.sections_failed} categorías fallidas")
            if item.marked_unavailable:
                changes.append(f"{item.marked_unavailable} retirados confirmados")
            if item.reactivated:
                changes.append(f"{item.reactivated} repuestos")
            lines.append(f"   Cambios: {', '.join(changes) if changes else 'ninguno'}")
            if item.source:
                lines.append(f"   Fuente: {item.source}")
        else:
            if getattr(item, "diagnostic_mode", False):
                lines.append(f"🧪 {item.store_name}")
                lines.append("   Diagnóstico fallido; no afecta comparador ni alertas públicas")
            else:
                lines.append(f"🔴 {item.store_name}")
                lines.append("   Collector fallido")
            if item.error_message:
                lines.append(f"   {item.error_message[:160]}")
        lines.append("")

    lines.extend(
        [
            "Los rankings extensos se envían solo cuando cambian o vence su intervalo.",
            "STALE conserva el último catálogo tras un fallo; DUE SOON aún no vence; PAUSED no se intenta en cada ciclo.",
        ]
    )
    return "\n".join(lines).strip()
