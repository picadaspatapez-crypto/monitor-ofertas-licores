from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlencode, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup, Tag
from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

from app.domain import CollectedProduct, CollectionBatch, CollectionStats


BASE_URL = "https://licor3b.cl"
OFFERS_URL = f"{BASE_URL}/product-category/ofertas/"
NAVIGATION_TIMEOUT_MS = 60_000
PAGE_SETTLE_MS = 4_000
MAX_PRODUCT_PAGES_PER_SECTION = 80
MAX_CAPTCHA_RETRIES = 4
MAX_SCROLL_ROUNDS = 10
MAX_CONSECUTIVE_EMPTY_PAGES = 2


@dataclass(frozen=True)
class CatalogSection:
    key: str
    name: str
    url: str


# Categorías principales visibles en la navegación de Licor3B. Se usan solo
# las categorías raíz para cubrir el catálogo sin recorrer cada subcategoría
# y multiplicar innecesariamente las páginas duplicadas.
FULL_CATALOG_SECTIONS: tuple[CatalogSection, ...] = (
    CatalogSection("cervezas", "Cervezas", f"{BASE_URL}/product-category/cervezas/"),
    CatalogSection("espumantes", "Espumantes", f"{BASE_URL}/product-category/espumantes/"),
    CatalogSection("licores", "Licores", f"{BASE_URL}/product-category/licores/"),
    CatalogSection("otros", "Otros", f"{BASE_URL}/product-category/otros/"),
    CatalogSection("packs", "Packs", f"{BASE_URL}/product-category/packs/"),
    CatalogSection("piscos", "Piscos", f"{BASE_URL}/product-category/piscos/"),
    CatalogSection("rones", "Rones", f"{BASE_URL}/product-category/rones/"),
    CatalogSection("tequilas", "Tequilas", f"{BASE_URL}/product-category/tequilas/"),
    CatalogSection("vinos", "Vinos", f"{BASE_URL}/product-category/vinos/"),
    CatalogSection("vodkas", "Vodkas", f"{BASE_URL}/product-category/vodkas/"),
    CatalogSection("whiskys", "Whisky", f"{BASE_URL}/product-category/whiskys/"),
)

OFFERS_SECTION = CatalogSection("ofertas", "Ofertas", OFFERS_URL)


def _configured_sections() -> tuple[CatalogSection, ...]:
    """Determina qué partes del sitio recorrer.

    LICOR3B_CATALOG_MODE=full   -> catálogo completo (predeterminado)
    LICOR3B_CATALOG_MODE=offers -> solo la categoría histórica de ofertas

    LICOR3B_SECTIONS permite limitar el catálogo para diagnóstico, por ejemplo:
    LICOR3B_SECTIONS=whiskys,vinos,piscos
    """
    mode = os.getenv("LICOR3B_CATALOG_MODE", "full").strip().casefold()
    if mode == "offers":
        return (OFFERS_SECTION,)
    if mode != "full":
        raise RuntimeError(
            "LICOR3B_CATALOG_MODE debe ser 'full' u 'offers'; "
            f"se recibió {mode!r}."
        )

    requested = {
        value.strip().casefold()
        for value in os.getenv("LICOR3B_SECTIONS", "").split(",")
        if value.strip()
    }
    if not requested:
        return FULL_CATALOG_SECTIONS

    available = {section.key: section for section in FULL_CATALOG_SECTIONS}
    unknown = sorted(requested - available.keys())
    if unknown:
        raise RuntimeError(
            "LICOR3B_SECTIONS contiene categorías desconocidas: "
            + ", ".join(unknown)
        )
    return tuple(section for section in FULL_CATALOG_SECTIONS if section.key in requested)


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


def _section_page_url(section: CatalogSection, page_number: int) -> str:
    if page_number <= 1:
        return section.url
    return f"{section.url}?{urlencode({'product-page': page_number})}"


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
    return "/producto/" in lowered or "/product/" in lowered or "/tienda/" in lowered


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
        ".woocommerce-loop-product__title, .product-title, .name, h2, h3, h4"
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
        extra_http_headers={"Accept-Language": "es-CL,es;q=0.9,en;q=0.7"},
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
) -> tuple[BrowserContext, Page, str, Optional[int]]:
    last_html = ""
    last_status: Optional[int] = None

    for attempt in range(1, MAX_CAPTCHA_RETRIES + 1):
        response = page.goto(url, wait_until="domcontentloaded", timeout=NAVIGATION_TIMEOUT_MS)
        last_status = response.status if response is not None else None
        _wait_for_page(page)
        last_html = page.content()

        if not _is_robot_challenge(page, last_html):
            return context, page, last_html, last_status

        print(
            f"Licor3B CAPTCHA: intento {attempt}/{MAX_CAPTCHA_RETRIES}, url={page.url}",
            flush=True,
        )
        page.wait_for_timeout(4_000)

        if attempt < MAX_CAPTCHA_RETRIES:
            try:
                context.close()
            except Exception:
                pass
            context = _create_context(browser)
            page = context.new_page()

    return context, page, last_html, last_status


