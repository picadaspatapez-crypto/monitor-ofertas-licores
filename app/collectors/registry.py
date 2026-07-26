from __future__ import annotations

from app.collectors.base import Collector
from app.collectors.licor3b import Licor3BCollector


def enabled_collectors() -> list[Collector]:
    return [Licor3BCollector()]
