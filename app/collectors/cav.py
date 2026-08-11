from __future__ import annotations

import html as html_lib
import random
import re
import time
import unicodedata
from dataclasses import dataclass
from urllib.parse import parse_qs, urlencode, unquote_plus, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup, Tag
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, sync_playwright

from app.collectors.base import StoreMetadata
from app.deadlines import ensure_budget
from app.domain import CollectedPriceQuote, CollectedProduct, CollectionBatch, CollectionStats, SectionStats
from app.performance import PerformanceSettings, install_resource_blocking

BASE_URL = "https://cav.cl"
SHOP_URL = f"{BASE_URL}/tienda"
PAGE_SIZE = 48
MAX_PAGES_PER_SHARD = 30
# La tienda publica actualmente alrededor de mil productos de vino y más de un
# centenar de destilados/otros alcoholes. En diagnóstico preferimos fallar antes
# que declarar cobertura completa con un subconjunto pequeño.
MIN_PLAUSIBLE_PRODUCTS = 800
BROWSER_NAV_TIMEOUT_MS = 30_000
STATIC_EDITORIAL_CEILING = 35

PRODUCT_LINK_SELECTOR = 'a[href*="/tienda/producto/"]'
ALGOLIA_HIT_SELECTOR = ".ais-Hits-item, .ais-InfiniteHits-item, [class*='ais-Hits-item']"

# CAV expone en la URL un estado de búsqueda compatible con InstantSearch:
# fR[family.name], fR[wine_type.name], hPP, idx, p y q. La búsqueda global se
# acerca/supera el límite habitual de paginación de Algolia, por lo que el
# collector no vuelve a recorrer el índice global. Se particiona por familias y,
# para Vinos, por categoría/tipo.
DEFAULT_WINE_TYPES = (
    "Tinto",
    "Ensamblaje Tinto",
    "Blanco",
    "Espumoso",
    "Bajos Y Sin Alcohol",
    "Ensamblaje Blanco",
    "Rosado",
    "Naranjo",
    "Sin Informacion",
)

# Solo familias pertinentes para el monitor. Accesorios, revistas/libros y otras
# familias editoriales quedan fuera deliberadamente.
ALCOHOL_FAMILIES = (
    "Licores",
    "Whisky",
    "Piscos",
    "Packs",
    "Cervezas",
)

_LABEL_RE = {
    "member": re.compile(r"Socio\s*:\s*\$?\s*([\d.]+)", re.I),
    "sale": re.compile(r"Oferta\s*:\s*\$?\s*([\d.]+)", re.I),
    "normal": re.compile(r"Normal\s*:\s*\$?\s*([\d.]+)", re.I),
    "stock": re.compile(r"Stock\s*:\s*(50\+|\d+)", re.I),
}
_PRODUCT_PATH_RE = re.compile(r"/tienda/producto/", re.I)
_SKU_RE = re.compile(r"-(\d{3,})/?$")


@dataclass(frozen=True)
class _Shard:
    key: str
    label: str
    filters: tuple[tuple[str, str], ...]
    max_plausible: int


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
            source_sections=("CAV diagnóstico segmentado",),
            sku=sku_match.group(1) if sku_match else None,
            price_quotes=tuple(quotes),
        )
    return products, cards


def _page_url(page: int, filters: tuple[tuple[str, str], ...] = ()) -> str:
    params: list[tuple[str, str | int]] = [
        ("idx", "products"),
        ("p", page),
        ("hPP", PAGE_SIZE),
        ("q", ""),
    ]
    params.extend(filters)
    return f"{SHOP_URL}?{urlencode(params)}"


def _wait_for_rendered_catalog(page: Page, timeout_ms: int) -> bool:
    try:
        page.locator(ALGOLIA_HIT_SELECTOR).first.wait_for(state="attached", timeout=timeout_ms)
        return True
    except PlaywrightTimeoutError:
        try:
            page.locator(PRODUCT_LINK_SELECTOR).first.wait_for(state="attached", timeout=2_000)
            return True
        except PlaywrightTimeoutError:
            return False


