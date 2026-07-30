from __future__ import annotations

import json
import random
import re
import sys
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
from urllib.parse import urlencode, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup, Tag
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from app.collectors.base import StoreMetadata
from app.deadlines import bounded_request_timeout, ensure_budget, remaining_seconds
from app.domain import CollectedProduct, CollectionBatch, CollectionStats, SectionStats
from app.performance import PhaseMetrics

BASE_URL = "https://elmundodelvino.cl"
ALT_BASE_URL = "https://www.elmundodelvino.cl"
REQUEST_TIMEOUT = (5, 18)
GLOBAL_PAGE_SIZE = 250
MAX_GLOBAL_PAGES = 10
MIN_PLAUSIBLE_PRODUCTS = 120
GLOBAL_PAGE_DELAY_RANGE_SECONDS = (12.0, 20.0)
RATE_LIMIT_MIN_SECONDS = 30.0
RATE_LIMIT_MAX_SECONDS = 120.0
RATE_LIMIT_RETRIES = 1

# Se prueba primero el feed global más corto. ``collections/all`` es un único
# respaldo global; nunca volvemos a disparar una solicitud por categoría.
GLOBAL_FEED_PATHS: tuple[str, ...] = (
    "/products.json",
    "/collections/all/products.json",
)

_PRICE_RE = re.compile(r"\$\s*([\d.]+)")
_CHALLENGE_MARKERS = (
    "cf-chl-",
    "challenge-platform",
    "captcha",
    "access denied",
    "temporarily unavailable",
)
_ACCESSORY_MARKERS = (
    "accesorio",
    "sacacorcho",
    "saca corcho",
    "copa ",
    "copas ",
    "vaso ",
    "vasos ",
    "decantador",
    "aireador",
    "gift card",
    "tarjeta de regalo",
    "bolsa de regalo",
)
_CATEGORY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Whisky", ("whisky", "whiskey", "bourbon", "scotch")),
    ("Espumantes", ("espumante", "champagne", "prosecco", "sparkling", "brut")),
    ("Cervezas", ("cerveza", "beer", "lager", " ale ", " ipa ")),
    ("Gin", ("gin", "ginebra")),
    ("Vodka", ("vodka",)),
    ("Ron", ("ron", " rum ")),
    ("Piscos", ("pisco",)),
    ("Tequila", ("tequila", "mezcal")),
    (
        "Licores",
        (
            "licor",
            "liqueur",
            "vermouth",
            "aperitivo",
            "bitter",
            "amaro",
            "cognac",
            "coñac",
            "brandy",
            "sake",
        ),
    ),
    (
        "Vinos",
        (
            "vino",
            " wine ",
            "cabernet",
            "carmenere",
            "carménère",
            "merlot",
            "syrah",
            "chardonnay",
            "sauvignon",
            "pinot",
            "malbec",
            "ensamblaje",
        ),
    ),
)


@dataclass(frozen=True)
class GlobalFeedSource:
    host: str
    path: str

    def url(self, page: int) -> str:
        return f"{self.host}{self.path}?{urlencode({'limit': GLOBAL_PAGE_SIZE, 'page': page})}"


class RateLimitError(RuntimeError):
    """Raised when Shopify keeps returning HTTP 429 after one controlled retry."""

    def __init__(self, *, url: str, delay_seconds: float, attempts: int = 2) -> None:
        self.url = url
        self.delay_seconds = float(delay_seconds)
        self.attempts = int(attempts)
        super().__init__(
            f"HTTP 429 persistente tras {self.attempts} intentos para {self.url}; "
            f"última pausa={self.delay_seconds:.0f}s"
        )


def _session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=2,
        connect=1,
        read=1,
        backoff_factor=0.7,
        # Los 429 se tratan explícitamente para no multiplicar solicitudes.
        status_forcelist=(500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=False,
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
            "Accept": "application/json,text/html;q=0.8,*/*;q=0.5",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        }
    )
    return session


def _retry_after_seconds(response: requests.Response) -> float:
    raw = (response.headers.get("Retry-After") or "").strip()
    delay: float | None = None
    if raw:
        try:
            delay = float(raw)
        except ValueError:
            try:
                when = parsedate_to_datetime(raw)
                if when.tzinfo is None:
                    when = when.replace(tzinfo=timezone.utc)
                delay = (when - datetime.now(timezone.utc)).total_seconds()
            except (TypeError, ValueError, OverflowError):
                delay = None
    if delay is None or delay <= 0:
        delay = RATE_LIMIT_MIN_SECONDS
    return max(RATE_LIMIT_MIN_SECONDS, min(RATE_LIMIT_MAX_SECONDS, delay))


