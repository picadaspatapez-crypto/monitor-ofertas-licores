from __future__ import annotations

import re
import sys
import time
import unicodedata
from dataclasses import dataclass, replace
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup, Tag
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from app.collectors.base import StoreMetadata
from app.deadlines import bounded_request_timeout, ensure_budget
from app.domain import CollectedProduct, CollectionBatch, CollectionStats, SectionStats
from app.performance import PhaseMetrics


BASE_URL = "https://www.gradounico.cl"
REQUEST_ORIGINS: tuple[str, ...] = (
    "https://www.gradounico.cl",
    "https://gradounico.cl",
)
REQUEST_TIMEOUT = (5, 18)
PREFLIGHT_TIMEOUT = (4, 8)
MAX_PAGES_PER_SECTION = 100
MAX_CONSECUTIVE_CONNECTION_FAILURES = 2


@dataclass(frozen=True)
class CatalogSection:
    key: str
    name: str
    path: str


CATALOG_SECTIONS: tuple[CatalogSection, ...] = (
    CatalogSection("packs", "Packs", "/packs"),
    CatalogSection("piscos", "Piscos", "/piscos"),
    CatalogSection("whisky", "Whisky", "/whisky"),
    CatalogSection("gin", "Gin", "/gin"),
    CatalogSection("vodka", "Vodka", "/vodka"),
    CatalogSection("ron", "Ron", "/ron"),
    CatalogSection("licores", "Licores", "/licores"),
    CatalogSection("tequila", "Tequila", "/tequila"),
    CatalogSection("vinos", "Vinos", "/vinos"),
    CatalogSection("espumantes", "Espumantes", "/espumantes"),
    CatalogSection("cervezas", "Cervezas", "/cervezas"),
)

_PRICE_RE = re.compile(r"\$\s*([\d.]+)")
_EXCLUDED_PATHS = {
    "",
    "inicio",
    "ofertas",
    "packs",
    "piscos",
    "whisky",
    "gin",
    "vodka",
    "ron",
    "licores",
    "tequila",
    "vinos",
    "espumantes",
    "cervezas",
    "tienda",
    "carro",
    "cart",
    "buscar",
    "search",
    "contacto",
    "quienes-somos",
    "politica-de-envio",
    "cambios-y-devoluciones",
    "politica-de-privacidad",
    "terminos-y-condiciones",
}


def _session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=2,
        connect=1,
        read=2,
        backoff_factor=0.4,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        raise_on_status=False,
    )
    session.mount("https://", HTTPAdapter(max_retries=retry, pool_connections=8, pool_maxsize=8))
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "es-CL,es;q=0.9,en;q=0.7",
        }
    )
    return session


def _normalize_text(value: str) -> str:
    return " ".join((value or "").replace("\xa0", " ").split())


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    return "".join(ch for ch in normalized if not unicodedata.combining(ch)).casefold()


def _canonical_url(raw_url: str) -> str:
    parsed = urlparse(urljoin(BASE_URL, raw_url))
    path = re.sub(r"/+", "/", parsed.path).rstrip("/")
    return urlunparse(("https", "www.gradounico.cl", path, "", "", ""))


def _category_url(
    section: CatalogSection,
    page: int,
    *,
    origin: str = BASE_URL,
) -> str:
    query = urlencode({"page": page})
    return f"{origin.rstrip('/')}{section.path}?{query}"


def _probe_session() -> requests.Session:
    """Create a no-retry session for the origin connectivity preflight."""

    session = requests.Session()
    session.mount(
        "https://",
        HTTPAdapter(
            max_retries=Retry(
                total=0,
                connect=0,
                read=0,
                redirect=0,
                raise_on_status=False,
            )
        ),
    )
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
            "Accept-Language": "es-CL,es;q=0.9,en;q=0.7",
        }
    )
    return session


def _select_origin() -> str:
    """Return the first reachable GradoÚnico origin or fail quickly.

    The store occasionally accepts residential/search-engine traffic while timing
    out from cloud providers.  Probing both the ``www`` and apex hosts before
    iterating eleven categories prevents a 10+ minute chain of identical TCP
    timeouts.  Any HTTP response proves that the TCP/TLS origin is reachable;
    category requests still validate their own status codes afterwards.
    """

    failures: list[str] = []
    session = _probe_session()
    try:
        for origin in REQUEST_ORIGINS:
            ensure_budget("preflight de GradoÚnico")
            probe_url = f"{origin.rstrip('/')}/api/mcp/llms.txt"
            started = time.monotonic()
            try:
                response = session.get(
                    probe_url,
                    timeout=bounded_request_timeout(PREFLIGHT_TIMEOUT),
                    allow_redirects=True,
                    stream=True,
                )
                elapsed = time.monotonic() - started
                response.close()
                print(
                    f"GradoÚnico preflight: origen={origin}, "
                    f"HTTP={response.status_code}, duración={elapsed:.1f}s.",
                    flush=True,
                )
                return origin
            except requests.RequestException as exc:
                elapsed = time.monotonic() - started
                detail = f"{origin}: {type(exc).__name__} tras {elapsed:.1f}s"
                failures.append(detail)
                print(
                    f"⚠ GradoÚnico preflight falló: {detail}.",
                    file=sys.stderr,
                    flush=True,
                )
    finally:
        session.close()

    raise RuntimeError(
        "GradoÚnico no es accesible desde Railway; "
        "se abrió el circuit breaker antes de recorrer categorías ("
        + "; ".join(failures)
        + ")."
    )