def _rendered_catalog_markup(page: Page) -> tuple[str, int, str]:
    hit_locator = page.locator(ALGOLIA_HIT_SELECTOR)
    hit_count = hit_locator.count()
    if hit_count:
        fragments = hit_locator.evaluate_all("els => els.map(el => el.outerHTML).join('\\n')")
        return f"<div>{fragments}</div>", hit_count, "algolia_hits"

    html = page.content()
    link_count = page.locator(PRODUCT_LINK_SELECTOR).count()
    return html, link_count, "rendered_full_page_fallback"


def _discover_filter_values(html: str, key: str) -> tuple[str, ...]:
    """Descubre valores de facetas expuestos por CAV en hrefs de la página.

    Soporta tanto URLs normales como entidades HTML/URLs percent-encoded. Si el
    frontend cambia y deja de exponer estos enlaces, el caller conserva una lista
    conocida y segura como fallback.
    """

    target = f"fR[{key}][0]"
    values: set[str] = set()
    soup = BeautifulSoup(html, "html.parser")
    for node in soup.find_all(href=True):
        href = html_lib.unescape(str(node.get("href") or ""))
        query = parse_qs(urlparse(urljoin(BASE_URL, href)).query)
        for value in query.get(target, []):
            cleaned = " ".join(str(value).split()).strip()
            if cleaned:
                values.add(cleaned)

    # Algunos bundles incrustan rutas en JSON/atributos en vez de anchors.
    decoded = unquote_plus(html_lib.unescape(html))
    pattern = re.compile(re.escape(target) + r"=([^&\"'<>]+)")
    for match in pattern.finditer(decoded):
        cleaned = " ".join(unquote_plus(match.group(1)).split()).strip()
        if cleaned:
            values.add(cleaned)
    return tuple(sorted(values, key=lambda value: (_fold(value), value)))


def _shards(discovered_wine_types: tuple[str, ...] = ()) -> tuple[_Shard, ...]:
    wine_types = list(DEFAULT_WINE_TYPES)
    for value in discovered_wine_types:
        if _fold(value) not in {_fold(current) for current in wine_types}:
            wine_types.append(value)

    result: list[_Shard] = []
    wine_limits = {
        "tinto": 750,
        "ensamblaje tinto": 450,
        "blanco": 300,
        "espumoso": 250,
        "bajos y sin alcohol": 180,
        "ensamblaje blanco": 150,
        "rosado": 150,
        "naranjo": 150,
        "sin informacion": 180,
    }
    for wine_type in wine_types:
        result.append(_Shard(
            key=f"vinos_{re.sub(r'[^a-z0-9]+', '_', _fold(wine_type)).strip('_')}",
            label=f"Vinos / {wine_type}",
            filters=(
                ("fR[family.name][0]", "Vinos"),
                ("fR[wine_type.name][0]", wine_type),
            ),
            max_plausible=wine_limits.get(_fold(wine_type), 400),
        ))

    family_limits = {
        "Licores": 300,
        "Whisky": 180,
        "Piscos": 120,
        "Packs": 150,
        "Cervezas": 120,
    }
    for family in ALCOHOL_FAMILIES:
        result.append(_Shard(
            key=re.sub(r"[^a-z0-9]+", "_", _fold(family)).strip("_"),
            label=family,
            filters=(("fR[family.name][0]", family),),
            max_plausible=family_limits[family],
        ))
    return tuple(result)


def _goto(page: Page, url: str, *, label: str) -> int | None:
    response = page.goto(url, wait_until="domcontentloaded", timeout=BROWSER_NAV_TIMEOUT_MS)
    status = response.status if response is not None else None
    if status in {403, 429, 430}:
        raise RuntimeError(f"CAV diagnóstico limitado por HTTP {status} en {label}; se corta sin fan-out.")
    if status is not None and not (200 <= status < 300):
        raise RuntimeError(f"CAV diagnóstico respondió HTTP {status} en {label}.")
    return status


