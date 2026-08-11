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
    if command == "/mas":
        return BotCommand("search_more")
    if command == "/historial":
        return BotCommand("history", query) if query else BotCommand("history_help")
    if command == "/oportunidades":
        return BotCommand("opportunities")
    if command == "/mejores":
        return BotCommand("best_prices")
    if command in {"/personal", "/miprecio"}:
        return BotCommand("personal_opportunities")
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
