from __future__ import annotations

import re
import sys
import time
from dataclasses import dataclass, replace
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup, NavigableString, Tag
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from app.collectors.base import StoreMetadata
from app.deadlines import bounded_request_timeout, ensure_budget
from app.domain import CollectedProduct, CollectionBatch, CollectionStats, SectionStats
from app.performance import PhaseMetrics

BASE_URL = "https://www.lamodelo.cl"
REQUEST_TIMEOUT = (5, 22)
MAX_PAGES = 120
MIN_PLAUSIBLE_PRODUCTS = 100
_PRICE_RE = re.compile(r"\$\s*([\d.]+)")
_CODE_RE = re.compile(r"C[oó]digo\s*:\s*([A-Za-z0-9_-]+)", re.IGNORECASE)


@dataclass(frozen=True)
class CatalogSource:
    key: str
    name: str
    path: str
    base_query: dict[str, str]

    def url(self, page: int) -> str:
        query = dict(self.base_query)
        if page > 1:
            query["page"] = str(page)
        return f"{BASE_URL}{self.path}?{urlencode(query)}"


SOURCES: tuple[CatalogSource, ...] = (
    CatalogSource(
        "catalogo-publico",
        "Catálogo público",
        "/catalogos/public/",
        {"grupo": "", "pp": "100", "q": "", "serie": "", "subclase": ""},
    ),
    CatalogSource(
        "catalogo-clasico",
        "Catálogo clásico",
        "/index.php",
        {"orden": "nombre_asc"},
    ),
)


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
    session.mount("https://", HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=4))
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


def _candidate_card(node: Tag) -> Tag:
    candidate = node
    for parent in node.parents:
        if not isinstance(parent, Tag) or parent.name in {"body", "html", "[document]"}:
            break
        text = _normalize_text(parent.get_text(" ", strip=True))
        code_count = len(_CODE_RE.findall(text))
        if _price_values(text) and code_count <= 1 and len(text) <= 3000:
            candidate = parent
            classes = " ".join(parent.get("class") or []).casefold()
            if parent.name in {"article", "li"} or any(word in classes for word in ("product", "card", "item")):
                break
    return candidate


def _code_from_card(card: Tag) -> str | None:
    match = _CODE_RE.search(_normalize_text(card.get_text(" ", strip=True)))
    if match:
        return match.group(1)
    for link in card.select("a[href]"):
        parsed = urlparse(urljoin(BASE_URL, str(link.get("href") or "")))
        query = parse_qs(parsed.query)
        for key in ("q", "codigo", "code"):
            if query.get(key):
                value = query[key][0].strip()
                if value:
                    return value
    return None


def _name_from_card(card: Tag, code: str | None) -> str:
    for selector in ("h1", "h2", "h3", "h4", "[class*='name']", "[class*='title']"):
        node = card.select_one(selector)
        if isinstance(node, Tag):
            value = _normalize_text(node.get_text(" ", strip=True))
            if len(value) >= 3:
                return value
    text = _normalize_text(card.get_text(" ", strip=True))
    if code:
        text = re.sub(rf"C[oó]digo\s*:\s*{re.escape(code)}", "", text, flags=re.IGNORECASE)
    text = _PRICE_RE.sub("", text)
    text = re.sub(r"\b(?:Unidad|Caja\s*X.*|valor\s+unid\.?|Agregar)\b.*$", "", text, flags=re.IGNORECASE)
    return _normalize_text(text).strip(" -–—")


def _canonical_url(card: Tag, code: str) -> str:
    for link in card.select("a[href]"):
        href = str(link.get("href") or "")
        parsed = urlparse(urljoin(BASE_URL, href))
        if parsed.netloc.casefold() in {"lamodelo.cl", "www.lamodelo.cl"}:
            query = parse_qs(parsed.query)
            if any(query.get(key) for key in ("q", "codigo", "code")):
                path = re.sub(r"/+", "/", parsed.path)
                return urlunparse(("https", "www.lamodelo.cl", path, "", parsed.query, ""))
    return f"{BASE_URL}/index.php?{urlencode({'q': code})}"


def _parse_html(html: str) -> tuple[dict[str, CollectedProduct], int]:
    soup = BeautifulSoup(html, "html.parser")
    products: dict[str, CollectedProduct] = {}
    seen_cards: set[int] = set()
    candidates = 0

    code_nodes: list[Tag] = []
    for text_node in soup.find_all(string=_CODE_RE):
        if isinstance(text_node, NavigableString) and isinstance(text_node.parent, Tag):
            code_nodes.append(text_node.parent)
    if not code_nodes:
        for link in soup.select("a[href*='q='], a[href*='codigo='], a[href*='code=']"):
            if isinstance(link, Tag):
                code_nodes.append(link)

    for node in code_nodes:
        card = _candidate_card(node)
        identity = id(card)
        if identity in seen_cards:
            continue
        code = _code_from_card(card)
        prices = _price_values(_normalize_text(card.get_text(" ", strip=True)))
        if not code or not prices:
            continue
        name = _name_from_card(card, code)
        if len(name) < 3:
            continue
        seen_cards.add(identity)
        candidates += 1
        current = min(prices)
        url = _canonical_url(card, code)
        products[url] = CollectedProduct(
            store="Distribuidora La Modelo",
            name=name[:500],
            url=url,
            current_price=current,
            regular_price=None,
            discount_pct=0.0,
            source_sections=("Catálogo general",),
        )
    return products, candidates


