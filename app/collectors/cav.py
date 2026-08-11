from __future__ import annotations

import random
import re
import time
import unicodedata
from urllib.parse import urlencode, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup, Tag
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, sync_playwright

from app.collectors.base import StoreMetadata
from app.deadlines import ensure_budget
from app.domain import CollectedPriceQuote, CollectedProduct, CollectionBatch, CollectionStats, SectionStats
from app.performance import PerformanceSettings, install_resource_blocking

BASE_URL = "https://cav.cl"
SHOP_URL = f"{BASE_URL}/tienda"
PAGE_SIZE = 48
MAX_PAGES = 60
MIN_PLAUSIBLE_PRODUCTS = 60
BROWSER_NAV_TIMEOUT_MS = 30_000
# El HTML entregado sin JavaScript contiene aproximadamente 20-30 productos de
# bloques editoriales (ofertas, destacados, liquidación, recomendados). El
# listado principal es client-side; por eso no aceptamos ese HTML estático como
# catálogo completo.
STATIC_EDITORIAL_CEILING = 35

PRODUCT_LINK_SELECTOR = 'a[href*="/tienda/producto/"]'
ALGOLIA_HIT_SELECTOR = ".ais-Hits-item, .ais-InfiniteHits-item, [class*='ais-Hits-item']"

_LABEL_RE = {
    "member": re.compile(r"Socio\s*:\s*\$?\s*([\d.]+)", re.I),
    "sale": re.compile(r"Oferta\s*:\s*\$?\s*([\d.]+)", re.I),
    "normal": re.compile(r"Normal\s*:\s*\$?\s*([\d.]+)", re.I),
    "stock": re.compile(r"Stock\s*:\s*(50\+|\d+)", re.I),
}
_PRODUCT_PATH_RE = re.compile(r"/tienda/producto/", re.I)
_SKU_RE = re.compile(r"-(\d{3,})/?$")


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
            source_sections=("CAV diagnóstico renderizado",),
            sku=sku_match.group(1) if sku_match else None,
            price_quotes=tuple(quotes),
        )
    return products, cards


def _page_url(page: int) -> str:
    return f"{SHOP_URL}?{urlencode({'idx': 'products', 'p': page, 'hPP': PAGE_SIZE, 'q': ''})}"


def _wait_for_rendered_catalog(page: Page, timeout_ms: int) -> bool:
    """Espera el listado client-side de CAV, no solo los bloques SSR estáticos."""

    try:
        page.locator(ALGOLIA_HIT_SELECTOR).first.wait_for(state="attached", timeout=timeout_ms)
        return True
    except PlaywrightTimeoutError:
        # Fallback diagnóstico: algunos despliegues pueden cambiar la clase del
        # widget aunque sigan renderizando tarjetas por JavaScript.
        try:
            page.locator(PRODUCT_LINK_SELECTOR).first.wait_for(state="attached", timeout=2_000)
            return True
        except PlaywrightTimeoutError:
            return False


def _rendered_catalog_markup(page: Page) -> tuple[str, int, str]:
    """Devuelve preferentemente solo los hits del buscador de CAV.

    Los bloques "Ofertas", "Destacados", "Liquidación" y "Recomendados" están
    presentes en todas las URLs paginadas y fueron la causa de la falsa
    repetición de v5.5.0. Al aislar `.ais-Hits-item` se pagina el catálogo real.
    """

    hit_locator = page.locator(ALGOLIA_HIT_SELECTOR)
    hit_count = hit_locator.count()
    if hit_count:
        fragments = hit_locator.evaluate_all("els => els.map(el => el.outerHTML).join('\\n')")
        return f"<div>{fragments}</div>", hit_count, "algolia_hits"

    # Fallback deliberadamente conservador: sirve para diagnosticar un cambio de
    # clases, pero la validación posterior impide confundir los bloques estáticos
    # con un catálogo completo.
    html = page.content()
    link_count = page.locator(PRODUCT_LINK_SELECTOR).count()
    return html, link_count, "rendered_full_page_fallback"