def _collect_products() -> CollectionBatch:
    sections = _configured_sections()
    all_products: dict[str, CollectedProduct] = {}
    pages_visited = 0
    cards_seen = 0
    sections_completed = 0
    last_html = ""

    print(
        "Licor3B modo catálogo: "
        + ("ofertas" if sections == (OFFERS_SECTION,) else "completo")
        + f"; secciones={len(sections)} [{', '.join(s.name for s in sections)}]",
        flush=True,
    )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = _create_context(browser)
        page = context.new_page()

        try:
            for section_index, section in enumerate(sections, start=1):
                consecutive_empty = 0
                section_products: set[str] = set()
                section_pages = 0
                section_cards = 0

                print(
                    f"Licor3B sección {section_index}/{len(sections)}: {section.name} ({section.url})",
                    flush=True,
                )

                for page_number in range(1, MAX_PRODUCT_PAGES_PER_SECTION + 1):
                    requested_url = _section_page_url(section, page_number)
                    context, page, last_html, status = _open_with_captcha_retries(
                        browser, context, page, requested_url
                    )

                    if _is_robot_challenge(page, last_html):
                        print(
                            f"Licor3B {section.name}: CAPTCHA persistente; se omite esta sección "
                            "y se conserva el catálogo ya recolectado.",
                            flush=True,
                        )
                        break

                    _scroll_until_stable(page)
                    last_html = page.content()
                    page_products, page_cards = _parse_html(last_html)
                    pages_visited += 1
                    section_pages += 1
                    cards_seen += page_cards
                    section_cards += page_cards

                    new_in_section = 0
                    new_global = 0
                    for product_url, product in page_products.items():
                        if product_url not in section_products:
                            section_products.add(product_url)
                            new_in_section += 1
                        if product_url not in all_products:
                            new_global += 1
                        all_products[product_url] = product

                    print(
                        f"Licor3B {section.key} product-page {page_number}: "
                        f"HTTP={status}, tarjetas={page_cards}, "
                        f"productos_página={len(page_products)}, "
                        f"nuevos_sección={new_in_section}, nuevos_globales={new_global}, "
                        f"productos_sección={len(section_products)}, "
                        f"productos_globales={len(all_products)}, url={page.url}",
                        flush=True,
                    )

                    if new_in_section == 0:
                        consecutive_empty += 1
                    else:
                        consecutive_empty = 0

                    if consecutive_empty >= MAX_CONSECUTIVE_EMPTY_PAGES:
                        print(
                            f"Licor3B {section.name}: dos páginas consecutivas sin productos "
                            "nuevos; termina la sección.",
                            flush=True,
                        )
                        sections_completed += 1
                        break
                else:
                    print(
                        f"Licor3B {section.name}: alcanzó el límite de "
                        f"{MAX_PRODUCT_PAGES_PER_SECTION} páginas.",
                        flush=True,
                    )
                    sections_completed += 1

                print(
                    f"Resumen sección {section.name}: páginas={section_pages}, "
                    f"tarjetas={section_cards}, productos_únicos={len(section_products)}, "
                    f"catálogo_global={len(all_products)}",
                    flush=True,
                )

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
                "Resumen Licor3B catálogo completo: "
                f"secciones={len(sections)}, secciones_completadas={sections_completed}, "
                f"páginas={pages_visited}, tarjetas={cards_seen}, "
                f"productos_únicos={len(all_products)}",
                flush=True,
            )

            products = sorted(all_products.values(), key=lambda product: product.name.casefold())
            return CollectionBatch(
                products=products,
                stats=CollectionStats(
                    pages_visited=pages_visited,
                    cards_seen=cards_seen,
                    unique_products=len(products),
                    sections_visited=len(sections),
                ),
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

    def collect(self) -> CollectionBatch:
        return _collect_products()


def scrape() -> list[CollectedProduct]:
    """Compatibilidad temporal con la arquitectura v1."""
    return Licor3BCollector().collect().products