def _merge(existing: CollectedProduct | None, incoming: CollectedProduct) -> CollectedProduct:
    if existing is None:
        return incoming
    sections = tuple(sorted(set(existing.source_sections + incoming.source_sections), key=str.casefold))
    chosen = incoming if incoming.current_price <= existing.current_price else existing
    return replace(chosen, source_sections=sections)


def _select_source(session: requests.Session, metrics: PhaseMetrics) -> tuple[CatalogSource, requests.Response, dict[str, CollectedProduct], int]:
    errors: list[str] = []
    for source in SOURCES:
        ensure_budget(f"La Modelo preflight {source.name}")
        try:
            with metrics.measure("http"):
                response = session.get(source.url(1), timeout=bounded_request_timeout(REQUEST_TIMEOUT))
            response.raise_for_status()
            products, cards = _parse_html(response.text)
            print(
                f"La Modelo preflight: fuente={source.key}, HTTP={response.status_code}, "
                f"tarjetas={cards}, productos={len(products)}",
                flush=True,
            )
            if products:
                return source, response, products, cards
            errors.append(f"{source.key}: 0 productos")
        except Exception as exc:
            errors.append(f"{source.key}: {type(exc).__name__}: {exc}")
    raise RuntimeError("La Modelo no entregó catálogo utilizable (" + "; ".join(errors) + ")")


def _health(product_count: int, complete: bool, warning: bool) -> tuple[str, int]:
    if product_count < MIN_PLAUSIBLE_PRODUCTS:
        return "BROKEN", 20 if product_count else 0
    if complete and not warning:
        return "HEALTHY", 100
    return "DEGRADED", 70


def _collect_products() -> CollectionBatch:
    started = time.monotonic()
    session = _session()
    metrics = PhaseMetrics()
    all_products: dict[str, CollectedProduct] = {}
    pages = cards = duplicates = 0
    complete = False
    warning_message: str | None = None
    source: CatalogSource | None = None
    try:
        source, first_response, first_products, first_cards = _select_source(session, metrics)
        previous_signature: tuple[str, ...] = ()
        for page_number in range(1, MAX_PAGES + 1):
            ensure_budget(f"La Modelo catálogo página {page_number}")
            if page_number == 1:
                response = first_response
                page_products = first_products
                page_cards = first_cards
            else:
                with metrics.measure("http"):
                    response = session.get(source.url(page_number), timeout=bounded_request_timeout(REQUEST_TIMEOUT))
                if response.status_code == 404:
                    complete = True
                    break
                response.raise_for_status()
                with metrics.measure("parse"):
                    page_products, page_cards = _parse_html(response.text)
            signature = tuple(sorted(page_products))
            if page_number > 1 and (not signature or signature == previous_signature):
                complete = True
                break
            previous_signature = signature
            pages += 1
            cards += page_cards
            before = len(all_products)
            for url, product in page_products.items():
                if url in all_products:
                    duplicates += 1
                all_products[url] = _merge(all_products.get(url), product)
            print(
                f"La Modelo página {page_number}: HTTP={response.status_code}, tarjetas={page_cards}, "
                f"productos={len(page_products)}, nuevos={len(all_products) - before}, global={len(all_products)}",
                flush=True,
            )
            if not page_products:
                complete = True
                break
        else:
            warning_message = f"Se alcanzó MAX_PAGES={MAX_PAGES}."
    except Exception as exc:
        if not all_products:
            raise
        warning_message = f"{type(exc).__name__}: {exc}"[:1000]
        print(f"⚠ La Modelo captura parcial: {warning_message}", file=sys.stderr, flush=True)
    finally:
        session.close()

    duration_ms = int((time.monotonic() - started) * 1000)
    health_status, health_score = _health(len(all_products), complete, warning_message is not None)
    section_status = "success" if health_status == "HEALTHY" else "partial"
    section = SectionStats(
        key="catalogo-general",
        name="Catálogo general",
        url=source.url(1) if source else BASE_URL,
        pages_visited=pages,
        cards_seen=cards,
        unique_products=len(all_products),
        duplicates_removed=duplicates,
        duration_ms=duration_ms,
        status=section_status,
        error_message=warning_message,
        structural_warning=section_status != "success",
        performance_ms=metrics.as_dict(),
    )
    stats = CollectionStats(
        pages_visited=pages,
        cards_seen=cards,
        unique_products=len(all_products),
        sections_discovered=1,
        sections_visited=1,
        sections_succeeded=int(section_status == "success"),
        sections_failed=int(section_status != "success"),
        duplicates_removed=duplicates,
        discovery_source=source.key if source else "unknown",
        health_status=health_status,
        health_score=health_score,
        structural_warnings=int(section.structural_warning),
        section_stats=(section,),
        performance_ms={**metrics.as_dict(), "total": duration_ms},
    )
    print(
        f"Resumen La Modelo: fuente={stats.discovery_source}, páginas={pages}, "
        f"productos_únicos={len(all_products)}, completo={'sí' if complete else 'no'}, "
        f"salud={health_status}({health_score})",
        flush=True,
    )
    if not all_products:
        raise RuntimeError("Distribuidora La Modelo no entregó productos.")
    return CollectionBatch(products=list(all_products.values()), stats=stats)


class LaModeloCollector:
    metadata = StoreMetadata(
        name="Distribuidora La Modelo",
        slug="distribuidora-la-modelo",
        base_url=f"{BASE_URL}/",
        connector_key="lamodelo",
        requires_browser=False,
    )
    key = metadata.connector_key
    store_name = metadata.name

    def collect(self) -> CollectionBatch:
        return _collect_products()


def scrape() -> list[CollectedProduct]:
    return LaModeloCollector().collect().products
