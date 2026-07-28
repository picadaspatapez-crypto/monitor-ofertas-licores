from __future__ import annotations

import json
import random
import re
import sys
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
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
MAX_PAGES_PER_SECTION = 80
JSON_PAGE_SIZE = 250
MIN_PLAUSIBLE_PRODUCTS = 120
SECTION_ATTEMPTS = 3
CATEGORY_DELAY_RANGE_SECONDS = (8.0, 12.0)
RATE_LIMIT_MIN_SECONDS = 30.0
RATE_LIMIT_MAX_SECONDS = 120.0
RATE_LIMIT_RETRIES = 1


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
_CHALLENGE_MARKERS = (
    "cf-chl-",
    "challenge-platform",
    "captcha",
    "access denied",
    "temporarily unavailable",
)


def _session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=2,
        connect=1,
        read=1,
        backoff_factor=0.7,
        # El HTTP 429 se maneja explícitamente para evitar reintentos ocultos y
        # cascadas JSON→HTML que agraven el bloqueo de Shopify.
        status_forcelist=(500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=False,
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
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        }
    )
    return session



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


def _rate_limit_wait(response: requests.Response, *, section_name: str, source: str) -> float:
    delay = _retry_after_seconds(response)
    print(
        f"⚠ El Mundo del Vino {section_name}: HTTP 429 en {source}; "
        f"pausa controlada de {delay:.0f}s antes de un único reintento.",
        file=sys.stderr,
        flush=True,
    )
    _sleep_with_budget(delay, context=f"rate limit de {section_name}")
    return delay

def _normalize_text(value: str) -> str:
    return " ".join((value or "").replace("\xa0", " ").split())


def _fold(value: str) -> str:
    return _normalize_text(value).casefold()


def _product_slug(raw_url: str) -> str | None:
    parsed = urlparse(urljoin(BASE_URL, raw_url))
    if parsed.netloc.casefold() not in {
        "elmundodelvino.cl",
        "www.elmundodelvino.cl",
    }:
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


def _category_url(section: CatalogSection, page: int, *, host: str = BASE_URL, cache_bust: bool = False) -> str:
    base = f"{host}/collections/{section.handle}"
    params: dict[str, str | int] = {}
    if page > 1:
        params["page"] = page
    if cache_bust:
        params["_monitor_ts"] = int(time.time() * 1000)
    return f"{base}?{urlencode(params)}" if params else base


def _json_url(section: CatalogSection, page: int, *, host: str = BASE_URL) -> str:
    return (
        f"{host}/collections/{section.handle}/products.json?"
        f"{urlencode({'limit': JSON_PAGE_SIZE, 'page': page})}"
    )


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


def _json_money(value: object) -> int | None:
    if value is None:
        return None
    raw = str(value).strip().replace("$", "").replace(" ", "")
    if not raw:
        return None
    # Shopify normalmente entrega CLP como "29990.00". El HTML chileno puede usar "29.990".
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
        ".card__heading",
        ".product-card__title",
        ".product-item__title",
        "h2",
        "h3",
        "h4",
        "[data-product-title]",
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


