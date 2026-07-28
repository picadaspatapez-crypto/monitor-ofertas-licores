from __future__ import annotations

import html
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.favorites.service import FavoriteResolution, FavoriteView
from app.search.engine import SearchResult
from app.search.formatting import format_clp, format_datetime_cl




@dataclass(frozen=True)
class StoreStatusView:
    name: str
    run_status: str
    health_status: str | None
    products_found: int
    finished_at: datetime | None

def _escape(value: object) -> str:
    return html.escape(str(value), quote=False)


def help_message(bot_username: str | None = None) -> str:
    mention = f"@{_escape(bot_username)}" if bot_username else "este bot"
    return (
        f"🍾 <b>Buscador de licores</b>\n\n"
        f"Escríbele directamente a {mention} el nombre de un producto o usa:\n"
        f"<code>/buscar johnnie black 750</code>\n\n"
        f"⭐ <b>Favoritos y avisos</b>\n"
        f"<code>/favorito johnnie black 750</code>\n"
        f"<code>/avisar johnnie black 750 bajo 25000</code>\n"
        f"<code>/misfavoritos</code>\n"
        f"<code>/eliminarfavorito 3</code>\n\n"
        f"Otros comandos: <code>/estado</code> y <code>/ayuda</code>.\n\n"
        f"El bot consulta PostgreSQL; no abre las tiendas en cada búsqueda."
    )


def search_help_message() -> str:
    return (
        "Escribe el producto después del comando.\n\n"
        "Ejemplo: <code>/buscar johnnie black 750</code>"
    )


def favorite_help_message() -> str:
    return (
        "⭐ Escribe el producto que quieres seguir.\n\n"
        "Ejemplo: <code>/favorito johnnie black 750</code>\n\n"
        "Te avisaré si baja, aparece en una tienda nueva, cambia la tienda más barata o vuelve a estar disponible."
    )


def favorite_target_help_message() -> str:
    return (
        "🎯 Indica un producto y el precio objetivo.\n\n"
        "Ejemplo: <code>/avisar johnnie black 750 bajo 25000</code>"
    )


def favorite_delete_help_message() -> str:
    return (
        "Usa el número mostrado por <code>/misfavoritos</code>.\n\n"
        "Ejemplo: <code>/eliminarfavorito 3</code>"
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
    favorites: int = 0,
    stores: tuple[StoreStatusView, ...] = (),
) -> str:
    latest = format_datetime_cl(latest_seen_at) if latest_seen_at else "sin datos"
    lines = [
        "📊 <b>Estado del catálogo</b>",
        "",
        f"Productos unificados: <b>{active_masters}</b>",
        f"Publicaciones vigentes: <b>{fresh_products}</b>",
        f"Tus favoritos activos: <b>{favorites}</b>",
        f"Última observación: <b>{_escape(latest)}</b>",
        f"Ventana de vigencia: <b>{max_age_hours} horas</b>",
    ]
    if stores:
        lines.extend(["", "🏪 <b>Última revisión por tienda</b>"])
        icons = {"HEALTHY": "🟢", "DEGRADED": "🟡", "BROKEN": "🔴"}
        for store in stores:
            health = store.health_status or store.run_status.upper()
            icon = icons.get(health, "🔴" if store.run_status == "failed" else "⚪")
            when = format_datetime_cl(store.finished_at) if store.finished_at else "sin ejecución"
            lines.append(
                f"{icon} <b>{_escape(store.name)}</b>: "
                f"{store.products_found} productos · {_escape(health)}"
            )
            lines.append(f"   {_escape(when)}")
    return "\n".join(lines)


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

        offer_buttons: list[dict[str, str]] = []
        for offer in result.offers[:4]:
            if offer.url.startswith(("https://", "http://")):
                label = f"{index} · {offer.store_name}"[:64]
                offer_buttons.append({"text": label, "url": offer.url})
        for start in range(0, len(offer_buttons), 2):
            keyboard.append(offer_buttons[start : start + 2])

    lines.extend(
        [
            "",
            "🕒 Precios de la última revisión disponible.",
            "Para seguir uno usa /favorito seguido del nombre completo.",
        ]
    )
    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3970].rstrip() + "\n…"
    markup = {"inline_keyboard": keyboard} if keyboard else None
    return text, markup


def _alternatives_lines(resolution: FavoriteResolution) -> list[str]:
    lines = ["Encontré varias opciones. Especifica mejor la variante o el volumen:", ""]
    for index, item in enumerate(resolution.alternatives, start=1):
        detail = f" · {item.volume_ml} ml" if item.volume_ml else ""
        lines.append(f"{index}. {_escape(item.canonical_name)}{detail}")
    return lines


def format_favorite_resolution_error(query: str, resolution: FavoriteResolution) -> str:
    if resolution.status == "not_found":
        return no_results_message(query)
    return "\n".join(_alternatives_lines(resolution))


def format_favorite_saved(
    *,
    result: SearchResult,
    favorite_id: int,
    created: bool,
    target_price: int | None,
) -> str:
    action = "guardado" if created else "actualizado"
    lines = [
        f"⭐ Favorito {action}",
        "",
        f"<b>{_escape(result.canonical_name)}</b>",
        f"ID: <code>{favorite_id}</code>",
        f"Precio actual: <b>{format_clp(result.winner.price)}</b> en {_escape(result.winner.store_name)}",
    ]
    if target_price is not None:
        lines.append(f"🎯 Objetivo: <b>{format_clp(target_price)}</b>")
        if result.winner.price <= target_price:
            lines.append("✅ El precio actual ya cumple tu objetivo.")
    lines.extend(
        [
            "",
            "Te avisaré por bajas, tienda nueva, cambio de ganador y reposición.",
        ]
    )
    return "\n".join(lines)


def format_favorites_list(views: list[FavoriteView]) -> str:
    if not views:
        return (
            "⭐ No tienes favoritos activos.\n\n"
            "Agrega uno con <code>/favorito nombre del producto</code>."
        )
    lines = ["⭐ <b>Mis favoritos</b>", ""]
    for view in views:
        details = []
        if view.volume_ml:
            details.append(f"{view.volume_ml} ml")
        if view.target_price is not None:
            details.append(f"objetivo {format_clp(view.target_price)}")
        suffix = f" · {' · '.join(details)}" if details else ""
        lines.append(f"<b>{view.favorite_id}.</b> {_escape(view.canonical_name)}{suffix}")
        if view.snapshot.winner is not None:
            lines.append(
                f"   🥇 {_escape(view.snapshot.winner.store_name)}: "
                f"<b>{format_clp(view.snapshot.winner.price)}</b>"
            )
        else:
            lines.append("   Sin disponibilidad reciente")
        lines.append("")
    lines.append("Eliminar: <code>/eliminarfavorito ID</code>")
    return "\n".join(lines)[:4000]


def format_favorite_deleted(favorite_id: int, deleted: bool) -> str:
    if deleted:
        return f"🗑️ Favorito <b>{favorite_id}</b> eliminado."
    return (
        f"No encontré un favorito activo con ID <b>{favorite_id}</b>.\n"
        "Consulta <code>/misfavoritos</code>."
    )
