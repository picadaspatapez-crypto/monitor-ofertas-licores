from types import SimpleNamespace

from app.analyzers import analyze_catalog
from app.domain import CollectedProduct, CollectionStats, SavedProduct
from app.reports import build_telegram_messages


def _saved(
    name: str,
    price: int,
    previous: int | None,
    *,
    regular: int | None = None,
    discount: float = 0.0,
    is_new: bool = False,
) -> SavedProduct:
    item = CollectedProduct(
        "Licor3B",
        name,
        f"https://example.com/{name}",
        price,
        regular,
        discount,
    )
    return SavedProduct(
        item=item,
        product=SimpleNamespace(),
        is_new=is_new,
        previous_price=previous,
    )


def test_report_builds_observability_summary():
    items = [
        _saved("Producto B", 9000, 10000),
        _saved("Producto A", 10000, None, is_new=True),
    ]
    analysis = analyze_catalog(
        items,
        missing_products=2,
        duration_ms=125000,
        collection_stats=CollectionStats(
            pages_visited=39,
            cards_seen=548,
            unique_products=548,
            sections_visited=11,
        ),
    )
    messages = build_telegram_messages(
        store_name="Licor3B",
        items=items,
        analysis=analysis,
    )
    assert "Duración: 2m 05s" in messages[0]
    assert "Secciones: 11" in messages[0]
    assert "Páginas: 39" in messages[0]
    assert "Bajaron: 1" in messages[0]
    assert "No observados: 2" in messages[0]
    assert "No se aplica un precio máximo" in messages[0]


def test_best_prices_prioritize_discount_not_alphabetical_order():
    items = [
        _saved("A barato", 5000, 5000),
        _saved("Z gran descuento", 70000, 70000, regular=140000, discount=0.50),
        _saved("M descuento medio", 10000, 10000, regular=12500, discount=0.20),
    ]
    analysis = analyze_catalog(items)
    messages = build_telegram_messages(
        store_name="Licor3B",
        items=items,
        analysis=analysis,
    )
    ranking = next(message for message in messages if "Mejores precios" in message)
    assert ranking.index("Z gran descuento") < ranking.index("M descuento medio")
    assert ranking.index("M descuento medio") < ranking.index("A barato")


def test_expensive_product_is_not_filtered_out():
    items = [
        _saved("Whisky premium", 250000, 250000, regular=500000, discount=0.50),
        _saved("Cerveza", 1500, 1500),
    ]
    analysis = analyze_catalog(items)
    messages = build_telegram_messages(
        store_name="Licor3B",
        items=items,
        analysis=analysis,
    )
    ranking = next(message for message in messages if "Mejores precios" in message)
    assert "Whisky premium" in ranking
    assert ranking.index("Whisky premium") < ranking.index("Cerveza")


def test_report_sends_up_to_thirty_ranked_products_in_three_blocks():
    items = [
        _saved(
            f"Producto {index:02d}",
            10000 + index,
            10000 + index,
            regular=20000 + index,
            discount=0.50 - index / 1000,
        )
        for index in range(35)
    ]
    analysis = analyze_catalog(items)
    messages = build_telegram_messages(
        store_name="Licor3B",
        items=items,
        analysis=analysis,
    )
    ranking_messages = [message for message in messages if "Mejores precios" in message]
    assert len(ranking_messages) == 3
    assert "1-10 de 30" in ranking_messages[0]
    assert "11-20 de 30" in ranking_messages[1]
    assert "21-30 de 30" in ranking_messages[2]
    assert "Producto 30" not in "\n".join(ranking_messages)
