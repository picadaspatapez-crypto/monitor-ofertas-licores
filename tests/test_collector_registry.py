import pytest

from app.collectors.base import StoreMetadata
from app.collectors.registry import _validate_collectors, enabled_collectors
from app.domain import CollectionBatch


def test_enabled_collectors_have_unique_valid_metadata():
    collectors = enabled_collectors()
    assert collectors
    assert {item.key for item in collectors} == {"licor3b", "liquidos", "elmundodelvino", "comercialjp"}
    assert len({item.key for item in collectors}) == len(collectors)
    assert len({item.metadata.slug for item in collectors}) == len(collectors)
    assert all(item.key == item.metadata.connector_key for item in collectors)
    assert all(item.store_name == item.metadata.name for item in collectors)


def test_store_metadata_exports_repository_arguments():
    metadata = StoreMetadata(
        name="Tienda Demo",
        slug="tienda-demo",
        base_url="https://example.com/",
        connector_key="tienda_demo",
        requires_browser=False,
    )
    values = metadata.repository_kwargs()
    assert values["slug"] == "tienda-demo"
    assert values["country_code"] == "CL"
    assert values["currency_code"] == "CLP"


def test_registry_rejects_duplicate_keys():
    metadata = StoreMetadata(
        name="Demo",
        slug="demo",
        base_url="https://example.com/",
        connector_key="demo",
        requires_browser=False,
    )

    class DemoCollector:
        key = "demo"
        store_name = "Demo"

        def collect(self) -> CollectionBatch:
            return CollectionBatch(products=[])

    DemoCollector.metadata = metadata

    with pytest.raises(RuntimeError, match="Collector duplicado"):
        _validate_collectors([DemoCollector(), DemoCollector()])
