import re
import sys
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Tag

BASE_URL = "https://licor3b.cl"
OFFERS_URL = f"{BASE_URL}/product-category/ofertas/"


@dataclass(frozen=True)
class ScrapedProduct:
    store: str
    name: str
    url: str
    current_price: int
    regular_price: Optional[int]
    discount_pct: float


def _all_prices(text: str) -> list[int]:
    values = []
    for raw in re.findall(r"\$\s*([\d.\s]+)", text or ""):
        digits = re.sub(r"[^\d]", "", raw)
        if digits:
            values.append(int(digits))
    return values


def _discount(regular: Optional[int], current: int) -> float:
    if not regular or regular <= current:
        return 0.0
    return (regular - current) / regular


def _clean_name(text: str) -> str:
    text = re.sub(r"^-\d+%\s*", "", text.strip())
    text = re.sub(r"\$\s*[\d.\s]+", "", text)
    return " ".join(text.split()).strip(" -|")


def _candidate_links(soup: BeautifulSoup) -> list[Tag]:
    selectors = [
        "a.woocommerce-LoopProduct-link",
        "a.woocommerce-loop-product__link",
        "li.product a[href]",
        ".product-small a[href]",
        ".product-item a[href]",
        ".product a[href]",
        "a[href*='/producto/']",
        "a[href*='/product/']",
    ]
    found = []
    seen = set()

    for selector in selectors:
        for node in soup.select(selector):
            marker = id(node)
            if marker not in seen:
                seen.add(marker)
                found.append(node)

    return found


def scrape() -> list[ScrapedProduct]:
    response = requests.get(
        OFFERS_URL,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0 Safari/537.36"
            ),
            "Accept-Language": "es-CL,es;q=0.9",
        },
        timeout=30,
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    links = _candidate_links(soup)
    products: dict[str, ScrapedProduct] = {}

    for link in links:
        href = (link.get("href") or "").strip()
        if not href:
            continue

        url = urljoin(BASE_URL, href)
        if url.rstrip("/") == OFFERS_URL.rstrip("/"):
            continue

        container = link
        for parent in link.parents:
            if not isinstance(parent, Tag):
                continue
            text = parent.get_text(" ", strip=True)
            if "$" in text and len(text) < 1200:
                container = parent
                break

        text = container.get_text(" ", strip=True)
        prices = _all_prices(text)
        if not prices:
            continue

        title_node = container.select_one(
            ".woocommerce-loop-product__title, "
            ".product-title, .name, h2, h3, h4"
        )
        name = _clean_name(
            title_node.get_text(" ", strip=True)
            if title_node
            else link.get_text(" ", strip=True)
        )

        if not name or name.upper() == "LLEVAR":
            previous = container.find_previous("a", href=True)
            if previous:
                name = _clean_name(previous.get_text(" ", strip=True))
                url = urljoin(BASE_URL, previous.get("href", ""))

        if not name or len(name) < 4:
            continue

        current_price = prices[-1]
        regular_price = (
            prices[-2]
            if len(prices) >= 2 and prices[-2] > current_price
            else None
        )

        if current_price < 500 or current_price > 1_000_000:
            continue

        products[url] = ScrapedProduct(
            store="Licor3B",
            name=name,
            url=url,
            current_price=current_price,
            regular_price=regular_price,
            discount_pct=_discount(regular_price, current_price),
        )

    if not products:
        preview = " ".join(response.text[:3000].split())
        history = " -> ".join(
            f"{item.status_code}:{item.url}" for item in response.history
        ) or "sin redirecciones"

        print("=== DIAGNÓSTICO LICOR3B ===", file=sys.stderr)
        print(f"URL solicitada: {OFFERS_URL}", file=sys.stderr)
        print(f"URL final: {response.url}", file=sys.stderr)
        print(f"HTTP: {response.status_code}", file=sys.stderr)
        print(
            f"Content-Type: {response.headers.get('Content-Type')}",
            file=sys.stderr,
        )
        print(f"Redirecciones: {history}", file=sys.stderr)
        print(f"HTML caracteres: {len(response.text)}", file=sys.stderr)
        print(f"Enlaces candidatos: {len(links)}", file=sys.stderr)
        print(f"Vista previa HTML: {preview}", file=sys.stderr)
        print("=== FIN DIAGNÓSTICO ===", file=sys.stderr)

        raise RuntimeError(
            "No se encontraron productos en Licor3B. "
            "Revisa el bloque DIAGNÓSTICO LICOR3B en los logs."
        )

    return list(products.values())
