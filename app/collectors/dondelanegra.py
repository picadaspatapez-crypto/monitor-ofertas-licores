from __future__ import annotations

import html as html_lib
import re
import sys
import time
import unicodedata
from dataclasses import dataclass, replace
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup, Tag
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, sync_playwright
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from app.collectors.base import StoreMetadata
from app.deadlines import bounded_request_timeout, ensure_budget
from app.domain import CollectedProduct, CollectionBatch, CollectionStats, SectionStats
from app.performance import PerformanceSettings, PhaseMetrics, install_resource_blocking, wait_for_any_selector

BASE_URL = "https://dondelanegra.cl"
STORE_API_URL = f"{BASE_URL}/wp-json/wc/store/v1/products"
REQUEST_TIMEOUT = (5, 22)
API_PAGE_SIZE = 100
MAX_API_PAGES = 40
MAX_BROWSER_PAGES_PER_SECTION = 50
MIN_PLAUSIBLE_PRODUCTS = 180
PRODUCT_SELECTOR = "a[href*='/producto/']"


@dataclass(frozen=True)
class CatalogSection:
    key: str
    name: str
    slug: str


# Rutas verificadas desde el menú público. La API global es la fuente principal;
# esta lista solo se usa como respaldo de navegador.
CATALOG_SECTIONS: tuple[CatalogSection, ...] = (
    CatalogSection("whiskey", "Whiskey", "whiskey"),
    CatalogSection("vinos", "Vinos", "vinos-y-espumantes"),
    CatalogSection("espumantes", "Espumantes", "espumantes"),
    CatalogSection("cervezas", "Cervezas", "cervezas"),
    CatalogSection("gin", "Gin", "gin"),
    CatalogSection("pisco", "Pisco", "pisco"),
    CatalogSection("destilados-uva", "Destilados de Uva", "destilados-de-uva"),
    CatalogSection("ron", "Ron", "ron"),
    CatalogSection("tequila", "Tequila", "tequilas"),
    CatalogSection("vodka", "Vodka", "vodka"),
    CatalogSection("otros-licores", "Otros Licores", "otros-licores"),
    CatalogSection("cocteleria", "Coctelería", "cocteleria"),
    CatalogSection("packs", "Packs", "packs"),
)

_PRICE_RE = re.compile(r"\$\s*([\d.]+)")
_ALLOWED_CATEGORY_WORDS = (
    "whiskey",
    "whisky",
    "vino",
    "espumante",
    "cerveza",
    "gin",
    "pisco",
    "destilado",
    "ron",
    "tequila",
    "vodka",
    "licor",
    "coctel",
    "cocktail",
    "pack",
    "sour",
)
_EXCLUDED_CATEGORY_WORDS = ("bebida", "energetica", "sin alcohol", "cafe")


def _session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=2,
        connect=1,
        read=1,
        backoff_factor=0.8,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    session.mount("https://", HTTPAdapter(max_retries=retry, pool_connections=6, pool_maxsize=6))
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
            ),
            "Accept-Language": "es-CL,es;q=0.9,en;q=0.7",
            "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
            "Cookie": "age_gate=1; age-verified=1",
        }
    )
    return session


def _normalize_text(value: str) -> str:
    return " ".join(html_lib.unescape((value or "").replace("\xa0", " ")).split())


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    return "".join(ch for ch in normalized if not unicodedata.combining(ch)).casefold()


def _section_url(section: CatalogSection, page: int) -> str:
    root = f"{BASE_URL}/categoria-producto/{section.slug}/"
    return root if page <= 1 else f"{root}page/{page}/"


def _canonical_url(raw_url: str) -> str:
    parsed = urlparse(urljoin(BASE_URL, raw_url))
    path = re.sub(r"/+", "/", parsed.path).rstrip("/")
    return urlunparse(("https", "dondelanegra.cl", path, "", "", ""))


def _is_product_url(raw_url: str) -> bool:
    parsed = urlparse(urljoin(BASE_URL, raw_url))
    return parsed.netloc.casefold() in {"dondelanegra.cl", "www.dondelanegra.cl"} and "/producto/" in parsed.path


