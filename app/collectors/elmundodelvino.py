from __future__ import annotations

import re
import sys
import time
from dataclasses import dataclass, replace
from urllib.parse import urlencode, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup, Tag
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from app.collectors.base import StoreMetadata
from app.deadlines import bounded_request_timeout, ensure_budget
from app.domain import CollectedProduct, CollectionBatch, CollectionStats, SectionStats
from app.performance import PhaseMetrics

BASE_URL = "https://elmundodelvino.cl"
REQUEST_TIMEOUT = (5, 18)
MAX_PAGES_PER_SECTION = 80
MIN_PLAUSIBLE_PRODUCTS = 120


@dataclass(frozen=True)
class CatalogSection:
    key: str
    name: str
    handle: str


CATALOG_SECTIONS: tuple[CatalogSection, ...] = (
    CatalogSection("licores", "Licores", "licores"),
    CatalogSection("whisky", "Whisky", "whisky"),
    CatalogSection("vinos", "Vinos", "vinos"),
    CatalogSection("espumantes", "Espumantes", "espumantes"),
    CatalogSection("cervezas", "Cervezas", "cervezas"),
)

_PRICE_RE = re.compile(r"\$\s*([\d.]+)")


def _session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=2,
        connect=1,
        read=1,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    session.mount("https://", HTTPAdapter(max_retries=retry, pool_connections=8, pool_maxsize=8))
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
            ),
            "Accept-Language": "es-CL,es;q=0.9,en;q=0.7",
        }
    )
    return session


def _normalize_text(value: str) -> str:
    return " ".join((value or "").replace("\xa0", " ").split())


def _fold(value: str) -> str:
    return _normalize_text(value).casefold()


def _product_slug(raw_url: str) -> str | None:
    """Acepta URLs Shopify directas y URLs con prefijo de colección."""
    parsed = urlparse(urljoin(BASE_URL, raw_url))
    if parsed.netloc.casefold() not in {"elmundodelvino.cl", "www.elmundodelvino.cl"}:
        return None
    parts = [part for part in parsed.path.split("/") if part]
    try:
        product_index = next(index for index, part in enumerate(parts) if part.casefold() == "products")
    except StopIteration:
        return None
    if product_index + 1 >= len(parts):
        return None
    slug = parts[product_index + 1].strip()
    if not slug or slug.casefold() in {"search", "all"}:
        return None
    return slug


def _canonical_url(raw_url: str) -> str:
    slug = _product_slug(raw_url)
    if slug is None:
        parsed = urlparse(urljoin(BASE_URL, raw_url))
        path = re.sub(r"/+", "/", parsed.path).rstrip("/")
    else:
        path = f"/products/{slug}"
    return urlunparse(("https", "elmundodelvino.cl", path, "", "", ""))


def _category_url(section: CatalogSection, page: int) -> str:
    base = f"{BASE_URL}/collections/{section.handle}"
    if page <= 1:
        return base
    return f"{base}?{urlencode({'page': page})}"


def _is_product_url(raw_url: str) -> bool:
    return _product_slug(raw_url) is not None


def _price_values(text: str) -> list[int]:
    values: list[int] = []
    cleaned = re.sub(r"Club:\s*\$\s*[\d.]+", " ", text or "", flags=re.IGNORECASE)
    for raw in _PRICE_RE.findall(cleaned):
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
        if _price_values(text) and len(product_links) <= 3 and len(text) <= 3500:
            candidate = parent
            if parent.name in {"article", "li"} or any(
                token in " ".join(parent.get("class") or []).casefold()
                for token in ("card", "product", "grid")
            ):
                break
    return candidate


