from app.collectors.dondelanegra import _canonical_url as negra_url
from app.collectors.dondelanegra import _parse_html as parse_negra
from app.collectors.labarra import _canonical_url as barra_url
from app.collectors.labarra import _parse_html as parse_barra
from app.collectors.lamodelo import _parse_html as parse_modelo


def test_labarra_parser_current_and_reference_price():
    html = """
    <article class="product-card">
      <a href="/producto/443046-whisky-jameson-irish-40deg-750cc-2504">
        <img alt="Whisky Jameson Irish 40° 750cc">
      </a>
      <h3>Whisky Jameson Irish 40° 750cc</h3>
      <span>Ref: $24.990</span><strong>$19.990</strong>
    </article>
    """
    products, cards = parse_barra(html, "Licores")
    assert cards == 1
    item = next(iter(products.values()))
    assert item.store == "La Barra"
    assert item.current_price == 19990
    assert item.regular_price == 24990
    assert item.url == "https://labarra.cl/producto/443046-whisky-jameson-irish-40deg-750cc-2504"


def test_labarra_canonical_removes_tracking():
    assert barra_url("/producto/123-demo?utm_source=x") == "https://labarra.cl/producto/123-demo"


def test_donde_la_negra_parser():
    html = """
    <li class="product">
      <a href="/producto/johnnie-black-label-750cc/">
        <h2 class="woocommerce-loop-product__title">Whisky Johnnie Walker Black Label 750cc</h2>
      </a>
      <span class="price"><del>$29.990</del><ins>$24.990</ins></span>
    </li>
    """
    products, cards = parse_negra(html, "Whiskey")
    assert cards == 1
    item = next(iter(products.values()))
    assert item.current_price == 24990
    assert item.regular_price == 29990
    assert item.url == "https://dondelanegra.cl/producto/johnnie-black-label-750cc"


def test_donde_la_negra_canonical_url():
    assert negra_url("https://www.dondelanegra.cl/producto/demo/?ref=x") == "https://dondelanegra.cl/producto/demo"


def test_la_modelo_parser_uses_code_and_unit_price():
    html = """
    <div class="product-card">
      <h3>100 PIPERS 1LT 40º WHISKY</h3>
      <div>Código: 317</div>
      <div>$ 6.960</div>
      <div>Unidad</div>
      <div>Caja X (1) valor unid. 6.960</div>
      <a href="/index.php?q=317">Ver producto</a>
    </div>
    """
    products, cards = parse_modelo(html)
    assert cards == 1
    item = next(iter(products.values()))
    assert item.store == "Distribuidora La Modelo"
    assert item.current_price == 6960
    assert item.regular_price is None
    assert item.sku == "317"
    assert "q=317" in item.url