def _price_values(text: str) -> list[int]:
    values: list[int] = []
    for raw in _PRICE_RE.findall(text or ""):
        digits = re.sub(r"\D", "", raw)
        if not digits:
            continue
        value = int(digits)
        if 100 <= value <= 20_000_000 and value not in values:
            values.append(value)
    return values


def _discount(regular: int | None, current: int) -> float:
    if regular is None or regular <= current:
        return 0.0
    return (regular - current) / regular


def _candidate_card(link: Tag) -> Tag:
    candidate = link
    for parent in link.parents:
        if not isinstance(parent, Tag) or parent.name in {"body", "html", "[document]"}:
            break
        text = _normalize_text(parent.get_text(" ", strip=True))
        links = [a for a in parent.select("a[href]") if _is_product_url(str(a.get("href") or ""))]
        if _price_values(text) and len(links) <= 4 and len(text) <= 4200:
            candidate = parent
            classes = " ".join(parent.get("class") or []).casefold()
            if parent.name in {"article", "li"} or "product" in classes:
                break
    return candidate


def _name_from_card(card: Tag, link: Tag) -> str:
    for selector in ("h1", "h2", "h3", "h4", ".woocommerce-loop-product__title", "[class*='title']"):
        node = card.select_one(selector)
        if isinstance(node, Tag):
            value = _normalize_text(node.get_text(" ", strip=True))
            if len(value) >= 3:
                return value
    value = _normalize_text(str(link.get("title") or link.get("aria-label") or ""))
    if len(value) >= 3:
        return value
    image = link.find("img")
    if isinstance(image, Tag):
        value = _normalize_text(str(image.get("alt") or ""))
        if len(value) >= 3:
            return value
    return _normalize_text(link.get_text(" ", strip=True))


def _parse_html(html: str, section_name: str) -> tuple[dict[str, CollectedProduct], int]:
    soup = BeautifulSoup(html, "html.parser")
    products: dict[str, CollectedProduct] = {}
    cards_seen: set[int] = set()
    candidates = 0
    for link in soup.select("a[href]"):
        if not isinstance(link, Tag) or not _is_product_url(str(link.get("href") or "")):
            continue
        card = _candidate_card(link)
        card_id = id(card)
        if card_id in cards_seen:
            continue
        text = _normalize_text(card.get_text(" ", strip=True))
        prices = _price_values(text)
        name = _name_from_card(card, link)
        if not prices or len(name) < 3:
            continue
        candidates += 1
        cards_seen.add(card_id)
        current = min(prices)
        higher = [price for price in prices if price > current]
        regular = max(higher) if higher else None
        url = _canonical_url(str(link.get("href") or ""))
        products[url] = CollectedProduct(
            store="Donde La Negra",
            name=name[:500],
            url=url,
            current_price=current,
            regular_price=regular,
            discount_pct=_discount(regular, current),
            source_sections=(section_name,),
        )
    return products, candidates


def _api_money(raw: Any, minor_unit: int) -> int | None:
    if raw is None or raw == "":
        return None
    try:
        value = int(str(raw))
    except (TypeError, ValueError):
        return None
    divisor = 10 ** max(0, min(minor_unit, 4))
    result = round(value / divisor)
    return result if 100 <= result <= 20_000_000 else None


def _api_categories(item: dict[str, Any]) -> tuple[str, ...]:
    names: list[str] = []
    for category in item.get("categories") or []:
        if not isinstance(category, dict):
            continue
        value = _normalize_text(str(category.get("name") or category.get("slug") or ""))
        if value and value not in names:
            names.append(value)
    return tuple(names)


def _is_relevant_api_product(categories: tuple[str, ...], name: str) -> bool:
    folded = _fold(" ".join(categories) + " " + name)
    if any(word in folded for word in _EXCLUDED_CATEGORY_WORDS):
        return False
    return any(word in folded for word in _ALLOWED_CATEGORY_WORDS)


