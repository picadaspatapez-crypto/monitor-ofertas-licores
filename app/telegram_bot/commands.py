from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BotCommand:
    name: str
    query: str = ""


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
    return BotCommand("unknown")
