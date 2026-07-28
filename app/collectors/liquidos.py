from __future__ import annotations

import re
import sys
import time
import unicodedata
from dataclasses import dataclass, replace
from typing import Iterable
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup, Tag
from playwright.sync_api import (
    Browser,
    BrowserContext,
    Locator,
    Page,
    sync_playwright,
)

from app.collectors.base import StoreMetadata
from app.deadlines import bounded_timeout_ms, ensure_budget
from app.domain import CollectedProduct, CollectionBatch, CollectionStats, SectionStats
from app.performance import (
    PerformanceSettings,
    PhaseMetrics,
    ResourceBlockStats,
    install_resource_blocking,
    wait_for_any_selector,
    wait_for_product_count_growth,
    wait_for_signature_change,
)


BASE_URL = "https://www.liquidos.cl"
HOME_URL = f"{BASE_URL}/"
NAVIGATION_TIMEOUT_MS = 40_000
MAX_PAGES_PER_SECTION = 80
MAX_LOAD_MORE_CLICKS = 30
MAX_SCROLL_ROUNDS = 8
MAX_STABLE_ROUNDS = 2
PRODUCT_SELECTOR = "a[href*='/productos/']"
CATEGORY_SELECTOR = "a[href*='/categorias/']"

# Fuerza la modalidad de precio web programado, que es más estable que una
# disponibilidad inmediata dependiente de un local concreto.
CATALOG_QUERY = {
    "delivery_type": "delivery",
    "delivery_time": "programmed",
    "filter_reset": "true",
}


@dataclass(frozen=True)
class CatalogSection:
    key: str
    name: str
    url: str


# Categorías raíz observadas en la navegación pública de Líquidos. Ofertas y
# Packs se conservan para registrar membresía de categoría; la deduplicación
# global evita guardar el mismo producto dos veces.
ROOT_CATEGORY_NAMES: dict[str, str] = {
    "packs": "Packs",
    "ofertas": "Ofertas",
    "piscos": "Piscos",
    "whiskys": "Whiskys",
    "licores": "Licores",
    "cervezas": "Cervezas",
    "vinos": "Vinos",
    "espumantes": "Espumantes",
    "otros": "Otros",
}

FALLBACK_CATALOG_SECTIONS: tuple[CatalogSection, ...] = tuple(
    CatalogSection(key=slug, name=name, url=f"{BASE_URL}/categorias/{slug}")
    for slug, name in ROOT_CATEGORY_NAMES.items()
)

_PRODUCT_PATH_RE = re.compile(r"^/productos/\d+/[^/?#]+/?$", re.IGNORECASE)
_PRICE_RE = re.compile(r"\$\s*([\d.\s]+)")
_UNIT_PRICE_RE = re.compile(
    r"\$\s*[\d.\s]+\s*x\s*(?:lt|l|litro|kg|gr|g|ml|cc|unidad|un)\b",
    re.IGNORECASE,
)


def _normalize_text(value: str) -> str:
    return " ".join((value or "").replace("\xa0", " ").split())


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(char for char in normalized if not unicodedata.combining(char)).casefold()


def _canonical_url(raw_url: str) -> str:
    absolute = urljoin(BASE_URL, (raw_url or "").strip())
    parsed = urlparse(absolute)
    path = re.sub(r"/+", "/", parsed.path).rstrip("/")
    return urlunparse(("https", "www.liquidos.cl", path, "", "", ""))


def _catalog_url(raw_url: str) -> str:
    absolute = urljoin(BASE_URL, (raw_url or "").strip())
    parsed = urlparse(absolute)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.update(CATALOG_QUERY)
    return urlunparse(
        (
            "https",
            "www.liquidos.cl",
            parsed.path.rstrip("/"),
            "",
            urlencode(query),
            "",
        )
    )


def _valid_product_url(raw_url: str) -> bool:
    parsed = urlparse(urljoin(BASE_URL, raw_url))
    return parsed.netloc.casefold() in {"liquidos.cl", "www.liquidos.cl"} and bool(
        _PRODUCT_PATH_RE.fullmatch(parsed.path)
    )


