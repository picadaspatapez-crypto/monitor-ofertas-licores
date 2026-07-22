import re
from dataclasses import dataclass
from typing import Optional

import requests
from bs4 import BeautifulSoup


OFFERS_URL = "https://licor3b.cl/product-category/ofertas/"


@dataclass(frozen=True)
class ScrapedProduct:
    store: str
    name: str
    url: str
    current_price: int
    regular_price: Optional[int]
    discount_pct: float


def _parse_clp(text: str) -> Optional[int]:
    digits = re.sub(r"[^\d]", "", text or "")
    return int(digits) if digits else None


def _discount(regular: Optional[int], current: int) -> float:
    if not regular or regular <= current:
        return 0.0
    return (regular - current) / regular


def scrape() -> list[ScrapedProduct]:
    response = requests.get(
        OFFERS_URL,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/126 Safari/537.36"
            )
        },
        timeout=30,
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    results: list[ScrapedProduct] = []

    for card in soup.select("li.product"):
        title = card.select_one(
            "h2.woocommerce-loop-product__title, "
            ".woocommerce-loop-product__title, .product-title"
        )
        link = card.select_one("a.woocommerce-LoopProduct-link, a[href]")
        price = card.select_one(".price")

        if not title or not link or not price:
            continue

        name = " ".join(title.get_text(" ", strip=True).split())
        url = (link.get("href") or "").strip()

        regular_node = price.select_one("del .woocommerce-Price-amount, del")
        current_node = price.select_one("ins .woocommerce-Price-amount, ins")

        if current_node:
            current_price = _parse_clp(current_node.get_text(" ", strip=True))
        else:
            amounts = price.select(".woocommerce-Price-amount")
            text = amounts[-1].get_text(" ", strip=True) if amounts else price.get_text(" ", strip=True)
            current_price = _parse_clp(text)

        regular_price = (
            _parse_clp(regular_node.get_text(" ", strip=True))
            if regular_node
            else None
        )

        if not name or not url or current_price is None:
            continue

        results.append(
            ScrapedProduct(
                store="Licor3B",
                name=name,
                url=url,
                current_price=current_price,
                regular_price=regular_price,
                discount_pct=_discount(regular_price, current_price),
            )
        )

    if not results:
        raise RuntimeError("No se encontraron productos en Licor3B.")

    return results
