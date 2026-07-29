from app.collectors.comercialjp import _parse_html as parse_jp
from app.collectors.elmundodelvino import _parse_html as parse_emv


def test_el_mundo_del_vino_parses_shopify_card():
    html = """
    <ul class='product-grid'>
      <li class='card product-card'>
        <h3 class='card__heading'><a href='/products/johnnie-walker-black'>WHISKY JOHNNIE WALKER BLACK LABEL 750 ML</a></h3>
        <span class='price-item'>$29.990</span>
        <button>Agregar al carro</button>
      </li>
    </ul>
    """
    products, cards = parse_emv(html, "Whisky")
    assert cards == 1
    item = next(iter(products.values()))
    assert item.current_price == 29990
    assert item.store == "El Mundo del Vino"


def test_comercial_jp_parses_jumpseller_card_and_regular_price():
    html = """
    <article class='product-block'>
      <a href='/whisky-johnnie-walker-black-label-750cc'><h2>Whisky Johnnie Walker Black Label 40° 750cc</h2></a>
      <span>$30.770 CLP</span><del>$34.990 CLP</del><label>Cantidad</label>
    </article>
    """
    products, cards = parse_jp(html, "Licores")
    assert cards == 1
    item = next(iter(products.values()))
    assert item.current_price == 30770
    assert item.regular_price == 34990
    assert item.store == "Comercial JP"


def test_el_mundo_del_vino_accepts_collection_prefixed_shopify_url():
    html = """
    <div class='collection-grid'>
      <article class='card product-card'>
        <h3 class='card__heading'>
          <a href='/collections/whisky/products/johnnie-walker-black'>WHISKY JOHNNIE WALKER BLACK LABEL 750 ML</a>
        </h3>
        <span class='price-item'>$29.990</span>
        <button>Agregar al carro</button>
      </article>
    </div>
    """
    products, cards = parse_emv(html, "Whisky")
    assert cards == 1
    assert list(products) == [
        "https://elmundodelvino.cl/products/johnnie-walker-black"
    ]
    item = next(iter(products.values()))
    assert item.name == "WHISKY JOHNNIE WALKER BLACK LABEL 750 ML"
    assert item.current_price == 29990


def test_el_mundo_del_vino_parses_shopify_json_feed():
    from app.collectors.elmundodelvino import _parse_json

    payload = {
        "products": [
            {
                "title": "WHISKY JOHNNIE WALKER BLACK LABEL 750 ML",
                "handle": "johnnie-walker-black-label-750",
                "variants": [
                    {
                        "available": True,
                        "price": "29990.00",
                        "compare_at_price": "34990.00",
                    }
                ],
            }
        ]
    }
    products, cards = _parse_json(payload, "Whisky")
    assert cards == 1
    item = next(iter(products.values()))
    assert item.current_price == 29990
    assert item.regular_price == 34990
    assert item.url == "https://elmundodelvino.cl/products/johnnie-walker-black-label-750"


def test_el_mundo_del_vino_json_ignores_unavailable_variants():
    from app.collectors.elmundodelvino import _parse_json

    payload = {
        "products": [
            {
                "title": "PRODUCTO AGOTADO",
                "handle": "producto-agotado",
                "variants": [{"available": False, "price": "9990.00"}],
            }
        ]
    }
    products, cards = _parse_json(payload, "Licores")
    assert cards == 1
    assert products == {}
