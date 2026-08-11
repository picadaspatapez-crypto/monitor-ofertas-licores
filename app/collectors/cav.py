from __future__ import annotations

import random
import re
import time
import unicodedata
from urllib.parse import urlencode, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup, Tag
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from app.collectors.base import StoreMetadata
from app.deadlines import bounded_request_timeout, ensure_budget
from app.domain import CollectedPriceQuote, CollectedProduct, CollectionBatch, CollectionStats, SectionStats

BASE_URL = "https://cav.cl"
SHOP_URL = f"{BASE_URL}/tienda"
PAGE_SIZE = 48
MAX_PAGES = 40
MIN_PLAUSIBLE_PRODUCTS = 60
REQUEST_TIMEOUT = (5, 22)

_LABEL_RE = {
    "member": re.compile(r"Socio\s*:\s*\$?\s*([\d.]+)", re.I),
    "sale": re.compile(r"Oferta\s*:\s*\$?\s*([\d.]+)", re.I),
    "normal": re.compile(r"Normal\s*:\s*\$?\s*([\d.]+)", re.I),
    "stock": re.compile(r"Stock\s*:\s*(50\+|\d+)", re.I),
}
_PRODUCT_PATH_RE = re.compile(r"/tienda/producto/", re.I)
_SKU_RE = re.compile(r"-(\d{3,})/?$")


def _session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=1,
        connect=1,
        read=1,
        backoff_factor=1.2,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    session.mount("https://", HTTPAdapter(max_retries=retry, pool_connections=3, pool_maxsize=3))
    session.headers.update({
        "User-Agent": "ProyectoMonitorLicores/5.5 (+diagnostic-catalog; Chile)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "es-CL,es;q=0.9",
    })
    return session


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    return "".join(ch for ch in normalized if not unicodedata.combining(ch)).casefold()


def _clp(raw: str | None) -> int | None:
    digits = re.sub(r"\D", "", raw or "")
    if not digits:
        return None
    value = int(digits)
    return value if 100 <= value <= 20_000_000 else None


def _canonical_url(href: str) -> str:
    parsed = urlparse(urljoin(BASE_URL, href))
    return urlunparse(("https", "cav.cl", parsed.path.rstrip("/"), "", "", ""))


def _candidate_card(link: Tag) -> Tag:
    candidate = link
    for parent in link.parents:
        if not isinstance(parent, Tag) or parent.name in {"body", "html", "[document]"}:
            break
        text = " ".join(parent.get_text(" ", strip=True).split())
        if "Socio" in text and "Normal" in text and len(text) <= 5000:
            candidate = parent
            classes = " ".join(parent.get("class") or []).casefold()
            if parent.name in {"article", "li"} or any(word in classes for word in ("product", "hit", "card", "item")):
                break
    return candidate


def _name_from_card(card: Tag, link: Tag) -> str:
    for selector in ("h2", "h3", "h4", ".product-name", ".ais-Highlight", ".name"):
        node = card.select_one(selector)
        if isinstance(node, Tag):
            name = " ".join(node.get_text(" ", strip=True).split())
            if len(name) >= 3:
                return name
    return " ".join(link.get_text(" ", strip=True).split())


def _parse_html(html: str) -> tuple[dict[str, CollectedProduct], int]:
    soup = BeautifulSoup(html, "html.parser")
    products: dict[str, CollectedProduct] = {}
    cards = 0
    seen_links: set[str] = set()
    for link in soup.select('a[href*="/tienda/producto/"]'):
        if not isinstance(link, Tag):
            continue
        href = str(link.get("href") or "")
        if not _PRODUCT_PATH_RE.search(href):
            continue
        url = _canonical_url(href)
        if url in seen_links:
            continue
        seen_links.add(url)
        card = _candidate_card(link)
        text = " ".join(card.get_text(" ", strip=True).split())
        member_match = _LABEL_RE["member"].search(text)
        normal_match = _LABEL_RE["normal"].search(text)
        sale_match = _LABEL_RE["sale"].search(text)
        member = _clp(member_match.group(1) if member_match else None)
        normal = _clp(normal_match.group(1) if normal_match else None)
        sale = _clp(sale_match.group(1) if sale_match else None)
        if normal is None and member is None and sale is None:
            continue
        cards += 1
        stock_match = _LABEL_RE["stock"].search(text)
        if stock_match and stock_match.group(1) != "50+" and int(stock_match.group(1)) <= 0:
            continue
        name = _name_from_card(card, link)
        if len(name) < 3:
            continue
        # CAV está en diagnóstico: el Product conserva el precio normal como base,
        # mientras todos los precios visibles se guardan como contextos separados.
        current = normal or sale or member
        assert current is not None
        quotes: list[CollectedPriceQuote] = []
        if normal is not None:
            quotes.append(CollectedPriceQuote(normal, "PUBLIC", None, "public", False))
        if sale is not None:
            quotes.append(CollectedPriceQuote(sale, "SALE", normal, "public_offer", False))
        if member is not None:
            quotes.append(CollectedPriceQuote(member, "MEMBER", normal, "cav_member", True))
        sku_match = _SKU_RE.search(url)
        products[url] = CollectedProduct(
            store="CAV",
            name=name[:500],
            url=url,
            current_price=current,
            regular_price=normal if normal and normal > current else None,
            discount_pct=((normal - current) / normal if normal and normal > current else 0.0),
            source_sections=("CAV diagnóstico",),
            sku=sku_match.group(1) if sku_match else None,
            price_quotes=tuple(quotes),
        )
    return products, cards


