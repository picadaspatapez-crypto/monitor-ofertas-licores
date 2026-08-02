from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ScrapeRun, Store
from app.repositories.common import utcnow


def _duration(milliseconds: float) -> str:
    seconds = int(max(0, milliseconds) // 1000)
    minutes, seconds = divmod(seconds, 60)
    return f"{minutes}m {seconds:02d}s" if minutes else f"{seconds}s"


def build_weekly_health_report(
    session: Session,
    *,
    days: int = 7,
    timeout_minutes: int = 25,
) -> str:
    cutoff = utcnow() - timedelta(days=max(1, days))
    stores = list(
        session.scalars(
            select(Store).where(Store.is_active.is_(True)).order_by(Store.name)
        )
    )
    lines = [
        "🩺 Reporte semanal de salud",
        "",
        f"Ventana analizada: últimos {days} días",
        "",
    ]
    total_runs = total_failures = total_rate_limits = 0
    for store in stores:
        runs = list(
            session.scalars(
                select(ScrapeRun)
                .where(
                    ScrapeRun.store_id == store.id,
                    ScrapeRun.started_at >= cutoff,
                    ScrapeRun.finished_at.is_not(None),
                )
                .order_by(ScrapeRun.started_at)
            )
        )
        total_runs += len(runs)
        healthy = sum(run.health_status == "HEALTHY" and run.status == "success" for run in runs)
        degraded = sum(run.health_status in {"DEGRADED", "STALE"} for run in runs)
        failures = sum(run.status == "failed" or run.health_status == "BROKEN" for run in runs)
        total_failures += failures
        rate_limits = sum(
            any(marker in (run.error_message or "") for marker in ("429", "430", "403", "RateLimit"))
            for run in runs
        )
        total_rate_limits += rate_limits
        durations = [int(run.duration_ms or 0) for run in runs if run.duration_ms is not None]
        products = [int(run.products_found or 0) for run in runs if run.products_found > 0]
        average_duration = sum(durations) / len(durations) if durations else 0
        average_products = round(sum(products) / len(products)) if products else 0
        near_timeout = sum(
            int(run.duration_ms or 0) >= int(timeout_minutes * 60 * 1000 * 0.80)
            for run in runs
        )
        latest = runs[-1] if runs else None
        source = None
        if latest is not None and isinstance(latest.metrics_json, dict):
            source = latest.metrics_json.get("discovery_source")
        success_rate = (healthy / len(runs) * 100) if runs else 0.0
        icon = "🟢" if success_rate >= 90 and failures == 0 else "🟡" if healthy else "🔴"
        lines.append(f"{icon} {store.name}")
        lines.append(
            f"   Éxito HEALTHY: {healthy}/{len(runs)} ({success_rate:.0f}%) · "
            f"DEGRADED/STALE: {degraded} · fallos: {failures}"
        )
        lines.append(
            f"   Promedio: {average_products} productos · {_duration(average_duration)}"
        )
        if source:
            lines.append(f"   Fuente: {source}")
        if rate_limits:
            lines.append(f"   Límites 429/430/403: {rate_limits}")
        if near_timeout:
            lines.append(f"   Cerca del límite de {timeout_minutes} min: {near_timeout} ejecución(es)")
        lines.append("")

    lines.extend(
        [
            f"Ejecuciones totales: {total_runs}",
            f"Fallos totales: {total_failures}",
            f"Incidentes de rate limit: {total_rate_limits}",
        ]
    )
    return "\n".join(lines)[:4000]
