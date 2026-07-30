from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.matching import build_product_signature
from app.models import MasterProduct, Product
from app.search.normalization import normalize_search_text, unique_aliases


@dataclass(frozen=True)
class CatalogRefreshSummary:
    masters_seen: int
    masters_updated: int
    aliases_indexed: int


def _variant_from_signature(name: str, brand: str | None) -> str | None:
    signature = build_product_signature(name)
    tokens = list(signature.core_tokens)
    if brand:
        brand_tokens = normalize_search_text(brand).split()
        for token in brand_tokens:
            try:
                tokens.remove(token)
            except ValueError:
                pass
    variant = " ".join(tokens).strip()
    return variant[:255] if variant else None


def refresh_search_catalog(session: Session) -> CatalogRefreshSummary:
    statement = (
        select(MasterProduct)
        .options(selectinload(MasterProduct.store_products).selectinload(Product.store_record))
        .where(MasterProduct.status != "merged")
        .order_by(MasterProduct.id)
    )
    masters = list(session.scalars(statement).unique())
    updated = 0
    alias_count = 0

    for master in masters:
        products: list[Product] = [
            product
            for product in master.store_products
            if product.store_record is None or product.store_record.is_active
        ]
        source_names = [product.name for product in products]
        aliases = unique_aliases([master.canonical_name, *source_names])
        signature_names = source_names or [master.canonical_name]
        signatures = [build_product_signature(name) for name in signature_names]

        brands = {signature.brand for signature in signatures if signature.brand}
        if not master.brand and len(brands) == 1:
            master.brand = next(iter(brands))

        volumes = {signature.volume_ml for signature in signatures if signature.volume_ml}
        if master.volume_ml is None and len(volumes) == 1:
            master.volume_ml = next(iter(volumes))

        pack_counts = {
            signature.pack_count
            for signature in signatures
            if signature.pack_count is not None
        }
        package_quantity = next(iter(pack_counts)) if len(pack_counts) == 1 else 1
        if package_quantity is None or package_quantity < 1:
            package_quantity = 1

        variant = _variant_from_signature(master.canonical_name, master.brand)
        search_parts = [
            master.canonical_name,
            master.normalized_key,
            master.brand or "",
            variant or "",
            *(aliases or []),
        ]
        search_text = normalize_search_text(" ".join(search_parts))

        changed = False
        if master.variant != variant:
            master.variant = variant
            changed = True
        if master.package_quantity != package_quantity:
            master.package_quantity = package_quantity
            changed = True
        if (master.aliases or []) != aliases:
            master.aliases = aliases
            changed = True
        if master.search_text != search_text:
            master.search_text = search_text
            changed = True
        if changed:
            updated += 1
        alias_count += len(aliases)

    session.flush()
    return CatalogRefreshSummary(
        masters_seen=len(masters),
        masters_updated=updated,
        aliases_indexed=alias_count,
    )