def _parse_store_api_products(payload: Any) -> dict[str, CollectedProduct]:
    if not isinstance(payload, list):
        return {}
    products: dict[str, CollectedProduct] = {}
    for item in payload:
        if not isinstance(item, dict):
            continue
        name = _normalize_text(str(item.get("name") or ""))
        permalink = str(item.get("permalink") or "")
        categories = _api_categories(item)
        if len(name) < 3 or not permalink or not _is_relevant_api_product(categories, name):
            continue
        prices = item.get("prices") if isinstance(item.get("prices"), dict) else {}
        minor_unit = int(prices.get("currency_minor_unit") or 0)
        current = _api_money(prices.get("price"), minor_unit)
        regular = _api_money(prices.get("regular_price"), minor_unit)
        sale = _api_money(prices.get("sale_price"), minor_unit)
        if sale is not None and (current is None or sale < current):
            current = sale
        if current is None:
            continue
        if regular is not None and regular <= current:
            regular = None
        url = _canonical_url(permalink)
        products[url] = CollectedProduct(
            store="Donde La Negra",
            name=name[:500],
            url=url,
            current_price=current,
            regular_price=regular,
            discount_pct=_discount(regular, current),
            sku=(_normalize_text(str(item.get("sku") or ""))[:120] or None),
            source_sections=categories or ("Catálogo general",),
        )
    return products


def _merge(existing: CollectedProduct | None, incoming: CollectedProduct) -> CollectedProduct:
    if existing is None:
        return incoming
    sections = tuple(sorted(set(existing.source_sections + incoming.source_sections), key=str.casefold))
    chosen = incoming if incoming.current_price <= existing.current_price else existing
    return replace(chosen, source_sections=sections)


def _health(section_stats: list[SectionStats], product_count: int) -> tuple[str, int]:
    if product_count < MIN_PLAUSIBLE_PRODUCTS:
        return "BROKEN", 20 if product_count else 0
    failed = sum(item.status != "success" for item in section_stats)
    warnings = sum(item.structural_warning for item in section_stats)
    score = max(0, min(100, 100 - failed * 8 - warnings * 5))
    if failed == 0 and warnings == 0:
        return "HEALTHY", score
    if failed <= 3 and score >= 55:
        return "DEGRADED", score
    return "BROKEN", score