def _parse_json(payload: object, section_name: str) -> tuple[dict[str, CollectedProduct], int]:
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
        available_variants = [
            item for item in variants
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
            if (amount := _json_money(item.get("compare_at_price"))) is not None and amount > current
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


def _looks_like_challenge(response: requests.Response) -> bool:
    folded = response.text[:100_000].casefold()
    return any(marker in folded for marker in _CHALLENGE_MARKERS)


def _response_details(response: requests.Response) -> str:
    body = response.text
    return (
        f"HTTP={response.status_code}, bytes={len(response.content)}, "
        f"product_refs={body.count('/products/')}, "
        f"content_type={response.headers.get('content-type', '?')}, "
        f"challenge={'sí' if _looks_like_challenge(response) else 'no'}"
    )


def _fetch_json_page(
    session: requests.Session,
    section: CatalogSection,
    page_number: int,
    metrics: PhaseMetrics,
) -> tuple[dict[str, CollectedProduct], int, str] | None:
    last_error: Exception | None = None
    for host in (BASE_URL, ALT_BASE_URL):
        url = _json_url(section, page_number, host=host)
        last_delay = RATE_LIMIT_MIN_SECONDS
        for rate_attempt in range(RATE_LIMIT_RETRIES + 1):
            try:
                with metrics.measure("json_http"):
                    response = session.get(
                        url,
                        timeout=bounded_request_timeout(REQUEST_TIMEOUT),
                        headers={
                            "Accept": "application/json",
                            "Referer": _category_url(section, 1, host=host),
                        },
                    )
                if response.status_code == 429:
                    last_delay = _retry_after_seconds(response)
                    if rate_attempt < RATE_LIMIT_RETRIES:
                        _rate_limit_wait(
                            response,
                            section_name=section.name,
                            source=f"JSON página {page_number}",
                        )
                        continue
                    raise RateLimitError(
                        url=url,
                        delay_seconds=last_delay,
                        attempts=rate_attempt + 1,
                    )
                if response.status_code in {404, 405}:
                    break
                response.raise_for_status()
                try:
                    payload = response.json()
                except (json.JSONDecodeError, ValueError) as exc:
                    last_error = exc
                    break
                with metrics.measure("json_parse"):
                    products, cards = _parse_json(payload, section.name)
                if products or cards:
                    return products, cards, url
                break
            except RateLimitError:
                # Un 429 persistente no debe activar inmediatamente el fallback HTML:
                # eso multiplicaría las solicitudes y prolongaría el bloqueo de Shopify.
                raise
            except Exception as exc:
                last_error = exc
                break
    if last_error is not None:
        print(
            f"⚠ El Mundo del Vino {section.name}: feed JSON no utilizable "
            f"({type(last_error).__name__}: {last_error}); se prueba HTML.",
            file=sys.stderr,
            flush=True,
        )
    return None

def _fetch_html_page(
    session: requests.Session,
    section: CatalogSection,
    page_number: int,
    metrics: PhaseMetrics,
) -> tuple[dict[str, CollectedProduct], int, str, str]:
    diagnostics: list[str] = []
    last_error: Exception | None = None
    hosts = (BASE_URL, ALT_BASE_URL)
    attempt = 1
    rate_retries = 0
    while attempt <= SECTION_ATTEMPTS:
        host = hosts[(attempt - 1) % len(hosts)]
        url = _category_url(section, page_number, host=host, cache_bust=attempt > 1)
        try:
            with metrics.measure("html_http"):
                response = session.get(
                    url,
                    timeout=bounded_request_timeout(REQUEST_TIMEOUT),
                    headers={
                        "Accept": "text/html,application/xhtml+xml",
                        "Referer": f"{host}/",
                        "X-Requested-With": "XMLHttpRequest" if attempt == 3 else "",
                    },
                )
            diagnostics.append(f"intento {attempt}: {_response_details(response)}")
            if response.status_code == 429:
                delay = _retry_after_seconds(response)
                if rate_retries < RATE_LIMIT_RETRIES:
                    rate_retries += 1
                    _rate_limit_wait(
                        response,
                        section_name=section.name,
                        source=f"HTML página {page_number}",
                    )
                    continue
                raise RateLimitError(
                    url=url,
                    delay_seconds=delay,
                    attempts=rate_retries + 1,
                )
            response.raise_for_status()
            with metrics.measure("html_parse"):
                products, cards = _parse_html(response.text, section.name)
            if products or cards:
                return products, cards, url, "; ".join(diagnostics)
            if page_number > 1:
                return {}, 0, url, "; ".join(diagnostics)
        except RateLimitError:
            raise
        except Exception as exc:
            last_error = exc
            diagnostics.append(f"intento {attempt}: {type(exc).__name__}: {exc}")
        if attempt < SECTION_ATTEMPTS:
            _sleep_with_budget(
                min(4.0, 0.8 * attempt + random.uniform(0.1, 0.5)),
                context=f"reintento HTML de {section.name}",
            )
        attempt += 1
    detail = "; ".join(diagnostics)
    if last_error is not None:
        raise RuntimeError(f"HTML sin productos tras {SECTION_ATTEMPTS} intentos ({detail})") from last_error
    raise RuntimeError(f"HTML sin productos tras {SECTION_ATTEMPTS} intentos ({detail})")

def _collect_section(
    session: requests.Session,
    section: CatalogSection,
    metrics: PhaseMetrics,
) -> tuple[dict[str, CollectedProduct], int, int, str, bool, str | None]:
    # Shopify JSON es la fuente preferida. Solo se usa HTML cuando JSON falla por
    # una causa distinta de rate limiting. Un HTTP 429 persistente se respeta y
    # no desencadena una cascada adicional de solicitudes.
    json_first = _fetch_json_page(session, section, 1, metrics)
    if json_first is not None:
        first_products, first_cards, first_url = json_first
        section_products = dict(first_products)
        cards = first_cards
        pages = 1
        partial_warning = False
        partial_error: str | None = None
        if len(first_products) >= JSON_PAGE_SIZE:
            for page_number in range(2, MAX_PAGES_PER_SECTION + 1):
                ensure_budget(f"El Mundo del Vino {section.name} JSON página {page_number}")
                try:
                    page_result = _fetch_json_page(session, section, page_number, metrics)
                except RateLimitError as exc:
                    partial_warning = True
                    partial_error = str(exc)
                    print(
                        f"⚠ El Mundo del Vino {section.name}: se conserva la página "
                        f"ya obtenida ({len(section_products)} productos) y se corta la "
                        f"paginación por rate limit: {exc}",
                        file=sys.stderr,
                        flush=True,
                    )
                    break
                if page_result is None:
                    break
                page_products, page_cards, _ = page_result
                pages += 1
                cards += page_cards
                if not page_products:
                    break
                before = len(section_products)
                section_products.update(page_products)
                if len(section_products) == before or len(page_products) < JSON_PAGE_SIZE:
                    break
        source = f"shopify_json:{first_url}"
        if partial_warning:
            source += ":partial_rate_limited"
        return section_products, cards, pages, source, partial_warning, partial_error

    section_products: dict[str, CollectedProduct] = {}
    cards = 0
    pages = 0
    previous_signature: tuple[str, ...] = ()
    source = "html"
    partial_warning = False
    partial_error: str | None = None
    for page_number in range(1, MAX_PAGES_PER_SECTION + 1):
        ensure_budget(f"El Mundo del Vino {section.name} HTML página {page_number}")
        try:
            page_products, page_cards, url, diagnostics = _fetch_html_page(
                session, section, page_number, metrics
            )
        except RateLimitError as exc:
            if section_products:
                partial_warning = True
                partial_error = str(exc)
                print(
                    f"⚠ El Mundo del Vino {section.name}: HTML parcial conservado "
                    f"({len(section_products)} productos); {exc}",
                    file=sys.stderr,
                    flush=True,
                )
                break
            raise
        pages += 1
        cards += page_cards
        signature = tuple(sorted(page_products))
        print(
            f"El Mundo del Vino {section.key} página {page_number}: "
            f"productos={len(page_products)}, tarjetas={page_cards}, diagnóstico=[{diagnostics}]",
            flush=True,
        )
        if page_number > 1 and (not signature or signature == previous_signature):
            break
        previous_signature = signature
        before = len(section_products)
        section_products.update(page_products)
        if not page_products or len(section_products) == before:
            break
        source = f"html:{url}"
    return section_products, cards, pages, source, partial_warning, partial_error

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
            print(f"El Mundo del Vino categoría {index}/{len(CATALOG_SECTIONS)}: {section.name}", flush=True)
            try:
                (
                    section_products,
                    section_cards,
                    section_pages,
                    source,
                    partial_warning,
                    partial_error,
                ) = _collect_section(session, section, metrics)
                if not section_products:
                    raise RuntimeError("la sección respondió, pero no entregó productos utilizables")
                for product_url, product in section_products.items():
                    section_urls.add(product_url)
                    if product_url in all_products:
                        duplicates += 1
                        section_duplicates += 1
                    all_products[product_url] = _merge(all_products.get(product_url), product)
                pages += section_pages
                cards += section_cards
                if partial_warning:
                    status = "partial"
                    warning = True
                    error_message = (partial_error or "sección parcial por rate limit")[:1000]
                    print(
                        f"⚠ El Mundo del Vino {section.name}: captura parcial conservada; "
                        f"fuente={source}, páginas={section_pages}, tarjetas={section_cards}, "
                        f"productos={len(section_urls)}, global={len(all_products)}",
                        file=sys.stderr,
                        flush=True,
                    )
                else:
                    print(
                        f"✓ El Mundo del Vino {section.name}: fuente={source}, páginas={section_pages}, "
                        f"tarjetas={section_cards}, productos={len(section_urls)}, global={len(all_products)}",
                        flush=True,
                    )
            except Exception as exc:
                status = "failed"
                warning = True
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
            if index < len(CATALOG_SECTIONS):
                delay = random.uniform(*CATEGORY_DELAY_RANGE_SECONDS)
                print(
                    f"El Mundo del Vino: pausa preventiva de {delay:.1f}s antes de la siguiente categoría.",
                    flush=True,
                )
                _sleep_with_budget(delay, context="pausa entre categorías de El Mundo del Vino")
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
        discovery_source="shopify_json_rate_limited_with_html_fallback",
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
        raise RuntimeError(
            "El Mundo del Vino no entregó productos en ninguna categoría tras JSON, "
            "reintentos HTML, host alternativo y bypass de caché."
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
