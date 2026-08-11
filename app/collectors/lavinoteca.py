from __future__ import annotations

import random
import re
import time
from dataclasses import dataclass
from urllib.parse import urljoin

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from app.collectors.base import StoreMetadata
from app.deadlines import bounded_request_timeout, ensure_budget
from app.domain import CollectedPriceQuote, CollectedProduct, CollectionBatch, CollectionStats, SectionStats
from app.performance import PhaseMetrics

BASE_URL = "https://www.lavinoteca.cl"
SEARCH_ENDPOINT = f"{BASE_URL}/api/catalog_system/pub/products/search"
PAGE_SIZE = 50
MAX_PAGES = 80
MIN_PLAUSIBLE_PRODUCTS = 80
REQUEST_TIMEOUT = (5, 22)
SUCCESS_STATUSES = frozenset({200, 206})
_CONTENT_RANGE_RE = re.compile(r"(?:[A-Za-z-]+\s+)?(\d+)-(\d+)/(\d+|\*)")


def _session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=2,
        connect=1,
        read=1,
        backoff_factor=1.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    session.mount("https://", HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=4))
    session.headers.update({
        "User-Agent": "ProyectoMonitorLicores/5.5 (+catalog-monitor; Chile)",
        "Accept": "application/json,text/plain;q=0.9,*/*;q=0.8",
        "Accept-Language": "es-CL,es;q=0.9",
    })
    return session


def _clp(value) -> int | None:
    if value is None:
        return None
    try:
        amount = int(round(float(value)))
    except (TypeError, ValueError):
        digits = re.sub(r"\D", "", str(value))
        amount = int(digits) if digits else 0
    return amount if 100 <= amount <= 20_000_000 else None


def _discount(regular: int | None, current: int) -> float:
    if not regular or regular <= current:
        return 0.0
    return (regular - current) / regular


def _canonical_url(raw: str, link_text: str = "") -> str:
    url = (raw or link_text or "").strip()
    if not url:
        return ""
    return urljoin(BASE_URL, url.split("?", 1)[0])


def _content_range_total(response: requests.Response) -> int | None:
    """Extrae el total anunciado por VTEX cuando responde contenido parcial.

    El Search API público puede devolver HTTP 206 para un rango válido. En ese
    caso el cuerpo JSON sigue siendo utilizable y Content-Range permite saber
    cuándo se alcanzó el final del catálogo sin depender de un HTTP 416.
    """

    raw = (response.headers.get("Content-Range") or "").strip()
    match = _CONTENT_RANGE_RE.search(raw)
    if not match or match.group(3) == "*":
        return None
    try:
        return max(0, int(match.group(3)))
    except ValueError:
        return None


def _extract_product(item: dict) -> CollectedProduct | None:
    name = str(item.get("productName") or item.get("productTitle") or item.get("productReference") or "").strip()
    url = _canonical_url(str(item.get("link") or ""), str(item.get("linkText") or ""))
    if not name or not url:
        return None

    best: tuple[int, int | None, str | None, str | None] | None = None
    for sku in item.get("items") or []:
        sku_id = str(sku.get("itemId") or "").strip() or None
        ean = str(sku.get("ean") or "").strip() or None
        for seller in sku.get("sellers") or []:
            offer = seller.get("commertialOffer") or seller.get("commercialOffer") or {}
            if offer.get("IsAvailable") is False:
                continue
            quantity = offer.get("AvailableQuantity")
            try:
                if quantity is not None and int(quantity) <= 0:
                    continue
            except (TypeError, ValueError):
                pass
            current = _clp(offer.get("Price"))
            regular = _clp(offer.get("ListPrice"))
            if current is None:
                continue
            if regular is not None and regular <= current:
                regular = None
            candidate = (current, regular, sku_id, ean)
            if best is None or candidate[0] < best[0]:
                best = candidate
    if best is None:
        return None
    current, regular, sku, ean = best
    return CollectedProduct(
        store="La Vinoteca",
        name=name[:500],
        url=url[:1000],
        current_price=current,
        regular_price=regular,
        discount_pct=_discount(regular, current),
        source_sections=("VTEX catálogo público",),
        sku=sku,
        ean=ean,
        price_quotes=(CollectedPriceQuote(
            price=current,
            regular_price=regular,
            price_type="SALE" if regular and regular > current else "PUBLIC",
            audience_key="public",
            eligibility_required=False,
        ),),
    )


