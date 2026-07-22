import json
import re
from dataclasses import dataclass
from typing import Any, Iterable, Optional
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup, Tag
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


BASE_URL = "https://licor3b.cl"
OFFERS_URL = f"{BASE_URL}/product-category/ofertas/"
STORE_API_URL = f"{BASE_URL}/wp-json/wc/store/v1"
TIMEOUT_SECONDS = 35

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "es-CL,es;q=0.9,en;q=0.7",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}


@dataclass(frozen=True)
class ScrapedProduct:
    store: str
    name: str
    url: str
    current_price: int
    regular_price: Optional[int]
    discount_pct: float


def _session() -> requests.Session:
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        status=3,
        backoff_factor=1.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        raise_on_status=False,
    )
    session = requests.Session()
    session.headers.update(HEADERS)
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.mount("http://", HTTPAdapter(max_retries=retry))
    return session


def _clean_url(raw_url: str) -> str:
    absolute = urljoin(BASE_URL, raw_url.strip())
    parsed = urlparse(absolute)
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc.lower(),
            parsed.path.rstrip("/") + "/",
            "",
            "",
            "",
        )
    )


def _all_prices(text: str) -> list[int]:
    values: list[int] = []
    for raw in re.findall(r"\$\s*([\d.\s]+)", text or ""):
        digits = re.sub(r"[^\d]", "", raw)
        if digits:
            value = int(digits)
            if 500 <= value <= 1_000_000:
                values.append(value)
    return values


def _to_int_price(value: Any, minor_unit: int = 0) -> Optional[int]:
    if value is None:
        return None

    digits = re.sub(r"[^\d]", "", str(value))
    if not digits:
        return None

    amount = int(digits)
    if minor_unit > 0:
        amount = round(amount / (10**minor_unit))

    return amount if 500 <= amount <= 1_000_000 else None


def _discount(regular: Optional[int], current: int) -> float:
    if not regular or regular <= current:
        return 0.0
    return (regular - current) / regular


def _clean_name(text: str) -> str:
    cleaned = re.sub(r"^-\d+(?:[.,]\d+)?%\s*", "", text.strip())
    cleaned = re.sub(r"\$\s*[\d.\s]+", "", cleaned)
    cleaned = re.sub(r"\bLLEVAR\b", "", cleaned, flags=re.IGNORECASE)
    return " ".join(cleaned.split()).strip(" -|")


def _valid_product_url(url: str) -> bool:
    lowered = url.lower()
    excluded = (
        "/cart",
        "/carrito",
        "/checkout",
        "/mi-cuenta",
        "/product-category/",
        "/categoria-producto/",
        "add-to-cart=",
    )
    if any(item in lowered for item in excluded):
        return False

    return (
        "/producto/" in lowered
        or "/product/" in lowered
        or "/tienda/" in lowered
    )


def _product_from_text(
    *,
    name: str,
    url: str,
    text: str,
) -> Optional[ScrapedProduct]:
    prices = _all_prices(text)
    cleaned_name = _clean_name(name)

    if not cleaned_name or len(cleaned_name) < 4 or not prices:
        return None

    current = prices[-1]
    regular = prices[-2] if len(prices) >= 2 and prices[-2] > current else None

    return ScrapedProduct(
        store="Licor3B",
        name=cleaned_name,
        url=_clean_url(url),
        current_price=current,
        regular_price=regular,
        discount_pct=_discount(regular, current),
    )


def _candidate_cards(soup: BeautifulSoup) -> Iterable[Tag]:
    selectors = (
        "li.product",
        ".products .product",
        ".product-small",
        ".product-item",
        ".wc-block-grid__product",
        "[data-product-id]",
        "article.product",
    )

    seen: set[int] = set()
    for selector in selectors:
        for node in soup.select(selector):
            marker = id(node)
            if marker not in seen:
                seen.add(marker)
                yield node


def _parse_html_cards(soup: BeautifulSoup) -> dict[str, ScrapedProduct]:
    products: dict[str, ScrapedProduct] = {}

    for card in _candidate_cards(soup):
        link = card.select_one(
            "a.woocommerce-LoopProduct-link[href], "
            "a.woocommerce-loop-product__link[href], "
            "a[href*='/producto/'], "
            "a[href*='/product/'], "
            "a[href*='/tienda/']"
        )
        if not link:
            continue

        href = str(link.get("href") or "").strip()
        if not href:
            continue

        url = _clean_url(href)
        if not _valid_product_url(url):
            continue

        title_node = card.select_one(
            ".woocommerce-loop-product__title, "
            ".product-title, "
            ".woocommerce-loop-product__title, "
            ".name, h2, h3, h4"
        )
        name = (
            title_node.get_text(" ", strip=True)
            if title_node
            else link.get_text(" ", strip=True)
        )

        parsed = _product_from_text(
            name=name,
            url=url,
            text=card.get_text(" ", strip=True),
        )
        if parsed:
            products[parsed.url] = parsed

    return products


def _parse_price_anchors(soup: BeautifulSoup) -> dict[str, ScrapedProduct]:
    """Respaldo para diseños donde cada producto completo está dentro de un enlace."""
    products: dict[str, ScrapedProduct] = {}

    for link in soup.select("a[href]"):
        href = str(link.get("href") or "").strip()
        if not href:
            continue

        url = _clean_url(href)
        if not _valid_product_url(url):
            continue

        link_text = link.get_text(" ", strip=True)
        if "$" not in link_text:
            continue

        parsed = _product_from_text(name=link_text, url=url, text=link_text)
        if parsed:
            products[parsed.url] = parsed

    return products