def _discover_sections_from_html(html: str) -> tuple[CatalogSection, ...]:
    soup = BeautifulSoup(html, "html.parser")
    discovered: dict[str, CatalogSection] = {}
    for link in soup.select("a[href*='/categorias/']"):
        href = str(link.get("href") or "").strip()
        parsed = urlparse(urljoin(BASE_URL, href))
        match = re.fullmatch(r"/categorias/([^/]+)/?", parsed.path, re.IGNORECASE)
        if match is None:
            continue
        slug = match.group(1).casefold()
        if slug not in ROOT_CATEGORY_NAMES:
            continue
        label = _normalize_text(link.get_text(" ", strip=True))
        discovered[slug] = CatalogSection(
            key=slug,
            name=label if 1 < len(label) <= 40 else ROOT_CATEGORY_NAMES[slug],
            url=f"{BASE_URL}/categorias/{slug}",
        )
    ordered = [discovered[slug] for slug in ROOT_CATEGORY_NAMES if slug in discovered]
    return tuple(ordered)


def _price_values(text: str) -> list[int]:
    # El sitio muestra también precio por litro. Se excluye antes de leer los
    # precios comerciales del producto.
    cleaned = _UNIT_PRICE_RE.sub(" ", text or "")
    values: list[int] = []
    for raw in _PRICE_RE.findall(cleaned):
        digits = re.sub(r"\D", "", raw)
        if not digits:
            continue
        value = int(digits)
        if 500 <= value <= 2_000_000 and value not in values:
            values.append(value)
    return values


def _price_from_node(node: Tag | None) -> int | None:
    if node is None:
        return None
    for attribute in ("data-price", "data-value", "content", "value"):
        raw = str(node.get(attribute) or "")
        digits = re.sub(r"\D", "", raw)
        if digits:
            value = int(digits)
            if 500 <= value <= 2_000_000:
                return value
    values = _price_values(node.get_text(" ", strip=True))
    return values[0] if values else None


def _first_price(card: Tag, selectors: Iterable[str]) -> int | None:
    for selector in selectors:
        for node in card.select(selector):
            value = _price_from_node(node)
            if value is not None:
                return value
    return None


def _extract_prices(card: Tag) -> tuple[int | None, int | None]:
    current = _first_price(
        card,
        (
            "ins",
            "[class*='internet-price' i]",
            "[class*='internetprice' i]",
            "[class*='sale-price' i]",
            "[class*='offer-price' i]",
            "[class*='precio-oferta' i]",
            "[class*='current-price' i]",
            "[data-price]",
        ),
    )
    regular = _first_price(
        card,
        (
            "del",
            "s",
            "[class*='old-price' i]",
            "[class*='regular-price' i]",
            "[class*='normal-price' i]",
            "[class*='list-price' i]",
            "[class*='precio-normal' i]",
        ),
    )

    values = _price_values(card.get_text(" ", strip=True))
    if current is None and values:
        # En las tarjetas públicas de Líquidos el valor vigente es el menor de
        # los precios comerciales mostrados. Esto también cubre fichas donde
        # el precio anterior aparece antes del precio internet.
        current = min(values)
    if regular is None and current is not None:
        higher = [value for value in values if value > current]
        regular = max(higher) if higher else None
    if regular is not None and current is not None and regular <= current:
        regular = None
    return current, regular


def _discount(regular: int | None, current: int) -> float:
    if regular is None or regular <= current:
        return 0.0
    return (regular - current) / regular


def _candidate_card(link: Tag) -> Tag:
    # Escoge el contenedor más pequeño que incluya enlace, nombre y precio.
    candidate: Tag = link
    for parent in link.parents:
        if not isinstance(parent, Tag):
            continue
        if parent.name in {"body", "html"}:
            break
        text = _normalize_text(parent.get_text(" ", strip=True))
        product_links = parent.select("a[href*='/productos/']")
        if _price_values(text) and len(product_links) <= 3 and len(text) <= 2_500:
            candidate = parent
            if parent.name in {"article", "li"}:
                break
    return candidate


