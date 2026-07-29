from __future__ import annotations

import re
import sys
import time
import unicodedata
from dataclasses import dataclass, replace
from urllib.parse import urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup, Tag
from playwright.sync_api import sync_playwright

from app.collectors.base import StoreMetadata
from app.deadlines import ensure_budget
from app.domain import CollectedProduct, CollectionBatch, CollectionStats, SectionStats
from app.performance import (
    PerformanceSettings,
    PhaseMetrics,
    install_resource_blocking,
    wait_for_any_selector,
    wait_for_product_count_growth,
)

BASE_URL = "https://labarra.cl"
MIN_PLAUSIBLE_PRODUCTS = 60
MAX_EXPANSION_ROUNDS = 35
PRODUCT_SELECTOR = "a[href*='/producto/']"


@dataclass(frozen=True)
class CatalogSection:
    key: str
    name: str
    url: str


CATALOG_SECTIONS: tuple[CatalogSection, ...] = (
    CatalogSection("licores", "Licores", f"{BASE_URL}/categoria/759"),
    CatalogSection("vinos-espumantes", "Vinos y Espumantes", f"{BASE_URL}/categoria/293"),
    CatalogSection("cervezas", "Cervezas", f"{BASE_URL}/categoria/cervezas"),
)

_PRICE_RE = re.compile(r"\$\s*([\d.]+)")


def _normalize_text(value: str) -> str:
    return " ".join((value or "").replace("\xa0", " ").split())


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    return "".join(ch for ch in normalized if not unicodedata.combining(ch)).casefold()


def _canonical_url(raw_url: str) -> str:
    parsed = urlparse(urljoin(BASE_URL, raw_url))
    path = re.sub(r"/+", "/", parsed.path).rstrip("/")
    return urlunparse(("https", "labarra.cl", path, "", "", ""))


def _is_product_url(raw_url: str) -> bool:
    parsed = urlparse(urljoin(BASE_URL, raw_url))
    return parsed.netloc.casefold() in {"labarra.cl", "www.labarra.cl"} and "/producto/" in parsed.path


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
        product_links = [a for a in parent.select("a[href]") if _is_product_url(str(a.get("href") or ""))]
        if _price_values(text) and len(product_links) <= 4 and len(text) <= 4500:
            candidate = parent
            classes = " ".join(parent.get("class") or []).casefold()
            if parent.name in {"article", "li"} or any(word in classes for word in ("product", "card", "item")):
                break
    return candidate


def _name_from_card(card: Tag, link: Tag) -> str:
    for selector in ("h1", "h2", "h3", "h4", "[class*='name']", "[class*='title']"):
        node = card.select_one(selector)
        if isinstance(node, Tag):
            value = _normalize_text(node.get_text(" ", strip=True))
            if len(value) >= 3:
                return value
    for attr in ("title", "aria-label"):
        value = _normalize_text(str(link.get(attr) or ""))
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
            store="La Barra",
            name=name[:500],
            url=url,
            current_price=current,
            regular_price=regular,
            discount_pct=_discount(regular, current),
            source_sections=(section_name,),
        )
    return products, candidates


def _merge(existing: CollectedProduct | None, incoming: CollectedProduct) -> CollectedProduct:
    if existing is None:
        return incoming
    sections = tuple(sorted(set(existing.source_sections + incoming.source_sections), key=str.casefold))
    chosen = incoming if incoming.current_price <= existing.current_price else existing
    return replace(chosen, source_sections=sections)


def _expand_catalog(page, settings: PerformanceSettings) -> int:
    rounds = 0
    stable = 0
    previous_count = page.locator(PRODUCT_SELECTOR).count()
    while rounds < MAX_EXPANSION_ROUNDS and stable < 3:
        ensure_budget("La Barra expansión dinámica")
        rounds += 1
        clicked = False
        for label in ("cargar más", "ver más", "mostrar más", "más productos"):
            button = page.get_by_text(re.compile(label, re.IGNORECASE)).last
            try:
                if button.count() and button.is_visible() and button.is_enabled():
                    button.click(timeout=2_000)
                    clicked = True
                    break
            except Exception:
                continue
        try:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        except Exception:
            pass
        grew = wait_for_product_count_growth(
            page,
            PRODUCT_SELECTOR,
            previous_count,
            timeout_ms=settings.dom_growth_timeout_ms,
        )
        current_count = page.locator(PRODUCT_SELECTOR).count()
        if grew or current_count > previous_count:
            previous_count = current_count
            stable = 0
        else:
            stable += 1
            page.wait_for_timeout(max(settings.quick_settle_ms, 350 if clicked else 200))
    return rounds