def _is_connection_failure(exc: BaseException) -> bool:
    return isinstance(exc, (requests.ConnectTimeout, requests.ConnectionError))


def _is_product_url(raw_url: str) -> bool:
    parsed = urlparse(urljoin(BASE_URL, raw_url))
    if parsed.netloc.casefold() not in {"gradounico.cl", "www.gradounico.cl"}:
        return False
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) != 1:
        return False
    return parts[0].casefold() not in _EXCLUDED_PATHS and len(parts[0]) > 2


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
        headings = parent.select("h2, h3, h4")
        product_links = [
            link
            for link in parent.select("a[href]")
            if _is_product_url(str(link.get("href") or ""))
        ]
        if _price_values(text) and len(headings) <= 2 and len(product_links) <= 3 and len(text) <= 3_500:
            candidate = parent
            if parent.name in {"article", "li"} or "agregar" in _fold(text):
                break
    return candidate


def _product_link(card: Tag, heading: Tag) -> Tag | None:
    if heading.name == "a" and _is_product_url(str(heading.get("href") or "")):
        return heading
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
    candidate_count = 0

    # Jumpseller expone los nombres de productos como encabezados dentro de
    # tarjetas. Este enfoque es más estable que depender de una sola clase CSS.
    for heading in soup.select("h2, h3, h4"):
        if not isinstance(heading, Tag):
            continue
        name = _normalize_text(heading.get_text(" ", strip=True))
        if len(name) < 4 or name.casefold() in {"categorías", "información", "productos recomendados"}:
            continue
        card = _candidate_card(heading)
        card_identity = id(card)
        if card_identity in seen_cards:
            continue
        link = _product_link(card, heading)
        if link is None:
            continue
        text = _normalize_text(card.get_text(" ", strip=True))
        values = _price_values(text)
        if not values:
            continue
        candidate_count += 1
        seen_cards.add(card_identity)
        folded = _fold(text)
        if any(marker in folded for marker in ("agotado", "sin stock", "no disponible")) and "agregar" not in folded:
            continue
        current = min(values)
        higher = [value for value in values if value > current]
        regular = max(higher) if higher else None
        url = _canonical_url(str(link.get("href") or ""))
        products[url] = CollectedProduct(
            store="GradoÚnico",
            name=name[:500],
            url=url,
            current_price=current,
            regular_price=regular,
            discount_pct=_discount(regular, current),
            source_sections=(section_name,),
        )
    return products, candidate_count


def _merge(existing: CollectedProduct | None, incoming: CollectedProduct) -> CollectedProduct:
    if existing is None:
        return incoming
    sections = tuple(sorted(set(existing.source_sections + incoming.source_sections), key=str.casefold))
    chosen = incoming if incoming.current_price <= existing.current_price else existing
    return replace(chosen, source_sections=sections)