def _clean_product_name(value: str) -> str:
    value = _normalize_text(value)
    value = re.sub(r"^(?:agotado|oferta\s+\d+%|agregar al carro)\s+", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+\$\s*[\d.]+(?:\s+\$\s*[\d.]+)?\s*$", "", value)
    return value.strip(" -–—")


def _name_from_card(card: Tag, link: Tag) -> str:
    for selector in (
        ".card__heading", ".product-card__title", ".product-item__title",
        "h2", "h3", "h4", "[data-product-title]",
    ):
        node = card.select_one(selector)
        if isinstance(node, Tag):
            value = _clean_product_name(node.get_text(" ", strip=True))
            if len(value) >= 3:
                return value
    return _clean_product_name(link.get_text(" ", strip=True))


def _parse_html(html: str, section_name: str) -> tuple[dict[str, CollectedProduct], int]:
    soup = BeautifulSoup(html, "html.parser")
    products: dict[str, CollectedProduct] = {}
    seen_cards: set[int] = set()
    candidates = 0
    for link in soup.select("a[href*='/products/']"):
        if not isinstance(link, Tag) or not _is_product_url(str(link.get("href") or "")):
            continue
        card = _candidate_card(link)
        identity = id(card)
        if identity in seen_cards:
            continue
        seen_cards.add(identity)
        text = _normalize_text(card.get_text(" ", strip=True))
        prices = _price_values(text)
        name = _name_from_card(card, link)
        if not prices or len(name) < 3:
            continue
        candidates += 1
        folded = _fold(text)
        if "agotado" in folded or "sold out" in folded:
            continue
        current = min(prices)
        higher = [price for price in prices if price > current]
        regular = max(higher) if higher else None
        url = _canonical_url(str(link.get("href") or ""))
        products[url] = CollectedProduct(
            store="El Mundo del Vino",
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
    score = max(0, min(100, 100 - failed * 12 - warnings * 8))
    if failed == 0 and warnings == 0:
        return "HEALTHY", score
    if failed <= 2 and score >= 55:
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
            ensure_budget(f"El Mundo del Vino categoría {section.name}")
            section_started = time.monotonic()
            metrics = PhaseMetrics()
            section_urls: set[str] = set()
            section_pages = section_cards = section_duplicates = 0
            status = "success"
            error_message: str | None = None
            warning = False
            previous_signature: tuple[str, ...] = ()
            print(f"El Mundo del Vino categoría {index}/{len(CATALOG_SECTIONS)}: {section.name}", flush=True)
            try:
                for page_number in range(1, MAX_PAGES_PER_SECTION + 1):
                    ensure_budget(f"El Mundo del Vino {section.name} página {page_number}")
                    url = _category_url(section, page_number)
                    with metrics.measure("http"):
                        response = session.get(url, timeout=bounded_request_timeout(REQUEST_TIMEOUT))
                    if response.status_code == 404 and page_number == 1:
                        raise requests.HTTPError(f"404 categoría inexistente: {url}", response=response)
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
                        f"El Mundo del Vino {section.key} página {page_number}: HTTP={response.status_code}, "
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
                print(f"✖ El Mundo del Vino {section.name}: {error_message}. Continúa.", file=sys.stderr, flush=True)
            duration_ms = int((time.monotonic() - section_started) * 1000)
            section_stats.append(
                SectionStats(
                    key=section.key,
                    name=section.name,
                    url=_category_url(section, 1),
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
        discovery_source="fixed_public_collections",
        health_status=health_status,
        health_score=health_score,
        structural_warnings=sum(item.structural_warning for item in section_stats),
        section_stats=tuple(section_stats),
        performance_ms={**aggregate.as_dict(), "total": duration_ms},
    )
    print(
        f"Resumen El Mundo del Vino: categorías={len(section_stats)}, "
        f"correctas={stats.sections_succeeded}, fallidas={stats.sections_failed}, "
        f"páginas={pages}, productos_únicos={len(all_products)}, salud={health_status}({health_score})",
        flush=True,
    )
    if not all_products:
        raise RuntimeError("El Mundo del Vino no entregó productos en ninguna categoría.")
    return CollectionBatch(products=list(all_products.values()), stats=stats)


class ElMundoDelVinoCollector:
    metadata = StoreMetadata(
        name="El Mundo del Vino",
        slug="el-mundo-del-vino",
        base_url=f"{BASE_URL}/",
        connector_key="elmundodelvino",
        requires_browser=False,
    )
    key = metadata.connector_key
    store_name = metadata.name

    def collect(self) -> CollectionBatch:
        return _collect_products()


def scrape() -> list[CollectedProduct]:
    return ElMundoDelVinoCollector().collect().products
