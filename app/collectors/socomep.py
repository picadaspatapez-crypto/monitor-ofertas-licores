from __future__ import annotations

import random
import re
import sys
import time
import unicodedata
from dataclasses import dataclass, replace
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup, Tag
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from app.collectors.base import StoreMetadata
from app.deadlines import bounded_request_timeout, ensure_budget
from app.domain import CollectedProduct, CollectionBatch, CollectionStats, SectionStats
from app.performance import PhaseMetrics

BASE_URL = "https://socomepcl.cl"
REQUEST_TIMEOUT = (5, 18)
MAX_PAGES_PER_SECTION = 80
MIN_PLAUSIBLE_PRODUCTS = 120


@dataclass(frozen=True)
class CatalogSection:
    key: str
    name: str
    path: str


# Secciones públicas de Jumpseller. Licores contiene whisky, pisco, gin, ron,
# vodka, tequila, cócteles y digestivos; las demás amplían vino, cerveza y
# espumantes sin depender de filtros internos frágiles.
CATALOG_SECTIONS: tuple[CatalogSection, ...] = (
    CatalogSection("licores", "Licores", "/catalogo/licores"),
    CatalogSection("vinos", "Vinos", "/catalogo/vinos"),
    CatalogSection("cervezas", "Cervezas", "/catalogo/cervezas"),
    CatalogSection("espumantes", "Espumantes", "/catalogo/espumantes"),
)

_PRICE_RE = re.compile(r"\$\s*([\d.]+)")
_PAGE_RE = re.compile(r"(?:[?&]page=|/page/)(\d+)", re.IGNORECASE)
_EXCLUDED_ROOTS = {
    "",
    "catalogo",
    "contact",
    "contacto",
    "conocenos",
    "promociones",
    "politicas-de-envio-y-devoluciones",
    "carro",
    "cart",
    "checkout",
    "search",
    "buscar",
    "cuenta",
    "login",
    "ccu",
}


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
    session.mount(
        "https://",
        HTTPAdapter(max_retries=retry, pool_connections=6, pool_maxsize=6),
    )
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
            ),
            "Accept-Language": "es-CL,es;q=0.9,en;q=0.7",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Cookie": "age_gate=1; age-verified=1",
        }
    )
    return session


def _normalize_text(value: str) -> str:
    return " ".join((value or "").replace("\xa0", " ").split())


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    return "".join(ch for ch in normalized if not unicodedata.combining(ch)).casefold()


def _category_url(section: CatalogSection, page: int) -> str:
    base = f"{BASE_URL}{section.path}"
    if page <= 1:
        return base
    return f"{base}?{urlencode({'page': page, 'sorting': 'position-asc'})}"


def _canonical_url(raw_url: str) -> str:
    parsed = urlparse(urljoin(BASE_URL, raw_url))
    path = re.sub(r"/+", "/", parsed.path).rstrip("/")
    return urlunparse(("https", "socomepcl.cl", path, "", "", ""))


def _is_product_url(raw_url: str) -> bool:
    parsed = urlparse(urljoin(BASE_URL, raw_url))
    if parsed.netloc.casefold() not in {"socomepcl.cl", "www.socomepcl.cl"}:
        return False
    parts = [part for part in parsed.path.split("/") if part]
    if not parts:
        return False
    root = parts[0].casefold()
    if root in _EXCLUDED_ROOTS:
        return False
    # Jumpseller normalmente publica productos en /slug. También se tolera
    # /products/slug por si el tema cambia sin abrir rutas de categorías.
    if len(parts) == 1:
        return len(root) > 3
    return len(parts) == 2 and root in {"product", "products", "producto", "productos"}


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


def _candidate_card(heading: Tag) -> Tag:
    candidate = heading
    for parent in heading.parents:
        if not isinstance(parent, Tag) or parent.name in {"body", "html", "[document]"}:
            break
        text = _normalize_text(parent.get_text(" ", strip=True))
        links = [a for a in parent.select("a[href]") if _is_product_url(str(a.get("href") or ""))]
        if _price_values(text) and len(links) <= 4 and len(text) <= 4200:
            candidate = parent
            classes = " ".join(parent.get("class") or []).casefold()
            if parent.name in {"article", "li"} or any(
                word in classes for word in ("product", "item", "card")
            ):
                break
    return candidate


def _product_link(card: Tag, heading: Tag) -> Tag | None:
    parent_link = heading.find_parent("a", href=True)
    if isinstance(parent_link, Tag) and _is_product_url(str(parent_link.get("href") or "")):
        return parent_link
    for link in card.select("a[href]"):
        if _is_product_url(str(link.get("href") or "")):
            return link
    return None


def _parse_html(html: str, section_name: str) -> tuple[dict[str, CollectedProduct], int]:
    soup = BeautifulSoup(html, "html.parser")
    products: dict[str, CollectedProduct] = {}
    seen_cards: set[int] = set()
    candidates = 0

    for heading in soup.select("h2, h3, h4"):
        if not isinstance(heading, Tag):
            continue
        name = _normalize_text(heading.get_text(" ", strip=True))
        if len(name) < 3:
            continue
        card = _candidate_card(heading)
        identity = id(card)
        if identity in seen_cards:
            continue
        link = _product_link(card, heading)
        if link is None:
            continue
        text = _normalize_text(card.get_text(" ", strip=True))
        prices = _price_values(text)
        if not prices:
            continue
        candidates += 1
        seen_cards.add(identity)
        folded = _fold(text)
        if "no disponible" in folded or "agotado" in folded:
            continue
        current = min(prices)
        higher = [price for price in prices if price > current]
        regular = max(higher) if higher else None
        url = _canonical_url(str(link.get("href") or ""))
        products[url] = CollectedProduct(
            store="Socomep",
            name=name[:500],
            url=url,
            current_price=current,
            regular_price=regular,
            discount_pct=_discount(regular, current),
            source_sections=(section_name,),
        )
    return products, candidates


