from __future__ import annotations

import html
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.favorites.service import FavoriteResolution, FavoriteView
from app.intelligence.queries import OpportunityView
from app.search.engine import SearchResult
from app.search.formatting import format_clp, format_datetime_cl




@dataclass(frozen=True)
class StoreStatusView:
    name: str
    run_status: str
    health_status: str | None
    products_found: int
    finished_at: datetime | None
    last_real_at: datetime | None = None
    next_due_at: datetime | None = None
    source: str | None = None

def _escape(value: object) -> str:
    return html.escape(str(value), quote=False)


def help_message(bot_username: str | None = None) -> str:
    mention = f"@{_escape(bot_username)}" if bot_username else "este bot"
    return (
        f"🍾 <b>Buscador de licores</b>\n\n"
        f"Escríbele directamente a {mention} el nombre de un producto o usa:\n"
        f"<code>/buscar johnnie black 750</code>\n"
        f"<code>/mas</code> para ver la página siguiente.\n\n"
        f"📊 <b>Comparación e historial</b>\n"
        f"<code>/historial johnnie black 750</code>\n"
        f"<code>/oportunidades</code>\n"
        f"<code>/mejores</code>\n\n"
        f"🟣 <b>Precios personales</b>\n"
        f"<code>/miprecio johnnie black 750</code>\n"
        f"<code>/personal</code>\n"
        f"<code>/historialsocio johnnie black 750</code>\n\n"
        f"⭐ <b>Favoritos y avisos</b>\n"
        f"<code>/favorito johnnie black 750</code>\n"
        f"<code>/avisar johnnie black 750 bajo 25000</code>\n"
        f"<code>/misfavoritos</code>\n"
        f"<code>/eliminarfavorito 3</code>\n\n"
        f"Estado de collectors: <code>/estado</code>.\n\n"
        f"El bot consulta PostgreSQL; no abre las tiendas en cada búsqueda."
    )


def search_help_message() -> str:
    return (
        "Escribe el producto después del comando.\n\n"
        "Ejemplo: <code>/buscar johnnie black 750</code>"
    )


def history_help_message() -> str:
    return (
        "📈 Escribe el producto después del comando.\n\n"
        "Ejemplo: <code>/historial johnnie black 750</code>"
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
            lines.append(f"   Último intento: {_escape(when)}")
            if store.last_real_at:
                lines.append(
                    f"   Última revisión real: {_escape(format_datetime_cl(store.last_real_at))}"
                )
            if store.next_due_at:
                lines.append(
                    f"   Próxima revisión: {_escape(format_datetime_cl(store.next_due_at))}"
                )
            if store.source:
                lines.append(f"   Fuente: {_escape(store.source)}")
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
        context = " · socio" if offer.price_type == "MEMBER" else (" · oferta" if result.price_mode == "personal" and offer.price_type == "SALE" else "")
        lines.append(
            f"{icon} {_escape(offer.store_name)}: <b>{format_clp(offer.price)}</b>{regular}{context}"
        )
    if result.price_mode == "personal" and result.personal_advantage_clp > 0:
        lines.append(
            f"🟣 Ventaja vs mercado público: <b>{format_clp(result.personal_advantage_clp)}</b> "
            f"({result.personal_advantage_pct * 100:.1f}%)"
        )
    if result.runner_up and result.saving_clp > 0:
        lines.append(
            f"💰 Ahorro: <b>{format_clp(result.saving_clp)}</b> "
            f"({result.saving_pct * 100:.1f}%)"
        )
    if result.opportunity_score is not None:
        lines.append(
            f"🔥 Oportunidad: <b>{result.opportunity_score:.0f}/100</b> "
            f"· {_escape(result.opportunity_classification or '')}"
        )
    if result.avg_90d and result.avg_90d > 0:
        difference = (result.winner.price - result.avg_90d) / result.avg_90d
        lines.append(
            f"📉 Frente al promedio 90 d: <b>{difference * 100:+.1f}%</b>"
        )
    return lines


def format_search_results(
    query: str,
    results: list[SearchResult],
    *,
    start_index: int = 1,
    has_more: bool = False,
) -> tuple[str, dict[str, Any] | None]:
    if not results:
        return no_results_message(query), None

    lines = [f"🔎 <b>Resultados para {_escape(query)}</b>", ""]
    keyboard: list[list[dict[str, str]]] = []

    for index, result in enumerate(results, start=start_index):
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
            ("Hay más resultados: usa <code>/mas</code>." if has_more else "Fin de los resultados disponibles."),
            "Para seguir uno usa /favorito seguido del nombre completo.",
        ]
    )
    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3970].rstrip() + "\n…"
    markup = {"inline_keyboard": keyboard} if keyboard else None
    return text, markup


