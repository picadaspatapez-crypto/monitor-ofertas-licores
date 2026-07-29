from __future__ import annotations

import requests

from app.collectors import elmundodelvino as emv
from app.performance import PhaseMetrics


def _payload(start: int, count: int, *, product_type: str = "Whisky") -> dict:
    return {
        "products": [
            {
                "title": f"Producto {index} 750 ml",
                "handle": f"producto-{index}",
                "product_type": product_type,
                "tags": [product_type],
                "variants": [
                    {
                        "available": True,
                        "price": "19990.00",
                        "compare_at_price": "24990.00",
                    }
                ],
            }
            for index in range(start, start + count)
        ]
    }


def test_global_url_uses_single_shopify_catalog():
    assert emv._global_json_url(2) == (
        "https://elmundodelvino.cl/products.json?limit=250&page=2"
    )


def test_global_parser_classifies_products_locally():
    products, cards = emv._parse_json(_payload(1, 1, product_type="Whisky"))
    assert cards == 1
    item = next(iter(products.values()))
    assert item.source_sections == ("Whisky",)
    assert item.current_price == 19990
    assert item.regular_price == 24990


def test_global_parser_skips_clear_accessories():
    payload = _payload(1, 1, product_type="")
    payload["products"][0]["title"] = "Sacacorcho profesional"
    products, cards = emv._parse_json(payload)
    assert cards == 1
    assert products == {}


def test_health_accepts_complete_catalog_and_preserves_partial():
    assert emv._health(product_count=592, partial=False, complete=True) == ("HEALTHY", 100)
    assert emv._health(product_count=250, partial=True, complete=False) == ("DEGRADED", 72)
    assert emv._health(product_count=23, partial=True, complete=False)[0] == "BROKEN"


def test_select_global_source_accepts_products_json(monkeypatch):
    class FakeResponse:
        status_code = 200
        content = b"{}"

        def raise_for_status(self):
            return None

        def json(self):
            return _payload(1, 2)

    monkeypatch.setattr(emv, "_fetch_json_response", lambda *args, **kwargs: FakeResponse())
    source, products, cards, raw_count = emv._select_global_source(
        requests.Session(), PhaseMetrics()
    )
    assert source.path == "/products.json"
    assert len(products) == 2
    assert cards == 2
    assert raw_count == 2


def test_requests_adapter_does_not_retry_429_implicitly():
    session = emv._session()
    try:
        retry = session.get_adapter("https://").max_retries
        assert 429 not in retry.status_forcelist
        assert retry.respect_retry_after_header is False
    finally:
        session.close()
