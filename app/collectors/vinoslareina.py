from __future__ import annotations

import time
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import requests

from app.collectors.base import StoreMetadata
from app.collectors.http_catalog import (
    HtmlCatalogSection,
    HtmlFetchResult,
    collect_html_store,
    parse_woocommerce_cards,
)
from app.deadlines import bounded_request_timeout, ensure_budget

BASE_URL = 'https://vinoslareina.cl'
SECTIONS = tuple(
    HtmlCatalogSection(key, name, f'/categoria-producto/{path}/')
    for key, name, path in (
        ('vinos', 'Vinos', 'vinos'),
        ('espumantes', 'Espumantes', 'espumantes'),
        ('destilados', 'Destilados', 'destilados'),
        ('cervezas', 'Cervezas', 'cervezas'),
    )
)


def _page(base: str, sec: HtmlCatalogSection, page: int) -> str:
    return f'{base}{sec.path}' if page <= 1 else f'{base}{sec.path}page/{page}/'


def _has_product_markup(html: str) -> bool:
    value = (html or '').casefold()
    return '/producto/' in value and ('woocommerce' in value or 'product' in value)


def _cache_bust(url: str) -> str:
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query['_monitor_retry'] = str(int(time.time() * 1000))
    return urlunparse(parsed._replace(query=urlencode(query)))


class _ResilientPageFetcher:
    """HTTP-first fetcher with lazy browser recovery for transient 202/interstitial pages.

    Vinos La Reina occasionally answers Railway's plain HTTP request with 202 and an empty
    storefront document. We retry HTTP once and only then launch Chromium. Playwright is
    imported lazily so services that merely import the collector registry do not inherit a
    browser dependency at import time.
    """

    def __init__(self) -> None:
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None

    def _http_once(self, session: requests.Session, url: str, *, no_cache: bool = False) -> HtmlFetchResult:
        headers = None
        target = url
        if no_cache:
            headers = {'Cache-Control': 'no-cache', 'Pragma': 'no-cache'}
            target = _cache_bust(url)
        response = session.get(target, headers=headers, timeout=bounded_request_timeout((5, 18)))
        return HtmlFetchResult(status_code=response.status_code, text=response.text, source='http-retry' if no_cache else 'http')

    def _ensure_browser(self) -> None:
        if self._page is not None:
            return
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu'],
        )
        self._context = self._browser.new_context(
            locale='es-CL',
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36',
            extra_http_headers={'Accept-Language': 'es-CL,es;q=0.9'},
        )
        self._context.route(
            '**/*',
            lambda route: route.abort()
            if route.request.resource_type in {'image', 'font', 'media'}
            else route.continue_(),
        )
        self._page = self._context.new_page()
        self._page.set_default_navigation_timeout(35_000)
        self._page.set_default_timeout(12_000)

    def _browser_fetch(self, url: str) -> HtmlFetchResult:
        ensure_budget('Tienda de Vinos La Reina fallback Chromium')
        self._ensure_browser()
        response = self._page.goto(url, wait_until='domcontentloaded')
        try:
            self._page.wait_for_selector("a[href*='/producto/']", timeout=12_000)
        except Exception:
            # Some challenge/interstitial responses settle after DOMContentLoaded.
            self._page.wait_for_timeout(2_000)
        html = self._page.content()
        status = response.status if response is not None else 200
        if _has_product_markup(html):
            status = 200
        return HtmlFetchResult(status_code=status, text=html, source='playwright-fallback')

    def fetch(self, session: requests.Session, url: str, section_name: str, page: int) -> HtmlFetchResult:
        first = self._http_once(session, url)
        if first.status_code == 200 and _has_product_markup(first.text):
            return first
        # A 404 on page >1 is a real pagination terminator and must not wake Chromium.
        if first.status_code == 404 and page > 1:
            return first

        reason = f'HTTP {first.status_code}' if first.status_code != 200 else 'HTML sin productos'
        print(f'Tienda de Vinos La Reina {section_name} página {page}: {reason}; reintento HTTP no-cache.', flush=True)
        ensure_budget(f'Tienda de Vinos La Reina {section_name} reintento HTTP')
        time.sleep(0.6)
        second = self._http_once(session, url, no_cache=True)
        if second.status_code == 200 and _has_product_markup(second.text):
            return second
        if second.status_code == 404 and page > 1:
            return second

        reason2 = f'HTTP {second.status_code}' if second.status_code != 200 else 'HTML sin productos'
        print(f'Tienda de Vinos La Reina {section_name} página {page}: {reason2}; activando fallback Chromium.', flush=True)
        return self._browser_fetch(url)

    def close(self) -> None:
        for obj in (self._page, self._context, self._browser):
            if obj is not None:
                try:
                    obj.close()
                except Exception:
                    pass
        if self._pw is not None:
            try:
                self._pw.stop()
            except Exception:
                pass
        self._pw = self._browser = self._context = self._page = None


class VinosLaReinaCollector:
    metadata = StoreMetadata(
        name='Tienda de Vinos La Reina',
        slug='vinos-la-reina',
        base_url=f'{BASE_URL}/',
        connector_key='vinoslareina',
        # HTTP remains the primary path. Chromium is lazy recovery only, so this collector
        # stays in the HTTP scheduling class and does not consume a browser slot by default.
        requires_browser=False,
    )
    key = metadata.connector_key
    store_name = metadata.name

    def collect(self):
        fetcher = _ResilientPageFetcher()
        try:
            return collect_html_store(
                store_name=self.store_name,
                base_url=BASE_URL,
                sections=SECTIONS,
                page_url=_page,
                max_pages=80,
                min_products=150,
                product_path_markers=('/producto/',),
                card_parser=parse_woocommerce_cards,
                terminal_404_after_success=True,
                page_fetcher=fetcher.fetch,
            )
        finally:
            fetcher.close()
