import re
import sys
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup, Tag
from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)


BASE_URL = "https://licor3b.cl"
OFFERS_URL = f"{BASE_URL}/product-category/ofertas/"
NAVIGATION_TIMEOUT_MS = 60_000
RENDER_WAIT_MS = 8_000


@dataclass(frozen=True)
class ScrapedProduct:
    store: str
    name: str
    url: str
    current_price: int
    regular_price: Optional[int]
    discount_pct: float


def _clean_url(raw_url: str) -> str:
    absolute = urljoin(BASE_URL, raw_url.strip())
    parsed = urlparse(absolute)
    path = parsed.path.rstrip("/") + "/"
    return urlunparse(
        (
            parsed.scheme or "https",
            parsed.netloc.lower(),
            path,
            "",
            "",
            "",
        )
    )


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
    if any(value in lowered for value in excluded):
        return False

    return (
        "/producto/" in lowered
        or "/product/" in lowered
        or "/tienda/" in lowered
    )


def _all_prices(text: str) -> list[int]:
    values: list[int] = []

    for raw in re.findall(r"\$\s*([\d.\s]+)", text or ""):
        digits = re.sub(r"[^\d]", "", raw)
        if not digits:
            continue

        value = int(digits)
        if 500 <= value <= 1_000_000:
            values.append(value)

    return values


def _discount(regular: Optional[int], current: int) -> float:
    if regular is None or regular <= current:
        return 0.0
    return (regular - current) / regular


def _clean_name(text: str) -> str:
    cleaned = re.sub(r"^-\d+(?:[.,]\d+)?%\s*", "", text.strip())
    cleaned = re.sub(r"\$\s*[\d.\s]+", "", cleaned)
    cleaned = re.sub(r"\bLLEVAR\b", "", cleaned, flags=re.IGNORECASE)
    return " ".join(cleaned.split()).strip(" -|")


def _candidate_cards(soup: BeautifulSoup) -> list[Tag]:
    selectors = (
        "li.product",
        ".products .product",
        ".product-small",
        ".product-item",
        ".wc-block-grid__product",
        "[data-product-id]",
        "article.product",
    )

    found: list[Tag] = []
    seen: set[int] = set()

    for selector in selectors:
        for node in soup.select(selector):
            marker = id(node)
            if marker in seen:
                continue
            seen.add(marker)
            found.append(node)

    return found


def _parse_card(card: Tag) -> Optional[ScrapedProduct]:
    link = card.select_one(
        "a.woocommerce-LoopProduct-link[href], "
        "a.woocommerce-loop-product__link[href], "
        "a[href*='/producto/'], "
        "a[href*='/product/'], "
        "a[href*='/tienda/']"
    )
    if link is None:
        return None

    href = str(link.get("href") or "").strip()
    if not href:
        return None

    url = _clean_url(href)
    if not _valid_product_url(url):
        return None

    title_node = card.select_one(
        ".woocommerce-loop-product__title, "
        ".product-title, "
        ".name, h2, h3, h4"
    )
    name = _clean_name(
        title_node.get_text(" ", strip=True)
        if title_node is not None
        else link.get_text(" ", strip=True)
    )

    prices = _all_prices(card.get_text(" ", strip=True))
    if not name or len(name) < 4 or not prices:
        return None

    current = prices[-1]
    regular = prices[-2] if len(prices) >= 2 and prices[-2] > current else None

    return ScrapedProduct(
        store="Licor3B",
        name=name,
        url=url,
        current_price=current,
        regular_price=regular,
        discount_pct=_discount(regular, current),
    )


def _parse_html(html: str) -> tuple[dict[str, ScrapedProduct], int]:
    soup = BeautifulSoup(html, "html.parser")
    cards = _candidate_cards(soup)
    products: dict[str, ScrapedProduct] = {}

    for card in cards:
        product = _parse_card(card)
        if product is not None:
            products[product.url] = product

    # Respaldo para diseños donde el enlace contiene nombre y precio.
    if not products:
        for link in soup.select("a[href]"):
            href = str(link.get("href") or "").strip()
            if not href:
                continue

            url = _clean_url(href)
            text = link.get_text(" ", strip=True)
            if not _valid_product_url(url) or "$" not in text:
                continue

            prices = _all_prices(text)
            name = _clean_name(text)
            if not prices or len(name) < 4:
                continue

            current = prices[-1]
            regular = (
                prices[-2]
                if len(prices) >= 2 and prices[-2] > current
                else None
            )
            products[url] = ScrapedProduct(
                store="Licor3B",
                name=name,
                url=url,
                current_price=current,
                regular_price=regular,
                discount_pct=_discount(regular, current),
            )

    return products, len(cards)


def _create_context(browser: Browser) -> BrowserContext:
    return browser.new_context(
        locale="es-CL",
        timezone_id="America/Santiago",
        viewport={"width": 1365, "height": 900},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36"
        ),
        extra_http_headers={
            "Accept-Language": "es-CL,es;q=0.9,en;q=0.7",
        },
    )


def _load_page(page: Page) -> tuple[str, Optional[int]]:
    response = page.goto(
        OFFERS_URL,
        wait_until="domcontentloaded",
        timeout=NAVIGATION_TIMEOUT_MS,
    )

    status = response.status if response is not None else None

    # La respuesta HTTP 202 usa una página intermedia con meta refresh.
    # Chromium procesa esa navegación; esperamos a que se estabilice.
    try:
        page.wait_for_load_state(
            "networkidle",
            timeout=20_000,
        )
    except PlaywrightTimeoutError:
        pass

    page.wait_for_timeout(RENDER_WAIT_MS)

    # Damos tiempo adicional si aún estamos en la página mínima de verificación.
    for _ in range(4):
        html = page.content()
        if len(html) > 5_000:
            return html, status
        page.wait_for_timeout(3_000)

    return page.content(), status


def scrape() -> list[ScrapedProduct]:
    diagnostics: list[str] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )

        try:
            context = _create_context(browser)
            page = context.new_page()

            html, initial_status = _load_page(page)
            final_url = page.url
            title = page.title()

            products, card_count = _parse_html(html)

            diagnostics.extend(
                [
                    f"initial_http={initial_status}",
                    f"final_url={final_url}",
                    f"title={title!r}",
                    f"html_chars={len(html)}",
                    f"cards={card_count}",
                    f"products={len(products)}",
                ]
            )

            if not products:
                preview = " ".join(
                    BeautifulSoup(html[:5_000], "html.parser")
                    .get_text(" ", strip=True)
                    .split()
                )

                print("=== DIAGNÓSTICO PLAYWRIGHT LICOR3B ===", file=sys.stderr)
                for diagnostic in diagnostics:
                    print(diagnostic, file=sys.stderr)
                print(f"html_preview={preview[:1_500]}", file=sys.stderr)
                print("=== FIN DIAGNÓSTICO ===", file=sys.stderr)

                raise RuntimeError(
                    "Playwright abrió Licor3B, pero no encontró productos. "
                    "Revisa el bloque DIAGNÓSTICO PLAYWRIGHT LICOR3B."
                )

            return sorted(
                products.values(),
                key=lambda product: product.name.casefold(),
            )
        finally:
            browser.close()
