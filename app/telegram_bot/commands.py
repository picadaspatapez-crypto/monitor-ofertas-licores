from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class BotCommand:
    name: str
    query: str = ""
    value: int | None = None


def _parse_clp(value: str) -> int | None:
    clean = value.strip().replace("$", "").replace("CLP", "").replace("clp", "")
    digits = re.sub(r"\D", "", clean)
    if not digits:
        return None
    amount = int(digits)
    return amount if amount > 0 else None


def _parse_alert_tail(tail: str) -> tuple[str, int | None]:
    patterns = (
        r"\s+bajo\s+",
        r"\s+menor\s+a\s+",
        r"\s+hasta\s+",
        r"\s+<=\s+",
    )
    for pattern in patterns:
        parts = re.split(pattern, tail, maxsplit=1, flags=re.IGNORECASE)
        if len(parts) == 2:
            return parts[0].strip()[:120], _parse_clp(parts[1])
    return tail.strip()[:120], None




def _parse_watch_tail(tail: str) -> BotCommand:
    clean = " ".join((tail or "").split()).strip()
    if not clean:
        return BotCommand("watch_help")

    product_query, price = _parse_alert_tail(clean)
    if price is not None and product_query != clean[:120]:
        return BotCommand("watch_target", product_query, price)

    score_match = re.match(
        r"^(.*?)\s+score\s*(?:>=|=>|sobre|desde|minimo|mínimo)?\s*(\d{1,3})$",
        clean,
        flags=re.IGNORECASE,
    )
    if score_match:
        query = score_match.group(1).strip()[:120]
        score = int(score_match.group(2))
        if query and 0 <= score <= 100:
            return BotCommand("watch_score", query, score)
        return BotCommand("watch_help")

    cav_match = re.match(
        r"^(.*?)\s+cav(?:\s+ventaja)?\s+(.+)$",
        clean,
        flags=re.IGNORECASE,
    )
    if cav_match:
        query = cav_match.group(1).strip()[:120]
        advantage = _parse_clp(cav_match.group(2))
        if query and advantage:
            return BotCommand("watch_cav", query, advantage)
        return BotCommand("watch_help")

    min_match = re.match(
        r"^(.*?)\s+(?:nuevo\s+)?m[ií]nimo(?:\s+hist[oó]rico)?$",
        clean,
        flags=re.IGNORECASE,
    )
    if min_match:
        query = min_match.group(1).strip()[:120]
        if query:
            return BotCommand("watch_historical_min", query)

    return BotCommand("watch_help")


def parse_command(text: str | None) -> BotCommand:
    clean = " ".join((text or "").split()).strip()
    if not clean:
        return BotCommand("ignore")
    if not clean.startswith("/"):
        return BotCommand("search", clean[:120])

    head, _, tail = clean.partition(" ")
    command = head.split("@", 1)[0].casefold()
    query = tail.strip()[:120]

    if command in {"/start", "/ayuda", "/help"}:
        return BotCommand("help")
    if command == "/buscar":
        return BotCommand("search", query) if query else BotCommand("search_help")
    if command == "/estado":
        return BotCommand("status")
    if command in {"/quality", "/calidad"}:
        return BotCommand("quality")
    if command in {"/auditoria", "/consolidacion", "/consolidación", "/expansion", "/expansión"}:
        return BotCommand("expansion_audit")
    if command == "/mas":
        return BotCommand("search_more")
    if command == "/historial":
        return BotCommand("history", query) if query else BotCommand("history_help")
    if command == "/oportunidades":
        return BotCommand("opportunities")
    if command == "/mejores":
        return BotCommand("best_prices")
    if command in {"/radar", "/inteligencia"}:
        return BotCommand("commercial_radar")
    if command in {"/minimos", "/mínimos"}:
        return BotCommand("historical_floors")
    if command == "/personal":
        return BotCommand("personal_opportunities")
    if command == "/miprecio":
        return BotCommand("personal_search", query) if query else BotCommand("personal_opportunities")
    if command in {"/historialsocio", "/historialpersonal"}:
        return BotCommand("personal_history", query) if query else BotCommand("personal_history_help")
    if command in {"/vigilar", "/watch"}:
        return _parse_watch_tail(tail)
    if command in {"/watchlist", "/miswatchlists", "/vigilados"}:
        return BotCommand("watch_list")
    if command in {"/quitarwatch", "/eliminarwatch"}:
        try:
            watch_id = int(query)
        except (TypeError, ValueError):
            watch_id = 0
        return BotCommand("watch_delete", value=watch_id) if watch_id > 0 else BotCommand("watch_delete_help")
    if command in {"/favorito", "/agregarfavorito"}:
        return BotCommand("favorite_add", query) if query else BotCommand("favorite_help")
    if command in {"/misfavoritos", "/favoritos"}:
        return BotCommand("favorite_list")
    if command in {"/eliminarfavorito", "/quitarfavorito"}:
        try:
            favorite_id = int(query)
        except (TypeError, ValueError):
            favorite_id = 0
        return BotCommand("favorite_delete", value=favorite_id) if favorite_id > 0 else BotCommand("favorite_delete_help")
    if command == "/avisar":
        product_query, price = _parse_alert_tail(tail)
        if product_query and price:
            return BotCommand("favorite_target", product_query, price)
        return BotCommand("favorite_target_help")
    return BotCommand("unknown")
