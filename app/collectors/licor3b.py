import re
import sys
from urllib.parse import urlencode, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup, Tag

from app.domain import CollectedProduct
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
MAX_PRODUCT_PAGES = 50
MAX_CAPTCHA_RETRIES = 4
MAX_SCROLL_ROUNDS = 10
MAX_CONSECUTIVE_EMPTY_PAGES = 2



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


def _product_page_url(page_number: int) -> str:
    if page_number <= 1:
        return OFFERS_URL
    return f"{OFFERS_URL}?{urlencode({'product-page': page_number})}"


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


def _parse_card(card: Tag) -> Optional[CollectedProduct]:
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
        ".product-title, .name, h2, h3, h4"
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

    return CollectedProduct(
        store="Licor3B",
        name=name,
        url=url,
        current_price=current,
        regular_price=regular,
        discount_pct=_discount(regular, current),
    )


def _parse_html(html: str) -> tuple[dict[str, CollectedProduct], int]:
    soup = BeautifulSoup(html, "html.parser")
    cards = _candidate_cards(soup)
    products: dict[str, CollectedProduct] = {}

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


def _is_robot_challenge(page: Page, html: str) -> bool:
    lowered = html.lower()
    return (
        "robot challenge screen" in lowered
        or "/.well-known/sgcaptcha/" in page.url.lower()
        or "sgcaptcha" in lowered
    )


def _wait_for_page(page: Page) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=20_000)
    except PlaywrightTimeoutError:
        pass

    page.wait_for_timeout(PAGE_SETTLE_MS)


def _scroll_until_stable(page: Page) -> None:
    previous_height = 0
    stable_rounds = 0

    for _ in range(MAX_SCROLL_ROUNDS):
        current_height = page.evaluate("document.body.scrollHeight")
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(1_000)
        new_height = page.evaluate("document.body.scrollHeight")

        if new_height == current_height == previous_height:
            stable_rounds += 1
        else:
            stable_rounds = 0

        previous_height = new_height
        if stable_rounds >= 2:
            break


def _open_with_captcha_retries(
    browser: Browser,
    context: BrowserContext,
    page: Page,
    url: str,
) -> tuple[Page, str, Optional[int]]:
    last_html = ""
    last_status: Optional[int] = None

    for attempt in range(1, MAX_CAPTCHA_RETRIES + 1):
        response = page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=NAVIGATION_TIMEOUT_MS,
        )
        last_status = response.status if response is not None else None
        _wait_for_page(page)
        last_html = page.content()

        if not _is_robot_challenge(page, last_html):
            return page, last_html, last_status

        print(
            f"Licor3B CAPTCHA: intento {attempt}/{MAX_CAPTCHA_RETRIES}, "
            f"url={page.url}",
            flush=True,
        )

        page.wait_for_timeout(4_000)

        if attempt < MAX_CAPTCHA_RETRIES:
            # Un contexto nuevo cambia cookies/sesión y suele resolver
            # la respuesta intermitente de SiteGround.
            try:
                context.close()
            except Exception:
                pass
            context = _create_context(browser)
            page = context.new_page()

    return page, last_html, last_status


def _collect_products() -> list[CollectedProduct]:
    all_products: dict[str, CollectedProduct] = {}
    pages_visited = 0
    cards_seen = 0
    consecutive_empty = 0
    last_html = ""

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )

        context = _create_context(browser)
        page = context.new_page()

        try:
            for page_number in range(1, MAX_PRODUCT_PAGES + 1):
                requested_url = _product_page_url(page_number)

                page, last_html, status = _open_with_captcha_retries(
                    browser,
                    context,
                    page,
                    requested_url,
                )

                if _is_robot_challenge(page, last_html):
                    if all_products:
                        print(
                            "Licor3B: CAPTCHA persistente; se conserva el "
                            "catálogo ya recolectado.",
                            flush=True,
                        )
                        break

                    raise RuntimeError(
                        "Licor3B mantuvo el Robot Challenge después de "
                        f"{MAX_CAPTCHA_RETRIES} intentos."
                    )

                _scroll_until_stable(page)
                last_html = page.content()

                page_products, page_cards = _parse_html(last_html)
                pages_visited += 1
                cards_seen += page_cards

                before = len(all_products)
                all_products.update(page_products)
                new_unique = len(all_products) - before

                print(
                    "Licor3B product-page "
                    f"{page_number}: HTTP={status}, "
                    f"tarjetas={page_cards}, "
                    f"productos_página={len(page_products)}, "
                    f"nuevos_únicos={new_unique}, "
                    f"productos_únicos={len(all_products)}, "
                    f"url={page.url}",
                    flush=True,
                )

                if new_unique == 0:
                    consecutive_empty += 1
                else:
                    consecutive_empty = 0

                if consecutive_empty >= MAX_CONSECUTIVE_EMPTY_PAGES:
                    print(
                        "Licor3B: dos páginas consecutivas sin productos "
                        "nuevos; termina la paginación.",
                        flush=True,
                    )
                    break

            if not all_products:
                preview = " ".join(
                    BeautifulSoup(last_html[:5_000], "html.parser")
                    .get_text(" ", strip=True)
                    .split()
                )
                print("=== DIAGNÓSTICO LICOR3B ===", file=sys.stderr)
                print(f"final_url={page.url}", file=sys.stderr)
                print(f"title={page.title()!r}", file=sys.stderr)
                print(f"html_chars={len(last_html)}", file=sys.stderr)
                print(f"html_preview={preview[:1_500]}", file=sys.stderr)
                print("=== FIN DIAGNÓSTICO ===", file=sys.stderr)
                raise RuntimeError("Licor3B no entregó productos.")

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
            try:
                context.close()
            except Exception:
                pass
            browser.close()


class Licor3BCollector:
    key = "licor3b"
    store_name = "Licor3B"

    def collect(self) -> list[CollectedProduct]:
        return _collect_products()


def scrape() -> list[CollectedProduct]:
    """Compatibilidad temporal con la arquitectura v1."""
    return Licor3BCollector().collect()
