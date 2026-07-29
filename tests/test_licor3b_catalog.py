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


def test_discovers_only_root_product_categories():
    from app.collectors.licor3b import _discover_sections_from_html

    html = """
    <nav>
      <a href="https://licor3b.cl/product-category/vinos/">Vinos</a>
      <a href="https://licor3b.cl/product-category/vinos/tintos/">Tintos</a>
      <a href="/product-category/whiskys/">Whisky</a>
      <a href="/product-category/vinos/">Vinos duplicado</a>
    </nav>
    """
    sections = _discover_sections_from_html(html)
    assert {section.key for section in sections} == {"vinos", "whiskys"}


def test_excludes_adios_gabriel_promotional_category():
    from app.collectors.licor3b import _discover_sections_from_html

    html = """
    <nav>
      <a href="/product-category/mascomprados/">Adiós Gabriel</a>
      <a href="/product-category/cervezas/">Cervezas</a>
    </nav>
    """
    sections = _discover_sections_from_html(html)
    assert {section.key for section in sections} == {"cervezas"}
