from __future__ import annotations

import re

_ABV_RE = re.compile(r"(?<!\d)(\d{1,2}(?:[.,]\d+)?)\s*(?:%\s*(?:alc\.?|vol\.?)?|°|grados?)(?!\d)", re.IGNORECASE)
_VINTAGE_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")


def extract_abv_pct(text: str) -> float | None:
    match = _ABV_RE.search(text or "")
    if match is None:
        return None
    value = float(match.group(1).replace(",", "."))
    return value if 0.0 <= value <= 96.0 else None


def extract_vintage_year(text: str) -> int | None:
    years = [int(value) for value in _VINTAGE_RE.findall(text or "")]
    plausible = [year for year in years if 1900 <= year <= 2035]
    return max(plausible) if plausible else None