def _name_from_link(link: Tag, card: Tag, url: str) -> str:
    selectors = (
        "[class*='product-name' i]",
        "[class*='product-title' i]",
        "[class*='nombre' i]",
        "h2",
        "h3",
        "h4",
    )
    for selector in selectors:
        node = card.select_one(selector)
        if node is not None:
            value = _normalize_text(node.get_text(" ", strip=True))
            if 3 < len(value) <= 240 and "$" not in value:
                return value
    for attribute in ("title", "aria-label"):
        value = _normalize_text(str(link.get(attribute) or ""))
        if 3 < len(value) <= 240:
            return value
    image = link.select_one("img[alt]") or card.select_one("img[alt]")
    if image is not None:
        value = _normalize_text(str(image.get("alt") or ""))
        if 3 < len(value) <= 240 and _fold(value) not in {"internetprice", "liquidos.cl"}:
            return value
    value = _normalize_text(link.get_text(" ", strip=True))
    if 3 < len(value) <= 240 and "$" not in value:
        return value
    slug = urlparse(url).path.rsplit("/", 1)[-1]
    return slug.replace("-", " ").strip().title()


def _parse_card(link: Tag, section_name: str) -> CollectedProduct | None:
    href = str(link.get("href") or "").strip()
    if not _valid_product_url(href):
        return None
    url = _canonical_url(href)
    card = _candidate_card(link)
    current, regular = _extract_prices(card)
    if current is None:
        return None
    name = _name_from_link(link, card, url)
    if len(name) < 4:
        return None
    unavailable = _fold(card.get_text(" ", strip=True))
    if "producto no disponible" in unavailable and not _price_values(unavailable):
        return None
    return CollectedProduct(
        store="Líquidos",
        name=name,
        url=url,
        current_price=current,
        regular_price=regular,
        discount_pct=_discount(regular, current),
        source_sections=(section_name,),
    )


def _parse_html(html: str, section_name: str) -> tuple[dict[str, CollectedProduct], int]:
    soup = BeautifulSoup(html, "html.parser")
    links = [
        link
        for link in soup.select("a[href*='/productos/']")
        if isinstance(link, Tag) and _valid_product_url(str(link.get("href") or ""))
    ]
    products: dict[str, CollectedProduct] = {}
    for link in links:
        product = _parse_card(link, section_name)
        if product is not None:
            products[product.url] = product
    return products, len(links)


def _merge_product(existing: CollectedProduct | None, incoming: CollectedProduct) -> CollectedProduct:
    if existing is None:
        return incoming
    sections = tuple(sorted(set(existing.source_sections + incoming.source_sections), key=str.casefold))
    # Conserva el menor precio observado si el mismo producto aparece en dos
    # bloques/categorías de la misma ejecución.
    selected = incoming if incoming.current_price <= existing.current_price else existing
    return replace(selected, source_sections=sections)


def _create_context(
    browser: Browser,
    performance: PerformanceSettings,
    block_stats: ResourceBlockStats,
) -> BrowserContext:
    context = browser.new_context(
        locale="es-CL",
        timezone_id="America/Santiago",
        viewport={"width": 1440, "height": 1000},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        ),
        extra_http_headers={"Accept-Language": "es-CL,es;q=0.9,en;q=0.7"},
    )
    install_resource_blocking(
        context,
        enabled=performance.block_browser_resources,
        stats=block_stats,
    )
    return context

def _wait_for_catalog_content(
    page: Page,
    performance: PerformanceSettings,
    *,
    discovery: bool = False,
) -> bool:
    return wait_for_any_selector(
        page,
        CATEGORY_SELECTOR if discovery else PRODUCT_SELECTOR,
        timeout_ms=performance.product_wait_timeout_ms,
        settle_ms=performance.quick_settle_ms,
    )

def _dismiss_overlays(page: Page) -> None:
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass
    selectors = (
        "button[aria-label*='cerrar' i]",
        "button[aria-label*='close' i]",
        "[role='dialog'] button:has-text('Cerrar')",
        "[role='dialog'] button:has-text('Continuar')",
        ".modal button.close",
    )
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if locator.is_visible(timeout=250):
                locator.click(timeout=1_000)
        except Exception:
            continue


