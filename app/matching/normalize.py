from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


_VOLUME_RE = re.compile(
    r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(ml|cc|cl|l|lt|lts|litro|litros)\b",
    re.IGNORECASE,
)

_STOP_WORDS = {
    "whisky",
    "whiskey",
    "vino",
    "ron",
    "gin",
    "vodka",
    "tequila",
    "licor",
    "espumante",
    "botella",
}


@dataclass(frozen=True)
class NormalizedProduct:
    source_name: str
    canonical_name: str
    normalized_key: str
    volume_ml: int | None


def _ascii_lower(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(char for char in normalized if not unicodedata.combining(char)).lower()


def extract_volume_ml(text: str) -> int | None:
    match = _VOLUME_RE.search(text)
    if match is None:
        return None

    raw_value = float(match.group(1).replace(",", "."))
    unit = match.group(2).lower()

    if unit in {"ml", "cc"}:
        multiplier = 1
    elif unit == "cl":
        multiplier = 10
    else:
        multiplier = 1000

    value = round(raw_value * multiplier)
    return value if 20 <= value <= 20_000 else None


def normalize_product_name(name: str) -> NormalizedProduct:
    lowered = _ascii_lower(name)
    volume_ml = extract_volume_ml(lowered)

    without_prices = re.sub(r"\$\s*[\d.]+", " ", lowered)
    without_discount = re.sub(r"-?\d+(?:[.,]\d+)?\s*%", " ", without_prices)
    without_volume = _VOLUME_RE.sub(" ", without_discount)
    words = re.findall(r"[a-z0-9]+", without_volume)

    meaningful_words = [word for word in words if word not in _STOP_WORDS]
    compact = " ".join(meaningful_words).strip()

    canonical_parts = [word.capitalize() for word in meaningful_words]
    canonical_name = " ".join(canonical_parts).strip() or name.strip()
    if volume_ml is not None:
        canonical_name = f"{canonical_name} {volume_ml} ml"

    key_parts = [compact]
    if volume_ml is not None:
        key_parts.append(str(volume_ml))

    normalized_key = "|".join(key_parts).strip("|")
    if not normalized_key:
        normalized_key = _ascii_lower(name).strip()

    return NormalizedProduct(
        source_name=name,
        canonical_name=canonical_name,
        normalized_key=normalized_key,
        volume_ml=volume_ml,
    )
