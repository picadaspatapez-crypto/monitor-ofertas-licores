from urllib.parse import parse_qs, urlparse


def test_lavinoteca_accepts_rest_content_range_header():
    from requests import Response
    from app.collectors.lavinoteca import _content_range_total

    response = Response()
    response.headers["REST-Content-Range"] = "resources 950-999/996"
    assert _content_range_total(response) == 996


def test_cav_page_url_encodes_family_and_wine_type_filters():
    from app.collectors.cav import _page_url

    url = _page_url(3, (
        ("fR[family.name][0]", "Vinos"),
        ("fR[wine_type.name][0]", "Ensamblaje Tinto"),
    ))
    query = parse_qs(urlparse(url).query)
    assert query["idx"] == ["products"]
    assert query["p"] == ["3"]
    assert query["hPP"] == ["48"]
    assert query["fR[family.name][0]"] == ["Vinos"]
    assert query["fR[wine_type.name][0]"] == ["Ensamblaje Tinto"]


def test_cav_discovers_dynamic_wine_type_facets_from_encoded_links():
    from app.collectors.cav import _discover_filter_values

    html = """
    <a href="/tienda?fR%5Bfamily.name%5D%5B0%5D=Vinos&amp;fR%5Bwine_type.name%5D%5B0%5D=Tinto&q=">Tinto</a>
    <a href="/tienda?fR%5Bfamily.name%5D%5B0%5D=Vinos&amp;fR%5Bwine_type.name%5D%5B0%5D=Blanco&q=">Blanco</a>
    """
    assert set(_discover_filter_values(html, "wine_type.name")) == {"Tinto", "Blanco"}


def test_cav_uses_shards_instead_of_unfiltered_global_index():
    from app.collectors.cav import _shards

    shards = _shards()
    assert shards
    assert any(shard.label == "Vinos / Tinto" for shard in shards)
    assert any(shard.label == "Licores" for shard in shards)
    assert any(shard.label == "Whisky" for shard in shards)
    for shard in shards:
        params = dict(shard.filters)
        assert "fR[family.name][0]" in params
        if params["fR[family.name][0]"] == "Vinos":
            assert "fR[wine_type.name][0]" in params


def test_cav_dynamic_wine_type_is_added_without_dropping_defaults():
    from app.collectors.cav import _shards

    shards = _shards(("Dulce",))
    labels = {shard.label for shard in shards}
    assert "Vinos / Tinto" in labels
    assert "Vinos / Dulce" in labels
