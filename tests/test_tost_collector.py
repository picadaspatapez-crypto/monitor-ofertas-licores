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


def test_tost_discovers_page_count_from_progress_and_links():
    from app.collectors.tost import _discover_page_count

    html = '''
    <div>Mostrando 40 de 146</div>
    <a href="/collections/whiskey?page=2">Mostrar más</a>
    '''
    assert _discover_page_count(html, 40) == 4


def test_tost_health_rejects_implausibly_small_catalog():
    from app.collectors.tost import MIN_PLAUSIBLE_PRODUCTS, _health
    from app.domain import SectionStats

    sections = [SectionStats(key="whisky", name="Whisky", url="https://tost.cl/collections/whiskey")]
    status, score = _health(sections, MIN_PLAUSIBLE_PRODUCTS - 1)
    assert status == "BROKEN"
    assert score <= 20


def test_tost_collects_paginated_html_instead_of_products_json(monkeypatch):
    import app.collectors.tost as tost

    section = tost.CatalogSection("whisky", "Whisky", "whiskey")
    monkeypatch.setattr(tost, "CATALOG_SECTIONS", (section,))
    monkeypatch.setattr(tost, "MIN_PLAUSIBLE_PRODUCTS", 5)

    def html_page(page: int) -> str:
        cards = "".join(
            f'''<article><a href="/products/whisky-{page}-{idx}"><h3>Whisky Prueba {page}-{idx} 750cc</h3></a>
            <span>${10 + page}.{idx:03d}</span><del>${20 + page}.{idx:03d}</del></article>'''
            for idx in range(1, 4)
        )
        progress = '<div>Mostrando 3 de 9</div><a href="?page=2">más</a><a href="?page=3">más</a>'
        return f'<div id="product-grid">{cards}</div>{progress}'

    def fake_fetch(_section, page_number):
        return page_number, html_page(page_number), 200

    monkeypatch.setattr(tost, "_fetch_html_page", fake_fetch)
    batch = tost._collect_products()
    assert len(batch.products) == 9
    assert batch.stats.pages_visited == 3
    assert batch.stats.health_status == "HEALTHY"
    assert batch.stats.discovery_source == "configured-html-collections-parallel-pagination"