def _walk_json_ld(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_json_ld(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json_ld(child)


def _parse_json_ld(soup: BeautifulSoup) -> dict[str, ScrapedProduct]:
    products: dict[str, ScrapedProduct] = {}

    for script in soup.select("script[type='application/ld+json']"):
        raw = script.string or script.get_text()
        if not raw.strip():
            continue

        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue

        for item in _walk_json_ld(payload):
            item_type = item.get("@type")
            if isinstance(item_type, list):
                is_product = "Product" in item_type
            else:
                is_product = item_type == "Product"

            if not is_product:
                continue

            name = str(item.get("name") or "").strip()
            url = str(item.get("url") or "").strip()
            offers = item.get("offers")

            if isinstance(offers, list):
                offers = offers[0] if offers else None
            if not isinstance(offers, dict):
                continue

            current = _to_int_price(
                offers.get("price") or offers.get("lowPrice")
            )
            if not name or not url or current is None:
                continue

            parsed = ScrapedProduct(
                store="Licor3B",
                name=_clean_name(name),
                url=_clean_url(url),
                current_price=current,
                regular_price=None,
                discount_pct=0.0,
            )
            products[parsed.url] = parsed

    return products


def _category_is_offer(item: dict[str, Any]) -> bool:
    for category in item.get("categories") or []:
        if not isinstance(category, dict):
            continue
        slug = str(category.get("slug") or "").lower()
        name = str(category.get("name") or "").lower()
        if slug == "ofertas" or "oferta" in name:
            return True
    return False


def _parse_api_product(item: dict[str, Any]) -> Optional[ScrapedProduct]:
    name = _clean_name(str(item.get("name") or ""))
    url = str(item.get("permalink") or "").strip()
    prices = item.get("prices") or {}

    try:
        minor_unit = int(prices.get("currency_minor_unit") or 0)
    except (TypeError, ValueError):
        minor_unit = 0

    current = _to_int_price(
        prices.get("sale_price") or prices.get("price"),
        minor_unit,
    )
    regular = _to_int_price(prices.get("regular_price"), minor_unit)

    if not name or not url or current is None:
        return None
    if regular is not None and regular <= current:
        regular = None

    return ScrapedProduct(
        store="Licor3B",
        name=name,
        url=_clean_url(url),
        current_price=current,
        regular_price=regular,
        discount_pct=_discount(regular, current),
    )


def _scrape_store_api(session: requests.Session) -> dict[str, ScrapedProduct]:
    products: dict[str, ScrapedProduct] = {}
    page = 1

    while page <= 20:
        response = session.get(
            f"{STORE_API_URL}/products",
            params={"per_page": 100, "page": page},
            headers={"Accept": "application/json"},
            timeout=TIMEOUT_SECONDS,
        )

        if response.status_code in (400, 404):
            break
        response.raise_for_status()

        try:
            payload = response.json()
        except ValueError:
            break

        if not isinstance(payload, list) or not payload:
            break

        for item in payload:
            if not isinstance(item, dict) or not _category_is_offer(item):
                continue
            parsed = _parse_api_product(item)
            if parsed:
                products[parsed.url] = parsed

        total_pages_raw = response.headers.get("X-WP-TotalPages")
        if total_pages_raw:
            try:
                if page >= int(total_pages_raw):
                    break
            except ValueError:
                pass
        elif len(payload) < 100:
            break

        page += 1

    return products


def _looks_blocked(response: requests.Response) -> bool:
    sample = response.text[:8000].lower()
    markers = (
        "cf-chl-",
        "cloudflare",
        "just a moment",
        "captcha",
        "access denied",
        "checking your browser",
    )
    return any(marker in sample for marker in markers)


def scrape() -> list[ScrapedProduct]:
    session = _session()
    diagnostics: list[str] = []

    response = session.get(OFFERS_URL, timeout=TIMEOUT_SECONDS)
    diagnostics.append(
        f"html_http={response.status_code}, html_chars={len(response.text)}"
    )
    response.raise_for_status()

    blocked = _looks_blocked(response)
    diagnostics.append(f"blocked={blocked}")

    soup = BeautifulSoup(response.text, "html.parser")

    products = _parse_html_cards(soup)
    diagnostics.append(f"html_cards={len(products)}")

    if not products:
        products.update(_parse_price_anchors(soup))
    diagnostics.append(f"html_links_total={len(products)}")

    if not products:
        products.update(_parse_json_ld(soup))
    diagnostics.append(f"json_ld_total={len(products)}")

    if not products:
        try:
            api_products = _scrape_store_api(session)
            products.update(api_products)
            diagnostics.append(f"store_api={len(api_products)}")
        except requests.RequestException as exc:
            diagnostics.append(
                f"store_api_error={type(exc).__name__}:{str(exc)[:180]}"
            )

    if not products:
        raise RuntimeError(
            "No se encontraron productos en Licor3B después de probar "
            "HTML, enlaces, JSON-LD y WooCommerce Store API. "
            + "; ".join(diagnostics)
        )

    return sorted(products.values(), key=lambda product: product.name.casefold())
