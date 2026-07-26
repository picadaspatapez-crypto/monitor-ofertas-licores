from __future__ import annotations

from dataclasses import dataclass

from app.domain import CollectionStats, SavedProduct


@dataclass(frozen=True)
class CatalogAnalysis:
    total: int
    reported_discounts: int
    price_drops: int
    price_increases: int
    unchanged: int
    new_products: int
    missing_products: int
    duration_ms: int
    collection_stats: CollectionStats


def analyze_catalog(
    items: list[SavedProduct],
    *,
    missing_products: int = 0,
    duration_ms: int = 0,
    collection_stats: CollectionStats | None = None,
) -> CatalogAnalysis:
    drops = sum(1 for item in items if item.price_dropped)
    increases = sum(1 for item in items if item.price_increased)
    new = sum(1 for item in items if item.is_new)
    unchanged = sum(1 for item in items if not item.is_new and not item.price_changed)
    return CatalogAnalysis(
        total=len(items),
        reported_discounts=sum(
            1 for item in items
            if item.item.regular_price is not None and item.item.discount_pct > 0
        ),
        price_drops=drops,
        price_increases=increases,
        unchanged=unchanged,
        new_products=new,
        missing_products=missing_products,
        duration_ms=duration_ms,
        collection_stats=collection_stats or CollectionStats(unique_products=len(items)),
    )
