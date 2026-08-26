from __future__ import annotations

import re
from urllib.parse import unquote, urlparse


def clean_name(text: str) -> str:
    cleaned = re.sub(r"^-\d+(?:[.,]\d+)?%\s*", "", text.strip())
    cleaned = re.sub(r"\$\s*[\d.\s]+", "", cleaned)
    cleaned = re.sub(r"\bLLEVAR\b", "", cleaned, flags=re.IGNORECASE)
    return " ".join(cleaned.split()).strip(" -|")


def name_from_product_url(url: str) -> str:
    path = unquote(urlparse(url).path or "").strip("/")
    parts = [part for part in path.split("/") if part]
    if len(parts) < 2 or parts[-2].casefold() not in {"product", "producto", "tienda"}:
        return ""
    slug = parts[-1].strip().replace("_", "-")
    if not slug:
        return ""
    words = [word for word in slug.split("-") if word]
    if len(words) < 3:
        return ""
    text = " ".join(words)
    text = re.sub(r"\b(ml|cc|cl|lt|lts)\b", lambda m: m.group(1).lower(), text, flags=re.IGNORECASE)
    return " ".join(text.split()).strip()


def _title_tokens(text: str) -> list[str]:
    normalized = re.sub(r"[^a-z0-9]+", " ", text.casefold())
    return [token for token in normalized.split() if token]


def looks_like_contaminated_title(title: str, url_name: str) -> bool:
    title_tokens = _title_tokens(title)
    slug_tokens = _title_tokens(url_name)
    if len(slug_tokens) < 3 or len(title_tokens) <= len(slug_tokens):
        return False
    slug_set = set(slug_tokens)
    title_set = set(title_tokens)
    overlap = len(slug_set & title_set) / max(1, len(slug_set))
    extras = len(title_tokens) - len(slug_tokens)
    repeated_product_word = sum(
        token in {"vino", "vinos", "whisky", "pisco", "ron", "gin", "vodka", "tequila"}
        for token in title_tokens
    ) >= 2
    repeated_volume = len(
        re.findall(r"(?<!\d)\d+(?:[.,]\d+)?\s*(?:ml|cc|cl|l|lt|lts)\b", title, flags=re.IGNORECASE)
    ) >= 2
    leading_bundle_noise = bool(
        re.match(r"^\s*\d+\s+(?:vinos?|botellas?|un(?:idades?)?)\b", title, flags=re.IGNORECASE)
    )
    return overlap >= 0.72 and extras >= 3 and (repeated_product_word or repeated_volume or leading_bundle_noise)


def safe_product_name(raw_title: str, url: str) -> str:
    visible = clean_name(raw_title)
    url_name = clean_name(name_from_product_url(url))
    if url_name and looks_like_contaminated_title(visible, url_name):
        return url_name
    return visible or url_name
