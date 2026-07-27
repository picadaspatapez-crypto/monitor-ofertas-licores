from app.collectors.licor3b import (
    FULL_CATALOG_SECTIONS,
    CatalogSection,
    _section_page_url,
)


def test_full_catalog_has_expected_root_sections():
    keys = {section.key for section in FULL_CATALOG_SECTIONS}
    assert keys == {
        "cervezas", "espumantes", "licores", "otros", "packs", "piscos",
        "rones", "tequilas", "vinos", "vodkas", "whiskys",
    }


def test_section_pagination_uses_product_page_query():
    section = CatalogSection("vinos", "Vinos", "https://licor3b.cl/product-category/vinos/")
    assert _section_page_url(section, 1) == section.url
    assert _section_page_url(section, 2) == section.url + "?product-page=2"