def _product_signature(page: Page) -> tuple[str, ...]:
    try:
        hrefs = page.locator("a[href*='/productos/']").evaluate_all(
            "els => els.map(el => el.href).filter(Boolean)"
        )
    except Exception:
        return ()
    return tuple(sorted({_canonical_url(str(href)) for href in hrefs if _valid_product_url(str(href))}))


def _click_visible(locator: Locator) -> bool:
    try:
        if locator.count() and locator.first.is_visible(timeout=300):
            locator.first.scroll_into_view_if_needed(timeout=1_000)
            locator.first.click(timeout=3_000)
            return True
    except Exception:
        return False
    return False


def _expand_current_page(page: Page, performance: PerformanceSettings) -> None:
    stable_rounds = 0
    previous_count = len(_product_signature(page))
    load_more_selectors = (
        "button:has-text('Cargar más')",
        "button:has-text('Mostrar más')",
        "button:has-text('Ver más productos')",
        "a:has-text('Cargar más')",
        "a:has-text('Mostrar más')",
    )

    for _ in range(MAX_LOAD_MORE_CLICKS):
        ensure_budget("expansión de catálogo de Líquidos")
        _dismiss_overlays(page)
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        clicked = any(_click_visible(page.locator(selector)) for selector in load_more_selectors)
        grew = wait_for_product_count_growth(
            page,
            PRODUCT_SELECTOR,
            previous_count,
            timeout_ms=(
                bounded_timeout_ms(performance.dom_growth_timeout_ms)
                if clicked
                else bounded_timeout_ms(min(700, performance.dom_growth_timeout_ms))
            ),
        )
        current_count = len(_product_signature(page))
        if grew or current_count > previous_count:
            stable_rounds = 0
            previous_count = current_count
        else:
            stable_rounds += 1
        if stable_rounds >= MAX_STABLE_ROUNDS and not clicked:
            break

def _next_href(page: Page) -> str | None:
    selectors = (
        "a[rel='next'][href]",
        "a[aria-label*='siguiente' i][href]",
        "a[aria-label*='next' i][href]",
        ".pagination a.next[href]",
        "a:has-text('Siguiente')",
    )
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if locator.count() and locator.is_visible(timeout=300):
                href = locator.get_attribute("href")
                if href:
                    return _catalog_url(href)
        except Exception:
            continue
    return None


def _click_next_button(
    page: Page,
    before_signature: tuple[str, ...],
    performance: PerformanceSettings,
) -> bool:
    selectors = (
        "button[aria-label*='siguiente' i]",
        "button[aria-label*='next' i]",
        "button:has-text('Siguiente')",
    )
    try:
        previous = page.locator(PRODUCT_SELECTOR).evaluate_all(
            "els => els.map(el => el.href || '').filter(Boolean).sort().join('|')"
        )
    except Exception:
        previous = "|".join(before_signature)
    for selector in selectors:
        locator = page.locator(selector)
        if not _click_visible(locator):
            continue
        if wait_for_signature_change(
            page,
            PRODUCT_SELECTOR,
            previous,
            timeout_ms=bounded_timeout_ms(performance.dom_growth_timeout_ms),
        ):
            return True
    return False

def _discover_sections(
    page: Page, performance: PerformanceSettings
) -> tuple[tuple[CatalogSection, ...], str]:
    try:
        ensure_budget("descubrimiento de categorías de Líquidos")
        page.goto(
            _catalog_url(HOME_URL),
            wait_until="domcontentloaded",
            timeout=bounded_timeout_ms(NAVIGATION_TIMEOUT_MS),
        )
        _wait_for_catalog_content(page, performance, discovery=True)
        _dismiss_overlays(page)
        sections = _discover_sections_from_html(page.content())
        if sections:
            return sections, "menu"
    except Exception as exc:
        print(
            f"Líquidos: no se pudo descubrir el menú ({type(exc).__name__}: {exc}); se usa respaldo.",
            flush=True,
        )
    return FALLBACK_CATALOG_SECTIONS, "fallback"


