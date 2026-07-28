from app.collectors.tost import _money, _parse_html, _parse_shopify_payload


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
            {
                "title": "Vino Gran Reserva Cepas 750cc",
                "handle": "vino-gran-reserva-cepas",
                "variants": [
                    {
                        "id": 201,
                        "title": "Carmenere",
                        "available": True,
                        "price": "7990.00",
                        "compare_at_price": "10990.00",
                    },
                    {
                        "id": 202,
                        "title": "Merlot",
                        "available": False,
                        "price": "7990.00",
                        "compare_at_price": "10990.00",
                    },
                ],
            },
        ]
    }
    products, cards = _parse_shopify_payload(payload, "Whisky")
    assert cards == 3  # controla la paginación con el tamaño bruto de la respuesta
    assert len(products) == 2
    black = next(item for item in products.values() if "Black Label" in item.name)
    assert black.current_price == 25990
    assert black.regular_price == 34990
    wine = next(item for item in products.values() if "Carmenere" in item.name)
    assert "variant=201" in wine.url


def test_tost_html_fallback_excludes_unit_price():
    html = """
    <article>
      <a href="/products/pisco-mistral-1000cc"><h3>Pisco Mistral 35º 1000cc</h3></a>
      <span>$7.490</span><del>$9.990</del><small>$7.490 /Litros</small>
    </article>
    """
    products, cards = _parse_html(html, "Piscos")
    assert cards == 1
    product = next(iter(products.values()))
    assert product.current_price == 7490
    assert product.regular_price == 9990
