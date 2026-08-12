from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import MasterProduct, PersonalOpportunitySnapshot, PriceQuoteObservation, Product, Store
from app.notifications.policy import NotificationBundle
from app.repositories.common import utcnow


@dataclass(frozen=True)
class MemberPriceDrop:
    product_id: int
    store_id: int
    store_name: str
    product_name: str
    url: str
    previous_price: int
    current_price: int
    audience_key: str

    @property
    def saving_clp(self) -> int:
        return max(0, self.previous_price - self.current_price)

    @property
    def drop_pct(self) -> float:
        return self.saving_clp / self.previous_price if self.previous_price else 0.0


def _recent_member_drops(
    session: Session,
    *,
    eligible_audiences: set[str],
) -> list[MemberPriceDrop]:
    cutoff = utcnow() - timedelta(days=90)
    rows = session.execute(
        select(PriceQuoteObservation, Product, Store)
        .join(Product, Product.id == PriceQuoteObservation.product_id)
        .join(Store, Store.id == Product.store_id)
        .where(
            Store.is_active.is_(True),
            Store.personal_comparison_enabled.is_(True),
            Product.is_available.is_(True),
            PriceQuoteObservation.price_type == "MEMBER",
            PriceQuoteObservation.audience_key.in_(eligible_audiences),
            PriceQuoteObservation.price > 0,
            PriceQuoteObservation.observed_at >= cutoff,
        )
        .order_by(
            PriceQuoteObservation.product_id,
            PriceQuoteObservation.observed_at.desc(),
            PriceQuoteObservation.id.desc(),
        )
    )
    grouped: dict[int, list[tuple[PriceQuoteObservation, Product, Store]]] = defaultdict(list)
    for observation, product, store in rows:
        group = grouped[int(product.id)]
        if len(group) < 2:
            group.append((observation, product, store))

    drops: list[MemberPriceDrop] = []
    for values in grouped.values():
        if len(values) < 2:
            continue
        latest, previous = values[0], values[1]
        latest_obs, product, store = latest
        previous_obs = previous[0]
        if int(latest_obs.price) >= int(previous_obs.price):
            continue
        drops.append(
            MemberPriceDrop(
                product_id=int(product.id),
                store_id=int(store.id),
                store_name=store.name,
                product_name=product.name,
                url=product.url,
                previous_price=int(previous_obs.price),
                current_price=int(latest_obs.price),
                audience_key=latest_obs.audience_key,
            )
        )
    return drops


def build_personal_price_notification_bundles(
    session: Session,
    *,
    eligible_audiences: tuple[str, ...] | list[str] | set[str],
    min_drop_pct: float,
    min_drop_amount: int,
    min_advantage_clp: int = 1000,
    limit: int = 10,
) -> list[NotificationBundle]:
    audiences = {str(value).strip().casefold() for value in eligible_audiences if str(value).strip()}
    if not audiences:
        return []
    candidates = [
        item
        for item in _recent_member_drops(session, eligible_audiences=audiences)
        if item.drop_pct >= min_drop_pct or item.saving_clp >= min_drop_amount
    ]
    candidates.sort(key=lambda item: (-item.drop_pct, -item.saving_clp, item.product_name.casefold()))

    bundles: list[NotificationBundle] = []
    for item in candidates[: max(1, min(int(limit), 30))]:
        fingerprint = hashlib.sha256(
            f"{item.product_id}:{item.audience_key}:{item.previous_price}:{item.current_price}".encode()
        ).hexdigest()
        previous = f"${item.previous_price:,}".replace(",", ".")
        current = f"${item.current_price:,}".replace(",", ".")
        saving = f"${item.saving_clp:,}".replace(",", ".")
        message = "\n".join(
            [
                "🟣 Bajó tu precio de socio",
                "",
                item.product_name,
                f"{item.store_name}: {current}",
                f"Antes: {previous}",
                f"Ahorro adicional: {saving} ({item.drop_pct:.1%})",
                "",
                item.url,
            ]
        )
        bundles.append(
            NotificationBundle(
                store_id=item.store_id,
                run_id=None,
                alert_type="personal_member_price_drop",
                deduplication_key=f"personal-member-drop:{fingerprint[:32]}",
                payload_hash=fingerprint,
                reason=f"Precio MEMBER bajó {item.saving_clp} CLP ({item.drop_pct:.2%})",
                messages=(message,),
                product_id=item.product_id,
                price=item.current_price,
            )
        )

    advantage_rows = list(session.execute(
        select(PersonalOpportunitySnapshot, MasterProduct, Product, Store)
        .join(MasterProduct, MasterProduct.id == PersonalOpportunitySnapshot.master_product_id)
        .join(Product, Product.id == PersonalOpportunitySnapshot.winner_product_id)
        .join(Store, Store.id == PersonalOpportunitySnapshot.winner_store_id)
        .where(
            Store.is_active.is_(True),
            Store.personal_comparison_enabled.is_(True),
            Product.is_available.is_(True),
            PersonalOpportunitySnapshot.winner_price_type == "MEMBER",
            PersonalOpportunitySnapshot.personal_advantage_clp >= int(min_advantage_clp),
        )
        .order_by(
            PersonalOpportunitySnapshot.personal_advantage_pct.desc(),
            PersonalOpportunitySnapshot.personal_advantage_clp.desc(),
        )
        .limit(max(1, min(int(limit), 30)))
    ))
    if advantage_rows:
        payload = [
            (
                int(snapshot.master_product_id),
                int(snapshot.winner_price or 0),
                int(snapshot.public_reference_price or 0),
                int(snapshot.personal_advantage_clp or 0),
            )
            for snapshot, _, _, _ in advantage_rows
        ]
        digest_hash = hashlib.sha256(repr(payload).encode()).hexdigest()
        lines = ["🟣 Tus mejores ventajas CAV", ""]
        for index, (snapshot, master, product, store) in enumerate(advantage_rows, start=1):
            price = f"${int(snapshot.winner_price or product.current_price):,}".replace(",", ".")
            advantage = f"${int(snapshot.personal_advantage_clp or 0):,}".replace(",", ".")
            lines.extend([
                f"{index}. {master.canonical_name}",
                f"   {store.name}: {price} · ahorras {advantage} vs mercado público",
            ])
        lines.extend(["", "Usa /miprecio <producto> para ver la comparación completa."])
        bundles.append(
            NotificationBundle(
                store_id=None,
                run_id=None,
                alert_type="personal_member_advantage_digest",
                deduplication_key=f"personal-member-advantage:{digest_hash[:32]}",
                payload_hash=digest_hash,
                reason=f"{len(advantage_rows)} ventajas MEMBER sobre el mercado público",
                messages=("\n".join(lines),),
                product_id=int(advantage_rows[0][2].id),
                price=int(advantage_rows[0][0].winner_price or advantage_rows[0][2].current_price),
            )
        )

    return bundles
