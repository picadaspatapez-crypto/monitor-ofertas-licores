from datetime import datetime, timezone

from app.search.engine import SearchOffer, SearchResult
from app.search.web import CatalogPulse, _result_html, _search_html


def _sample_result() -> SearchResult:
    first = SearchOffer(
        product_id=1,
        store_name="La Vinoteca",
        product_name="Johnnie Walker Black Label 750 ml",
        price=22990,
        regular_price=27990,
        discount_pct=0.1786,
        url="https://example.com/black",
        last_seen_at=datetime(2026, 8, 12, 12, 0, tzinfo=timezone.utc),
    )
    second = SearchOffer(
        product_id=2,
        store_name="Socomep",
        product_name="Whisky Johnnie Walker Black 750 cc",
        price=24990,
        regular_price=None,
        discount_pct=0,
        url="https://example.com/black-2",
        last_seen_at=datetime(2026, 8, 12, 11, 30, tzinfo=timezone.utc),
    )
    return SearchResult(
        master_product_id=10,
        canonical_name="Johnnie Walker Black Label 750 ml",
        brand="Johnnie Walker",
        variant="Black Label",
        volume_ml=750,
        package_quantity=1,
        score=0.96,
        offers=(first, second),
        winner=first,
        runner_up=second,
        saving_clp=2000,
        saving_pct=2000 / 24990,
        min_90d=21990,
        avg_90d=26500,
        historical_min=20990,
        opportunity_score=91,
        opportunity_classification="Excelente",
    )


def test_home_ui_shows_catalog_pulse_and_quick_searches():
    page = _search_html(
        query="",
        results=[],
        max_age_hours=72,
        pulse=CatalogPulse(public_stores=8, comparable_products=2450, fresh_offers=8200),
    ).decode("utf-8")
    assert "Personal Pricing &amp; CAV Activation" in page
    assert "8</strong><span>tiendas públicas" in page
    assert "2.450</strong><span>productos comparables" in page
    assert "8.200</strong><span>precios vigentes" in page
    assert "Búsquedas rápidas" in page
    assert "/buscar?q=johnnie+black+750" in page
    assert "Mercado público" in page


def test_result_ui_emphasizes_best_price_and_history():
    result_html = _result_html(_sample_result())
    assert "Mejor precio público" in result_html
    assert "$22.990" in result_html
    assert "La Vinoteca" in result_html
    assert "Socomep" in result_html
    assert "91/100" in result_html
    assert "Excelente" in result_html
    assert "Ahorro vs. 2ª tienda" in result_html
    assert "Mínimo 90 días" in result_html
    assert "Comparación por tienda" in result_html
    assert "Ver en tienda" in result_html


def test_search_ui_escapes_query_and_product_content():
    page = _search_html(
        query='<script>alert("x")</script>',
        results=[],
        max_age_hours=72,
    ).decode("utf-8")
    assert "<script>" not in page
    assert "&lt;script&gt;" in page
