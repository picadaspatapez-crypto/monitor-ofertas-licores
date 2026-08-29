from __future__ import annotations

from types import SimpleNamespace

from app.collectors.http_catalog import HtmlFetchResult
from app.collectors.vinoslareina import _ResilientPageFetcher, _cache_bust, _has_product_markup

PRODUCT_HTML = '''
<html><body class="woocommerce">
<li class="product"><a href="https://vinoslareina.cl/producto/test/">Test</a><span>$9.990</span></li>
</body></html>
'''


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


def resp(status, text=''):
    return SimpleNamespace(status_code=status, text=text)


def test_product_markup_detection_is_not_satisfied_by_empty_interstitial():
    assert not _has_product_markup('<html><body>Accepted</body></html>')
    assert _has_product_markup(PRODUCT_HTML)


def test_cache_bust_preserves_existing_query():
    url = _cache_bust('https://vinoslareina.cl/cat/?page=2')
    assert 'page=2' in url
    assert '_monitor_retry=' in url


def test_202_retries_http_and_recovers_without_browser(monkeypatch):
    fetcher = _ResilientPageFetcher()
    monkeypatch.setattr('app.collectors.vinoslareina.time.sleep', lambda *_: None)
    session = FakeSession([resp(202, 'Accepted'), resp(200, PRODUCT_HTML)])
    result = fetcher.fetch(session, 'https://vinoslareina.cl/categoria-producto/vinos/', 'Vinos', 1)
    assert result.status_code == 200
    assert result.source == 'http-retry'
    assert len(session.calls) == 2
    assert session.calls[1][1]['headers']['Cache-Control'] == 'no-cache'


def test_repeated_202_activates_browser_fallback(monkeypatch):
    fetcher = _ResilientPageFetcher()
    monkeypatch.setattr('app.collectors.vinoslareina.time.sleep', lambda *_: None)
    monkeypatch.setattr(fetcher, '_browser_fetch', lambda url: HtmlFetchResult(200, PRODUCT_HTML, 'playwright-fallback'))
    session = FakeSession([resp(202, 'Accepted'), resp(202, 'Accepted')])
    result = fetcher.fetch(session, 'https://vinoslareina.cl/categoria-producto/vinos/', 'Vinos', 1)
    assert result.source == 'playwright-fallback'


def test_terminal_404_does_not_launch_browser(monkeypatch):
    fetcher = _ResilientPageFetcher()
    called = {'browser': False}
    monkeypatch.setattr(fetcher, '_browser_fetch', lambda url: called.__setitem__('browser', True))
    session = FakeSession([resp(404, 'Not found')])
    result = fetcher.fetch(session, 'https://vinoslareina.cl/categoria-producto/vinos/page/99/', 'Vinos', 99)
    assert result.status_code == 404
    assert called['browser'] is False
