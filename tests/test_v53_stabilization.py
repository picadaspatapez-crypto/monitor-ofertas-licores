from app.collectors.dondelanegra import (
    CATALOG_SECTIONS as NEGRA_SECTIONS,
    _parse_store_api_products,
)
from app.collectors.labarra import (
    CATALOG_SECTIONS as BARRA_SECTIONS,
    _extract_json_products,
    _looks_like_maintenance,
)


def test_donde_la_negra_store_api_parses_clp_and_categories():
    payload = [
        {
            "name": "Whisky Johnnie Walker Black Label 750cc",
            "permalink": "https://dondelanegra.cl/producto/johnnie-black-750/",
            "categories": [{"name": "Whiskey", "slug": "whiskey"}],
            "prices": {
                "price": "24990",
                "regular_price": "29990",
                "sale_price": "24990",
                "currency_minor_unit": 0,
            },
        }
    ]
    products = _parse_store_api_products(payload)
    item = next(iter(products.values()))
    assert item.current_price == 24990
    assert item.regular_price == 29990
    assert item.source_sections == ("Whiskey",)
    assert item.url == "https://dondelanegra.cl/producto/johnnie-black-750"


def test_donde_la_negra_store_api_excludes_soft_drinks():
    payload = [
        {
            "name": "Bebida Cola 1.5L",
            "permalink": "https://dondelanegra.cl/producto/bebida-cola/",
            "categories": [{"name": "Bebidas y Energéticas", "slug": "bebidas"}],
            "prices": {"price": "1990", "currency_minor_unit": 0},
        }
    ]
    assert _parse_store_api_products(payload) == {}


def test_donde_la_negra_uses_current_tequila_slug():
    tequila = next(section for section in NEGRA_SECTIONS if section.key == "tequila")
    assert tequila.slug == "tequilas"


def test_labarra_extracts_products_from_nested_json_payload():
    payload = {
        "data": {
            "category": {
                "products": [
                    {
                        "name": "Whisky Jameson Irish 40° 750cc",
                        "url": "/producto/443046-whisky-jameson-irish-40deg-750cc-2504",
                        "salePrice": "$19.990",
                        "regularPrice": "$24.990",
                    }
                ]
            }
        }
    }
    products = _extract_json_products(payload, "Whisky")
    item = next(iter(products.values()))
    assert item.current_price == 19990
    assert item.regular_price == 24990
    assert item.url.endswith("/producto/443046-whisky-jameson-irish-40deg-750cc-2504")


def test_labarra_detects_maintenance_page():
    assert _looks_like_maintenance("<html><h1>¡Volveremos pronto! 🔧</h1></html>") is True


def test_labarra_uses_specific_current_categories():
    urls = {section.url for section in BARRA_SECTIONS}
    assert "https://labarra.cl/categoria/whisky-348" in urls
    assert "https://labarra.cl/categoria/vinos-y-espumantes-293" in urls
    assert "https://labarra.cl/categoria/cervezas-288" in urls