def _sleep_with_budget(seconds: float, *, context: str) -> None:
    ensure_budget(context)
    remaining = remaining_seconds()
    delay = max(0.0, float(seconds))
    if remaining is not None:
        available = max(0.0, remaining - 0.5)
        if available <= 0:
            ensure_budget(context)
        delay = min(delay, available)
    if delay > 0:
        time.sleep(delay)
    ensure_budget(context)


def _rate_limit_wait(response: requests.Response, *, page_number: int) -> float:
    delay = _retry_after_seconds(response)
    print(
        f"⚠ El Mundo del Vino catálogo global página {page_number}: HTTP 429; "
        f"pausa controlada de {delay:.0f}s antes de un único reintento.",
        file=sys.stderr,
        flush=True,
    )
    _sleep_with_budget(delay, context=f"rate limit global página {page_number}")
    return delay


def _normalize_text(value: str) -> str:
    return " ".join((value or "").replace("\xa0", " ").split())


def _fold(value: str) -> str:
    return f" {_normalize_text(value).casefold()} "


def _product_slug(raw_url: str) -> str | None:
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


def _global_json_url(page: int, *, host: str = BASE_URL, path: str = GLOBAL_FEED_PATHS[0]) -> str:
    return GlobalFeedSource(host=host, path=path).url(page)


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


def _json_money(value: object) -> int | None:
    if value is None:
        return None
    raw = str(value).strip().replace("$", "").replace(" ", "")
    if not raw:
        return None
    if re.fullmatch(r"\d+\.\d{2}", raw):
        try:
            amount = int(Decimal(raw))
        except (InvalidOperation, ValueError):
            return None
    else:
        digits = re.sub(r"\D", "", raw)
        if not digits:
            return None
        amount = int(digits)
    return amount if 100 <= amount <= 20_000_000 else None


def _discount(regular: int | None, current: int) -> float:
    if regular is None or regular <= current:
        return 0.0
    return (regular - current) / regular