def _collect_via_store_api(session: requests.Session) -> CollectionBatch | None:
    started = time.monotonic()
    metrics = PhaseMetrics()
    all_products: dict[str, CollectedProduct] = {}
    pages = cards = duplicates = 0
    total_pages: int | None = None
    warning_message: str | None = None

    for page_number in range(1, MAX_API_PAGES + 1):
        ensure_budget(f"Donde La Negra Store API página {page_number}")
        params = {"per_page": API_PAGE_SIZE, "page": page_number, "orderby": "id", "order": "asc"}
        try:
            with metrics.measure("api_http"):
                response = session.get(
                    STORE_API_URL,
                    params=params,
                    timeout=bounded_request_timeout(REQUEST_TIMEOUT),
                )
        except Exception as exc:
            if page_number == 1:
                print(
                    f"⚠ Donde La Negra Store API no accesible: {type(exc).__name__}: {exc}. "
                    "Se prueba navegador.",
                    file=sys.stderr,
                    flush=True,
                )
                return None
            warning_message = f"{type(exc).__name__}: {exc}"[:1000]
            break

        if page_number == 1 and response.status_code in {401, 403, 404, 405}:
            print(
                f"⚠ Donde La Negra Store API respondió HTTP {response.status_code}; se prueba navegador.",
                file=sys.stderr,
                flush=True,
            )
            return None
        if response.status_code == 400 and page_number > 1:
            break
        try:
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            if page_number == 1:
                print(
                    f"⚠ Donde La Negra Store API no utilizable: {type(exc).__name__}: {exc}. "
                    "Se prueba navegador.",
                    file=sys.stderr,
                    flush=True,
                )
                return None
            warning_message = f"{type(exc).__name__}: {exc}"[:1000]
            break

        if total_pages is None:
            try:
                total_pages = int(response.headers.get("X-WP-TotalPages") or 0) or None
            except ValueError:
                total_pages = None
        with metrics.measure("api_parse"):
            page_products = _parse_store_api_products(payload)
        cards += len(payload) if isinstance(payload, list) else 0
        pages += 1
        before = len(all_products)
        for url, product in page_products.items():
            if url in all_products:
                duplicates += 1
            all_products[url] = _merge(all_products.get(url), product)
        print(
            f"Donde La Negra Store API página {page_number}"
            f"/{total_pages or '?'}: HTTP={response.status_code}, registros={len(payload) if isinstance(payload, list) else 0}, "
            f"productos={len(page_products)}, nuevos={len(all_products) - before}, global={len(all_products)}",
            flush=True,
        )
        if not isinstance(payload, list) or len(payload) < API_PAGE_SIZE:
            break
        if total_pages is not None and page_number >= total_pages:
            break
    else:
        warning_message = f"Se alcanzó MAX_API_PAGES={MAX_API_PAGES}."

    if not all_products:
        return None
    duration_ms = int((time.monotonic() - started) * 1000)
    complete = warning_message is None and (total_pages is None or pages >= total_pages)
    health_status = "HEALTHY" if complete and len(all_products) >= MIN_PLAUSIBLE_PRODUCTS else "DEGRADED"
    health_score = 100 if health_status == "HEALTHY" else 78
    section = SectionStats(
        key="store-api-global",
        name="Catálogo global WooCommerce",
        url=STORE_API_URL,
        pages_visited=pages,
        cards_seen=cards,
        unique_products=len(all_products),
        duplicates_removed=duplicates,
        duration_ms=duration_ms,
        status="success" if complete else "partial",
        error_message=warning_message,
        structural_warning=not complete,
        performance_ms=metrics.as_dict(),
    )
    stats = CollectionStats(
        pages_visited=pages,
        cards_seen=cards,
        unique_products=len(all_products),
        sections_discovered=1,
        sections_visited=1,
        sections_succeeded=int(complete),
        sections_failed=int(not complete),
        duplicates_removed=duplicates,
        discovery_source="woocommerce_store_api",
        health_status=health_status,
        health_score=health_score,
        structural_warnings=int(not complete),
        section_stats=(section,),
        performance_ms={**metrics.as_dict(), "total": duration_ms},
    )
    print(
        f"Resumen Donde La Negra: fuente=woocommerce_store_api, páginas={pages}, "
        f"productos_únicos={len(all_products)}, salud={health_status}({health_score})",
        flush=True,
    )
    return CollectionBatch(products=list(all_products.values()), stats=stats)


def _accept_age_gate(page) -> None:
    for pattern in ("Sí, quiero descubrir la felicidad", "Sí, soy mayor", "Tengo más de 18"):
        try:
            button = page.get_by_text(re.compile(pattern, re.IGNORECASE)).first
            if button.count() and button.is_visible():
                button.click(timeout=2_500)
                page.wait_for_timeout(300)
                return
        except Exception:
            continue