def _health(product_count: int, *, failed_pages: int) -> tuple[str, int]:
    if product_count < MIN_PLAUSIBLE_PRODUCTS:
        return "BROKEN", 20 if product_count else 0
    if failed_pages:
        return "DEGRADED", max(50, 90 - failed_pages * 10)
    return "HEALTHY", 100


def _collect_products() -> CollectionBatch:
    session = _session()
    started = time.monotonic()
    metrics = PhaseMetrics()
    products: dict[str, CollectedProduct] = {}
    pages = cards = duplicates = failed_pages = 0
    section_started = time.monotonic()
    try:
        for page in range(MAX_PAGES):
            ensure_budget(f"La Vinoteca VTEX página {page + 1}")
            start = page * PAGE_SIZE
            end = start + PAGE_SIZE - 1
            response = session.get(
                SEARCH_ENDPOINT,
                params={"_from": start, "_to": end, "O": "OrderByNameASC"},
                timeout=bounded_request_timeout(REQUEST_TIMEOUT),
            )
            metrics.add("http", int(response.elapsed.total_seconds() * 1000))
            if response.status_code == 416:
                break
            if response.status_code not in SUCCESS_STATUSES:
                failed_pages += 1
                raise RuntimeError(f"La Vinoteca VTEX respondió HTTP {response.status_code} en rango {start}-{end}.")
            try:
                payload = response.json()
            except ValueError as exc:
                raise RuntimeError("La Vinoteca VTEX no devolvió JSON válido.") from exc
            if not isinstance(payload, list):
                raise RuntimeError("La Vinoteca VTEX cambió el formato esperado del catálogo.")
            pages += 1
            if not payload:
                break
            before = len(products)
            for raw in payload:
                cards += 1
                if not isinstance(raw, dict):
                    continue
                product = _extract_product(raw)
                if product is None:
                    continue
                if product.url in products:
                    duplicates += 1
                    if product.current_price < products[product.url].current_price:
                        products[product.url] = product
                else:
                    products[product.url] = product
            announced_total = _content_range_total(response)
            print(
                f"La Vinoteca VTEX página {page + 1}: HTTP={response.status_code}, "
                f"{len(payload)} registros, total={len(products)}"
                + (f", catálogo_anunciado={announced_total}" if announced_total is not None else ""),
                flush=True,
            )
            if len(payload) < PAGE_SIZE:
                break
            if announced_total is not None and end + 1 >= announced_total:
                break
            if len(products) == before:
                raise RuntimeError("La Vinoteca VTEX repitió una página completa sin productos nuevos.")
            time.sleep(random.uniform(0.35, 0.8))
    finally:
        session.close()

    health_status, health_score = _health(len(products), failed_pages=failed_pages)
    duration_ms = int((time.monotonic() - section_started) * 1000)
    section = SectionStats(
        key="vtex_catalog",
        name="VTEX catálogo público",
        url=SEARCH_ENDPOINT,
        pages_visited=pages,
        cards_seen=cards,
        unique_products=len(products),
        duplicates_removed=duplicates,
        duration_ms=duration_ms,
        status="success" if health_status != "BROKEN" else "failed",
        structural_warning=health_status != "HEALTHY",
    )
    return CollectionBatch(
        products=sorted(products.values(), key=lambda item: (item.name.casefold(), item.url)),
        stats=CollectionStats(
            pages_visited=pages,
            cards_seen=cards,
            unique_products=len(products),
            sections_discovered=1,
            sections_visited=1,
            sections_succeeded=int(health_status != "BROKEN"),
            sections_failed=int(health_status == "BROKEN"),
            duplicates_removed=duplicates,
            discovery_source="vtex_catalog_search",
            health_status=health_status,
            health_score=health_score,
            structural_warnings=int(health_status != "HEALTHY"),
            section_stats=(section,),
            performance_ms={"total_collect": int((time.monotonic() - started) * 1000)},
        ),
    )


class LaVinotecaCollector:
    key = "lavinoteca"
    store_name = "La Vinoteca"
    metadata = StoreMetadata(
        name=store_name,
        slug="la-vinoteca",
        base_url=BASE_URL,
        connector_key=key,
        requires_browser=False,
        comparison_enabled=True,
        diagnostic_mode=False,
    )

    def collect(self) -> CollectionBatch:
        return _collect_products()


def scrape() -> list[CollectedProduct]:
    return _collect_products().products
