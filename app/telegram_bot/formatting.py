from __future__ import annotations

import html
from datetime import datetime
from typing import Any

from app.search.engine import SearchResult
from app.search.formatting import format_clp, format_datetime_cl


def _escape(value: object) -> str:
    return html.escape(str(value), quote=False)


def help_message(bot_username: str | None = None) -> str:
    mention = f"@{_escape(bot_username)}" if bot_username else "este bot"
    return (
        f"🍾 <b>Buscador de licores</b>\n\n"
        f"Escríbele directamente a {mention} el nombre de un producto o usa:\n"
        f"<code>/buscar johnnie black 750</code>\n\n"
        f"También puedes probar:\n"
        f"• <code>jack honey</code>\n"
        f"• <code>mistral 35 1 litro</code>\n"
        f"• <code>etiqueta negra 750</code>\n\n"
        f"El bot consulta la última revisión guardada en PostgreSQL; no abre las tiendas en cada búsqueda."
    )


def search_help_message() -> str:
    return (
        "Escribe el producto después del comando.\n\n"
        "Ejemplo: <code>/buscar johnnie black 750</code>"
    )


def no_results_message(query: str) -> str:
    return (
        f"🔎 No encontré coincidencias para <b>{_escape(query)}</b>.\n\n"
        "Prueba con menos palabras, revisa la marca o elimina el volumen."
    )


def unauthorized_message() -> str:
    return "🔒 Este bot es privado y este chat no está autorizado."


def status_message(
    *,
    active_masters: int,
    fresh_products: int,
    latest_seen_at: datetime | None,
    max_age_hours: int,
) -> str:
    latest = format_datetime_cl(latest_seen_at) if latest_seen_at else "sin datos"
    return (
        "📊 <b>Estado del catálogo</b>\n\n"
        f"Productos unificados: <b>{active_masters}</b>\n"
        f"Publicaciones vigentes: <b>{fresh_products}</b>\n"
        f"Última observación: <b>{_escape(latest)}</b>\n"
        f"Ventana de vigencia: <b>{max_age_hours} horas</b>"
    )


def _result_lines(index: int, result: SearchResult) -> list[str]:
    details: list[str] = []
    if result.volume_ml:
        details.append(f"{result.volume_ml} ml")
    if result.package_quantity > 1:
        details.append(f"pack {result.package_quantity}")
    details.append(f"coincidencia {result.score * 100:.0f}%")

    lines = [
        f"<b>{index}. {_escape(result.canonical_name)}</b>",
        f"🎯 {' · '.join(details)}",
    ]
    for offer_index, offer in enumerate(result.offers):
        icon = "🥇" if offer_index == 0 else "•"
        regular = ""
        if offer.regular_price and offer.regular_price > offer.price:
            regular = f" <s>{format_clp(offer.regular_price)}</s>"
        lines.append(
            f"{icon} {_escape(offer.store_name)}: <b>{format_clp(offer.price)}</b>{regular}"
        )
    if result.runner_up and result.saving_clp > 0:
        lines.append(
            f"💰 Ahorro: <b>{format_clp(result.saving_clp)}</b> "
            f"({result.saving_pct * 100:.1f}%)"
        )
    return lines


def format_search_results(
    query: str,
    results: list[SearchResult],
) -> tuple[str, dict[str, Any] | None]:
    if not results:
        return no_results_message(query), None

    lines = [f"🔎 <b>Resultados para {_escape(query)}</b>", ""]
    keyboard: list[list[dict[str, str]]] = []

    for index, result in enumerate(results, start=1):
        if index > 1:
            lines.append("")
        lines.extend(_result_lines(index, result))

        row: list[dict[str, str]] = []
        for offer in result.offers[:2]:
            if offer.url.startswith(("https://", "http://")):
                label = f"{index} · {offer.store_name}"[:64]
                row.append({"text": label, "url": offer.url})
        if row:
            keyboard.append(row)

    lines.extend(
        [
            "",
            "🕒 Precios de la última revisión disponible.",
            "Refina la búsqueda indicando marca, variante o volumen si aparecen varias opciones.",
        ]
    )
    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3970].rstrip() + "\n…"
    markup = {"inline_keyboard": keyboard} if keyboard else None
    return text, markup
