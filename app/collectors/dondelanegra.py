from __future__ import annotations

import re
import sys
import time
import unicodedata
from dataclasses import dataclass, replace
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup, Tag
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from app.collectors.base import StoreMetadata
from app.deadlines import bounded_request_timeout, ensure_budget
from app.domain import CollectedProduct, CollectionBatch, CollectionStats, SectionStats
from app.performance import PhaseMetrics

BASE_URL = "https://dondelanegra.cl"
REQUEST_TIMEOUT = (5, 20)
MAX_PAGES_PER_SECTION = 80
MIN_PLAUSIBLE_PRODUCTS = 180


@dataclass(frozen=True)
class CatalogSection:
    key: str
    name: str
    slug: str


CATALOG_SECTIONS: tuple[CatalogSection, ...] = (
    CatalogSection("whiskey", "Whiskey", "whiskey"),
    CatalogSection("vinos", "Vinos", "vinos-y-espumantes"),
    CatalogSection("espumantes", "Espumantes", "espumantes"),
    CatalogSection("cervezas", "Cervezas", "cervezas"),
    CatalogSection("gin", "Gin", "gin"),
    CatalogSection("pisco", "Pisco", "pisco"),
    CatalogSection("destilados-uva", "Destilados de Uva", "destilados-de-uva"),
    CatalogSection("ron", "Ron", "ron"),
    CatalogSection("tequila", "Tequila", "tequila"),
    CatalogSection("vodka", "Vodka", "vodka"),
    CatalogSection("otros-licores", "Otros Licores", "otros-licores"),
    CatalogSection("cocteleria", "Coctelería", "cocteleria"),
    CatalogSection("packs", "Packs", "packs"),
    CatalogSection("premium", "Licores Premium", "licores-premium"),
)

_PRICE_RE = re.compile(r"\$\s*([\d.]+)")


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
            "Cookie": "age_gate=1; age-verified=1",
        }
    )
    return session


def _normalize_text(value: str) -> str:
    return " ".join((value or "").replace("\xa0", " ").split())


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


def _collect_products() -> CollectionBatch:
    started = time.monotonic()
    session = _session()
    all_products: dict[str, CollectedProduct] = {}
    section_stats: list[SectionStats] = []
    pages = cards = duplicates = 0
    aggregate = PhaseMetrics()
    try:
        for index, section in enumerate(CATALOG_SECTIONS, start=1):
            ensure_budget(f"Donde La Negra categoría {section.name}")
            section_started = time.monotonic()
            metrics = PhaseMetrics()
            section_urls: set[str] = set()
            section_pages = section_cards = section_duplicates = 0
            status = "success"
            error_message: str | None = None
            warning = False
            previous_signature: tuple[str, ...] = ()
            print(f"Donde La Negra categoría {index}/{len(CATALOG_SECTIONS)}: {section.name}", flush=True)
            try:
                for page_number in range(1, MAX_PAGES_PER_SECTION + 1):
                    ensure_budget(f"Donde La Negra {section.name} página {page_number}")
                    url = _section_url(section, page_number)
                    with metrics.measure("http"):
                        response = session.get(url, timeout=bounded_request_timeout(REQUEST_TIMEOUT))
                    if response.status_code == 404 and page_number > 1:
                        break
                    response.raise_for_status()
                    with metrics.measure("parse"):
                        page_products, page_cards = _parse_html(response.text, section.name)
                    signature = tuple(sorted(page_products))
                    pages += 1
                    section_pages += 1
                    cards += page_cards
                    section_cards += page_cards
                    if page_number > 1 and (not signature or signature == previous_signature):
                        break
                    previous_signature = signature
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
                    print(
                        f"Donde La Negra {section.key} página {page_number}: HTTP={response.status_code}, "
                        f"tarjetas={page_cards}, productos={len(page_products)}, nuevos={new_page}, "
                        f"sección={len(section_urls)}, global={len(all_products)}",
                        flush=True,
                    )
                    if page_number == 1 and page_cards == 0:
                        warning = True
                    if not page_products or new_page == 0:
                        break
            except Exception as exc:
                status = "failed"
                error_message = f"{type(exc).__name__}: {exc}"[:1000]
                print(f"✖ Donde La Negra {section.name}: {error_message}. Continúa.", file=sys.stderr, flush=True)
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
        session.close()

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
        discovery_source="fixed_woocommerce_categories",
        health_status=health_status,
        health_score=health_score,
        structural_warnings=sum(item.structural_warning for item in section_stats),
        section_stats=tuple(section_stats),
        performance_ms={**aggregate.as_dict(), "total": duration_ms},
    )
    print(
        f"Resumen Donde La Negra: categorías={len(section_stats)}, correctas={stats.sections_succeeded}, "
        f"fallidas={stats.sections_failed}, páginas={pages}, productos_únicos={len(all_products)}, "
        f"salud={health_status}({health_score})",
        flush=True,
    )
    if not all_products:
        raise RuntimeError("Donde La Negra no entregó productos en ninguna categoría.")
    return CollectionBatch(products=list(all_products.values()), stats=stats)


class DondeLaNegraCollector:
    metadata = StoreMetadata(
        name="Donde La Negra",
        slug="donde-la-negra",
        base_url=f"{BASE_URL}/",
        connector_key="dondelanegra",
        requires_browser=False,
    )
    key = metadata.connector_key
    store_name = metadata.name

    def collect(self) -> CollectionBatch:
        return _collect_products()


def scrape() -> list[CollectedProduct]:
    return DondeLaNegraCollector().collect().products
