from __future__ import annotations

import math
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextvars import copy_context
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlencode, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup, Tag
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from app.collectors.base import StoreMetadata
from app.deadlines import bounded_request_timeout, ensure_budget
from app.domain import CollectedProduct, CollectionBatch, CollectionStats, SectionStats
from app.performance import PhaseMetrics


BASE_URL = "https://tost.cl"
REQUEST_TIMEOUT = (5, 15)
MAX_PAGES_PER_SECTION = 30
PAGE_FETCH_WORKERS = 3
MIN_PLAUSIBLE_PRODUCTS = 50


@dataclass(frozen=True)
class CatalogSection:
    key: str
    name: str
    handle: str


# Colecciones públicas oficiales observadas en la navegación de Tost.
# Se recorren las páginas HTML normales; no se depende del endpoint products.json.
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


def _session() -> requests.Session:
    session = requests.Session()
    retries = Retry(
        total=1,
        connect=1,
        read=1,
        backoff_factor=0.25,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        raise_on_status=False,
    )
    session.mount("https://", HTTPAdapter(max_retries=retries, pool_connections=8, pool_maxsize=8))
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
            "Accept-Language": "es-CL,es;q=0.9,en;q=0.7",
        }
    )
    return session


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
    # Shopify suele entregar "7990.00"; la tienda visible usa "7.990".
    # Se distinguen decimales de separadores de miles antes de convertir.
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
    # Shopify usa variantes reales para cepas y formatos. Añadir el nombre de
    # la variante evita guardar dos precios distintos con el mismo título.
    if variant_title.casefold() in title.casefold():
        return title
    return f"{title} · {variant_title}"[:500]


