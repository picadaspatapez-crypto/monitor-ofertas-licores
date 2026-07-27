from __future__ import annotations

from app.analyzers import CatalogAnalysis
from app.domain import SavedProduct

REPORT_LIMIT = 30
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


def _reported_saving(saved: SavedProduct) -> int:
    if not _reported_discount(saved) or saved.item.regular_price is None:
        return 0
    return saved.item.regular_price - saved.item.current_price


def _real_drop_pct(saved: SavedProduct) -> float:
    return abs(saved.price_change_pct) if saved.price_dropped else 0.0


def _real_saving(saved: SavedProduct) -> int:
    if not saved.price_dropped or saved.previous_price is None:
        return 0
    return saved.previous_price - saved.item.current_price


def _effective_discount_pct(saved: SavedProduct) -> float:
    """Mejor señal porcentual disponible, sin filtrar por precio actual."""
    reported = saved.item.discount_pct if _reported_discount(saved) else 0.0
    return max(_real_drop_pct(saved), reported)


def _ranked_best_prices(items: list[SavedProduct]) -> list[SavedProduct]:
    """Ordena oportunidades sin imponer un precio máximo.

    Prioridades:
    1. Productos con una señal verificable: baja histórica o descuento informado.
    2. Mayor porcentaje efectivo entre ambas señales.
    3. En empate, una baja histórica real precede al descuento solamente informado.
    4. Mayor ahorro absoluto en CLP.
    5. Menor precio actual y nombre, solo como desempate final.
    """
    return sorted(
        items,
        key=lambda saved: (
            0 if (saved.price_dropped or _reported_discount(saved)) else 1,
            -_effective_discount_pct(saved),
            0 if saved.price_dropped else 1,
            -max(_real_saving(saved), _reported_saving(saved)),
            saved.item.current_price,
            saved.item.name.casefold(),
        ),
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


def _ranking_reason(saved: SavedProduct) -> str:
    real_pct = _real_drop_pct(saved)
    reported_pct = saved.item.discount_pct if _reported_discount(saved) else 0.0
    if real_pct > 0 and real_pct >= reported_pct:
        return "baja histórica real"
    if reported_pct > 0:
        return "descuento informado por la tienda"
    if saved.is_new:
        return "producto nuevo; ordenado por precio actual"
    return "precio actual; sin descuento verificable"


def build_telegram_messages(
    *, store_name: str, items: list[SavedProduct], analysis: CatalogAnalysis
) -> list[str]:
    stats = analysis.collection_stats
    health_icon = {"HEALTHY": "🟢", "DEGRADED": "🟡", "BROKEN": "🔴"}.get(
        stats.health_status, "⚪"
    )
    selected = _ranked_best_prices(items)[:REPORT_LIMIT]
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
        f"🏆 Productos destacados: {len(selected)}",
        "",
        "Ranking: mayor baja histórica o descuento informado; luego mayor ahorro.",
        "No se aplica un precio máximo: los productos caros también pueden entrar.",
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

    for start in range(0, len(selected), ITEMS_PER_MESSAGE):
        group = selected[start:start + ITEMS_PER_MESSAGE]
        lines = [
            f"🏆 Mejores precios {start + 1}-{start + len(group)} "
            f"de {len(selected)} · {store_name}",
            "",
        ]
        for position, saved in enumerate(group, start=start + 1):
            item = saved.item
            lines += [f"{position}. {item.name}", f"Precio actual: {clp(item.current_price)}"]

            if saved.price_dropped and saved.previous_price is not None:
                lines.append(
                    f"Baja real: {clp(saved.previous_price)} → {clp(item.current_price)} "
                    f"(▼ {_real_drop_pct(saved):.1%})"
                )
                lines.append(f"Ahorro real: {clp(_real_saving(saved))}")

            if _reported_discount(saved) and item.regular_price is not None:
                lines.append(f"Precio normal informado: {clp(item.regular_price)}")
                lines.append(f"Descuento informado: {item.discount_pct:.0%}")
                lines.append(f"Ahorro informado: {clp(_reported_saving(saved))}")

            lines += [f"Motivo del ranking: {_ranking_reason(saved)}", item.url, ""]
        messages.append("\n".join(lines).rstrip())

    return messages
