from __future__ import annotations

from dataclasses import dataclass

from app.domain import SavedProduct


@dataclass(frozen=True)
class CatalogAnalysis:
    total: int
    reported_discounts: int
    price_drops: int
    new_products: int


def analyze_catalog(items: list[SavedProduct]) -> CatalogAnalysis:
    return CatalogAnalysis(
        total=len(items),
        reported_discounts=sum(1 for item in items if item.item.regular_price is not None and item.item.discount_pct > 0),
        price_drops=sum(1 for item in items if item.price_dropped),
        new_products=sum(1 for item in items if item.is_new),
    )
