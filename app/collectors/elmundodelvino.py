from __future__ import annotations

import json
import os
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
SHOPIFY_PERMANENT_HOST = "https://elmundodelvino-cl.myshopify.com"
STOREFRONT_API_VERSION = os.getenv("EL_MUNDO_STOREFRONT_API_VERSION", "2026-07").strip() or "2026-07"
STOREFRONT_GRAPHQL_URL = (
    f"{SHOPIFY_PERMANENT_HOST}/api/{STOREFRONT_API_VERSION}/graphql.json"
)
REQUEST_TIMEOUT = (5, 22)
STOREFRONT_PAGE_SIZE = 75
STOREFRONT_VARIANTS_PER_PRODUCT = 5
MAX_STOREFRONT_PAGES = 15
STOREFRONT_INITIAL_JITTER_RANGE_SECONDS = (45.0, 90.0)
STOREFRONT_PAGE_DELAY_RANGE_SECONDS = (5.0, 8.0)
STOREFRONT_RATE_LIMIT_DEFAULT_SECONDS = 90.0
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

STOREFRONT_PRODUCTS_QUERY = """
query ElMundoCatalog($first: Int!, $after: String, $variantsFirst: Int!) @inContext(country: CL) {
  products(first: $first, after: $after, sortKey: ID) {
    nodes {
      id
      handle
      title
      productType
      vendor
      availableForSale
      priceRange {
        minVariantPrice { amount currencyCode }
        maxVariantPrice { amount currencyCode }
      }
      compareAtPriceRange {
        minVariantPrice { amount currencyCode }
        maxVariantPrice { amount currencyCode }
      }
      selectedOrFirstAvailableVariant {
        id
        availableForSale
        price { amount currencyCode }
        compareAtPrice { amount currencyCode }
      }
      variants(first: $variantsFirst) {
        nodes {
          id
          availableForSale
          price { amount currencyCode }
          compareAtPrice { amount currencyCode }
        }
      }
    }
    pageInfo {
      hasNextPage
      endCursor
    }
  }
}
"""

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


@dataclass(frozen=True)
class CatalogResult:
    source_name: str
    source_url: str
    products: dict[str, CollectedProduct]
    pages: int
    cards: int
    duplicates: int
    partial: bool
    complete: bool
    warning_message: str | None = None


class StorefrontUnavailableError(RuntimeError):
    """The Storefront API is unavailable or incompatible; legacy fallback is allowed."""


