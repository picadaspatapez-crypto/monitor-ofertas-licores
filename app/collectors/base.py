from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Protocol

from app.domain import CollectionBatch


@dataclass(frozen=True)
class StoreMetadata:
    """Metadata necesaria para registrar una tienda sin tocar el pipeline."""

    name: str
    slug: str
    base_url: str
    connector_key: str
    requires_browser: bool
    country_code: str = "CL"
    currency_code: str = "CLP"

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("StoreMetadata.name no puede estar vacío.")
        if not self.slug.strip():
            raise ValueError("StoreMetadata.slug no puede estar vacío.")
        if not self.connector_key.strip():
            raise ValueError("StoreMetadata.connector_key no puede estar vacío.")
        if not self.base_url.startswith(("http://", "https://")):
            raise ValueError("StoreMetadata.base_url debe ser una URL HTTP(S).")
        if len(self.country_code) != 2:
            raise ValueError("StoreMetadata.country_code debe tener 2 caracteres.")
        if len(self.currency_code) != 3:
            raise ValueError("StoreMetadata.currency_code debe tener 3 caracteres.")

    def repository_kwargs(self) -> dict[str, object]:
        """Argumentos compatibles con get_or_create_store()."""
        return asdict(self)


class Collector(Protocol):
    """Contrato mínimo de cualquier tienda integrada al sistema."""

    key: str
    store_name: str
    metadata: StoreMetadata

    def collect(self) -> CollectionBatch:
        ...