def format_history_result(query: str, result: SearchResult | None) -> str:
    if result is None:
        return no_results_message(query)
    lines = [
        "📈 <b>Historial de precio</b>",
        "",
        f"<b>{_escape(result.canonical_name)}</b>",
        f"Precio actual: <b>{format_clp(result.winner.price)}</b> en {_escape(result.winner.store_name)}",
    ]
    if result.min_30d is not None:
        lines.append(f"Mínimo 30 días: <b>{format_clp(result.min_30d)}</b>")
    if result.avg_30d is not None:
        lines.append(f"Promedio 30 días: <b>{format_clp(round(result.avg_30d))}</b>")
    if result.min_90d is not None:
        lines.append(f"Mínimo 90 días: <b>{format_clp(result.min_90d)}</b>")
    if result.avg_90d is not None:
        lines.append(f"Promedio 90 días: <b>{format_clp(round(result.avg_90d))}</b>")
        difference = (result.winner.price - result.avg_90d) / result.avg_90d
        lines.append(f"Precio actual frente al promedio: <b>{difference * 100:+.1f}%</b>")
    if result.historical_min is not None:
        lines.append(f"Mínimo histórico: <b>{format_clp(result.historical_min)}</b>")
    lines.append(f"Días observados al precio actual: <b>{result.days_at_current_price}</b>")
    if result.opportunity_score is not None:
        lines.append(
            f"🔥 Opportunity Score: <b>{result.opportunity_score:.0f}/100</b> "
            f"· {_escape(result.opportunity_classification or '')}"
        )
    return "\n".join(lines)


def format_opportunities(
    views: list[OpportunityView], *, title: str = "Oportunidades"
) -> tuple[str, dict[str, Any] | None]:
    if not views:
        return "No hay oportunidades verificadas disponibles en este momento.", None
    lines = [f"🔥 <b>{_escape(title)}</b>", ""]
    keyboard: list[list[dict[str, str]]] = []
    for index, view in enumerate(views, start=1):
        if index > 1:
            lines.append("")
        lines.extend(
            [
                f"<b>{index}. {_escape(view.canonical_name)}</b>",
                f"Score: <b>{view.score:.0f}/100</b> · {_escape(view.classification)}",
                f"🥇 {_escape(view.winner_store)}: <b>{format_clp(view.winner_price)}</b>",
                f"Ahorro: <b>{format_clp(view.saving_clp)}</b> ({view.saving_pct * 100:.1f}%)",
                f"Confianza: {view.confidence * 100:.0f}%",
            ]
        )
        if view.avg_90d:
            difference = (view.winner_price - view.avg_90d) / view.avg_90d
            lines.append(f"Vs. promedio 90 d: {difference * 100:+.1f}%")
        if view.url.startswith(("http://", "https://")):
            keyboard.append([{"text": f"{index} · Ver oferta"[:64], "url": view.url}])
    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3970].rstrip() + "\n…"
    return text, ({"inline_keyboard": keyboard} if keyboard else None)


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


def personal_history_help_message() -> str:
    return (
        "🟣 Escribe el producto después del comando.\n\n"
        "Ejemplo: <code>/historialsocio johnnie black 750</code>"
    )


def format_personal_history_result(query: str, result: SearchResult | None) -> str:
    if result is None:
        return no_results_message(query)
    context = "socio" if result.winner.price_type == "MEMBER" else result.winner.price_type.casefold()
    lines = [
        "🟣 <b>Historial de precio personal</b>",
        "",
        f"<b>{_escape(result.canonical_name)}</b>",
        f"Mejor para ti: <b>{format_clp(result.winner.price)}</b> · {_escape(result.winner.store_name)} ({_escape(context)})",
    ]
    if result.public_reference_price:
        lines.append(f"Mejor precio público: <b>{format_clp(result.public_reference_price)}</b>")
    if result.personal_advantage_clp > 0:
        lines.append(f"Ventaja de membresía: <b>{format_clp(result.personal_advantage_clp)}</b> ({result.personal_advantage_pct:.1%})")
    if result.min_30d:
        lines.append(f"Mínimo del contexto 30 d: <b>{format_clp(result.min_30d)}</b>")
    if result.avg_30d:
        lines.append(f"Promedio del contexto 30 d: <b>{format_clp(round(result.avg_30d))}</b>")
    if result.min_90d:
        lines.append(f"Mínimo del contexto 90 d: <b>{format_clp(result.min_90d)}</b>")
    if result.avg_90d:
        lines.append(f"Promedio del contexto 90 d: <b>{format_clp(round(result.avg_90d))}</b>")
    if result.historical_min:
        lines.append(f"Mínimo histórico del contexto: <b>{format_clp(result.historical_min)}</b>")
    lines.extend(["", result.winner.url])
    return "\n".join(lines)