def _page_url(page: int) -> str:
    return f"{SHOP_URL}?{urlencode({'idx': 'products', 'p': page, 'hPP': PAGE_SIZE, 'q': ''})}"


def _collect_products() -> CollectionBatch:
    session = _session()
    started = time.monotonic()
    products: dict[str, CollectedProduct] = {}
    pages = cards = duplicates = 0
    previous_signature: tuple[str, ...] | None = None
    try:
        for page in range(MAX_PAGES):
            ensure_budget(f"CAV diagnóstico página {page + 1}")
            response = session.get(_page_url(page), timeout=bounded_request_timeout(REQUEST_TIMEOUT))
            if response.status_code in {403, 429, 430}:
                raise RuntimeError(f"CAV diagnóstico limitado por HTTP {response.status_code}; se corta sin fan-out.")
            if response.status_code != 200:
                raise RuntimeError(f"CAV diagnóstico respondió HTTP {response.status_code} en página {page + 1}.")
            parsed, page_cards = _parse_html(response.text)
            pages += 1
            cards += page_cards
            if not parsed:
                if page == 0:
                    raise RuntimeError("CAV no entregó tarjetas compatibles en la primera página.")
                break
            signature = tuple(sorted(parsed))
            if signature == previous_signature:
                print("CAV diagnóstico: paginación repetida detectada; fin seguro.", flush=True)
                break
            previous_signature = signature
            before = len(products)
            for url, product in parsed.items():
                if url in products:
                    duplicates += 1
                products[url] = product
            print(f"CAV diagnóstico página {page + 1}: {len(parsed)} productos, total={len(products)}", flush=True)
            if len(products) == before:
                break
            time.sleep(random.uniform(1.0, 2.0))
    finally:
        session.close()

    count = len(products)
    health_status = "HEALTHY" if count >= MIN_PLAUSIBLE_PRODUCTS else "BROKEN"
    health_score = 100 if health_status == "HEALTHY" else (20 if count else 0)
    section = SectionStats(
        key="cav_diagnostic",
        name="CAV catálogo diagnóstico",
        url=SHOP_URL,
        pages_visited=pages,
        cards_seen=cards,
        unique_products=count,
        duplicates_removed=duplicates,
        duration_ms=int((time.monotonic() - started) * 1000),
        status="success" if health_status == "HEALTHY" else "failed",
        structural_warning=health_status != "HEALTHY",
    )
    return CollectionBatch(
        products=sorted(products.values(), key=lambda item: (item.name.casefold(), item.url)),
        stats=CollectionStats(
            pages_visited=pages,
            cards_seen=cards,
            unique_products=count,
            sections_discovered=1,
            sections_visited=1,
            sections_succeeded=int(health_status == "HEALTHY"),
            sections_failed=int(health_status != "HEALTHY"),
            duplicates_removed=duplicates,
            discovery_source="cav_public_catalog_diagnostic",
            health_status=health_status,
            health_score=health_score,
            structural_warnings=int(health_status != "HEALTHY"),
            section_stats=(section,),
            performance_ms={"total_collect": int((time.monotonic() - started) * 1000)},
        ),
    )


class CAVCollector:
    key = "cav"
    store_name = "CAV"
    metadata = StoreMetadata(
        name=store_name,
        slug="cav",
        base_url=BASE_URL,
        connector_key=key,
        requires_browser=False,
        comparison_enabled=False,
        diagnostic_mode=True,
    )

    def collect(self) -> CollectionBatch:
        return _collect_products()


def scrape() -> list[CollectedProduct]:
    return _collect_products().products