def _clean_product_name(value: str) -> str:
    value = _normalize_text(value)
    value = re.sub(r"^(?:agotado|oferta\s+\d+%|agregar al carro)\s+", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+\$\s*[\d.]+(?:\s+\$\s*[\d.]+)?\s*$", "", value)
    return value.strip(" -–—")


def _classify_product(raw_product: dict[str, object]) -> str:
    title = str(raw_product.get("title") or "")
    product_type = str(raw_product.get("product_type") or "")
    tags_raw = raw_product.get("tags")
    if isinstance(tags_raw, list):
        tags = " ".join(str(item) for item in tags_raw)
    else:
        tags = str(tags_raw or "")
    haystack = _fold(f"{product_type} {tags} {title}")
    for category, markers in _CATEGORY_RULES:
        if any(marker in haystack for marker in markers):
            return category
    return _normalize_text(product_type)[:80] or "Otros"


def _is_accessory(raw_product: dict[str, object], category: str) -> bool:
    if category != "Otros":
        return False
    haystack = _fold(
        f"{raw_product.get('product_type') or ''} {raw_product.get('tags') or ''} "
        f"{raw_product.get('title') or ''}"
    )
    return any(marker in haystack for marker in _ACCESSORY_MARKERS)


def _parse_json(
    payload: object,
    section_name: str | None = None,
) -> tuple[dict[str, CollectedProduct], int]:
    """Parse a Shopify feed.

    ``section_name`` remains optional for compatibility with parser tests and
    older callers. The global collector leaves it as ``None`` and classifies
    each product locally from Shopify metadata.
    """
    if not isinstance(payload, dict):
        return {}, 0
    raw_products = payload.get("products")
    if not isinstance(raw_products, list):
        return {}, 0

    products: dict[str, CollectedProduct] = {}
    candidates = 0
    for raw_product in raw_products:
        if not isinstance(raw_product, dict):
            continue
        name = _clean_product_name(str(raw_product.get("title") or ""))
        handle = str(raw_product.get("handle") or "").strip()
        variants = raw_product.get("variants")
        if len(name) < 3 or not handle or not isinstance(variants, list):
            continue
        candidates += 1
        category = section_name or _classify_product(raw_product)
        if section_name is None and _is_accessory(raw_product, category):
            continue
        available_variants = [
            item
            for item in variants
            if isinstance(item, dict) and item.get("available", True) is not False
        ]
        if not available_variants:
            continue
        prices = [
            amount
            for item in available_variants
            if (amount := _json_money(item.get("price"))) is not None
        ]
        if not prices:
            continue
        current = min(prices)
        compare_prices = [
            amount
            for item in available_variants
            if (amount := _json_money(item.get("compare_at_price"))) is not None
            and amount > current
        ]
        regular = max(compare_prices) if compare_prices else None
        url = _canonical_url(f"/products/{handle}")
        products[url] = CollectedProduct(
            store="El Mundo del Vino",
            name=name[:500],
            url=url,
            current_price=current,
            regular_price=regular,
            discount_pct=_discount(regular, current),
            source_sections=(category,),
        )
    return products, candidates


# Kept for parser compatibility and diagnostics. The production collector no
# longer uses collection HTML, which avoids the category-by-category request
# pattern that triggered Shopify rate limiting.
def _parse_html(html: str, section_name: str) -> tuple[dict[str, CollectedProduct], int]:
    soup = BeautifulSoup(html, "html.parser")
    products: dict[str, CollectedProduct] = {}
    candidates = 0
    seen: set[str] = set()
    for link in soup.select("a[href*='/products/']"):
        if not isinstance(link, Tag):
            continue
        slug = _product_slug(str(link.get("href") or ""))
        if not slug:
            continue
        url = _canonical_url(f"/products/{slug}")
        if url in seen:
            continue
        card = link
        for parent in link.parents:
            if not isinstance(parent, Tag) or parent.name in {"body", "html", "[document]"}:
                break
            text = _normalize_text(parent.get_text(" ", strip=True))
            if _price_values(text) and len(text) <= 3500:
                card = parent
                if parent.name in {"article", "li"}:
                    break
        text = _normalize_text(card.get_text(" ", strip=True))
        prices = _price_values(text)
        name = _clean_product_name(link.get_text(" ", strip=True))
        if not prices or len(name) < 3:
            continue
        candidates += 1
        seen.add(url)
        if "agotado" in _fold(text) or "sold out" in _fold(text):
            continue
        current = min(prices)
        higher = [price for price in prices if price > current]
        regular = max(higher) if higher else None
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


def _looks_like_challenge(response: requests.Response) -> bool:
    folded = response.text[:100_000].casefold()
    return any(marker in folded for marker in _CHALLENGE_MARKERS)


def _fetch_json_response(
    session: requests.Session,
    source: GlobalFeedSource,
    page_number: int,
    metrics: PhaseMetrics,
    *,
    retry_rate_limit: bool = True,
) -> requests.Response:
    url = source.url(page_number)
    last_delay = RATE_LIMIT_MIN_SECONDS
    for attempt in range(RATE_LIMIT_RETRIES + 1):
        with metrics.measure("global_json_http"):
            response = session.get(
                url,
                timeout=bounded_request_timeout(REQUEST_TIMEOUT),
                headers={"Accept": "application/json", "Referer": f"{source.host}/"},
            )
        if response.status_code != 429:
            return response
        last_delay = _retry_after_seconds(response)
        if not retry_rate_limit:
            print(
                f"⚠ El Mundo del Vino catálogo global página {page_number}: "
                "HTTP 429 en el preflight; se corta sin solicitar otras páginas.",
                file=sys.stderr,
                flush=True,
            )
            raise RateLimitError(url=url, delay_seconds=last_delay, attempts=1)
        if attempt < RATE_LIMIT_RETRIES:
            _rate_limit_wait(response, page_number=page_number)
            continue
        raise RateLimitError(url=url, delay_seconds=last_delay, attempts=attempt + 1)
    raise RuntimeError(f"No fue posible solicitar {url}")


def _select_global_source(
    session: requests.Session,
    metrics: PhaseMetrics,
) -> tuple[GlobalFeedSource, dict[str, CollectedProduct], int, int]:
    diagnostics: list[str] = []
    for path in GLOBAL_FEED_PATHS:
        for host in (BASE_URL, ALT_BASE_URL):
            source = GlobalFeedSource(host=host, path=path)
            try:
                response = _fetch_json_response(
                    session, source, 1, metrics, retry_rate_limit=False
                )
                diagnostics.append(
                    f"{source.url(1)} HTTP={response.status_code} bytes={len(response.content)}"
                )
                if response.status_code in {404, 405}:
                    continue
                response.raise_for_status()
                try:
                    payload = response.json()
                except (json.JSONDecodeError, ValueError):
                    continue
                raw_products = payload.get("products") if isinstance(payload, dict) else None
                raw_count = len(raw_products) if isinstance(raw_products, list) else 0
                with metrics.measure("global_json_parse"):
                    products, candidates = _parse_json(payload)
                if raw_count > 0:
                    return source, products, candidates, raw_count
            except RateLimitError:
                # Alternar host/ruta tras un 429 solo multiplicaría solicitudes
                # desde la misma IP de Railway.
                raise
            except Exception as exc:
                diagnostics.append(f"{source.url(1)} {type(exc).__name__}: {exc}")
    raise RuntimeError(
        "El catálogo global de Shopify no entregó productos. Diagnóstico: "
        + "; ".join(diagnostics[-6:])
    )


def _health(*, product_count: int, partial: bool, complete: bool) -> tuple[str, int]:
    if product_count < MIN_PLAUSIBLE_PRODUCTS:
        return "BROKEN", 20 if product_count else 0
    if partial or not complete:
        return "DEGRADED", 72
    return "HEALTHY", 100


def _collect_products() -> CollectionBatch:
    started = time.monotonic()
    session = _session()
    metrics = PhaseMetrics()
    all_products: dict[str, CollectedProduct] = {}
    pages = 0
    cards = 0
    duplicates = 0
    partial = False
    complete = False
    warning_message: str | None = None
    source: GlobalFeedSource | None = None

    try:
        ensure_budget("El Mundo del Vino catálogo global")
        source, first_products, first_cards, first_raw_count = _select_global_source(session, metrics)
        pages = 1
        cards = first_cards
        all_products.update(first_products)
        previous_signature = tuple(sorted(first_products))
        print(
            f"✓ El Mundo del Vino catálogo global página 1: fuente={source.url(1)}, "
            f"registros_shopify={first_raw_count}, productos={len(first_products)}, "
            f"global={len(all_products)}",
            flush=True,
        )
        if first_raw_count < GLOBAL_PAGE_SIZE:
            complete = True
        else:
            for page_number in range(2, MAX_GLOBAL_PAGES + 1):
                ensure_budget(f"El Mundo del Vino catálogo global página {page_number}")
                delay = random.uniform(*GLOBAL_PAGE_DELAY_RANGE_SECONDS)
                print(
                    f"El Mundo del Vino: pausa preventiva de {delay:.1f}s antes de la página {page_number}.",
                    flush=True,
                )
                _sleep_with_budget(delay, context="pausa catálogo global de El Mundo del Vino")
                try:
                    response = _fetch_json_response(session, source, page_number, metrics)
                    response.raise_for_status()
                    payload = response.json()
                    raw_products = payload.get("products") if isinstance(payload, dict) else None
                    raw_count = len(raw_products) if isinstance(raw_products, list) else 0
                    with metrics.measure("global_json_parse"):
                        page_products, page_cards = _parse_json(payload)
                except RateLimitError as exc:
                    partial = True
                    warning_message = str(exc)
                    print(
                        f"⚠ El Mundo del Vino: se conservan {len(all_products)} productos "
                        f"obtenidos antes del rate limit en página {page_number}: {exc}",
                        file=sys.stderr,
                        flush=True,
                    )
                    break
                except Exception as exc:
                    partial = True
                    warning_message = f"{type(exc).__name__}: {exc}"
                    print(
                        f"⚠ El Mundo del Vino: catálogo parcial conservado tras fallo "
                        f"en página {page_number}: {warning_message}",
                        file=sys.stderr,
                        flush=True,
                    )
                    break

                pages += 1
                cards += page_cards
                signature = tuple(sorted(page_products))
                if signature and signature == previous_signature:
                    partial = True
                    warning_message = (
                        f"Shopify repitió la página {page_number}; se corta para evitar duplicados."
                    )
                    print(f"⚠ El Mundo del Vino: {warning_message}", file=sys.stderr, flush=True)
                    break
                previous_signature = signature
                before = len(all_products)
                for url, product in page_products.items():
                    if url in all_products:
                        duplicates += 1
                    all_products[url] = _merge(all_products.get(url), product)
                print(
                    f"✓ El Mundo del Vino catálogo global página {page_number}: "
                    f"registros_shopify={raw_count}, productos={len(page_products)}, "
                    f"nuevos={len(all_products) - before}, global={len(all_products)}",
                    flush=True,
                )
                if raw_count < GLOBAL_PAGE_SIZE:
                    complete = True
                    break
            else:
                partial = True
                warning_message = f"Se alcanzó MAX_GLOBAL_PAGES={MAX_GLOBAL_PAGES}."
    finally:
        session.close()

    health_status, health_score = _health(
        product_count=len(all_products), partial=partial, complete=complete
    )
    duration_ms = int((time.monotonic() - started) * 1000)
    section_status = "partial" if partial or not complete else "success"
    section = SectionStats(
        key="catalogo-global",
        name="Catálogo global Shopify",
        url=source.url(1) if source else _global_json_url(1),
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
        discovery_source="shopify_global_products_json",
        health_status=health_status,
        health_score=health_score,
        structural_warnings=int(section.structural_warning),
        section_stats=(section,),
        performance_ms={**metrics.as_dict(), "total": duration_ms},
    )
    print(
        f"Resumen El Mundo del Vino: fuente=catálogo_global, páginas={pages}, "
        f"productos_únicos={len(all_products)}, completo={'sí' if complete else 'no'}, "
        f"salud={health_status}({health_score})",
        flush=True,
    )
    if not all_products:
        raise RuntimeError("El Mundo del Vino no entregó productos desde el catálogo global Shopify.")
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
