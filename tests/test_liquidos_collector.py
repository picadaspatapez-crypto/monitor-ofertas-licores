from app.collectors.liquidos import (
    _canonical_url,
    _discover_sections_from_html,
    _parse_html,
    _price_values,
)


def test_discovers_only_supported_root_categories():
    html = """
    <nav>
      <a href="/categorias/piscos">PISCOS</a>
      <a href="https://www.liquidos.cl/categorias/whiskys">WHISKYS</a>
      <a href="/categorias/cyber">Cyber</a>
      <a href="/categorias/licores?licor_type=vodka">LICORES</a>
    </nav>
    """
    sections = _discover_sections_from_html(html)
    assert [section.key for section in sections] == ["piscos", "whiskys", "licores"]


def test_price_parser_ignores_unit_price():
    text = "$29.990 $36.450 $29.990 x lt. agregar"
    assert _price_values(text) == [29990, 36450]


def test_parses_liquidos_card_with_current_and_regular_price():
    html = """
    <div class="product-card">
      <a href="/productos/2494/whiskey-jack-daniels-honey-750-cc">
        <img alt="Whiskey Jack Daniels Honey 750 CC">
      </a>
      <h3>Whiskey Jack Daniels Honey 750 CC</h3>
      <span class="internetPrice">$26.990</span>
      <span class="regular-price">$30.990</span>
      <span>$35.987 x lt.</span>
      <button>agregar</button>
    </div>
    """
    products, links = _parse_html(html, "Whiskys")
    assert links == 1
    product = next(iter(products.values()))
    assert product.store == "Líquidos"
    assert product.name == "Whiskey Jack Daniels Honey 750 CC"
    assert product.current_price == 26990
    assert product.regular_price == 30990
    assert product.source_sections == ("Whiskys",)


def test_parses_product_when_regular_price_appears_first():
    html = """
    <article>
      <a title="Pisco Mistral 35 grados 1 litro"
         href="https://liquidos.cl/productos/2937/pisco-mistral-35-grados-1-litro">producto</a>
      <div>$10.290</div><div>$7.590</div><div>$7.590 x lt.</div>
    </article>
    """
    products, _ = _parse_html(html, "Piscos")
    product = next(iter(products.values()))
    assert product.current_price == 7590
    assert product.regular_price == 10290
    assert product.url == "https://www.liquidos.cl/productos/2937/pisco-mistral-35-grados-1-litro"


def test_canonical_url_removes_tracking_query():
    assert _canonical_url(
        "/productos/814/whisky-johnnie-walker-roja-750-cc-x6?_tl_pid=abc"
    ) == "https://www.liquidos.cl/productos/814/whisky-johnnie-walker-roja-750-cc-x6"
