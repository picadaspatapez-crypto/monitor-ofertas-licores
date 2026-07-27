from __future__ import annotations

from app.analyzers import CatalogAnalysis
from app.domain import SavedProduct

REPORT_LIMIT = 20
ITEMS_PER_MESSAGE = 10
CHANGE_LIMIT = 10


def clp(value: int) -> str:
    return "$" + f"{value:,}".replace(",", ".")


def duration_text(duration_ms: int) -> str:
    total_seconds = max(0, duration_ms // 1000)
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes}m {seconds:02d}s" if minutes else f"{seconds}s"


def _reported_discount(saved: SavedProduct) -> bool:
    return (
        saved.item.regular_price is not None
        and saved.item.regular_price > saved.item.current_price
        and saved.item.discount_pct > 0
    )


def _alphabetical(items: list[SavedProduct]) -> list[SavedProduct]:
    return sorted(items, key=lambda saved: saved.item.name.casefold())


def _change_lines(saved: SavedProduct) -> list[str]:
    item = saved.item
    if saved.previous_price is None:
        return [f"• {item.name}: {clp(item.current_price)}"]
    symbol = "▼" if saved.price_dropped else "▲"
    return [
        f"• {item.name}",
        f"  {clp(saved.previous_price)} → {clp(item.current_price)} "
        f"({symbol} {abs(saved.price_change_pct):.1%})",
    ]


def build_telegram_messages(
    *, store_name: str, items: list[SavedProduct], analysis: CatalogAnalysis
) -> list[str]:
    stats = analysis.collection_stats
    health_icon = {"HEALTHY": "🟢", "DEGRADED": "🟡", "BROKEN": "🔴"}.get(
        stats.health_status, "⚪"
    )
    summary = [
        f"📊 Ejecución completada: {store_name}",
        "",
        f"{health_icon} Salud: {stats.health_status} ({stats.health_score}/100)",
        f"⏱ Duración: {duration_text(analysis.duration_ms)}",
        f"🗂 Secciones: {stats.sections_visited}",
        f"🧭 Categorías descubiertas: {stats.sections_discovered}",
        f"✅ Categorías correctas: {stats.sections_succeeded}",
        f"❌ Categorías fallidas: {stats.sections_failed}",
        f"⚠️ Alertas estructurales: {stats.structural_warnings}",
        f"📄 Páginas: {stats.pages_visited}",
        f"🧾 Tarjetas procesadas: {stats.cards_seen}",
        f"♻️ Duplicados eliminados: {stats.duplicates_removed}",
        f"📦 Productos encontrados: {analysis.total}",
        f"🆕 Nuevos: {analysis.new_products}",
        f"🔄 Actualizados: {analysis.total - analysis.new_products}",
        f"📉 Bajaron: {analysis.price_drops}",
        f"📈 Subieron: {analysis.price_increases}",
        f"➖ Sin cambios: {analysis.unchanged}",
        f"👻 No observados: {analysis.missing_products}",
        f"🏷️ Con descuento informado: {analysis.reported_discounts}",
    ]
    messages = ["\n".join(summary)]

    if stats.section_stats:
        lines = ["🗂 Resumen por categoría", ""]
        for section in stats.section_stats:
            icon = "✅" if section.status == "success" else "❌"
            warning = " ⚠️" if section.structural_warning else ""
            lines.append(
                f"{icon} {section.name}: {section.unique_products} productos, "
                f"{section.pages_visited} páginas, {duration_text(section.duration_ms)}{warning}"
            )
        messages.append("\n".join(lines))

    problems = [
        section for section in stats.section_stats
        if section.status != "success" or section.structural_warning
    ]
    if problems:
        lines = ["⚠️ Incidencias del collector", ""]
        for section in problems:
            if section.status != "success":
                lines.append(f"• {section.name}: {section.error_message or 'error desconocido'}")
            elif section.structural_warning:
                lines.append(f"• {section.name}: HTTP correcto, pero 0 tarjetas en la primera página.")
        messages.append("\n".join(lines))

    drops = sorted(
        (item for item in items if item.price_dropped),
        key=lambda item: (item.price_change_pct, item.item.name.casefold()),
    )[:CHANGE_LIMIT]
    if drops:
        lines = ["🔥 Mayores bajas reales", ""]
        for saved in drops:
            lines.extend(_change_lines(saved))
        messages.append("\n".join(lines))

    increases = sorted(
        (item for item in items if item.price_increased),
        key=lambda item: (-item.price_change_pct, item.item.name.casefold()),
    )[:CHANGE_LIMIT]
    if increases:
        lines = ["📈 Mayores alzas", ""]
        for saved in increases:
            lines.extend(_change_lines(saved))
        messages.append("\n".join(lines))

    new_items = _alphabetical([item for item in items if item.is_new])[:CHANGE_LIMIT]
    if new_items:
        lines = ["🆕 Productos nuevos", ""]
        for saved in new_items:
            lines.extend(_change_lines(saved))
        messages.append("\n".join(lines))

    selected = _alphabetical(items)[:REPORT_LIMIT]
    for start in range(0, len(selected), ITEMS_PER_MESSAGE):
        group = selected[start:start + ITEMS_PER_MESSAGE]
        lines = [
            f"🔤 Catálogo alfabético {start + 1}-{start + len(group)} "
            f"de {min(len(items), REPORT_LIMIT)}",
            "",
        ]
        for position, saved in enumerate(group, start=start + 1):
            item = saved.item
            lines += [f"{position}. {item.name}", f"Precio: {clp(item.current_price)}"]
            if _reported_discount(saved):
                lines.append(f"Descuento informado: {item.discount_pct:.0%}")
            if saved.price_changed and saved.previous_price is not None:
                movement = "bajó" if saved.price_dropped else "subió"
                lines.append(
                    f"Cambio real: {movement} desde {clp(saved.previous_price)} "
                    f"({abs(saved.price_change_pct):.1%})"
                )
            elif saved.is_new:
                lines.append("Estado: nuevo")
            else:
                lines.append("Estado: sin cambio")
            lines += [item.url, ""]
        messages.append("\n".join(lines).rstrip())

    return messages
