from app.collectors.labarra import _parse_product_page, _parse_sitemap_xml
from app.collectors.lamodelo import _detected_total_pages


def test_labarra_sitemap_index_prefers_product_sitemaps():
    xml = """
    <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <sitemap><loc>https://labarra.cl/sitemap-pages.xml</loc></sitemap>
      <sitemap><loc>https://labarra.cl/sitemap-products.xml</loc></sitemap>
    </sitemapindex>
    """
    children, products = _parse_sitemap_xml(xml)
    assert products == []
    assert children[0].endswith("sitemap-products.xml")


def test_labarra_sitemap_urlset_extracts_only_products():
    xml = """
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://labarra.cl/producto/201-chivas-regal-25-anos?ref=x</loc></url>
      <url><loc>https://labarra.cl/categoria/759</loc></url>
    </urlset>
    """
    children, products = _parse_sitemap_xml(xml)
    assert children == []
    assert products == ["https://labarra.cl/producto/201-chivas-regal-25-anos"]


def test_labarra_product_page_parses_json_ld():
    html = """
    <html><head>
      <script type="application/ld+json">
      {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": "Whisky Chivas Regal 25 Años 700cc",
        "url": "https://labarra.cl/producto/201-chivas-regal-25-anos",
        "offers": {"@type": "Offer", "price": "401289.00", "priceCurrency": "CLP"}
      }
      </script>
    </head></html>
    """
    item = _parse_product_page(html, "https://labarra.cl/producto/201-chivas-regal-25-anos")
    assert item is not None
    assert item.current_price == 401289
    assert item.name == "Whisky Chivas Regal 25 Años 700cc"


def test_lamodelo_detects_186_pages():
    html = "<html><body><div>Página 1 de 186</div></body></html>"
    assert _detected_total_pages(html) == 186
