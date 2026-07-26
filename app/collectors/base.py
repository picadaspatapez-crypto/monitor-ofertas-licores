from __future__ import annotations

from typing import Protocol

from app.domain import CollectionBatch


class Collector(Protocol):
    key: str
    store_name: str

    def collect(self) -> CollectionBatch:
        ...
