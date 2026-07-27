from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from app.matching import build_product_signature


_PHRASE_ALIASES = {
    "etiqueta negra": "black label",
    "etiqueta roja": "red label",
    "etiqueta azul": "blue label",
    "etiqueta dorada": "gold label",
    "etiqueta oro": "gold label",
    "etiqueta verde": "green label",
    "johnny walker": "johnnie walker",
    "jhonnie walker": "johnnie walker",
    "johnie walker": "johnnie walker",
    "jack daniel s": "jack daniels",
    "jack daniel": "jack daniels",
    "jw": "johnnie walker",
    "j w": "johnnie walker",
}

_STOP_WORDS = {
    "comprar",
    "precio",
    "precios",
    "oferta",
    "ofertas",
    "barato",
    "barata",
    "botella",
    "unidad",
    "unidades",
    "formato",
    "contenido",
}


@dataclass(frozen=True)
class SearchQuery:
    source: str
    normalized: str
    tokens: tuple[str, ...]
    volume_ml: int | None
    package_quantity: int | None
    brand: str | None


def ascii_fold(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text or "")
    plain = "".join(char for char in normalized if not unicodedata.combining(char))
    return plain.casefold()


def normalize_search_text(text: str) -> str:
    normalized = f" {ascii_fold(text)} "
    normalized = normalized.replace("&", " and ").replace("'", " ").replace("’", " ")
    for source, target in _PHRASE_ALIASES.items():
        normalized = re.sub(rf"\b{re.escape(source)}\b", target, normalized)
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    tokens = [token for token in normalized.split() if token not in _STOP_WORDS]
    return " ".join(tokens)


def parse_search_query(query: str) -> SearchQuery:
    source = (query or "").strip()
    normalized = normalize_search_text(source)
    signature = build_product_signature(source)
    volume_ml = signature.volume_ml
    if volume_ml is None:
        # En búsquedas coloquiales es común escribir “black 750” sin “ml”.
        naked_numbers = [
            int(value)
            for value in re.findall(r"(?<!\d)(\d{2,4})(?!\d)", normalized)
            if 50 <= int(value) <= 5000
        ]
        if naked_numbers:
            volume_ml = naked_numbers[-1]
    tokens = tuple(dict.fromkeys(normalized.split()))
    return SearchQuery(
        source=source,
        normalized=normalized,
        tokens=tokens,
        volume_ml=volume_ml,
        package_quantity=signature.pack_count,
        brand=signature.brand,
    )


def unique_aliases(values: list[str], *, limit: int = 25) -> list[str]:
    seen: set[str] = set()
    aliases: list[str] = []
    for value in values:
        clean = " ".join((value or "").split()).strip()
        key = normalize_search_text(clean)
        if not clean or not key or key in seen:
            continue
        seen.add(key)
        aliases.append(clean)
        if len(aliases) >= limit:
            break
    return aliases