class SecurityRejectionError(RuntimeError):
    """Shopify rejected the request as automated/malicious traffic (HTTP 430/403)."""


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
        allowed_methods=frozenset({"GET", "POST"}),
        respect_retry_after_header=False,
        raise_on_status=False,
    )
    session.mount("https://", HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=4))
    session.headers.update(
        {
            # Identidad estable y transparente. No fingimos un navegador: Shopify
            # recomienda autenticar bots con Web Bot Auth cuando se requieren límites altos.
            "User-Agent": "ProyectoMonitorLicores/5.3.4",
            "Accept-Language": "es-CL,es;q=0.9,en;q=0.7",
            "Accept": "application/json,text/html;q=0.8,*/*;q=0.5",
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
    if re.fullmatch(r"\d+(?:\.\d+)?", raw):
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



def _storefront_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Origin": BASE_URL,
        "Referer": f"{BASE_URL}/",
    }
    token = os.getenv("EL_MUNDO_STOREFRONT_ACCESS_TOKEN", "").strip()
    if token:
        headers["X-Shopify-Storefront-Access-Token"] = token
    return headers


def _storefront_retry_after_seconds(response: requests.Response) -> float:
    if (response.headers.get("Retry-After") or "").strip():
        return _retry_after_seconds(response)
    return min(RATE_LIMIT_MAX_SECONDS, STOREFRONT_RATE_LIMIT_DEFAULT_SECONDS)


def _graphql_error_details(payload: object) -> tuple[set[str], str]:
    if not isinstance(payload, dict):
        return set(), "respuesta GraphQL no es un objeto JSON"
    raw_errors = payload.get("errors")
    if not isinstance(raw_errors, list):
        return set(), ""
    codes: set[str] = set()
    messages: list[str] = []
    for item in raw_errors:
        if not isinstance(item, dict):
            continue
        message = _normalize_text(str(item.get("message") or ""))
        if message:
            messages.append(message[:240])
        extensions = item.get("extensions")
        if isinstance(extensions, dict):
            code = _normalize_text(str(extensions.get("code") or "")).upper()
            if code:
                codes.add(code)
    return codes, "; ".join(messages[:3])


def _graphql_throttled(payload: object) -> bool:
    codes, message = _graphql_error_details(payload)
    return "THROTTLED" in codes or "throttled" in message.casefold()


def _fetch_storefront_payload(
    session: requests.Session,
    *,
    after: str | None,
    page_number: int,
    metrics: PhaseMetrics,
) -> object:
    variables = {
        "first": STOREFRONT_PAGE_SIZE,
        "after": after,
        "variantsFirst": STOREFRONT_VARIANTS_PER_PRODUCT,
    }
    last_delay = RATE_LIMIT_MIN_SECONDS
    for attempt in range(RATE_LIMIT_RETRIES + 1):
        with metrics.measure("storefront_graphql_http"):
            response = session.post(
                STOREFRONT_GRAPHQL_URL,
                json={"query": STOREFRONT_PRODUCTS_QUERY, "variables": variables},
                timeout=bounded_request_timeout(REQUEST_TIMEOUT),
                headers=_storefront_headers(),
            )

        if response.status_code in {403, 430}:
            raise SecurityRejectionError(
                f"Shopify rechazó Storefront API con HTTP {response.status_code} "
                f"en página {page_number}; no se prueban endpoints alternativos en este ciclo."
            )

        if response.status_code in {404, 405}:
            raise StorefrontUnavailableError(
                f"Storefront API no disponible: HTTP {response.status_code} en "
                f"{STOREFRONT_GRAPHQL_URL}"
            )

        if response.status_code == 429:
            last_delay = _storefront_retry_after_seconds(response)
            if attempt < RATE_LIMIT_RETRIES:
                print(
                    f"⚠ El Mundo del Vino Storefront API página {page_number}: HTTP 429; "
                    f"pausa controlada de {last_delay:.0f}s antes de un único reintento.",
                    file=sys.stderr,
                    flush=True,
                )
                _sleep_with_budget(
                    last_delay,
                    context=f"rate limit Storefront API página {page_number}",
                )
                continue
            raise RateLimitError(
                url=STOREFRONT_GRAPHQL_URL,
                delay_seconds=last_delay,
                attempts=attempt + 1,
            )

        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise StorefrontUnavailableError(
                f"Storefront API respondió HTTP {response.status_code}: {exc}"
            ) from exc

        try:
            payload = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            if _looks_like_challenge(response):
                raise SecurityRejectionError(
                    "Storefront API devolvió una página de challenge en lugar de JSON."
                ) from exc
            raise StorefrontUnavailableError(
                "Storefront API no devolvió JSON válido."
            ) from exc

        if _graphql_throttled(payload):
            last_delay = _storefront_retry_after_seconds(response)
            if attempt < RATE_LIMIT_RETRIES:
                print(
                    f"⚠ El Mundo del Vino Storefront API página {page_number}: "
                    f"GraphQL THROTTLED; pausa de {last_delay:.0f}s antes de un único reintento.",
                    file=sys.stderr,
                    flush=True,
                )
                _sleep_with_budget(
                    last_delay,
                    context=f"throttle GraphQL página {page_number}",
                )
                continue
            raise RateLimitError(
                url=STOREFRONT_GRAPHQL_URL,
                delay_seconds=last_delay,
                attempts=attempt + 1,
            )

        codes, message = _graphql_error_details(payload)
        if codes or message:
            code_text = ",".join(sorted(codes)) or "sin código"
            raise StorefrontUnavailableError(
                f"Storefront API devolvió errores GraphQL ({code_text}): {message or 'sin detalle'}"
            )
        return payload

    raise RuntimeError("No fue posible consultar Storefront API.")


def _money_amount(money: object) -> object:
    if not isinstance(money, dict):
        return None
    return money.get("amount")


def _parse_storefront_graphql(
    payload: object,
) -> tuple[dict[str, CollectedProduct], int, int, bool, str | None]:
    if not isinstance(payload, dict):
        raise StorefrontUnavailableError("Respuesta Storefront API inválida.")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise StorefrontUnavailableError("Storefront API no incluyó data.")
    connection = data.get("products")
    if not isinstance(connection, dict):
        raise StorefrontUnavailableError("Storefront API no incluyó data.products.")
    nodes = connection.get("nodes")
    page_info = connection.get("pageInfo")
    if not isinstance(nodes, list) or not isinstance(page_info, dict):
        raise StorefrontUnavailableError("Storefront API entregó una estructura incompleta.")

    mapped: list[dict[str, object]] = []
    for raw_product in nodes:
        if not isinstance(raw_product, dict):
            continue
        variants_payload = raw_product.get("variants")
        variant_nodes = (
            variants_payload.get("nodes")
            if isinstance(variants_payload, dict)
            else []
        )
        variants: list[dict[str, object]] = []
        seen_variant_ids: set[str] = set()
        if isinstance(variant_nodes, list):
            for raw_variant in variant_nodes:
                if not isinstance(raw_variant, dict):
                    continue
                variant_id = str(raw_variant.get("id") or "")
                if variant_id:
                    seen_variant_ids.add(variant_id)
                variants.append(
                    {
                        "available": raw_variant.get("availableForSale", True),
                        "price": _money_amount(raw_variant.get("price")),
                        "compare_at_price": _money_amount(raw_variant.get("compareAtPrice")),
                    }
                )

        selected = raw_product.get("selectedOrFirstAvailableVariant")
        if isinstance(selected, dict):
            selected_id = str(selected.get("id") or "")
            if not selected_id or selected_id not in seen_variant_ids:
                variants.append(
                    {
                        "available": selected.get("availableForSale", True),
                        "price": _money_amount(selected.get("price")),
                        "compare_at_price": _money_amount(selected.get("compareAtPrice")),
                    }
                )

        if not variants and raw_product.get("availableForSale", False):
            price_range = raw_product.get("priceRange")
            compare_range = raw_product.get("compareAtPriceRange")
            min_price = (
                _money_amount(price_range.get("minVariantPrice"))
                if isinstance(price_range, dict)
                else None
            )
            max_compare = (
                _money_amount(compare_range.get("maxVariantPrice"))
                if isinstance(compare_range, dict)
                else None
            )
            variants.append(
                {
                    "available": True,
                    "price": min_price,
                    "compare_at_price": max_compare,
                }
            )

        mapped.append(
            {
                "title": raw_product.get("title"),
                "handle": raw_product.get("handle"),
                "product_type": raw_product.get("productType"),
                "tags": [raw_product.get("vendor") or ""],
                "variants": variants,
            }
        )

    products, candidates = _parse_json({"products": mapped})
    has_next = bool(page_info.get("hasNextPage"))
    end_cursor_raw = page_info.get("endCursor")
    end_cursor = str(end_cursor_raw) if end_cursor_raw else None
    return products, candidates, len(nodes), has_next, end_cursor


def _collect_storefront_catalog(
    session: requests.Session,
    metrics: PhaseMetrics,
) -> CatalogResult:
    all_products: dict[str, CollectedProduct] = {}
    pages = 0
    cards = 0
    duplicates = 0
    after: str | None = None
    previous_cursor: str | None = None

    initial_delay = random.uniform(*STOREFRONT_INITIAL_JITTER_RANGE_SECONDS)
    print(
        f"El Mundo del Vino: jitter inicial de {initial_delay:.1f}s para separar "
        "la consulta Shopify del arranque paralelo de otros collectors.",
        flush=True,
    )
    _sleep_with_budget(initial_delay, context="jitter inicial Storefront API")

    for page_number in range(1, MAX_STOREFRONT_PAGES + 1):
        ensure_budget(f"El Mundo del Vino Storefront API página {page_number}")
        if page_number > 1:
            delay = random.uniform(*STOREFRONT_PAGE_DELAY_RANGE_SECONDS)
            print(
                f"El Mundo del Vino: pausa preventiva de {delay:.1f}s antes de "
                f"Storefront API página {page_number}.",
                flush=True,
            )
            _sleep_with_budget(delay, context="pausa Storefront API de El Mundo del Vino")

        payload = _fetch_storefront_payload(
            session,
            after=after,
            page_number=page_number,
            metrics=metrics,
        )
        with metrics.measure("storefront_graphql_parse"):
            page_products, page_cards, raw_count, has_next, end_cursor = (
                _parse_storefront_graphql(payload)
            )
        pages += 1
        cards += page_cards
        before = len(all_products)
        for url, product in page_products.items():
            if url in all_products:
                duplicates += 1
            all_products[url] = _merge(all_products.get(url), product)
        print(
            f"✓ El Mundo del Vino Storefront API página {page_number}: "
            f"registros_shopify={raw_count}, productos={len(page_products)}, "
            f"nuevos={len(all_products) - before}, global={len(all_products)}",
            flush=True,
        )

        if not has_next:
            if not all_products:
                raise StorefrontUnavailableError(
                    "Storefront API respondió correctamente, pero no entregó productos."
                )
            return CatalogResult(
                source_name="shopify_storefront_graphql",
                source_url=STOREFRONT_GRAPHQL_URL,
                products=all_products,
                pages=pages,
                cards=cards,
                duplicates=duplicates,
                partial=False,
                complete=True,
            )
        if not end_cursor or end_cursor == previous_cursor:
            raise StorefrontUnavailableError(
                f"Storefront API indicó más páginas, pero no avanzó el cursor en página {page_number}."
            )
        previous_cursor = end_cursor
        after = end_cursor

    return CatalogResult(
        source_name="shopify_storefront_graphql",
        source_url=STOREFRONT_GRAPHQL_URL,
        products=all_products,
        pages=pages,
        cards=cards,
        duplicates=duplicates,
        partial=True,
        complete=False,
        warning_message=f"Se alcanzó MAX_STOREFRONT_PAGES={MAX_STOREFRONT_PAGES}.",
    )


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
        for host in (SHOPIFY_PERMANENT_HOST, BASE_URL, ALT_BASE_URL):
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



def _collect_legacy_global_catalog(
    session: requests.Session,
    metrics: PhaseMetrics,
) -> CatalogResult:
    all_products: dict[str, CollectedProduct] = {}
    pages = 0
    cards = 0
    duplicates = 0
    partial = False
    complete = False
    warning_message: str | None = None

    ensure_budget("El Mundo del Vino catálogo global legacy")
    source, first_products, first_cards, first_raw_count = _select_global_source(session, metrics)
    pages = 1
    cards = first_cards
    all_products.update(first_products)
    previous_signature = tuple(sorted(first_products))
    print(
        f"✓ El Mundo del Vino catálogo legacy página 1: fuente={source.url(1)}, "
        f"registros_shopify={first_raw_count}, productos={len(first_products)}, "
        f"global={len(all_products)}",
        flush=True,
    )
    if first_raw_count < GLOBAL_PAGE_SIZE:
        complete = True
    else:
        for page_number in range(2, MAX_GLOBAL_PAGES + 1):
            ensure_budget(f"El Mundo del Vino catálogo legacy página {page_number}")
            delay = random.uniform(*GLOBAL_PAGE_DELAY_RANGE_SECONDS)
            print(
                f"El Mundo del Vino: pausa preventiva de {delay:.1f}s antes de "
                f"catálogo legacy página {page_number}.",
                flush=True,
            )
            _sleep_with_budget(delay, context="pausa catálogo legacy de El Mundo del Vino")
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
                    f"obtenidos antes del rate limit legacy en página {page_number}: {exc}",
                    file=sys.stderr,
                    flush=True,
                )
                break
            except Exception as exc:
                partial = True
                warning_message = f"{type(exc).__name__}: {exc}"
                print(
                    f"⚠ El Mundo del Vino: catálogo legacy parcial conservado tras fallo "
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
                    f"Shopify repitió la página legacy {page_number}; "
                    "se corta para evitar duplicados."
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
                f"✓ El Mundo del Vino catálogo legacy página {page_number}: "
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

    return CatalogResult(
        source_name="shopify_global_products_json_legacy",
        source_url=source.url(1),
        products=all_products,
        pages=pages,
        cards=cards,
        duplicates=duplicates,
        partial=partial,
        complete=complete,
        warning_message=warning_message,
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
    fallback_warning: str | None = None

    try:
        ensure_budget("El Mundo del Vino Storefront API")
        try:
            result = _collect_storefront_catalog(session, metrics)
        except (RateLimitError, SecurityRejectionError):
            # Un 429/430 indica clasificación o límite de tráfico. Probar más rutas
            # desde la misma IP solo empeora la reputación; el runner reutilizará
            # el último snapshot HEALTHY.
            raise
        except (StorefrontUnavailableError, requests.RequestException) as exc:
            fallback_warning = f"{type(exc).__name__}: {exc}"
            print(
                "⚠ El Mundo del Vino: Storefront API no estuvo disponible; "
                f"se intenta una única ruta legacy de bajo volumen. Detalle: {fallback_warning}",
                file=sys.stderr,
                flush=True,
            )
            result = _collect_legacy_global_catalog(session, metrics)
    finally:
        session.close()

    all_products = result.products
    warning_message = result.warning_message
    if fallback_warning:
        warning_message = (
            f"Storefront API fallback: {fallback_warning}"
            + (f" | {warning_message}" if warning_message else "")
        )

    health_status, health_score = _health(
        product_count=len(all_products),
        partial=result.partial,
        complete=result.complete,
    )
    duration_ms = int((time.monotonic() - started) * 1000)
    section_status = "partial" if result.partial or not result.complete else "success"
    section = SectionStats(
        key="catalogo-global",
        name=(
            "Catálogo global Shopify Storefront API"
            if result.source_name == "shopify_storefront_graphql"
            else "Catálogo global Shopify legacy"
        ),
        url=result.source_url,
        pages_visited=result.pages,
        cards_seen=result.cards,
        unique_products=len(all_products),
        duplicates_removed=result.duplicates,
        duration_ms=duration_ms,
        status=section_status,
        error_message=warning_message,
        structural_warning=section_status != "success" or bool(fallback_warning),
        performance_ms=metrics.as_dict(),
    )
    stats = CollectionStats(
        pages_visited=result.pages,
        cards_seen=result.cards,
        unique_products=len(all_products),
        sections_discovered=1,
        sections_visited=1,
        sections_succeeded=int(section_status == "success"),
        sections_failed=int(section_status != "success"),
        duplicates_removed=result.duplicates,
        discovery_source=result.source_name,
        health_status=health_status,
        health_score=health_score,
        structural_warnings=int(section.structural_warning),
        section_stats=(section,),
        performance_ms={**metrics.as_dict(), "total": duration_ms},
    )
    print(
        f"Resumen El Mundo del Vino: fuente={result.source_name}, "
        f"páginas={result.pages}, productos_únicos={len(all_products)}, "
        f"completo={'sí' if result.complete else 'no'}, "
        f"salud={health_status}({health_score})",
        flush=True,
    )
    if not all_products:
        raise RuntimeError(
            "El Mundo del Vino no entregó productos desde Storefront API ni catálogo legacy."
        )
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