def _health(section_stats: list[SectionStats], product_count: int) -> tuple[str, int]:
    if product_count < MIN_PLAUSIBLE_PRODUCTS:
        return "BROKEN", 20 if product_count else 0
    failed = sum(item.status != "success" for item in section_stats)
    warnings = sum(item.structural_warning for item in section_stats)
    score = max(0, min(100, 100 - failed * 18 - warnings * 8))
    if failed == 0 and warnings == 0:
        return "HEALTHY", score
    if failed <= 1 and score >= 55:
        return "DEGRADED", score
    return "BROKEN", score


def _collect_products() -> CollectionBatch:
    started = time.monotonic()
    settings = PerformanceSettings.from_env()
    all_products: dict[str, CollectedProduct] = {}
    section_stats: list[SectionStats] = []
    pages = cards = duplicates = 0
    aggregate = PhaseMetrics()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(locale="es-CL", timezone_id="America/Santiago")
        block_stats = install_resource_blocking(
            context, enabled=settings.block_browser_resources
        )
        page = context.new_page()
        page.set_default_timeout(settings.product_wait_timeout_ms)
        try:
            for index, section in enumerate(CATALOG_SECTIONS, start=1):
                ensure_budget(f"La Barra categoría {section.name}")
                section_started = time.monotonic()
                metrics = PhaseMetrics()
                status = "success"
                error_message: str | None = None
                warning = False
                section_products: dict[str, CollectedProduct] = {}
                print(f"La Barra categoría {index}/{len(CATALOG_SECTIONS)}: {section.name}", flush=True)
                try:
                    with metrics.measure("navigation_wait"):
                        response = page.goto(section.url, wait_until="domcontentloaded", timeout=25_000)
                        wait_for_any_selector(
                            page,
                            PRODUCT_SELECTOR,
                            timeout_ms=settings.product_wait_timeout_ms,
                            settle_ms=settings.quick_settle_ms,
                        )
                    with metrics.measure("scroll_expand"):
                        rounds = _expand_catalog(page, settings)
                    with metrics.measure("parse"):
                        section_products, section_cards = _parse_html(page.content(), section.name)
                    pages += 1
                    cards += section_cards
                    warning = not section_products
                    for url, product in section_products.items():
                        if url in all_products:
                            duplicates += 1
                        all_products[url] = _merge(all_products.get(url), product)
                    code = response.status if response is not None else None
                    print(
                        f"La Barra {section.key}: HTTP={code}, rondas={rounds}, "
                        f"tarjetas={section_cards}, productos={len(section_products)}, global={len(all_products)}",
                        flush=True,
                    )
                except Exception as exc:
                    status = "failed"
                    error_message = f"{type(exc).__name__}: {exc}"[:1000]
                    print(f"✖ La Barra {section.name}: {error_message}. Continúa.", file=sys.stderr, flush=True)
                duration_ms = int((time.monotonic() - section_started) * 1000)
                section_stats.append(
                    SectionStats(
                        key=section.key,
                        name=section.name,
                        url=section.url,
                        pages_visited=1 if status == "success" else 0,
                        cards_seen=len(section_products),
                        unique_products=len(section_products),
                        duplicates_removed=0,
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

    duration_ms = int((time.monotonic() - started) * 1000)
    health_status, health_score = _health(section_stats, len(all_products))
    stats = CollectionStats(
        pages_visited=pages,
        cards_seen=cards,
        unique_products=len(all_products),
        sections_discovered=len(CATALOG_SECTIONS),
        sections_visited=len(section_stats),
        sections_succeeded=sum(item.status == "success" for item in section_stats),
        sections_failed=sum(item.status != "success" for item in section_stats),
        duplicates_removed=duplicates,
        discovery_source="fixed_dynamic_root_categories",
        health_status=health_status,
        health_score=health_score,
        structural_warnings=sum(item.structural_warning for item in section_stats),
        section_stats=tuple(section_stats),
        performance_ms={
            **aggregate.as_dict(),
            "blocked_requests": block_stats.blocked_requests,
            "total": duration_ms,
        },
    )
    print(
        f"Resumen La Barra: categorías={len(section_stats)}, correctas={stats.sections_succeeded}, "
        f"fallidas={stats.sections_failed}, productos_únicos={len(all_products)}, "
        f"salud={health_status}({health_score})",
        flush=True,
    )
    if not all_products:
        raise RuntimeError("La Barra no entregó productos en ninguna categoría.")
    return CollectionBatch(products=list(all_products.values()), stats=stats)


class LaBarraCollector:
    metadata = StoreMetadata(
        name="La Barra",
        slug="la-barra",
        base_url=f"{BASE_URL}/",
        connector_key="labarra",
        requires_browser=True,
    )
    key = metadata.connector_key
    store_name = metadata.name

    def collect(self) -> CollectionBatch:
        return _collect_products()


def scrape() -> list[CollectedProduct]:
    return LaBarraCollector().collect().products
