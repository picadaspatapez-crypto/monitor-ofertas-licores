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


def test_licor3b_uses_product_slug_when_card_title_is_contaminated():
    from app.collectors.licor3b import _safe_product_name

    url = "https://licor3b.cl/product/vino-marques-de-casa-concha-cabernet-sauvignon-750-ml/"
    bad = "3 Vinos Montes Alpha Cabernet Sauvignon 3 Vinos Marques De Casa Concha Cabernet Sauvignon 750 ml"
    fixed = _safe_product_name(bad, url)
    assert fixed == "vino marques de casa concha cabernet sauvignon 750 ml"


def test_licor3b_keeps_legitimate_pack_title_when_slug_agrees():
    from app.collectors.licor3b import _safe_product_name

    url = "https://licor3b.cl/product/pack-6-vinos-reserva-cabernet-sauvignon-750-ml/"
    title = "Pack 6 Vinos Reserva Cabernet Sauvignon 750 ml"
    assert _safe_product_name(title, url) == title
