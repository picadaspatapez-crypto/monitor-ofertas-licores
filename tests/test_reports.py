from types import SimpleNamespace

from app.analyzers import analyze_catalog
from app.domain import CollectedProduct, CollectionStats, SavedProduct
from app.reports import build_telegram_messages


def _saved(name: str, price: int, previous: int | None, is_new: bool = False) -> SavedProduct:
    item = CollectedProduct("Licor3B", name, f"https://example.com/{name}", price, None, 0.0)
    return SavedProduct(item=item, product=SimpleNamespace(), is_new=is_new, previous_price=previous)


def test_report_builds_observability_summary():
    items = [_saved("Producto B", 9000, 10000), _saved("Producto A", 10000, None, True)]
    analysis = analyze_catalog(
        items,
        missing_products=2,
        duration_ms=125000,
        collection_stats=CollectionStats(pages_visited=39, cards_seen=548, unique_products=548, sections_visited=11),
    )
    messages = build_telegram_messages(store_name="Licor3B", items=items, analysis=analysis)
    assert "Duración: 2m 05s" in messages[0]
    assert "Secciones: 11" in messages[0]
    assert "Páginas: 39" in messages[0]
    assert "Bajaron: 1" in messages[0]
    assert "No observados: 2" in messages[0]


def test_catalog_is_alphabetical():
    items = [_saved("Whisky Z", 10000, 10000), _saved("Gin A", 9000, 9000)]
    analysis = analyze_catalog(items)
    messages = build_telegram_messages(store_name="Licor3B", items=items, analysis=analysis)
    catalog = next(message for message in messages if "Catálogo alfabético" in message)
    assert catalog.index("Gin A") < catalog.index("Whisky Z")
