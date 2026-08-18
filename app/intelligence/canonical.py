from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.matching.identity import extract_abv_pct, extract_vintage_year
from app.matching import build_product_signature, normalize_product_name
from app.models import CanonicalAlias, MasterProduct, Product


def canonical_fingerprint(name: str) -> str:
    sig = build_product_signature(name)
    parts = [
        sig.brand or "unknown",
        sig.core_key or "unknown",
        str(sig.volume_ml or "unknown"),
        "+".join(sorted(sig.variant_tokens)) or "base",
        str(extract_vintage_year(name) or "nv"),
        f"{extract_abv_pct(name):.1f}" if extract_abv_pct(name) is not None else "na",
        str(sig.pack_count or 1),
    ]
    return "|".join(parts)


def register_alias(
    session: Session,
    *,
    master_product_id: int,
    alias_text: str,
    source: str = "observed",
    confirmed: bool = False,
) -> CanonicalAlias:
    alias_text = " ".join((alias_text or "").split()).strip()
    alias_key = normalize_product_name(alias_text).normalized_key
    row = session.scalar(
        select(CanonicalAlias).where(
            CanonicalAlias.master_product_id == master_product_id,
            CanonicalAlias.alias_key == alias_key,
        )
    )
    if row is None:
        row = CanonicalAlias(
            master_product_id=master_product_id,
            alias_text=alias_text,
            alias_key=alias_key,
            source=source,
            is_confirmed=confirmed,
        )
        session.add(row)
    else:
        row.alias_text = alias_text or row.alias_text
        row.source = source or row.source
        row.is_confirmed = bool(row.is_confirmed or confirmed)
    return row


@dataclass(frozen=True)
class CanonicalRefreshSummary:
    masters_updated: int
    aliases_registered: int


def refresh_canonical_catalog(session: Session, master_ids: set[int] | None = None) -> CanonicalRefreshSummary:
    statement = select(MasterProduct).where(MasterProduct.status == "active")
    if master_ids:
        statement = statement.where(MasterProduct.id.in_(master_ids))
    masters = list(session.scalars(statement.order_by(MasterProduct.id)))
    if not masters:
        return CanonicalRefreshSummary(0, 0)

    ids = [int(master.id) for master in masters]
    products = list(
        session.scalars(
            select(Product)
            .where(Product.master_product_id.in_(ids))
            .order_by(Product.master_product_id, Product.id)
        )
    )
    by_master: dict[int, list[Product]] = {}
    for product in products:
        if product.master_product_id is not None:
            by_master.setdefault(int(product.master_product_id), []).append(product)

    existing_aliases = {
        (int(alias.master_product_id), alias.alias_key): alias
        for alias in session.scalars(
            select(CanonicalAlias).where(CanonicalAlias.master_product_id.in_(ids))
        )
    }

    aliases_registered = 0
    updated = 0
    for master in masters:
        group = by_master.get(int(master.id), [])
        if not group:
            continue
        # Never let a longer multipack title become the display identity of a
        # canonical single-bottle group. Legacy versions could leave an X6/X24
        # alias attached to a master even after the pack itself was excluded.
        single_group = [
            item
            for item in group
            if int(item.package_quantity or 1) == 1
            and not build_product_signature(item.name or "").is_pack
        ]
        candidates = single_group or group
        best = max(
            candidates,
            key=lambda item: (int(item.data_quality_score or 0), len(item.name or "")),
        )
        fingerprint = canonical_fingerprint(best.name)
        sig = build_product_signature(best.name)
        normalized = normalize_product_name(best.name)
        changed = False
        for attr, value in (
            ("canonical_name", normalized.canonical_name),
            ("canonical_fingerprint", fingerprint),
            ("brand", sig.brand or master.brand),
            ("volume_ml", sig.volume_ml or master.volume_ml),
            ("abv_pct", best.abv_pct if best.abv_pct is not None else extract_abv_pct(best.name)),
            ("vintage_year", best.vintage_year if best.vintage_year is not None else extract_vintage_year(best.name)),
            ("package_quantity", int(best.package_quantity or sig.pack_count or 1)),
        ):
            if value is not None and getattr(master, attr) != value:
                setattr(master, attr, value)
                changed = True
        if changed:
            updated += 1

        for product in group:
            alias_text = " ".join((product.name or "").split()).strip()
            if not alias_text:
                continue
            alias_key = normalize_product_name(alias_text).normalized_key
            key = (int(master.id), alias_key)
            row = existing_aliases.get(key)
            if row is None:
                row = CanonicalAlias(
                    master_product_id=int(master.id), alias_text=alias_text, alias_key=alias_key,
                    source=f"store:{product.store}", is_confirmed=False,
                )
                session.add(row)
                existing_aliases[key] = row
                aliases_registered += 1
            elif not row.is_confirmed:
                row.alias_text = alias_text
                row.source = f"store:{product.store}"

    session.flush()
    return CanonicalRefreshSummary(updated, aliases_registered)


def refresh_canonical_for_runs(session: Session, run_ids: list[int]) -> CanonicalRefreshSummary:
    if not run_ids:
        return CanonicalRefreshSummary(0, 0)
    master_ids = set(
        int(value)
        for value in session.scalars(
            select(Product.master_product_id)
            .where(Product.last_confirmed_run_id.in_([int(run_id) for run_id in run_ids]))
            .where(Product.master_product_id.is_not(None))
            .distinct()
        )
        if value is not None
    )
    return refresh_canonical_catalog(session, master_ids=master_ids)
