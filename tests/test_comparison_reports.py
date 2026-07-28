from app.analyzers import ComparisonAnalysis, PriceComparison, StoreOffer
from app.notifications import (
    ComparisonAlertContext,
    build_comparison_notification_bundles,
)
from app.reports import (
    build_comparison_ranking_messages,
    build_comparison_summary_message,
)


def _analysis() -> ComparisonAnalysis:
    cheap = StoreOffer(2, 2, "Líquidos", "Producto", 21990, None, 0, "https://liq/p")
    expensive = StoreOffer(1, 1, "Licor3B", "Producto", 24990, None, 0, "https://l3b/p")
    comparison = PriceComparison(
        master_product_id=10,
        canonical_name="Johnnie Walker Black 750 ml",
        volume_ml=750,
        offers=(cheap, expensive),
        winner=cheap,
        runner_up=expensive,
        saving_clp=3000,
        saving_pct=3000 / 24990,
        confidence=0.96,
        previous_winner_store_id=1,
        previous_winner_store_name="Licor3B",
        winner_changed=True,
        is_tie=False,
    )
    return ComparisonAnalysis(
        current_products=100,
        master_groups=50,
        verified_matches=1,
        opportunities=(comparison,),
        winner_changes=(comparison,),
        ties=0,
        unverified_groups=2,
    )


def test_comparison_report_shows_store_prices_and_saving():
    analysis = _analysis()
    summary = build_comparison_summary_message(analysis)
    ranking = build_comparison_ranking_messages(analysis)[0]
    assert "Productos equivalentes verificados: 1" in summary
    assert "Líquidos: $21.990" in ranking
    assert "Licor3B: $24.990" in ranking
    assert "Ahorro: $3.000" in ranking


def test_first_comparison_creates_digest_and_winner_change():
    bundles = build_comparison_notification_bundles(
        analysis=_analysis(),
        context=ComparisonAlertContext(
            run_ids=(1, 2),
            digest_interval_hours=24,
            report_limit=20,
            winner_change_limit=10,
        ),
    )
    types = {bundle.alert_type for bundle in bundles}
    assert "cross_store_digest" in types
    assert "cross_store_winner_change" in types


def test_comparison_report_lists_all_available_stores():
    offers = (
        StoreOffer(3, 3, "Tost", "Producto", 19_990, None, 0, "https://tost/p"),
        StoreOffer(4, 4, "GradoÚnico", "Producto", 20_990, None, 0, "https://grado/p"),
        StoreOffer(2, 2, "Líquidos", "Producto", 21_990, None, 0, "https://liq/p"),
        StoreOffer(1, 1, "Licor3B", "Producto", 24_990, None, 0, "https://l3b/p"),
    )
    comparison = PriceComparison(
        master_product_id=11,
        canonical_name="Producto 750 ml",
        volume_ml=750,
        offers=offers,
        winner=offers[0],
        runner_up=offers[1],
        saving_clp=1_000,
        saving_pct=1_000 / 20_990,
        confidence=0.97,
        previous_winner_store_id=None,
        previous_winner_store_name=None,
        winner_changed=False,
        is_tie=False,
    )
    analysis = ComparisonAnalysis(
        current_products=4,
        master_groups=1,
        verified_matches=1,
        opportunities=(comparison,),
        winner_changes=(),
        ties=0,
        unverified_groups=0,
    )
    ranking = build_comparison_ranking_messages(analysis)[0]
    for store in ("Tost", "GradoÚnico", "Líquidos", "Licor3B"):
        assert store in ranking
    assert "Ahorro frente al más caro: $5.000" in ranking