def _health(section_stats: list[SectionStats], products: int) -> tuple[str, int]:
    total = len(section_stats)
    failed = sum(item.status == "failed" for item in section_stats)
    warnings = sum(item.structural_warning for item in section_stats)
    if total == 0 or products == 0:
        return "BROKEN", 0
    score = max(0, min(100, 100 - round((failed / total) * 70) - round((warnings / total) * 30)))
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

    performance = PerformanceSettings.from_env()
    collector_started = time.monotonic()
    aggregate_metrics = PhaseMetrics()
    block_stats = ResourceBlockStats()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-background-networking"],
        )
        context = _create_context(browser, performance, block_stats)
        page = context.new_page()
        try:
            with aggregate_metrics.measure("discovery"):
                sections, discovery_source = _discover_sections(page, performance)
            print(
                f"Líquidos catálogo: categorías={len(sections)}, origen={discovery_source} "
                f"[{', '.join(section.name for section in sections)}]",
                flush=True,
            )

            for index, section in enumerate(sections, start=1):
                ensure_budget(f"Líquidos categoría {section.name}")
                started = time.monotonic()
                phase_metrics = PhaseMetrics()
                section_products: set[str] = set()
                section_cards = section_duplicates = section_pages = 0
                status = "success"
                error_message: str | None = None
                structural_warning = False
                visited_urls: set[str] = set()
                visited_signatures: set[tuple[str, ...]] = set()
                next_url: str | None = _catalog_url(section.url)

                print(
                    f"Líquidos categoría {index}/{len(sections)}: {section.name} ({next_url})",
                    flush=True,
                )

                try:
                    for page_number in range(1, MAX_PAGES_PER_SECTION + 1):
                        ensure_budget(f"Líquidos {section.name} página {page_number}")
                        if next_url is not None:
                            if next_url in visited_urls:
                                break
                            visited_urls.add(next_url)
                            with phase_metrics.measure("navigation_wait"):
                                response = page.goto(
                                    next_url,
                                    wait_until="domcontentloaded",
                                    timeout=bounded_timeout_ms(NAVIGATION_TIMEOUT_MS),
                                )
                                http_status = response.status if response else None
                                _wait_for_catalog_content(page, performance)
                        else:
                            http_status = None

                        _dismiss_overlays(page)
                        with phase_metrics.measure("scroll_expand"):
                            _expand_current_page(page, performance)
                        last_html = page.content()
                        signature = _product_signature(page)
                        if signature in visited_signatures and page_number > 1:
                            break
                        visited_signatures.add(signature)

                        with phase_metrics.measure("parse"):
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
                            all_products[product_url] = _merge_product(
                                all_products.get(product_url), product
                            )

                        print(
                            f"Líquidos {section.key} página {page_number}: HTTP={http_status}, "
                            f"enlaces={page_cards}, productos_página={len(page_products)}, "
                            f"nuevos_sección={new_in_section}, nuevos_globales={new_global}, "
                            f"productos_sección={len(section_products)}, "
                            f"productos_globales={len(all_products)}, url={page.url}",
                            flush=True,
                        )

                        if page_number == 1 and http_status == 200 and page_cards == 0:
                            structural_warning = True
                            print(
                                f"⚠ Posible cambio estructural en {section.name}: "
                                "HTTP 200 con 0 enlaces de productos.",
                                flush=True,
                            )

                        href = _next_href(page)
                        if href and href not in visited_urls:
                            next_url = href
                            continue
                        before = _product_signature(page)
                        if _click_next_button(page, before, performance):
                            next_url = None
                            continue
                        break
                    else:
                        print(
                            f"Líquidos {section.name}: alcanzó límite de {MAX_PAGES_PER_SECTION} páginas.",
                            flush=True,
                        )
                except Exception as exc:
                    status = "failed"
                    error_message = f"{type(exc).__name__}: {exc}"[:1000]
                    print(
                        f"✖ Líquidos {section.name}: {error_message}. Continúa con la siguiente categoría.",
                        file=sys.stderr,
                        flush=True,
                    )

                duration_ms = int((time.monotonic() - started) * 1000)
                section_results.append(
                    SectionStats(
                        key=section.key,
                        name=section.name,
                        url=section.url,
                        pages_visited=section_pages,
                        cards_seen=section_cards,
                        unique_products=len(section_products),
                        duplicates_removed=section_duplicates,
                        duration_ms=duration_ms,
                        status=status,
                        error_message=error_message,
                        structural_warning=structural_warning,
                        performance_ms=phase_metrics.as_dict(),
                    )
                )
                print("=" * 46, flush=True)
                print(f"Categoría..............: {section.name}", flush=True)
                print(f"Estado.................: {'OK' if status == 'success' else 'ERROR'}", flush=True)
                print(f"Páginas................: {section_pages}", flush=True)
                print(f"Enlaces de producto....: {section_cards}", flush=True)
                print(f"Productos únicos.......: {len(section_products)}", flush=True)
                print(f"Duplicados sección.....: {section_duplicates}", flush=True)
                print(f"Duración................: {duration_ms / 1000:.1f} s", flush=True)
                print(
                    "PERF....................: "
                    + ", ".join(
                        f"{name}={value / 1000:.1f}s"
                        for name, value in phase_metrics.as_dict().items()
                    ),
                    flush=True,
                )
                print("=" * 46, flush=True)

            if not all_products:
                preview = _normalize_text(
                    BeautifulSoup(last_html[:10_000], "html.parser").get_text(" ", strip=True)
                )
                print(f"Diagnóstico HTML Líquidos: {preview[:1800]}", file=sys.stderr, flush=True)
                raise RuntimeError("Líquidos no entregó productos en ninguna categoría.")

            health_status, health_score = _health(section_results, len(all_products))
            succeeded = sum(item.status == "success" for item in section_results)
            failed = len(section_results) - succeeded
            warnings = sum(item.structural_warning for item in section_results)
            aggregate_metrics.add(
                "collector_total", int((time.monotonic() - collector_started) * 1000)
            )
            aggregate_metrics.add("blocked_requests", block_stats.blocked_requests)
            for section_result in section_results:
                for phase_name, phase_ms in section_result.performance_ms.items():
                    aggregate_metrics.add(phase_name, phase_ms)
            print(
                "PERF RESUMEN · Líquidos: "
                + ", ".join(
                    f"{name}={value / 1000:.1f}s"
                    if name != "blocked_requests"
                    else f"{name}={value}"
                    for name, value in aggregate_metrics.as_dict().items()
                ),
                flush=True,
            )
            products = sorted(all_products.values(), key=lambda product: product.name.casefold())
            print(
                f"Resumen Líquidos: categorías={len(sections)}, correctas={succeeded}, "
                f"fallidas={failed}, páginas={pages_visited}, enlaces={cards_seen}, "
                f"duplicados={duplicates_removed}, productos_únicos={len(products)}, "
                f"salud={health_status}({health_score})",
                flush=True,
            )
            return CollectionBatch(
                products=products,
                stats=CollectionStats(
                    pages_visited=pages_visited,
                    cards_seen=cards_seen,
                    unique_products=len(products),
                    sections_discovered=len(sections),
                    sections_visited=len(section_results),
                    sections_succeeded=succeeded,
                    sections_failed=failed,
                    duplicates_removed=duplicates_removed,
                    discovery_source=discovery_source,
                    health_status=health_status,
                    health_score=health_score,
                    structural_warnings=warnings,
                    section_stats=tuple(section_results),
                    performance_ms=aggregate_metrics.as_dict(),
                ),
            )
        finally:
            try:
                context.close()
            except Exception:
                pass
            browser.close()


class LiquidosCollector:
    metadata = StoreMetadata(
        name="Líquidos",
        slug="liquidos",
        base_url="https://www.liquidos.cl/",
        connector_key="liquidos",
        requires_browser=True,
    )
    key = metadata.connector_key
    store_name = metadata.name

    def collect(self) -> CollectionBatch:
        return _collect_products()


def scrape() -> list[CollectedProduct]:
    return LiquidosCollector().collect().products
