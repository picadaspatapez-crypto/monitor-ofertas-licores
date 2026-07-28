from __future__ import annotations

from collections.abc import Callable

from app.collectors.base import Collector
from app.collectors.licor3b import Licor3BCollector
from app.collectors.liquidos import LiquidosCollector
from app.collectors.tost import TostCollector
from app.collectors.gradounico import GradoUnicoCollector


CollectorFactory = Callable[[], Collector]

# Una tienda nueva se incorpora agregando su clase a esta tupla. El pipeline no
# contiene condiciones por tienda y no necesita conocer selectores ni URLs.
COLLECTOR_FACTORIES: tuple[CollectorFactory, ...] = (
    Licor3BCollector,
    LiquidosCollector,
    TostCollector,
    GradoUnicoCollector,
)


def _validate_collectors(collectors: list[Collector]) -> None:
    keys: set[str] = set()
    slugs: set[str] = set()
    connector_keys: set[str] = set()

    for collector in collectors:
        metadata = collector.metadata
        if collector.key != metadata.connector_key:
            raise RuntimeError(
                f"Collector {type(collector).__name__}: key y metadata.connector_key no coinciden."
            )
        if collector.store_name != metadata.name:
            raise RuntimeError(
                f"Collector {type(collector).__name__}: store_name y metadata.name no coinciden."
            )
        if collector.key in keys:
            raise RuntimeError(f"Collector duplicado: key={collector.key}")
        if metadata.slug in slugs:
            raise RuntimeError(f"Collector duplicado: slug={metadata.slug}")
        if metadata.connector_key in connector_keys:
            raise RuntimeError(
                f"Collector duplicado: connector_key={metadata.connector_key}"
            )
        if not callable(getattr(collector, "collect", None)):
            raise RuntimeError(f"Collector inválido sin collect(): {type(collector).__name__}")

        keys.add(collector.key)
        slugs.add(metadata.slug)
        connector_keys.add(metadata.connector_key)


def enabled_collectors() -> list[Collector]:
    collectors = [factory() for factory in COLLECTOR_FACTORIES]
    _validate_collectors(collectors)
    return collectors
