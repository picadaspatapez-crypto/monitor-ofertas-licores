from __future__ import annotations

from typing import Protocol

from app.domain import CollectedProduct


class Collector(Protocol):
    key: str
    store_name: str

    def collect(self) -> list[CollectedProduct]:
        ...
