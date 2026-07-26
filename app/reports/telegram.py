from __future__ import annotations

from app.analyzers import CatalogAnalysis
from app.domain import SavedProduct

REPORT_LIMIT = 20
ITEMS_PER_MESSAGE = 10


def clp(value: int) -> str:
    return "$" + f"{value:,}".replace(",", ".")


def _reported_discount(saved: SavedProduct) -> bool:
    return saved.item.regular_price is not None and saved.item.regular_price > saved.item.current_price and saved.item.discount_pct > 0


def _status(saved: SavedProduct) -> str:
    if saved.price_dropped:
        return "📉 Bajó de precio"
    if saved.is_new:
        return "🆕 Nuevo"
    return "Sin cambio"


def _rank(items: list[SavedProduct]) -> list[SavedProduct]:
    return sorted(items, key=lambda saved: (
        0 if _reported_discount(saved) else 1,
        -saved.item.discount_pct if _reported_discount(saved) else 0,
        0 if saved.price_dropped else 1,
        0 if saved.is_new else 1,
        saved.item.name.casefold(),
    ))


def build_telegram_messages(
    *, store_name: str, items: list[SavedProduct], analysis: CatalogAnalysis
) -> list[str]:
    selected = _rank(items)[:REPORT_LIMIT]
    summary = [
        f"📊 Monitor {store_name} actualizado", "",
        f"Productos revisados: {analysis.total}",
        f"Con descuento informado: {analysis.reported_discounts}",
        f"Bajaron de precio: {analysis.price_drops}",
        f"Productos nuevos: {analysis.new_products}",
        f"Productos mostrados: {len(selected)}", "",
        "ℹ️ Orden: descuento informado, bajas reales, nuevos y alfabético.",
    ]
    if not selected:
        return ["\n".join(summary + ["", "No fue posible obtener productos para mostrar."])]

    messages = ["\n".join(summary)]
    for start in range(0, len(selected), ITEMS_PER_MESSAGE):
        group = selected[start:start + ITEMS_PER_MESSAGE]
        lines = [f"🏷️ Productos destacados {start + 1}-{start + len(group)}", ""]
        for position, saved in enumerate(group, start=start + 1):
            item = saved.item
            lines += [f"{position}. {item.name}", f"Precio actual: {clp(item.current_price)}"]
            if _reported_discount(saved):
                saving = item.regular_price - item.current_price
                lines += [
                    f"Precio normal informado: {clp(item.regular_price)}",
                    f"Descuento informado: {item.discount_pct:.0%}",
                    f"Ahorro informado: {clp(saving)}",
                ]
            else:
                lines.append("Descuento informado: no disponible")
            lines += [f"Estado: {_status(saved)}", item.url, ""]
        messages.append("\n".join(lines).rstrip())
    return messages