def _parse_shopify_payload(
    payload: dict[str, Any], section_name: str
) -> tuple[dict[str, CollectedProduct], int]:
    products: dict[str, CollectedProduct] = {}
    raw_products = [item for item in (payload.get("products") or []) if isinstance(item, dict)]
    cards_seen = len(raw_products)
    for raw_product in raw_products:
        if not isinstance(raw_product, dict):
            continue
        title = _normalize_text(str(raw_product.get("title") or ""))
        handle = str(raw_product.get("handle") or "").strip()
        if len(title) < 3 or not handle:
            continue
        # Tost publica una ficha personalizada junto a la botella normal. Se
        # omite para no duplicar ni comparar un servicio de grabado como si
        # fuera exactamente el mismo artículo.
        if _SKIP_PERSONALIZED_RE.search(title):
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
            name = _variant_name(title, variant, len(variants))
            products[url] = CollectedProduct(
                store="Tost",
                name=name,
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
    # Elimina precios unitarios por litro o por artículo antes de tomar el
    # precio comercial principal de la tarjeta.
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


def _product_grid_root(soup: BeautifulSoup) -> Tag | BeautifulSoup:
    selectors = (
        "#product-grid",
        "[id*='product-grid' i]",
        "[data-product-grid]",
        ".collection__product-grid",
        ".boost-pfs-filter-products",
        ".product-grid",
    )
    for selector in selectors:
        root = soup.select_one(selector)
        if isinstance(root, Tag) and root.select("a[href*='/products/']"):
            return root
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


def _collection_url(section: CatalogSection, page_number: int) -> str:
    return f"{BASE_URL}/collections/{section.handle}?page={page_number}"


def _discover_page_count(html: str, first_page_cards: int) -> int:
    soup = BeautifulSoup(html, "html.parser")
    discovered = {1}
    for link in soup.select("a[href*='page=']"):
        href = str(link.get("href") or "")
        match = re.search(r"(?:[?&])page=(\d+)", href)
        if match:
            discovered.add(int(match.group(1)))

    text = _normalize_text(soup.get_text(" ", strip=True))
    progress = re.search(r"Mostrando\s+(\d+)\s+de\s+(\d+)", text, re.IGNORECASE)
    if progress:
        shown = max(1, int(progress.group(1)))
        total = max(shown, int(progress.group(2)))
        page_size = max(1, first_page_cards or shown)
        discovered.add(math.ceil(total / page_size))

    return max(1, min(MAX_PAGES_PER_SECTION, max(discovered)))


def _fetch_html_page(section: CatalogSection, page_number: int) -> tuple[int, str, int]:
    ensure_budget(f"Tost {section.name} página {page_number}")
    session = _session()
    try:
        response = session.get(
            _collection_url(section, page_number),
            timeout=bounded_request_timeout(REQUEST_TIMEOUT),
        )
        response.raise_for_status()
        return page_number, response.text, response.status_code
    finally:
        session.close()

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


def _collect_products() -> CollectionBatch:
    started = time.monotonic()
    all_products: dict[str, CollectedProduct] = {}
    section_stats: list[SectionStats] = []
    pages_visited = cards_seen = duplicates_removed = 0
    aggregate = PhaseMetrics()

    for index, section in enumerate(CATALOG_SECTIONS, start=1):
        ensure_budget(f"Tost categoría {section.name}")
        section_started = time.monotonic()
        metrics = PhaseMetrics()
        section_products: set[str] = set()
        section_cards = section_pages = section_duplicates = 0
        status = "success"
        error_message: str | None = None
        structural_warning = False
        print(
            f"Tost categoría {index}/{len(CATALOG_SECTIONS)}: {section.name}",
            flush=True,
        )

        def merge_page(
            *,
            page_number: int,
            page_products: dict[str, CollectedProduct],
            page_cards: int,
            status_code: int,
        ) -> None:
            nonlocal pages_visited, cards_seen, duplicates_removed
            nonlocal section_pages, section_cards, section_duplicates
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
                f"Tost {section.key} página {page_number}: HTTP={status_code}, "
                f"tarjetas={page_cards}, productos={len(page_products)}, "
                f"nuevos={new_page}, sección={len(section_products)}, global={len(all_products)}",
                flush=True,
            )

        try:
            with metrics.measure("http"):
                first_page_number, first_html, first_status = _fetch_html_page(section, 1)
            with metrics.measure("parse"):
                first_products, first_cards = _parse_html(first_html, section.name)
            merge_page(
                page_number=first_page_number,
                page_products=first_products,
                page_cards=first_cards,
                status_code=first_status,
            )
            if first_cards == 0 or not first_products:
                structural_warning = True

            page_count = _discover_page_count(first_html, first_cards)
            if page_count > 1:
                fetched: list[tuple[int, str, int]] = []
                with metrics.measure("parallel_pages"):
                    # Se trabaja en lotes de tres: acelera la colección sin dejar
                    # decenas de solicitudes en cola cuando el sitio se vuelve lento.
                    for batch_start in range(2, page_count + 1, PAGE_FETCH_WORKERS):
                        ensure_budget(f"Tost categoría {section.name}")
                        page_numbers = list(
                            range(
                                batch_start,
                                min(page_count + 1, batch_start + PAGE_FETCH_WORKERS),
                            )
                        )
                        with ThreadPoolExecutor(
                            max_workers=len(page_numbers),
                            thread_name_prefix=f"tost-{section.key}",
                        ) as executor:
                            futures = {
                                executor.submit(
                                    copy_context().run,
                                    _fetch_html_page,
                                    section,
                                    page_number,
                                ): page_number
                                for page_number in page_numbers
                            }
                            batch_failures = 0
                            for future in as_completed(futures):
                                ensure_budget(f"Tost categoría {section.name}")
                                try:
                                    fetched.append(future.result())
                                except Exception:
                                    batch_failures += 1
                            if batch_failures:
                                raise RuntimeError(
                                    f"fallaron {batch_failures}/{len(page_numbers)} "
                                    f"páginas del lote {page_numbers[0]}-{page_numbers[-1]}"
                                )

                for page_number, html, status_code in sorted(fetched):
                    ensure_budget(f"Tost {section.name} página {page_number}")
                    with metrics.measure("parse"):
                        page_products, page_cards = _parse_html(html, section.name)
                    merge_page(
                        page_number=page_number,
                        page_products=page_products,
                        page_cards=page_cards,
                        status_code=status_code,
                    )
        except Exception as exc:
            status = "failed"
            error_message = f"{type(exc).__name__}: {exc}"[:1000]
            print(
                f"✖ Tost {section.name}: {error_message}. Continúa con la siguiente categoría.",
                file=sys.stderr,
                flush=True,
            )

        duration_ms = int((time.monotonic() - section_started) * 1000)
        section_stats.append(
            SectionStats(
                key=section.key,
                name=section.name,
                url=f"{BASE_URL}/collections/{section.handle}",
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
        raise RuntimeError("Tost no entregó productos en ninguna colección.")

    for section in section_stats:
        for name, value in section.performance_ms.items():
            aggregate.add(name, value)
    aggregate.add("collector_total", int((time.monotonic() - started) * 1000))
    succeeded = sum(item.status == "success" for item in section_stats)
    failed = len(section_stats) - succeeded
    warnings = sum(item.structural_warning for item in section_stats)
    health_status, health_score = _health(section_stats, len(all_products))
    if len(all_products) < MIN_PLAUSIBLE_PRODUCTS:
        warnings += 1
        print(
            f"⚠ Tost: cobertura inverosímil ({len(all_products)} productos; "
            f"mínimo esperado={MIN_PLAUSIBLE_PRODUCTS}). Estado forzado a BROKEN.",
            file=sys.stderr,
            flush=True,
        )
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
            discovery_source="configured-html-collections-parallel-pagination",
            health_status=health_status,
            health_score=health_score,
            structural_warnings=warnings,
            section_stats=tuple(section_stats),
            performance_ms=aggregate.as_dict(),
        ),
    )


class TostCollector:
    metadata = StoreMetadata(
        name="Tost",
        slug="tost",
        base_url="https://tost.cl/",
        connector_key="tost",
        requires_browser=False,
    )
    key = metadata.connector_key
    store_name = metadata.name

    def collect(self) -> CollectionBatch:
        return _collect_products()


def scrape() -> list[CollectedProduct]:
    return TostCollector().collect().products
