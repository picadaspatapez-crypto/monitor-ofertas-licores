from app.collectors.gradounico import _parse_html


def test_gradounico_parses_static_product_cards():
    html = """
    <div class="product-block">
      <div>G-BG-242823 | Bombay</div>
      <a href="/gin-bombay-sapphire-750cc"><h2>Gin Bombay Sapphire 750cc</h2></a>
      <span class="price">$15.990</span>
      <span class="old-price">$17.990</span>
      <button>Agregar al Carro</button>
    </div>
    <div class="product-block">
      <a href="/gin-agotado-750cc"><h2>Gin Agotado 750cc</h2></a>
      <span>$12.990</span><span>Agotado</span>
    </div>
    """
    products, cards = _parse_html(html, "Gin")
    assert cards == 2
    assert len(products) == 1
    product = next(iter(products.values()))
    assert product.name == "Gin Bombay Sapphire 750cc"
    assert product.current_price == 15990
    assert product.regular_price == 17990
    assert product.url == "https://www.gradounico.cl/gin-bombay-sapphire-750cc"


def test_gradounico_rejects_navigation_headings():
    html = """
    <section><h2>Categorías</h2><a href="/gin">Gin</a></section>
    <footer><h3>Información</h3></footer>
    """
    products, cards = _parse_html(html, "Gin")
    assert products == {}
    assert cards == 0

import requests
import pytest

import app.collectors.gradounico as gradounico


def test_gradounico_category_url_supports_alternate_origin():
    section = gradounico.CatalogSection("whisky", "Whisky", "/whisky")
    assert (
        gradounico._category_url(
            section,
            3,
            origin="https://gradounico.cl",
        )
        == "https://gradounico.cl/whisky?page=3"
    )


def test_gradounico_circuit_breaker_stops_after_two_tcp_failures(monkeypatch):
    class FailingSession:
        def __init__(self):
            self.calls = 0

        def get(self, *args, **kwargs):
            self.calls += 1
            raise requests.ConnectTimeout("origin timed out")

        def close(self):
            return None

    session = FailingSession()
    monkeypatch.setattr(gradounico, "_session", lambda: session)
    monkeypatch.setattr(
        gradounico,
        "_select_origin",
        lambda: "https://www.gradounico.cl",
    )

    with pytest.raises(RuntimeError, match="no entregó productos"):
        gradounico._collect_products()

    assert session.calls == gradounico.MAX_CONSECUTIVE_CONNECTION_FAILURES