def _collect_via_browser() -> CollectionBatch:
    started = time.monotonic()
    settings = PerformanceSettings.from_env()
    all_products: dict[str, CollectedProduct] = {}
    section_stats: list[SectionStats] = []
    pages = cards = duplicates = 0
    aggregate = PhaseMetrics()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(locale="es-CL", timezone_id="America/Santiago")
        install_resource_blocking(context, enabled=settings.block_browser_resources)
        page = context.new_page()
        page.set_default_timeout(settings.product_wait_timeout_ms)
        try:
            for index, section in enumerate(CATALOG_SECTIONS, start=1):
                ensure_budget(f"Donde La Negra navegador {section.name}")
                section_started = time.monotonic()
                metrics = PhaseMetrics()
                section_urls: set[str] = set()
                section_pages = section_cards = section_duplicates = 0
                status = "success"
                error_message: str | None = None
                warning = False
                print(
                    f"Donde La Negra navegador categoría {index}/{len(CATALOG_SECTIONS)}: {section.name}",
                    flush=True,
                )
                try:
                    for page_number in range(1, MAX_BROWSER_PAGES_PER_SECTION + 1):
                        ensure_budget(f"Donde La Negra navegador {section.name} página {page_number}")
                        url = _section_url(section, page_number)
                        with metrics.measure("browser_navigation"):
                            response = page.goto(url, wait_until="domcontentloaded", timeout=25_000)
                            _accept_age_gate(page)
                            wait_for_any_selector(
                                page,
                                PRODUCT_SELECTOR,
                                timeout_ms=settings.product_wait_timeout_ms,
                                settle_ms=settings.quick_settle_ms,
                            )
                        with metrics.measure("browser_parse"):
                            page_products, page_cards = _parse_html(page.content(), section.name)
                        pages += 1
                        section_pages += 1
                        cards += page_cards
                        section_cards += page_cards
                        new_page = 0
                        for product_url, product in page_products.items():
                            if product_url in section_urls:
                                section_duplicates += 1
                            else:
                                section_urls.add(product_url)
                                new_page += 1
                            if product_url in all_products:
                                duplicates += 1
                            all_products[product_url] = _merge(all_products.get(product_url), product)
                        code = response.status if response is not None else None
                        print(
                            f"Donde La Negra navegador {section.key} página {page_number}: "
                            f"HTTP={code}, tarjetas={page_cards}, productos={len(page_products)}, "
                            f"nuevos={new_page}, global={len(all_products)}",
                            flush=True,
                        )
                        if not page_products or new_page == 0:
                            if page_number == 1:
                                warning = True
                            break
                except (PlaywrightTimeoutError, Exception) as exc:
                    status = "failed"
                    error_message = f"{type(exc).__name__}: {exc}"[:1000]
                    print(
                        f"✖ Donde La Negra navegador {section.name}: {error_message}. Continúa.",
                        file=sys.stderr,
                        flush=True,
                    )
                duration_ms = int((time.monotonic() - section_started) * 1000)
                section_stats.append(
                    SectionStats(
                        key=section.key,
                        name=section.name,
                        url=_section_url(section, 1),
                        pages_visited=section_pages,
                        cards_seen=section_cards,
                        unique_products=len(section_urls),
                        duplicates_removed=section_duplicates,
                        duration_ms=duration_ms,
                        status=status,
                        error_message=error_message,
                        structural_warning=warning,
                        performance_ms=metrics.as_dict(),
                    )
                )
                aggregate.merge(metrics)
        finally:
            context.close()
            browser.close()

    health_status, health_score = _health(section_stats, len(all_products))
    duration_ms = int((time.monotonic() - started) * 1000)
    stats = CollectionStats(
        pages_visited=pages,
        cards_seen=cards,
        unique_products=len(all_products),
        sections_discovered=len(CATALOG_SECTIONS),
        sections_visited=len(section_stats),
        sections_succeeded=sum(item.status == "success" for item in section_stats),
        sections_failed=sum(item.status != "success" for item in section_stats),
        duplicates_removed=duplicates,
        discovery_source="playwright_fallback",
        health_status=health_status,
        health_score=health_score,
        structural_warnings=sum(item.structural_warning for item in section_stats),
        section_stats=tuple(section_stats),
        performance_ms={**aggregate.as_dict(), "total": duration_ms},
    )
    print(
        f"Resumen Donde La Negra: fuente=playwright_fallback, categorías={len(section_stats)}, "
        f"productos_únicos={len(all_products)}, salud={health_status}({health_score})",
        flush=True,
    )
    if not all_products:
        raise RuntimeError("Donde La Negra no entregó productos mediante API ni navegador.")
    return CollectionBatch(products=list(all_products.values()), stats=stats)


def _collect_products() -> CollectionBatch:
    session = _session()
    try:
        api_batch = _collect_via_store_api(session)
    finally:
        session.close()
    if api_batch is not None:
        return api_batch
    return _collect_via_browser()


class DondeLaNegraCollector:
    metadata = StoreMetadata(
        name="Donde La Negra",
        slug="donde-la-negra",
        base_url=f"{BASE_URL}/",
        connector_key="dondelanegra",
        requires_browser=True,
    )
    key = metadata.connector_key
    store_name = metadata.name

    def collect(self) -> CollectionBatch:
        return _collect_products()


def scrape() -> list[CollectedProduct]:
    return DondeLaNegraCollector().collect().products
