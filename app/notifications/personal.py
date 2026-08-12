from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain import SavedProduct
from app.models import MasterProduct, PersonalOpportunitySnapshot, PriceQuoteObservation, Product, Store
from app.notifications.policy import NotificationBundle, ranking_fingerprint
from app.reports.telegram import build_ranking_messages
from app.repositories.common import utcnow


def member_priced_saved_items(
    items: list[SavedProduct],
    *,
    eligible_audiences: tuple[str, ...] | list[str] | set[str],
) -> list[SavedProduct]:
    """Proyecta publicaciones personales al precio MEMBER elegible.

    CAV conserva ``Product.current_price`` como precio público/normal para no
    contaminar el mercado general. Para el ranking de tienda necesitamos, en
    cambio, mostrar exactamente el precio de socio que fue observado en la
    misma revisión. Esta función crea una vista inmutable de ``SavedProduct``
    usando las ``price_quotes`` recolectadas; no toca la base de datos.

    ``previous_price`` se deja en ``None`` deliberadamente. Las bajas MEMBER
    tienen su canal específico de alertas personales y así evitamos duplicar
    una misma baja como evento estándar del collector.
    """

    audiences = {
        str(value).strip().casefold()
        for value in eligible_audiences
        if str(value).strip()
    }
    if not audiences:
        return []

    projected: list[SavedProduct] = []
    for saved in items:
        eligible_member_quotes = [
            quote
            for quote in saved.item.price_quotes
            if (quote.price_type or "").strip().upper() == "MEMBER"
            and (quote.audience_key or "").strip().casefold() in audiences
            and int(quote.price) > 0
        ]
        if not eligible_member_quotes:
            continue

        member = min(eligible_member_quotes, key=lambda quote: int(quote.price))
        regular = int(member.regular_price) if member.regular_price else None
        if regular is None:
            public_prices = [
                int(quote.price)
                for quote in saved.item.price_quotes
                if (quote.price_type or "").strip().upper() == "PUBLIC"
                and int(quote.price) > 0
            ]
            regular = min(public_prices) if public_prices else None

        current = int(member.price)
        discount_pct = (
            (regular - current) / regular
            if regular is not None and regular > current
            else 0.0
        )
        item = replace(
            saved.item,
            current_price=current,
            regular_price=regular if regular is not None and regular > current else None,
            discount_pct=discount_pct,
        )
        projected.append(replace(saved, item=item, previous_price=None))

    return projected


def build_personal_store_ranking_bundle(
    *,
    store_id: int,
    run_id: int,
    store_name: str,
    member_items: list[SavedProduct],
    report_limit: int = 30,
) -> NotificationBundle | None:
    """Ranking de tienda para una fuente personal-only (actualmente CAV).

    A diferencia del digest global ``Tus mejores ventajas CAV``, este bundle
    replica el formato ``Mejores precios 1-10 de 30 · <tienda>`` usado por el
    resto de los collectors y se genera en *cada revisión HEALTHY*. El
    ``run_id`` forma parte de la clave de deduplicación, por lo que un reintento
    del mismo run no duplica mensajes, pero el siguiente run válido sí los
    vuelve a emitir como pidió el usuario.
    """

    if not member_items:
        return None
    limit = max(1, min(int(report_limit), 30))
    messages = build_ranking_messages(
        store_name=store_name,
        items=member_items,
        report_limit=limit,
    )
    if not messages:
        return None
    fingerprint = ranking_fingerprint(member_items, limit=limit)
    return NotificationBundle(
        store_id=store_id,
        run_id=run_id,
        alert_type="personal_store_ranking",
        deduplication_key=f"personal-store-ranking:{store_id}:{run_id}:{fingerprint[:20]}",
        payload_hash=fingerprint,
        reason=f"ranking de precio socio {store_name} tras revisión HEALTHY",
        messages=tuple(messages),
        product_id=int(member_items[0].product.id) if member_items else None,
        price=member_items[0].item.current_price if member_items else None,
    )


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