def _health(section_stats: list[SectionStats], product_count: int) -> tuple[str, int]:
    if not section_stats or product_count == 0:
        return "BROKEN", 0
    failed = sum(item.status != "success" for item in section_stats)
    warnings = sum(item.structural_warning for item in section_stats)
    score = max(0, min(100, 100 - failed * 12 - warnings * 8))
    if failed == 0 and warnings == 0:
        return "HEALTHY", score
    if failed <= max(2, len(section_stats) // 3) and score >= 55:
        return "DEGRADED", score
    return "BROKEN", score


def _collect_products() -> CollectionBatch:
    collector_started = time.monotonic()
    session = _session()
    all_products: dict[str, CollectedProduct] = {}
    section_stats: list[SectionStats] = []
    pages_visited = cards_seen = duplicates_removed = 0
    aggregate = PhaseMetrics()

    try:
        active_origin = _select_origin()
        consecutive_connection_failures = 0
        for index, section in enumerate(CATALOG_SECTIONS, start=1):
            ensure_budget(f"GradoÚnico categoría {section.name}")
            section_started = time.monotonic()
            metrics = PhaseMetrics()
            section_products: set[str] = set()
            section_pages = section_cards = section_duplicates = 0
            status = "success"
            error_message: str | None = None
            structural_warning = False
            previous_signature: tuple[str, ...] = ()
            print(
                f"GradoÚnico categoría {index}/{len(CATALOG_SECTIONS)}: {section.name}",
                flush=True,
            )
            try:
                for page_number in range(1, MAX_PAGES_PER_SECTION + 1):
                    ensure_budget(f"GradoÚnico {section.name} página {page_number}")
                    url = _category_url(section, page_number, origin=active_origin)
                    with metrics.measure("http"):
                        response = session.get(url, timeout=bounded_request_timeout(REQUEST_TIMEOUT))
                    response.raise_for_status()
                    consecutive_connection_failures = 0
                    with metrics.measure("parse"):
                        page_products, page_cards = _parse_html(response.text, section.name)
                    signature = tuple(sorted(page_products))
                    pages_visited += 1
                    section_pages += 1
                    cards_seen += page_cards
                    section_cards += page_cards

                    if page_number > 1 and signature == previous_signature:
                        break
                    previous_signature = signature
                    new_page = 0
                    for product_url, product in page_products.items():
                        if product_url in section_products:
                            section_duplicates += 1
                        else:
                            section_products.add(product_url)
                            new_page += 1
                        if product_url in all_products:
                            duplicates_removed += 1
                        all_products[product_url] = _merge(all_products.get(product_url), product)

                    print(
                        f"GradoÚnico {section.key} página {page_number}: HTTP={response.status_code}, "
                        f"tarjetas={page_cards}, productos={len(page_products)}, "
                        f"nuevos={new_page}, sección={len(section_products)}, global={len(all_products)}",
                        flush=True,
                    )
                    if page_number == 1 and page_cards == 0:
                        structural_warning = True
                    if not page_products or new_page == 0:
                        break
            except Exception as exc:
                status = "failed"
                error_message = f"{type(exc).__name__}: {exc}"[:1000]
                if _is_connection_failure(exc):
                    consecutive_connection_failures += 1
                else:
                    consecutive_connection_failures = 0
                print(
                    f"✖ GradoÚnico {section.name}: {error_message}. "
                    f"Fallas de conexión consecutivas="
                    f"{consecutive_connection_failures}/"
                    f"{MAX_CONSECUTIVE_CONNECTION_FAILURES}.",
                    file=sys.stderr,
                    flush=True,
                )

            duration_ms = int((time.monotonic() - section_started) * 1000)
            section_stats.append(
                SectionStats(
                    key=section.key,
                    name=section.name,
                    url=f"{BASE_URL}{section.path}",
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

            if (
                consecutive_connection_failures
                >= MAX_CONSECUTIVE_CONNECTION_FAILURES
            ):
                remaining = CATALOG_SECTIONS[index:]
                breaker_error = (
                    "Circuit breaker abierto tras "
                    f"{consecutive_connection_failures} fallas TCP consecutivas; "
                    f"se omiten {len(remaining)} categorías para no prolongar la ejecución."
                )
                print(
                    f"⚠ GradoÚnico: {breaker_error}",
                    file=sys.stderr,
                    flush=True,
                )
                for skipped in remaining:
                    section_stats.append(
                        SectionStats(
                            key=skipped.key,
                            name=skipped.name,
                            url=f"{BASE_URL}{skipped.path}",
                            status="skipped",
                            error_message=breaker_error,
                        )
                    )
                break

        if not all_products:
            raise RuntimeError("GradoÚnico no entregó productos en ninguna categoría.")

        for section in section_stats:
            for name, value in section.performance_ms.items():
                aggregate.add(name, value)
        aggregate.add("collector_total", int((time.monotonic() - collector_started) * 1000))
        succeeded = sum(item.status == "success" for item in section_stats)
        failed = len(section_stats) - succeeded
        warnings = sum(item.structural_warning for item in section_stats)
        health_status, health_score = _health(section_stats, len(all_products))
        products = sorted(all_products.values(), key=lambda item: item.name.casefold())
        print(
            f"Resumen GradoÚnico: categorías={len(CATALOG_SECTIONS)}, correctas={succeeded}, "
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
                discovery_source="configured-http-categories-with-circuit-breaker",
                health_status=health_status,
                health_score=health_score,
                structural_warnings=warnings,
                section_stats=tuple(section_stats),
                performance_ms=aggregate.as_dict(),
            ),
        )
    finally:
        session.close()


class GradoUnicoCollector:
    metadata = StoreMetadata(
        name="GradoÚnico",
        slug="gradounico",
        base_url="https://www.gradounico.cl/",
        connector_key="gradounico",
        requires_browser=False,
    )
    key = metadata.connector_key
    store_name = metadata.name

    def collect(self) -> CollectionBatch:
        return _collect_products()


def scrape() -> list[CollectedProduct]:
    return GradoUnicoCollector().collect().products
