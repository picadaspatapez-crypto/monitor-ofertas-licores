from __future__ import annotations

import re
import sys
import time
from dataclasses import dataclass, replace
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

from app.domain import (
    CollectedProduct,
    CollectionBatch,
    CollectionStats,
    SectionStats,
)


BASE_URL = "https://licor3b.cl"
HOME_URL = f"{BASE_URL}/"
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


# Respaldo determinista. El collector intenta descubrir las categorías desde
# la navegación del sitio; esta lista solo se usa si el menú no puede leerse.
FALLBACK_CATALOG_SECTIONS: tuple[CatalogSection, ...] = (
    CatalogSection("ofertas", "Ofertas", f"{BASE_URL}/product-category/ofertas/"),
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
# Alias de compatibilidad con la v2.2: categorías raíz sin la página promocional Ofertas.
FULL_CATALOG_SECTIONS = tuple(section for section in FALLBACK_CATALOG_SECTIONS if section.key != "ofertas")


def _clean_url(raw_url: str) -> str:
    absolute = urljoin(BASE_URL, raw_url.strip())
    parsed = urlparse(absolute)
    path = parsed.path.rstrip("/") + "/"
    return urlunparse((parsed.scheme or "https", parsed.netloc.lower(), path, "", "", ""))


def _humanize_slug(slug: str) -> str:
    special = {"whiskys": "Whisky", "piscos": "Piscos", "rones": "Rones"}
    return special.get(slug, slug.replace("-", " ").title())


def _discover_sections_from_html(html: str) -> tuple[CatalogSection, ...]:
    soup = BeautifulSoup(html, "html.parser")
    discovered: dict[str, CatalogSection] = {}
    for link in soup.select("a[href*='/product-category/']"):
        href = str(link.get("href") or "").strip()
        if not href:
            continue
        url = _clean_url(href)
        parsed = urlparse(url)
        if parsed.netloc.lower() not in {"licor3b.cl", "www.licor3b.cl"}:
            continue
        match = re.fullmatch(r"/product-category/([^/]+)/", parsed.path)
        if match is None:
            # Evita subcategorías: solo categorías raíz para no multiplicar duplicados.
            continue
        key = match.group(1).casefold()
        if key in {"uncategorized", "sin-categoria"}:
            continue
        visible_name = " ".join(link.get_text(" ", strip=True).split())
        if not visible_name or len(visible_name) > 60:
            visible_name = _humanize_slug(key)
        discovered[key] = CatalogSection(key=key, name=visible_name, url=url)
    return tuple(sorted(discovered.values(), key=lambda item: item.name.casefold()))


def _section_page_url(section: CatalogSection, page_number: int) -> str:
    if page_number <= 1:
        return section.url
    return f"{section.url}?{urlencode({'product-page': page_number})}"


def _valid_product_url(url: str) -> bool:
    lowered = url.lower()
    excluded = ("/cart", "/carrito", "/checkout", "/mi-cuenta", "/product-category/", "add-to-cart=")
    return not any(value in lowered for value in excluded) and (
        "/producto/" in lowered or "/product/" in lowered or "/tienda/" in lowered
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


def _discount(regular: Optional[int], current: int) -> float:
    return 0.0 if regular is None or regular <= current else (regular - current) / regular


def _clean_name(text: str) -> str:
    cleaned = re.sub(r"^-\d+(?:[.,]\d+)?%\s*", "", text.strip())
    cleaned = re.sub(r"\$\s*[\d.\s]+", "", cleaned)
    cleaned = re.sub(r"\bLLEVAR\b", "", cleaned, flags=re.IGNORECASE)
    return " ".join(cleaned.split()).strip(" -|")


def _candidate_cards(soup: BeautifulSoup) -> list[Tag]:
    selectors = (
        "li.product", ".products .product", ".product-small", ".product-item",
        ".wc-block-grid__product", "[data-product-id]", "article.product",
    )
    found: list[Tag] = []
    seen: set[int] = set()
    for selector in selectors:
        for node in soup.select(selector):
            marker = id(node)
            if marker not in seen:
                seen.add(marker)
                found.append(node)
    return found


def _parse_card(card: Tag, section_name: str) -> Optional[CollectedProduct]:
    link = card.select_one(
        "a.woocommerce-LoopProduct-link[href], a.woocommerce-loop-product__link[href], "
        "a[href*='/producto/'], a[href*='/product/'], a[href*='/tienda/']"
    )
    if link is None:
        return None
    href = str(link.get("href") or "").strip()
    if not href:
        return None
    url = _clean_url(href)
    if not _valid_product_url(url):
        return None
    title_node = card.select_one(".woocommerce-loop-product__title, .product-title, .name, h2, h3, h4")
    name = _clean_name(title_node.get_text(" ", strip=True) if title_node else link.get_text(" ", strip=True))
    prices = _all_prices(card.get_text(" ", strip=True))
    if not name or len(name) < 4 or not prices:
        return None
    current = prices[-1]
    regular = prices[-2] if len(prices) >= 2 and prices[-2] > current else None
    return CollectedProduct(
        store="Licor3B", name=name, url=url, current_price=current,
        regular_price=regular, discount_pct=_discount(regular, current),
        source_sections=(section_name,),
    )


def _parse_html(html: str, section_name: str) -> tuple[dict[str, CollectedProduct], int]:
    soup = BeautifulSoup(html, "html.parser")
    cards = _candidate_cards(soup)
    products: dict[str, CollectedProduct] = {}
    for card in cards:
        product = _parse_card(card, section_name)
        if product is not None:
            products[product.url] = product
    return products, len(cards)


def _create_context(browser: Browser) -> BrowserContext:
    return browser.new_context(
        locale="es-CL", timezone_id="America/Santiago", viewport={"width": 1365, "height": 900},
        user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"),
        extra_http_headers={"Accept-Language": "es-CL,es;q=0.9,en;q=0.7"},
    )


def _is_robot_challenge(page: Page, html: str) -> bool:
    lowered = html.lower()
    return "robot challenge screen" in lowered or "/.well-known/sgcaptcha/" in page.url.lower() or "sgcaptcha" in lowered


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
        stable_rounds = stable_rounds + 1 if new_height == current_height == previous_height else 0
        previous_height = new_height
        if stable_rounds >= 2:
            break


def _open_with_captcha_retries(browser: Browser, context: BrowserContext, page: Page, url: str) -> tuple[BrowserContext, Page, str, Optional[int]]:
    last_html = ""
    last_status: Optional[int] = None
    for attempt in range(1, MAX_CAPTCHA_RETRIES + 1):
        response = page.goto(url, wait_until="domcontentloaded", timeout=NAVIGATION_TIMEOUT_MS)
        last_status = response.status if response else None
        _wait_for_page(page)
        last_html = page.content()
        if not _is_robot_challenge(page, last_html):
            return context, page, last_html, last_status
        print(f"Licor3B CAPTCHA: intento {attempt}/{MAX_CAPTCHA_RETRIES}, url={page.url}", flush=True)
        page.wait_for_timeout(4_000)
        if attempt < MAX_CAPTCHA_RETRIES:
            try:
                context.close()
            except Exception:
                pass
            context = _create_context(browser)
            page = context.new_page()
    return context, page, last_html, last_status


def _discover_sections(browser: Browser, context: BrowserContext, page: Page) -> tuple[BrowserContext, Page, tuple[CatalogSection, ...], str]:
    try:
        context, page, html, _ = _open_with_captcha_retries(browser, context, page, HOME_URL)
        if not _is_robot_challenge(page, html):
            discovered = _discover_sections_from_html(html)
            if discovered:
                return context, page, discovered, "menu"
    except Exception as exc:
        print(f"Licor3B: no se pudo descubrir el menú ({type(exc).__name__}: {exc}); se usa respaldo.", flush=True)
    return context, page, FALLBACK_CATALOG_SECTIONS, "fallback"


def _merge_product(existing: CollectedProduct | None, incoming: CollectedProduct) -> CollectedProduct:
    if existing is None:
        return incoming
    sections = tuple(sorted(set(existing.source_sections + incoming.source_sections), key=str.casefold))
    # Si aparece en varias categorías, conservamos el precio más reciente leído y unimos orígenes.
    return replace(incoming, source_sections=sections)


def _health(section_stats: list[SectionStats], products: int) -> tuple[str, int]:
    total = len(section_stats)
    failed = sum(item.status == "failed" for item in section_stats)
    warnings = sum(item.structural_warning for item in section_stats)
    if total == 0 or products == 0:
        return "BROKEN", 0
    score = 100 - round((failed / total) * 70) - round((warnings / total) * 30)
    score = max(0, min(100, score))
    if failed == 0 and warnings == 0:
        return "HEALTHY", score
    if failed < max(2, total // 3) and score >= 55:
        return "DEGRADED", score
    return "BROKEN", score


def _collect_products() -> CollectionBatch:
    all_products: dict[str, CollectedProduct] = {}
    pages_visited = cards_seen = duplicates_removed = 0
    section_results: list[SectionStats] = []
    last_html = ""

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        context = _create_context(browser)
        page = context.new_page()
        try:
            context, page, sections, discovery_source = _discover_sections(browser, context, page)
            print(
                f"Licor3B catálogo completo: categorías={len(sections)}, origen={discovery_source} "
                f"[{', '.join(section.name for section in sections)}]",
                flush=True,
            )

            for index, section in enumerate(sections, start=1):
                started = time.monotonic()
                section_products: set[str] = set()
                section_pages = section_cards = section_duplicates = 0
                consecutive_empty = 0
                status = "success"
                error_message: str | None = None
                structural_warning = False
                print(f"Licor3B categoría {index}/{len(sections)}: {section.name} ({section.url})", flush=True)

                try:
                    for page_number in range(1, MAX_PRODUCT_PAGES_PER_SECTION + 1):
                        requested_url = _section_page_url(section, page_number)
                        context, page, last_html, http_status = _open_with_captcha_retries(browser, context, page, requested_url)
                        if _is_robot_challenge(page, last_html):
                            raise RuntimeError("CAPTCHA persistente")
                        _scroll_until_stable(page)
                        last_html = page.content()
                        page_products, page_cards = _parse_html(last_html, section.name)
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
                            else:
                                section_duplicates += 1
                            if product_url not in all_products:
                                new_global += 1
                            else:
                                duplicates_removed += 1
                            all_products[product_url] = _merge_product(all_products.get(product_url), product)

                        print(
                            f"Licor3B {section.key} product-page {page_number}: HTTP={http_status}, "
                            f"tarjetas={page_cards}, productos_página={len(page_products)}, "
                            f"nuevos_sección={new_in_section}, nuevos_globales={new_global}, "
                            f"productos_sección={len(section_products)}, productos_globales={len(all_products)}, url={page.url}",
                            flush=True,
                        )

                        if page_number == 1 and http_status == 200 and page_cards == 0:
                            structural_warning = True
                            print(
                                f"⚠ Posible cambio estructural en {section.name}: HTTP 200 con 0 tarjetas en primera página.",
                                flush=True,
                            )

                        consecutive_empty = consecutive_empty + 1 if new_in_section == 0 else 0
                        if consecutive_empty >= MAX_CONSECUTIVE_EMPTY_PAGES:
                            break
                    else:
                        print(f"Licor3B {section.name}: alcanzó límite de {MAX_PRODUCT_PAGES_PER_SECTION} páginas.", flush=True)
                except Exception as exc:
                    status = "failed"
                    error_message = f"{type(exc).__name__}: {exc}"[:1000]
                    print(f"✖ Licor3B {section.name}: {error_message}. Continúa con la siguiente categoría.", file=sys.stderr, flush=True)

                duration_ms = int((time.monotonic() - started) * 1000)
                result = SectionStats(
                    key=section.key, name=section.name, url=section.url,
                    pages_visited=section_pages, cards_seen=section_cards,
                    unique_products=len(section_products), duplicates_removed=section_duplicates,
                    duration_ms=duration_ms, status=status, error_message=error_message,
                    structural_warning=structural_warning,
                )
                section_results.append(result)
                print("=" * 46, flush=True)
                print(f"Categoría..............: {section.name}", flush=True)
                print(f"Estado.................: {'OK' if status == 'success' else 'ERROR'}", flush=True)
                print(f"Páginas................: {section_pages}", flush=True)
                print(f"Tarjetas...............: {section_cards}", flush=True)
                print(f"Productos únicos.......: {len(section_products)}", flush=True)
                print(f"Duplicados sección.....: {section_duplicates}", flush=True)
                print(f"Duración................: {duration_ms / 1000:.1f} s", flush=True)
                print("=" * 46, flush=True)

            if not all_products:
                preview = " ".join(BeautifulSoup(last_html[:5_000], "html.parser").get_text(" ", strip=True).split())
                print(f"Diagnóstico HTML: {preview[:1500]}", file=sys.stderr)
                raise RuntimeError("Licor3B no entregó productos en ninguna categoría.")

            health_status, health_score = _health(section_results, len(all_products))
            succeeded = sum(item.status == "success" for item in section_results)
            failed = len(section_results) - succeeded
            warnings = sum(item.structural_warning for item in section_results)
            print(
                f"Resumen Licor3B: categorías={len(sections)}, correctas={succeeded}, fallidas={failed}, "
                f"páginas={pages_visited}, tarjetas={cards_seen}, duplicados={duplicates_removed}, "
                f"productos_únicos={len(all_products)}, salud={health_status}({health_score})",
                flush=True,
            )
            products = sorted(all_products.values(), key=lambda product: product.name.casefold())
            return CollectionBatch(
                products=products,
                stats=CollectionStats(
                    pages_visited=pages_visited, cards_seen=cards_seen,
                    unique_products=len(products), sections_discovered=len(sections),
                    sections_visited=len(section_results), sections_succeeded=succeeded,
                    sections_failed=failed, duplicates_removed=duplicates_removed,
                    discovery_source=discovery_source, health_status=health_status,
                    health_score=health_score, structural_warnings=warnings,
                    section_stats=tuple(section_results),
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
    return Licor3BCollector().collect().products