def _collect_products() -> CollectionBatch:
    settings = PerformanceSettings.from_env()
    started = time.monotonic()
    products: dict[str, CollectedProduct] = {}
    total_pages = total_cards = duplicates = 0
    section_stats: list[SectionStats] = []
    source_modes: set[str] = set()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-background-networking"],
        )
        context = browser.new_context(locale="es-CL", timezone_id="America/Santiago")
        install_resource_blocking(context, enabled=settings.block_browser_resources)
        page = context.new_page()
        page.set_default_timeout(settings.product_wait_timeout_ms)
        try:
            # Descubrimiento de categorías de vino. No usamos el índice global
            # como fuente de cobertura, porque puede quedar truncado por el límite
            # de paginación del buscador.
            discovered_wine_types: tuple[str, ...] = ()
            try:
                ensure_budget("CAV diagnóstico descubrimiento de facetas")
                discovery_url = _page_url(0, (("fR[family.name][0]", "Vinos"),))
                _goto(page, discovery_url, label="descubrimiento de facetas")
                if _wait_for_rendered_catalog(page, settings.product_wait_timeout_ms):
                    page.wait_for_timeout(max(500, settings.quick_settle_ms))
                    discovered_wine_types = _discover_filter_values(page.content(), "wine_type.name")
            except Exception as exc:  # fallback seguro a categorías conocidas
                print(f"CAV diagnóstico: no se pudieron descubrir facetas dinámicas ({exc}); se usan defaults.", flush=True)

            shard_list = _shards(discovered_wine_types)
            print(
                "CAV diagnóstico segmentado: "
                + ", ".join(shard.label for shard in shard_list),
                flush=True,
            )

            for shard in shard_list:
                ensure_budget(f"CAV diagnóstico shard {shard.label}")
                shard_started = time.monotonic()
                shard_seen: dict[str, CollectedProduct] = {}
                shard_pages = shard_cards = shard_duplicates = 0
                previous_signature: tuple[str, ...] | None = None
                tolerated_zero_one_alias = False
                shard_complete = False
                shard_mode = "rendered_full_page_fallback"

                for page_number in range(MAX_PAGES_PER_SHARD):
                    ensure_budget(f"CAV {shard.label} página {page_number + 1}")
                    url = _page_url(page_number, shard.filters)
                    status = _goto(page, url, label=f"{shard.label} página {page_number + 1}")
                    if not _wait_for_rendered_catalog(page, settings.product_wait_timeout_ms):
                        raise RuntimeError(
                            f"CAV {shard.label} no renderizó el listado dentro del tiempo esperado."
                        )
                    page.wait_for_timeout(max(500, settings.quick_settle_ms))
                    markup, hit_count, mode = _rendered_catalog_markup(page)
                    parsed, page_cards = _parse_html(markup)
                    shard_mode = mode
                    source_modes.add(mode)
                    shard_pages += 1
                    shard_cards += page_cards
                    total_pages += 1
                    total_cards += page_cards

                    if not parsed:
                        if page_number == 0:
                            # Una subcategoría de vino puede desaparecer del
                            # catálogo. Si es una faceta conocida pero hoy vacía,
                            # se considera shard vacío, no error estructural.
                            if shard.key.startswith("vinos_"):
                                shard_complete = True
                                print(f"CAV {shard.label}: sin productos vigentes; shard vacío.", flush=True)
                                break
                            raise RuntimeError(f"CAV {shard.label} no entregó tarjetas compatibles.")
                        shard_complete = True
                        break

                    signature = tuple(sorted(parsed))
                    if page_number == 1 and signature == previous_signature and not tolerated_zero_one_alias:
                        tolerated_zero_one_alias = True
                        print(
                            f"CAV {shard.label}: p=0 y p=1 parecen alias; se prueba la página siguiente.",
                            flush=True,
                        )
                        continue

                    before_shard = len(shard_seen)
                    for url_key, product in parsed.items():
                        if url_key in shard_seen:
                            shard_duplicates += 1
                        shard_seen[url_key] = product
                        if url_key in products:
                            duplicates += 1
                        products[url_key] = product
                    new_count = len(shard_seen) - before_shard

                    print(
                        f"CAV {shard.label} página {page_number + 1}: HTTP={status}, "
                        f"modo={mode}, hits_dom={hit_count}, productos={len(parsed)}, "
                        f"nuevos_shard={new_count}, shard_total={len(shard_seen)}, total={len(products)}",
                        flush=True,
                    )

                    if len(shard_seen) > shard.max_plausible:
                        raise RuntimeError(
                            f"CAV {shard.label} superó el máximo plausible ({len(shard_seen)} > "
                            f"{shard.max_plausible}); probablemente el filtro no fue aplicado."
                        )

                    # Señal terminal principal para el fallback DOM: CAV conserva
                    # bloques editoriales al pedir una página posterior al final.
                    # Esos bloques ya fueron vistos, por lo que la primera página
                    # sin URLs nuevas marca un final natural del shard. Esto evita
                    # convertir la cola repetida en un falso error.
                    if page_number > 0 and new_count == 0:
                        shard_complete = True
                        print(
                            f"CAV {shard.label}: fin confirmado por cola sin productos nuevos "
                            f"(página {page_number + 1}).",
                            flush=True,
                        )
                        break

                    # Si el frontend vuelve a exponer hits Algolia estándar, una
                    # página corta es una señal explícita de fin y evita el probe
                    # adicional.
                    if mode == "algolia_hits" and hit_count < PAGE_SIZE:
                        shard_complete = True
                        break

                    previous_signature = signature
                    time.sleep(random.uniform(0.55, 1.1))
                else:
                    raise RuntimeError(
                        f"CAV {shard.label} alcanzó {MAX_PAGES_PER_SHARD} páginas sin señal confiable de fin."
                    )

                if not shard_complete:
                    raise RuntimeError(f"CAV {shard.label} terminó sin confirmar cobertura.")

                section_stats.append(SectionStats(
                    key=f"cav_{shard.key}",
                    name=f"CAV diagnóstico · {shard.label}",
                    url=_page_url(0, shard.filters),
                    pages_visited=shard_pages,
                    cards_seen=shard_cards,
                    unique_products=len(shard_seen),
                    duplicates_removed=shard_duplicates,
                    duration_ms=int((time.monotonic() - shard_started) * 1000),
                    status="success",
                    structural_warning=False,
                ))
        finally:
            context.close()
            browser.close()

    count = len(products)
    health_status = "HEALTHY" if count >= MIN_PLAUSIBLE_PRODUCTS else "BROKEN"
    health_score = 100 if health_status == "HEALTHY" else (20 if count else 0)
    if health_status != "HEALTHY":
        raise RuntimeError(
            f"CAV entregó una cobertura segmentada no confiable ({count} productos; "
            f"mínimo esperado {MIN_PLAUSIBLE_PRODUCTS}). No se persiste la captura parcial."
        )

    discovery_source = "cav_sharded_" + ("algolia_hits" if source_modes == {"algolia_hits"} else "rendered_dom")
    return CollectionBatch(
        products=sorted(products.values(), key=lambda item: (item.name.casefold(), item.url)),
        stats=CollectionStats(
            pages_visited=total_pages,
            cards_seen=total_cards,
            unique_products=count,
            sections_discovered=len(section_stats),
            sections_visited=len(section_stats),
            sections_succeeded=len(section_stats),
            sections_failed=0,
            duplicates_removed=duplicates,
            discovery_source=discovery_source,
            health_status=health_status,
            health_score=health_score,
            structural_warnings=0,
            section_stats=tuple(section_stats),
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
        requires_browser=True,
        comparison_enabled=False,
        diagnostic_mode=True,
    )

    def collect(self) -> CollectionBatch:
        return _collect_products()


def scrape() -> list[CollectedProduct]:
    return _collect_products().products