def _detected_last_page(html: str, section: CatalogSection) -> int | None:
    soup = BeautifulSoup(html, "html.parser")
    pages: list[int] = []
    for link in soup.select("a[href]"):
        if not isinstance(link, Tag):
            continue
        href = str(link.get("href") or "")
        parsed = urlparse(urljoin(BASE_URL, href))
        if parsed.path.rstrip("/") != section.path.rstrip("/"):
            continue
        query = parse_qs(parsed.query)
        if query.get("page"):
            try:
                pages.append(int(query["page"][0]))
            except (TypeError, ValueError):
                pass
        else:
            match = _PAGE_RE.search(href)
            if match:
                pages.append(int(match.group(1)))
    return max(pages) if pages else None


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
    score = max(0, min(100, 100 - failed * 18 - warnings * 8))
    if failed == 0 and warnings == 0:
        return "HEALTHY", score
    if failed <= 1 and score >= 55:
        return "DEGRADED", score
    return "BROKEN", min(score, 35)


def _collect_products() -> CollectionBatch:
    started = time.monotonic()
    session = _session()
    all_products: dict[str, CollectedProduct] = {}
    section_stats: list[SectionStats] = []
    aggregate = PhaseMetrics()
    pages = cards = duplicates = 0

    try:
        for index, section in enumerate(CATALOG_SECTIONS, start=1):
            ensure_budget(f"Socomep categoría {section.name}")
            section_started = time.monotonic()
            metrics = PhaseMetrics()
            section_urls: set[str] = set()
            section_pages = section_cards = section_duplicates = 0
            status = "success"
            error_message = None
            warning = False
            previous_signature: tuple[str, ...] | None = None
            detected_last_page: int | None = None
            print(f"Socomep categoría {index}/{len(CATALOG_SECTIONS)}: {section.name}", flush=True)
            try:
                for page_number in range(1, MAX_PAGES_PER_SECTION + 1):
                    ensure_budget(f"Socomep {section.name} página {page_number}")
                    url = _category_url(section, page_number)
                    with metrics.measure("http"):
                        response = session.get(
                            url,
                            timeout=bounded_request_timeout(REQUEST_TIMEOUT),
                        )
                    if response.status_code >= 400:
                        response.raise_for_status()
                    with metrics.measure("parse"):
                        page_products, page_cards = _parse_html(response.text, section.name)
                    if page_number == 1:
                        detected_last_page = _detected_last_page(response.text, section)
                    signature = tuple(sorted(page_products))
                    section_pages += 1
                    pages += 1
                    section_cards += page_cards
                    cards += page_cards
                    if page_number > 1 and signature and signature == previous_signature:
                        warning = True
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
                        f"Socomep {section.key} página {page_number}: HTTP={response.status_code}, "
                        f"tarjetas={page_cards}, productos={len(page_products)}, nuevos={new_page}, "
                        f"sección={len(section_urls)}, global={len(all_products)}",
                        flush=True,
                    )
                    if page_number == 1 and page_cards == 0:
                        warning = True
                    if not page_products or new_page == 0:
                        break
                    if detected_last_page is not None and page_number >= detected_last_page:
                        break
                    # Ritmo conservador para no activar limitaciones del hosting.
                    delay = random.uniform(0.45, 0.85)
                    with metrics.measure("rate_limit_wait"):
                        time.sleep(delay)
            except Exception as exc:
                status = "failed"
                error_message = f"{type(exc).__name__}: {exc}"[:1000]
                print(
                    f"✖ Socomep {section.name}: {error_message}. Continúa con la siguiente categoría.",
                    file=sys.stderr,
                    flush=True,
                )

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
        discovery_source="jumpseller_public_categories",
        health_status=health_status,
        health_score=health_score,
        structural_warnings=sum(item.structural_warning for item in section_stats),
        section_stats=tuple(section_stats),
        performance_ms={**aggregate.as_dict(), "total": duration_ms},
    )
    print(
        f"Resumen Socomep: categorías={len(section_stats)}, correctas={stats.sections_succeeded}, "
        f"fallidas={stats.sections_failed}, páginas={pages}, productos_únicos={len(all_products)}, "
        f"salud={health_status}({health_score})",
        flush=True,
    )
    if not all_products:
        raise RuntimeError("Socomep no entregó productos en ninguna categoría.")
    if health_status == "BROKEN":
        raise RuntimeError(
            f"Socomep entregó una cobertura no confiable ({len(all_products)} productos)."
        )
    return CollectionBatch(products=list(all_products.values()), stats=stats)


class SocomepCollector:
    metadata = StoreMetadata(
        name="Socomep",
        slug="socomep",
        base_url=f"{BASE_URL}/",
        connector_key="socomep",
        requires_browser=False,
    )
    key = metadata.connector_key
    store_name = metadata.name

    def collect(self) -> CollectionBatch:
        return _collect_products()


def scrape() -> list[CollectedProduct]:
    return SocomepCollector().collect().products
