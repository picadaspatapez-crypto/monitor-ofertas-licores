from bs4 import BeautifulSoup

from app.collectors.tost import (
    MIN_PLAUSIBLE_PRODUCTS,
    TostCollector,
    _discover_page_count,
    _expected_result_count,
    _health,
    _money,
    _parse_html,
    _parse_shopify_payload,
    _product_grid_root,
    _unique_product_handles,
)
from app.domain import SectionStats


def test_tost_money_supports_shopify_decimals_and_chilean_format():
    assert _money("7990.00") == 7990
    assert _money("7.990") == 7990
    assert _money(12990) == 12990
    assert _money(12990.0) == 12990


def test_tost_parses_available_shopify_variants_and_skips_personalized():
    payload = {
        "products": [
            {
                "title": "Whisky Johnnie Walker Black Label 750cc",
                "handle": "johnnie-walker-black-label-750cc",
                "variants": [
                    {
                        "id": 101,
                        "title": "Default Title",
                        "available": True,
                        "price": "25990.00",
                        "compare_at_price": "34990.00",
                    }
                ],
            },
            {
                "title": "Whisky Johnnie Walker Black Label 750cc - Personalizado",
                "handle": "johnnie-black-personalizado",
                "variants": [
                    {
                        "id": 102,
                        "title": "Default Title",
                        "available": True,
                        "price": "25990.00",
                        "compare_at_price": None,
                    }
                ],
            },
        ]
    }
    products, cards = _parse_shopify_payload(payload, "Whisky")
    assert cards == 2
    assert len(products) == 1
    product = next(iter(products.values()))
    assert product.current_price == 25990
    assert product.regular_price == 34990


def test_tost_html_excludes_unit_price():
    html = """
    <div id="product-grid">
      <article>
        <a href="/products/pisco-mistral-1000cc"><h3>Pisco Mistral 35º 1000cc</h3></a>
        <span>$7.490</span><del>$9.990</del><small>$7.490 /Litros</small>
      </article>
    </div>
    """
    products, cards = _parse_html(html, "Piscos")
    assert cards == 1
    product = next(iter(products.values()))
    assert product.current_price == 7490
    assert product.regular_price == 9990


def test_tost_discovers_page_count_from_rendered_progress_and_links():
    html = '''
    <div>Mostrando 40 de 146</div>
    <a href="/collections/whiskey?page=2">Mostrar más</a>
    '''
    assert _expected_result_count(html) == 146
    assert _discover_page_count(html, 40) == 4


def test_tost_health_rejects_implausibly_small_catalog():
    sections = [SectionStats(key="whisky", name="Whisky", url="https://tost.cl/collections/whiskey")]
    status, score = _health(sections, MIN_PLAUSIBLE_PRODUCTS - 1)
    assert status == "BROKEN"
    assert score <= 20


def test_tost_prefers_semantic_main_grid_over_larger_recommendations():
    recommendations = "".join(
        f'<article><a href="/products/recommended-{i}">Recomendado {i}</a></article>'
        for i in range(11)
    )
    collection = "".join(
        f'<article><a href="/products/collection-{i}">Producto {i}</a></article>'
        for i in range(7)
    )
    html = (
        '<main>'
        f'<section class="product-grid imperdibles">{recommendations}</section>'
        f'<section id="ProductGridContainer"><div id="product-grid">{collection}</div></section>'
        '</main>'
    )
    soup = BeautifulSoup(html, "html.parser")
    root = _product_grid_root(soup)
    handles = _unique_product_handles(root)
    assert handles == {f"collection-{i}" for i in range(7)}


def test_tost_is_declared_as_browser_collector():
    assert TostCollector.metadata.requires_browser is True
