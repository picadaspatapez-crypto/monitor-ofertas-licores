from __future__ import annotations

from dataclasses import dataclass, field
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
    source_sections: tuple[str, ...] = ()


@dataclass(frozen=True)
class SectionStats:
    key: str
    name: str
    url: str
    pages_visited: int = 0
    cards_seen: int = 0
    unique_products: int = 0
    duplicates_removed: int = 0
    duration_ms: int = 0
    status: str = "success"
    error_message: str | None = None
    structural_warning: bool = False
    performance_ms: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class CollectionStats:
    pages_visited: int = 0
    cards_seen: int = 0
    unique_products: int = 0
    sections_discovered: int = 0
    sections_visited: int = 0
    sections_succeeded: int = 0
    sections_failed: int = 0
    duplicates_removed: int = 0
    discovery_source: str = "unknown"
    health_status: str = "UNKNOWN"
    health_score: int = 0
    structural_warnings: int = 0
    section_stats: tuple[SectionStats, ...] = ()
    performance_ms: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class CollectionBatch:
    products: list[CollectedProduct]
    stats: CollectionStats = field(default_factory=CollectionStats)


@dataclass(frozen=True)
class SavedProduct:
    item: CollectedProduct
    product: Product
    is_new: bool
    previous_price: Optional[int]

    @property
    def price_dropped(self) -> bool:
        return self.previous_price is not None and self.item.current_price < self.previous_price

    @property
    def price_increased(self) -> bool:
        return self.previous_price is not None and self.item.current_price > self.previous_price

    @property
    def price_changed(self) -> bool:
        return self.price_dropped or self.price_increased

    @property
    def price_change_amount(self) -> int:
        if self.previous_price is None:
            return 0
        return self.item.current_price - self.previous_price

    @property
    def price_change_pct(self) -> float:
        if not self.previous_price:
            return 0.0
        return self.price_change_amount / self.previous_price
