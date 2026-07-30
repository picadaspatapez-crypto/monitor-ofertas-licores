from app.collectors.socomep import (
    CATALOG_SECTIONS,
    _canonical_url,
    _category_url,
    _detected_last_page,
    _parse_html,
)


def test_socomep_parser_current_regular_and_canonical_url():
    html = """
    <article class="product-card">
      <div>5301 | Chivas Regal</div>
      <a href="/whisky-chivas-regal-12-anos-750cc?utm_source=test">
        <h2>Whisky Chivas Regal 12 años 750cc</h2>
      </a>
      <span>-10% OFF</span>
      <span>$25.500</span>
      <del>$51.000</del>
      <button>Agregar al Carro</button>
    </article>
    """
    products, cards = _parse_html(html, "Licores")
    assert cards == 1
    item = next(iter(products.values()))
    assert item.store == "Socomep"
    assert item.name == "Whisky Chivas Regal 12 años 750cc"
    assert item.current_price == 25500
    assert item.regular_price == 51000
    assert item.url == "https://socomepcl.cl/whisky-chivas-regal-12-anos-750cc"


def test_socomep_parser_skips_unavailable_products():
    html = """
    <li class="product">
      <a href="/whisky-johnnie-walker-swing-750cc"><h2>Whisky Johnnie Walker Swing 750cc</h2></a>
      <div>No disponible</div><span>$41.650</span>
    </li>
    """
    products, cards = _parse_html(html, "Licores")
    assert cards == 1
    assert products == {}


def test_socomep_pagination_and_page_detection():
    section = CATALOG_SECTIONS[0]
    assert _category_url(section, 1) == "https://socomepcl.cl/catalogo/licores"
    assert "page=2" in _category_url(section, 2)
    html = """
    <nav>
      <a href="/catalogo/licores?page=2">2</a>
      <a href="/catalogo/licores?page=7">7</a>
      <a href="/catalogo/vinos?page=12">otra categoría</a>
    </nav>
    """
    assert _detected_last_page(html, section) == 7


def test_socomep_canonical_removes_query_and_www():
    assert (
        _canonical_url("https://www.socomepcl.cl/gin-tanqueray-750cc?ref=x")
        == "https://socomepcl.cl/gin-tanqueray-750cc"
    )
