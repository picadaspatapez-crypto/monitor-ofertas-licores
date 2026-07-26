from types import SimpleNamespace
from app.analyzers import analyze_catalog
from app.domain import CollectedProduct, SavedProduct
from app.reports import build_telegram_messages


def test_report_builds_messages():
    item = CollectedProduct("Licor3B", "Producto A", "https://example.com/a", 10000, None, 0.0)
    saved = SavedProduct(item=item, product=SimpleNamespace(), is_new=True, price_dropped=False)
    analysis = analyze_catalog([saved])
    messages = build_telegram_messages(store_name="Licor3B", items=[saved], analysis=analysis)
    assert "Productos revisados: 1" in messages[0]
    assert "Producto A" in messages[1]
