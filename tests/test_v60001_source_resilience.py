from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from app.collectors import cav, lavinoteca, vinoslareina
from app.performance import PhaseMetrics
from app.pipeline.runner import _supports_stale_recovery


def test_cav_catalog_query_uses_current_store_route():
    url = cav._page_url(0, (("fR[family.name][0]", "Vinos"),))
    assert url.startswith("https://cav.cl/tienda?")
    assert "https://cav.cl/?" not in url


@dataclass
class _Elapsed:
    def total_seconds(self):
        return 0.01


class _Response:
    def __init__(self, status, payload=None, headers=None):
        self.status_code = status
        self._payload = payload if payload is not None else []
        self.headers = headers or {}
        self.elapsed = _Elapsed()

    def json(self):
        return self._payload


class _SplitSession:
    def __init__(self):
        self.calls = []

    def get(self, _url, *, params, timeout):
        start, end = params["_from"], params["_to"]
        self.calls.append((start, end))
        if (start, end) == (0, 49):
            return _Response(500)
        return _Response(200, [{"productId": str(i)} for i in range(start, end + 1)], {"Content-Range": f"resources {start}-{end}/100"})


def test_lavinoteca_splits_a_500_window_and_recovers_all_items():
    session = _SplitSession()
    result = lavinoteca._fetch_range(session, start=0, end=49, metrics=PhaseMetrics())
    assert result.split_recovered is True
    assert len(result.payload) == 50
    assert (0, 24) in session.calls
    assert (25, 49) in session.calls


def test_vinos_la_reina_has_sticky_browser_state():
    fetcher = vinoslareina._ResilientPageFetcher()
    assert fetcher._browser_sticky_remaining == 0


def test_known_transient_collectors_support_stale_recovery():
    for key in ("elmundodelvino", "lamodelo", "lavinoteca", "cav", "vinoslareina"):
        assert _supports_stale_recovery(key)
    assert not _supports_stale_recovery("licor3b")
