from __future__ import annotations

import math
import re
import sys
import time
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlencode, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup, Tag
from playwright.sync_api import Browser, BrowserContext, Page, TimeoutError as PlaywrightTimeoutError, sync_playwright

from app.collectors.base import StoreMetadata
from app.deadlines import bounded_timeout_ms, ensure_budget
from app.domain import CollectedProduct, CollectionBatch, CollectionStats, SectionStats
from app.performance import (
    PerformanceSettings,
    PhaseMetrics,
    ResourceBlockStats,
    install_resource_blocking,
    wait_for_any_selector,
)


BASE_URL = "https://tost.cl"
NAVIGATION_TIMEOUT_MS = 40_000
MAX_PAGES_PER_SECTION = 30
MIN_PLAUSIBLE_PRODUCTS = 50
PRODUCT_SELECTOR = "a[href*='/products/']"
RENDER_POLL_MS = 450
MAX_RENDER_WAIT_MS = 12_000


@dataclass(frozen=True)
class CatalogSection:
    key: str
    name: str
    handle: str


CATALOG_SECTIONS: tuple[CatalogSection, ...] = (
    CatalogSection("whisky", "Whisky", "whiskey"),
    CatalogSection("gin", "Gin", "gin"),
    CatalogSection("vodka", "Vodka", "vodka"),
    CatalogSection("ron", "Ron", "ron"),
    CatalogSection("tequila", "Tequila", "tequila"),
    CatalogSection("piscos-licores", "Piscos y licores", "piscos-y-licores"),
    CatalogSection("vinos", "Vinos", "vinos"),
    CatalogSection("espumantes", "Espumantes", "espumantes"),
    CatalogSection("cervezas", "Cervezas", "cervezas"),
)

_PRICE_RE = re.compile(r"\$\s*([\d.]+)")
_PRODUCT_PATH_RE = re.compile(r"^/products/[^/?#]+/?$", re.IGNORECASE)
_SKIP_PERSONALIZED_RE = re.compile(
    r"\b(personalizad[oa]s?|personalizalo|personalízalo|graba(?:do)?|grabada)\b",
    re.IGNORECASE,
)


def _normalize_text(value: str) -> str:
    return " ".join((value or "").replace("\xa0", " ").split())


def _canonical_product_url(handle: str, variant_id: int | str | None = None) -> str:
    path = f"/products/{str(handle).strip('/')}"
    query = urlencode({"variant": str(variant_id)}) if variant_id else ""
    return urlunparse(("https", "tost.cl", path, "", query, ""))


