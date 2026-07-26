from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.models import Product


@dataclass(frozen=True)
class CollectedProduct:
    store: str
    name: str
    url: str
    current_price: int
    regular_price: Optional[int]
    discount_pct: float


@dataclass(frozen=True)
class SavedProduct:
    item: CollectedProduct
    product: Product
    is_new: bool
    price_dropped: bool
