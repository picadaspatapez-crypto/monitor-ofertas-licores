from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.analyzers import analyze_catalog
from app.domain import CollectedProduct, CollectionStats, SavedProduct
from app.notifications import (
    SmartAlertContext,
    build_smart_notification_bundles,
    ranking_fingerprint,
)


def _saved(
    product_id: int,
    name: str,
    price: int,
    previous: int | None,
    *,
    regular: int | None = None,
    discount: float = 0.0,
    is_new: bool = False,
) -> SavedProduct:
    return SavedProduct(
        item=CollectedProduct(
            "Licor3B",
            name,
            f"https://example.com/{product_id}",
            price,
            regular,
            discount,
        ),
        product=SimpleNamespace(id=product_id),
        is_new=is_new,
        previous_price=previous,
    )


def _analysis(items):
    return analyze_catalog(
        items,
        collection_stats=CollectionStats(
            unique_products=len(items),
            health_status="HEALTHY",
            health_score=100,
            sections_discovered=2,
            sections_visited=2,
            sections_succeeded=2,
        ),
    )


def _context(**kwargs):
    defaults = dict(
        store_id=1,
        run_id=20,
        store_name="Licor3B",
        previous_health_status="HEALTHY",
        previous_product_count=100,
        min_drop_pct=0.05,
        min_drop_amount=1000,
        digest_interval_hours=24,
        alert_new_products=False,
        alert_price_increases=False,
        max_change_items=10,
        report_limit=30,
        now=datetime(2026, 7, 27, tzinfo=timezone.utc),
    )
    defaults.update(kwargs)
    return SmartAlertContext(**defaults)


def test_first_smart_run_sends_summary_and_ranking_digest():
    items = [_saved(i, f"Producto {i}", 10000 + i, 10000 + i) for i in range(35)]
    bundles = build_smart_notification_bundles(
        items=items,
        analysis=_analysis(items),
        context=_context(last_ranking_alert=None),
    )
    assert [bundle.alert_type for bundle in bundles] == [
        "smart_summary",
        "ranking_digest",
    ]
    ranking = bundles[1]
    assert len(ranking.messages) == 3
    assert "1-10 de 30" in ranking.messages[0]
    assert "21-30 de 30" in ranking.messages[2]


def test_unchanged_recent_ranking_creates_no_telegram_messages():
    items = [_saved(i, f"Producto {i}", 10000 + i, 10000 + i) for i in range(5)]
    fingerprint = ranking_fingerprint(items, limit=30)
    last = SimpleNamespace(
        payload_hash=fingerprint,
        sent_at=datetime(2026, 7, 26, 20, 0, tzinfo=timezone.utc),
    )
    bundles = build_smart_notification_bundles(
        items=items,
        analysis=_analysis(items),
        context=_context(last_ranking_alert=last),
    )
    assert bundles == []


def test_same_ranking_is_refreshed_after_digest_interval():
    items = [_saved(i, f"Producto {i}", 10000 + i, 10000 + i) for i in range(5)]
    fingerprint = ranking_fingerprint(items, limit=30)
    last = SimpleNamespace(
        payload_hash=fingerprint,
        sent_at=datetime(2026, 7, 25, 23, 0, tzinfo=timezone.utc),
    )
    bundles = build_smart_notification_bundles(
        items=items,
        analysis=_analysis(items),
        context=_context(last_ranking_alert=last),
    )
    assert any(bundle.alert_type == "ranking_digest" for bundle in bundles)
    assert "refresco periódico" in next(
        bundle.reason for bundle in bundles if bundle.alert_type == "ranking_digest"
    )


def test_relevant_drop_uses_percentage_or_absolute_saving():
    items = [
        _saved(1, "Baja porcentual", 9000, 10000),
        _saved(2, "Baja absoluta", 198000, 200000),
        _saved(3, "Baja pequeña", 9950, 10000),
    ]
    # Evita que el digest sea la causa de envío: representa el ranking actual.
    last = SimpleNamespace(
        payload_hash=ranking_fingerprint(items, limit=30),
        sent_at=datetime(2026, 7, 27, tzinfo=timezone.utc),
    )
    bundles = build_smart_notification_bundles(
        items=items,
        analysis=_analysis(items),
        context=_context(last_ranking_alert=last),
    )
    drop_bundle = next(bundle for bundle in bundles if bundle.alert_type == "price_drop")
    text = drop_bundle.messages[0]
    assert "Baja porcentual" in text
    assert "Baja absoluta" in text
    assert "Baja pequeña" not in text


def test_new_products_are_disabled_by_default():
    items = [_saved(1, "Nuevo", 10000, None, is_new=True)]
    last = SimpleNamespace(
        payload_hash=ranking_fingerprint(items, limit=30),
        sent_at=datetime(2026, 7, 27, tzinfo=timezone.utc),
    )
    bundles = build_smart_notification_bundles(
        items=items,
        analysis=_analysis(items),
        context=_context(last_ranking_alert=last, alert_new_products=False),
    )
    assert not any(bundle.alert_type == "new_product" for bundle in bundles)