def _money(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        integer = int(value)
        return integer if 100 <= integer <= 20_000_000 else None
    raw = str(value).replace("$", "").replace(" ", "").strip()
    if re.fullmatch(r"\d+[.,]\d{2}", raw):
        normalized = raw.replace(",", ".")
    else:
        normalized = raw.replace(".", "").replace(",", ".")
    try:
        amount = Decimal(normalized)
    except (InvalidOperation, ValueError):
        return None
    integer = int(amount)
    return integer if 100 <= integer <= 20_000_000 else None


def _discount(regular: int | None, current: int) -> float:
    if regular is None or regular <= current:
        return 0.0
    return (regular - current) / regular


def _variant_name(title: str, variant: dict[str, Any], total_variants: int) -> str:
    variant_title = _normalize_text(str(variant.get("title") or ""))
    if total_variants <= 1 or variant_title.casefold() in {"", "default title", "default"}:
        return title
    if variant_title.casefold() in title.casefold():
        return title
    return f"{title} · {variant_title}"[:500]


def _parse_shopify_payload(
    payload: dict[str, Any], section_name: str
) -> tuple[dict[str, CollectedProduct], int]:
    """Kept for compatibility and parser tests; browser HTML is the live path."""
    products: dict[str, CollectedProduct] = {}
    raw_products = [item for item in (payload.get("products") or []) if isinstance(item, dict)]
    cards_seen = len(raw_products)
    for raw_product in raw_products:
        title = _normalize_text(str(raw_product.get("title") or ""))
        handle = str(raw_product.get("handle") or "").strip()
        if len(title) < 3 or not handle or _SKIP_PERSONALIZED_RE.search(title):
            continue
        variants = [item for item in (raw_product.get("variants") or []) if isinstance(item, dict)]
        for variant in variants:
            if variant.get("available") is False:
                continue
            current = _money(variant.get("price"))
            if current is None:
                continue
            regular = _money(variant.get("compare_at_price"))
            if regular is not None and regular <= current:
                regular = None
            variant_id = variant.get("id") if len(variants) > 1 else None
            url = _canonical_product_url(handle, variant_id)
            products[url] = CollectedProduct(
                store="Tost",
                name=_variant_name(title, variant, len(variants)),
                url=url,
                current_price=current,
                regular_price=regular,
                discount_pct=_discount(regular, current),
                source_sections=(section_name,),
            )
    return products, cards_seen


def _valid_html_product_link(raw_url: str) -> bool:
    parsed = urlparse(urljoin(BASE_URL, raw_url))
    return parsed.netloc.casefold() in {"tost.cl", "www.tost.cl"} and bool(
        _PRODUCT_PATH_RE.fullmatch(parsed.path)
    )


def _html_price_values(text: str) -> list[int]:
    values: list[int] = []
    cleaned = re.sub(
        r"\$\s*[\d.]+\s*(?:/\s*litros?|cada\s+art[ií]culo)",
        " ",
        text or "",
        flags=re.IGNORECASE,
    )
    for raw in _PRICE_RE.findall(cleaned):
        digits = re.sub(r"\D", "", raw)
        if digits:
            value = int(digits)
            if 100 <= value <= 20_000_000 and value not in values:
                values.append(value)
    return values


def _candidate_card(link: Tag) -> Tag:
    candidate = link
    for parent in link.parents:
        if not isinstance(parent, Tag) or parent.name in {"body", "html", "[document]"}:
            break
        text = _normalize_text(parent.get_text(" ", strip=True))
        links = parent.select("a[href*='/products/']")
        if _html_price_values(text) and len(links) <= 3 and len(text) <= 3_500:
            candidate = parent
            if parent.name in {"article", "li"}:
                break
    return candidate


def _unique_product_handles(root: Tag | BeautifulSoup) -> set[str]:
    handles: set[str] = set()
    for link in root.select("a[href*='/products/']"):
        if not isinstance(link, Tag):
            continue
        href = str(link.get("href") or "")
        if not _valid_html_product_link(href):
            continue
        parsed = urlparse(urljoin(BASE_URL, href))
        handles.add(parsed.path.rstrip("/").rsplit("/", 1)[-1])
    return handles


def _expected_result_count(html: str) -> int | None:
    text = _normalize_text(BeautifulSoup(html, "html.parser").get_text(" ", strip=True))
    patterns = (
        r"Mostrar\s+(\d+)\s+resultados?",
        r"Mostrando\s+\d+\s+de\s+(\d+)",
        r"(\d+)\s+resultados?",
    )
    for pattern in patterns:
        matches = [int(value) for value in re.findall(pattern, text, re.IGNORECASE)]
        if matches:
            return max(matches)
    return None


def _product_grid_root(soup: BeautifulSoup) -> Tag | BeautifulSoup:
    """Prefer the rendered collection grid over the 11-item recommendation rail."""
    priority_groups = (
        (
            "#product-grid",
            "#ProductGridContainer #product-grid",
            "#ProductGridContainer",
            "[id*='main-collection-product-grid' i]",
            "[id*='main-collection' i]",
            "[data-collection-products]",
            "[data-product-grid]",
            ".boost-pfs-filter-products",
            ".collection__product-grid",
        ),
        (".product-grid", "main"),
    )
    for selectors in priority_groups:
        candidates: list[Tag] = []
        seen: set[int] = set()
        for selector in selectors:
            for root in soup.select(selector):
                if isinstance(root, Tag) and id(root) not in seen:
                    seen.add(id(root))
                    candidates.append(root)
        if candidates:
            best = max(candidates, key=lambda root: len(_unique_product_handles(root)))
            if _unique_product_handles(best):
                return best
    return soup


def _parse_html(html: str, section_name: str) -> tuple[dict[str, CollectedProduct], int]:
    soup = BeautifulSoup(html, "html.parser")
    root = _product_grid_root(soup)
    products: dict[str, CollectedProduct] = {}
    links = [
        link
        for link in root.select("a[href*='/products/']")
        if isinstance(link, Tag) and _valid_html_product_link(str(link.get("href") or ""))
    ]
    seen_handles: set[str] = set()
    for link in links:
        href = str(link.get("href") or "")
        parsed = urlparse(urljoin(BASE_URL, href))
        handle = parsed.path.rstrip("/").rsplit("/", 1)[-1]
        if handle in seen_handles:
            continue
        seen_handles.add(handle)
        card = _candidate_card(link)
        text = _normalize_text(card.get_text(" ", strip=True))
        values = _html_price_values(text)
        if not values:
            continue
        heading = card.select_one("h2, h3, h4, [class*='title' i]")
        name = _normalize_text(heading.get_text(" ", strip=True)) if heading else ""
        if len(name) < 3:
            name = _normalize_text(link.get_text(" ", strip=True))
        if len(name) < 3 or _SKIP_PERSONALIZED_RE.search(name):
            continue
        current = min(values)
        higher = [value for value in values if value > current]
        regular = max(higher) if higher else None
        url = _canonical_product_url(handle)
        products[url] = CollectedProduct(
            store="Tost",
            name=name[:500],
            url=url,
            current_price=current,
            regular_price=regular,
            discount_pct=_discount(regular, current),
            source_sections=(section_name,),
        )
    return products, len(seen_handles)


def _discover_page_count(html: str, first_page_cards: int) -> int:
    soup = BeautifulSoup(html, "html.parser")
    discovered = {1}
    for link in soup.select("a[href*='page=']"):
        href = str(link.get("href") or "")
        match = re.search(r"(?:[?&])page=(\d+)", href)
        if match:
            discovered.add(int(match.group(1)))
    total = _expected_result_count(html)
    if total:
        page_size = max(1, first_page_cards)
        discovered.add(math.ceil(total / page_size))
    return max(1, min(MAX_PAGES_PER_SECTION, max(discovered)))


def _collection_url(section: CatalogSection, page_number: int) -> str:
    base = f"{BASE_URL}/collections/{section.handle}"
    return base if page_number == 1 else f"{base}?page={page_number}"


def _merge(existing: CollectedProduct | None, incoming: CollectedProduct) -> CollectedProduct:
    if existing is None:
        return incoming
    sections = tuple(sorted(set(existing.source_sections + incoming.source_sections), key=str.casefold))
    chosen = incoming if incoming.current_price <= existing.current_price else existing
    return replace(chosen, source_sections=sections)


def _health(section_stats: list[SectionStats], product_count: int) -> tuple[str, int]:
    if not section_stats or product_count == 0:
        return "BROKEN", 0
    failed = sum(item.status == "failed" for item in section_stats)
    warnings = sum(item.structural_warning for item in section_stats)
    score = max(0, min(100, 100 - failed * 14 - warnings * 8))
    if product_count < MIN_PLAUSIBLE_PRODUCTS:
        return "BROKEN", min(score, 20)
    if failed == 0 and warnings == 0:
        return "HEALTHY", score
    if failed <= max(2, len(section_stats) // 3) and score >= 55:
        return "DEGRADED", score
    return "BROKEN", score


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


def _dismiss_overlays(page: Page) -> None:
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass
    for selector in (
        "button[aria-label*='cerrar' i]",
        "button[aria-label*='close' i]",
        "[role='dialog'] button:has-text('Cerrar')",
        ".modal button.close",
    ):
        try:
            locator = page.locator(selector).first
            if locator.is_visible(timeout=200):
                locator.click(timeout=800)
        except Exception:
            continue


def _rendered_page_html(
    page: Page,
    section: CatalogSection,
    page_number: int,
    performance: PerformanceSettings,
) -> tuple[str, int | None]:
    ensure_budget(f"Tost {section.name} página {page_number}")
    response = page.goto(
        _collection_url(section, page_number),
        wait_until="domcontentloaded",
        timeout=bounded_timeout_ms(NAVIGATION_TIMEOUT_MS),
    )
    status = response.status if response else None
    if status == 429:
        page.wait_for_timeout(bounded_timeout_ms(5_000))
        response = page.reload(
            wait_until="domcontentloaded",
            timeout=bounded_timeout_ms(NAVIGATION_TIMEOUT_MS),
        )
        status = response.status if response else status
    if status is not None and status >= 400:
        raise RuntimeError(f"HTTP {status} al abrir {_collection_url(section, page_number)}")

    wait_for_any_selector(
        page,
        PRODUCT_SELECTOR,
        timeout_ms=bounded_timeout_ms(performance.product_wait_timeout_ms),
        settle_ms=performance.quick_settle_ms,
    )
    _dismiss_overlays(page)

    started = time.monotonic()
    last_html = page.content()
    while (time.monotonic() - started) * 1000 < MAX_RENDER_WAIT_MS:
        ensure_budget(f"render dinámico de Tost {section.name}")
        html = page.content()
        products, cards = _parse_html(html, section.name)
        expected = _expected_result_count(html)
        threshold = min(expected, 20) if expected else 1
        if cards >= max(1, threshold) and products:
            return html, status
        last_html = html
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(bounded_timeout_ms(RENDER_POLL_MS))
    return last_html, status


def _collect_products() -> CollectionBatch:
    started = time.monotonic()
    all_products: dict[str, CollectedProduct] = {}
    section_stats: list[SectionStats] = []
    pages_visited = cards_seen = duplicates_removed = 0
    aggregate = PhaseMetrics()
    performance = PerformanceSettings.from_env()
    block_stats = ResourceBlockStats()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-background-networking"],
        )
        context = _create_context(browser, performance, block_stats)
        page = context.new_page()
        try:
            for index, section in enumerate(CATALOG_SECTIONS, start=1):
                ensure_budget(f"Tost categoría {section.name}")
                section_started = time.monotonic()
                metrics = PhaseMetrics()
                section_products: set[str] = set()
                section_cards = section_pages = section_duplicates = 0
                status = "success"
                error_message: str | None = None
                structural_warning = False
                previous_signature: tuple[str, ...] = ()
                print(f"Tost categoría {index}/{len(CATALOG_SECTIONS)}: {section.name}", flush=True)

                try:
                    with metrics.measure("browser_navigation_render"):
                        first_html, first_status = _rendered_page_html(
                            page, section, 1, performance
                        )
                    with metrics.measure("parse"):
                        first_products, first_cards = _parse_html(first_html, section.name)
                    expected_total = _expected_result_count(first_html)
                    page_count = _discover_page_count(first_html, first_cards)

                    for page_number in range(1, page_count + 1):
                        if page_number == 1:
                            html, http_status = first_html, first_status
                            page_products, page_cards = first_products, first_cards
                        else:
                            with metrics.measure("browser_navigation_render"):
                                html, http_status = _rendered_page_html(
                                    page, section, page_number, performance
                                )
                            with metrics.measure("parse"):
                                page_products, page_cards = _parse_html(html, section.name)

                        signature = tuple(sorted(page_products))
                        if page_number > 1 and signature == previous_signature:
                            raise RuntimeError(
                                "Tost repitió el mismo conjunto renderizado; "
                                "la paginación dinámica no avanzó."
                            )
                        previous_signature = signature
                        pages_visited += 1
                        section_pages += 1
                        cards_seen += page_cards
                        section_cards += page_cards
                        new_page = 0
                        for url, product in page_products.items():
                            if url in section_products:
                                section_duplicates += 1
                            else:
                                section_products.add(url)
                                new_page += 1
                            if url in all_products:
                                duplicates_removed += 1
                            all_products[url] = _merge(all_products.get(url), product)
                        print(
                            f"Tost {section.key} página {page_number}/{page_count}: "
                            f"HTTP={http_status}, tarjetas={page_cards}, "
                            f"productos={len(page_products)}, nuevos={new_page}, "
                            f"sección={len(section_products)}, global={len(all_products)}",
                            flush=True,
                        )
                        if not page_products:
                            structural_warning = True
                            break
                        if expected_total and len(section_products) >= expected_total:
                            break
                        if page_number < page_count:
                            page.wait_for_timeout(bounded_timeout_ms(700))

                    if expected_total and len(section_products) < min(expected_total, 20):
                        structural_warning = True
                        raise RuntimeError(
                            f"Tost esperaba {expected_total} resultados pero solo renderizó "
                            f"{len(section_products)}."
                        )
                except Exception as exc:
                    status = "failed"
                    error_message = f"{type(exc).__name__}: {exc}"[:1000]
                    print(
                        f"✖ Tost {section.name}: {error_message}. "
                        "Continúa con la siguiente categoría.",
                        file=sys.stderr,
                        flush=True,
                    )

                duration_ms = int((time.monotonic() - section_started) * 1000)
                section_stats.append(
                    SectionStats(
                        key=section.key,
                        name=section.name,
                        url=_collection_url(section, 1),
                        pages_visited=section_pages,
                        cards_seen=section_cards,
                        unique_products=len(section_products),
                        duplicates_removed=section_duplicates,
                        duration_ms=duration_ms,
                        status=status,
                        error_message=error_message,
                        structural_warning=structural_warning,
                        performance_ms=metrics.as_dict(),
                    )
                )

            if not all_products:
                raise RuntimeError("Tost no entregó productos en ninguna categoría.")

            for section in section_stats:
                for name, value in section.performance_ms.items():
                    aggregate.add(name, value)
            aggregate.add("collector_total", int((time.monotonic() - started) * 1000))
            aggregate.add("blocked_requests", block_stats.blocked_requests)
            succeeded = sum(item.status == "success" for item in section_stats)
            failed = len(section_stats) - succeeded
            warnings = sum(item.structural_warning for item in section_stats)
            health_status, health_score = _health(section_stats, len(all_products))
            products = sorted(all_products.values(), key=lambda item: item.name.casefold())
            print(
                f"Resumen Tost: categorías={len(CATALOG_SECTIONS)}, correctas={succeeded}, "
                f"fallidas={failed}, páginas={pages_visited}, tarjetas={cards_seen}, "
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
                    sections_discovered=len(CATALOG_SECTIONS),
                    sections_visited=len(section_stats),
                    sections_succeeded=succeeded,
                    sections_failed=failed,
                    duplicates_removed=duplicates_removed,
                    discovery_source="configured-playwright-rendered-collections",
                    health_status=health_status,
                    health_score=health_score,
                    structural_warnings=warnings,
                    section_stats=tuple(section_stats),
                    performance_ms=aggregate.as_dict(),
                ),
            )
        finally:
            try:
                context.close()
            except Exception:
                pass
            browser.close()


class TostCollector:
    metadata = StoreMetadata(
        name="Tost",
        slug="tost",
        base_url="https://tost.cl/",
        connector_key="tost",
        requires_browser=True,
    )
    key = metadata.connector_key
    store_name = metadata.name

    def collect(self) -> CollectionBatch:
        return _collect_products()


def scrape() -> list[CollectedProduct]:
    return TostCollector().collect().products
