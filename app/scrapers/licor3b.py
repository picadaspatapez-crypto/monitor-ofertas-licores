import re
import sys
from dataclasses import dataclass
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

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
PAGE_SETTLE_MS = 4_000
MAX_PAGES = 50
MAX_SCROLL_ROUNDS = 12


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


def _normalize_page_url(raw_url: str) -> str:
    absolute = urljoin(BASE_URL, raw_url.strip())
    parsed = urlparse(absolute)

    if parsed.netloc.lower() != urlparse(BASE_URL).netloc.lower():
        return ""

    path = parsed.path.rstrip("/") + "/"
    query_items = parse_qsl(parsed.query, keep_blank_values=True)

    # Evita URLs híbridas como /page/3/?product-page=4.
    if re.search(r"/page/\d+/$", path):
        query_items = [
            (key, value)
            for key, value in query_items
            if key.lower() not in {"product-page", "product_page", "paged"}
        ]

    query = urlencode(query_items)

    return urlunparse(
        (
            parsed.scheme or "https",
            parsed.netloc.lower(),
            path,
            "",
            query,
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


def _wait_for_real_page(page: Page) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=20_000)
    except PlaywrightTimeoutError:
        pass

    page.wait_for_timeout(PAGE_SETTLE_MS)

    for _ in range(5):
        if len(page.content()) > 5_000:
            return
        page.wait_for_timeout(3_000)


def _scroll_until_stable(page: Page) -> None:
    previous_height = 0
    stable_rounds = 0

    for _ in range(MAX_SCROLL_ROUNDS):
        current_height = page.evaluate("document.body.scrollHeight")
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(1_200)
        new_height = page.evaluate("document.body.scrollHeight")

        if new_height == current_height == previous_height:
            stable_rounds += 1
        else:
            stable_rounds = 0

        previous_height = new_height

        if stable_rounds >= 2:
            break


def _next_page_url(html: str, current_url: str) -> str:
    soup = BeautifulSoup(html, "html.parser")

    selectors = (
        "link[rel='next'][href]",
        "a.next.page-numbers[href]",
        "a.next[href]",
        ".woocommerce-pagination a.next[href]",
        "nav.pagination a.next[href]",
    )

    for selector in selectors:
        node = soup.select_one(selector)
        if node is None:
            continue

        href = str(node.get("href") or "").strip()
        if not href:
            continue

        normalized = _normalize_page_url(href)
        if not normalized or normalized == current_url:
            continue

        lowered = normalized.lower()
        if (
            "/product-category/ofertas/" in lowered
            or "/categoria-producto/ofertas/" in lowered
        ):
            return normalized

    return ""


def _diagnose_failure(
    *,
    page: Page,
    html: str,
    pages_visited: int,
    cards_seen: int,
) -> None:
    preview = " ".join(
        BeautifulSoup(html[:5_000], "html.parser")
        .get_text(" ", strip=True)
        .split()
    )

    print("=== DIAGNÓSTICO PLAYWRIGHT LICOR3B ===", file=sys.stderr)
    print(f"final_url={page.url}", file=sys.stderr)
    print(f"title={page.title()!r}", file=sys.stderr)
    print(f"html_chars={len(html)}", file=sys.stderr)
    print(f"pages_visited={pages_visited}", file=sys.stderr)
    print(f"cards_seen={cards_seen}", file=sys.stderr)
    print(f"html_preview={preview[:1_500]}", file=sys.stderr)
    print("=== FIN DIAGNÓSTICO ===", file=sys.stderr)


def scrape() -> list[ScrapedProduct]:
    all_products: dict[str, ScrapedProduct] = {}
    visited: set[str] = set()
    current_url = _normalize_page_url(OFFERS_URL)

    pages_visited = 0
    cards_seen = 0
    last_html = ""

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

            while current_url and pages_visited < MAX_PAGES:
                if current_url in visited:
                    print(
                        f"Licor3B: se detuvo por URL repetida: {current_url}",
                        flush=True,
                    )
                    break

                visited.add(current_url)

                response = page.goto(
                    current_url,
                    wait_until="domcontentloaded",
                    timeout=NAVIGATION_TIMEOUT_MS,
                )

                _wait_for_real_page(page)
                _scroll_until_stable(page)

                last_html = page.content()
                page_products, page_cards = _parse_html(last_html)

                pages_visited += 1
                cards_seen += page_cards

                before = len(all_products)
                all_products.update(page_products)
                new_unique = len(all_products) - before

                status = response.status if response is not None else None
                final_page_url = _normalize_page_url(page.url)

                print(
                    "Licor3B página "
                    f"{pages_visited}: HTTP={status}, "
                    f"tarjetas={page_cards}, "
                    f"productos_página={len(page_products)}, "
                    f"nuevos_únicos={new_unique}, "
                    f"productos_únicos={len(all_products)}, "
                    f"url={final_page_url}",
                    flush=True,
                )

                next_url = _next_page_url(last_html, final_page_url)

                # Protección contra paginación defectuosa:
                # si una página no aporta nada nuevo, no seguimos indefinidamente.
                if pages_visited > 1 and new_unique == 0:
                    print(
                        "Licor3B: página sin productos nuevos; "
                        "se detiene la paginación.",
                        flush=True,
                    )
                    break

                current_url = next_url

            if not all_products:
                _diagnose_failure(
                    page=page,
                    html=last_html,
                    pages_visited=pages_visited,
                    cards_seen=cards_seen,
                )
                raise RuntimeError(
                    "Playwright abrió Licor3B, pero no encontró productos. "
                    "Revisa el bloque DIAGNÓSTICO PLAYWRIGHT LICOR3B."
                )

            print(
                "Resumen Licor3B: "
                f"páginas={pages_visited}, "
                f"tarjetas={cards_seen}, "
                f"productos_únicos={len(all_products)}",
                flush=True,
            )

            return sorted(
                all_products.values(),
                key=lambda product: product.name.casefold(),
            )
        finally:
            browser.close()