def _collect_products() -> CollectionBatch:
    settings = PerformanceSettings.from_env()
    started = time.monotonic()
    products: dict[str, CollectedProduct] = {}
    pages = cards = duplicates = 0
    previous_signature: tuple[str, ...] | None = None
    pagination_complete = False
    tolerated_zero_one_alias = False
    source_mode = "cav_rendered_algolia"

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
            for page_number in range(MAX_PAGES):
                ensure_budget(f"CAV diagnóstico renderizado página {page_number + 1}")
                url = _page_url(page_number)
                response = page.goto(url, wait_until="domcontentloaded", timeout=BROWSER_NAV_TIMEOUT_MS)
                status = response.status if response is not None else None
                if status in {403, 429, 430}:
                    raise RuntimeError(f"CAV diagnóstico limitado por HTTP {status}; se corta sin fan-out.")
                if status is not None and not (200 <= status < 300):
                    raise RuntimeError(f"CAV diagnóstico respondió HTTP {status} en página {page_number + 1}.")

                rendered = _wait_for_rendered_catalog(page, settings.product_wait_timeout_ms)
                if not rendered:
                    raise RuntimeError(
                        "CAV no renderizó el listado de productos client-side dentro del tiempo esperado."
                    )
                # Damos un margen corto para que InstantSearch termine de poblar
                # precios/tarjetas después de insertar el contenedor de hits.
                page.wait_for_timeout(max(500, settings.quick_settle_ms))
                markup, hit_count, mode = _rendered_catalog_markup(page)
                parsed, page_cards = _parse_html(markup)
                pages += 1
                cards += page_cards

                if mode != "algolia_hits":
                    source_mode = "cav_rendered_dom_fallback"
                    if page_number == 0 and len(parsed) <= STATIC_EDITORIAL_CEILING:
                        raise RuntimeError(
                            "CAV solo mostró los bloques editoriales estáticos; el listado dinámico de búsqueda "
                            "no quedó disponible. No se persiste una captura parcial."
                        )

                if not parsed:
                    if page_number == 0:
                        raise RuntimeError("CAV no entregó tarjetas compatibles tras renderizar JavaScript.")
                    pagination_complete = True
                    break

                signature = tuple(sorted(parsed))
                if signature == previous_signature:
                    # Algunos routers tratan p=0 y p=1 como alias de la primera
                    # página. Permitimos exactamente esa ambigüedad y probamos p=2;
                    # cualquier repetición posterior se considera cobertura incompleta.
                    if page_number == 1 and not tolerated_zero_one_alias:
                        tolerated_zero_one_alias = True
                        print(
                            "CAV diagnóstico: p=0 y p=1 parecen alias; se prueba la página siguiente.",
                            flush=True,
                        )
                        continue
                    raise RuntimeError(
                        f"CAV repitió el listado renderizado en página {page_number + 1}; "
                        "se rechaza la captura para evitar declarar cobertura falsa."
                    )
                previous_signature = signature

                before = len(products)
                for url_key, product in parsed.items():
                    if url_key in products:
                        duplicates += 1
                    products[url_key] = product
                new_count = len(products) - before
                print(
                    f"CAV diagnóstico renderizado página {page_number + 1}: HTTP={status}, "
                    f"modo={mode}, hits={hit_count}, productos={len(parsed)}, "
                    f"nuevos={new_count}, total={len(products)}",
                    flush=True,
                )

                # En el modo Algolia el número de hits es la señal correcta de
                # fin. En fallback DOM solo aceptamos fin por página vacía, porque
                # los bloques editoriales pueden alterar el conteo.
                if mode == "algolia_hits" and hit_count < PAGE_SIZE:
                    pagination_complete = True
                    break
                time.sleep(random.uniform(0.8, 1.5))
            else:
                raise RuntimeError(
                    f"CAV alcanzó el límite de {MAX_PAGES} páginas sin una señal confiable de fin de catálogo."
                )
        finally:
            context.close()
            browser.close()

    count = len(products)
    health_status = "HEALTHY" if count >= MIN_PLAUSIBLE_PRODUCTS and pagination_complete else "BROKEN"
    health_score = 100 if health_status == "HEALTHY" else (20 if count else 0)
    section = SectionStats(
        key="cav_diagnostic",
        name="CAV catálogo diagnóstico renderizado",
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
            discovery_source=source_mode,
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
        requires_browser=True,
        comparison_enabled=False,
        diagnostic_mode=True,
    )

    def collect(self) -> CollectionBatch:
        return _collect_products()


def scrape() -> list[CollectedProduct]:
    return _collect_products().products
