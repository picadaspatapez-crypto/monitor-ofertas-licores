from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload, sessionmaker

from app.models import (
    FavoriteAlert,
    MasterProduct,
    PriceObservation,
    Product,
    TelegramFavorite,
)
from app.repositories.common import utcnow
from app.search.engine import SearchResult, search_products
from app.search.formatting import format_clp


@dataclass(frozen=True)
class FavoriteOffer:
    store_name: str
    price: int
    regular_price: int | None
    url: str


@dataclass(frozen=True)
class FavoriteSnapshot:
    available: bool
    offers: tuple[FavoriteOffer, ...]
    winner: FavoriteOffer | None

    @property
    def store_names(self) -> tuple[str, ...]:
        return tuple(sorted({offer.store_name for offer in self.offers}, key=str.casefold))


@dataclass(frozen=True)
class FavoriteView:
    favorite_id: int
    master_product_id: int
    canonical_name: str
    volume_ml: int | None
    target_price: int | None
    snapshot: FavoriteSnapshot


@dataclass(frozen=True)
class FavoriteResolution:
    status: str
    result: SearchResult | None
    alternatives: tuple[SearchResult, ...] = ()


def resolve_favorite_query(
    session: Session,
    query: str,
    *,
    max_age_hours: int = 72,
) -> FavoriteResolution:
    results = search_products(
        session,
        query,
        limit=4,
        max_age_hours=max_age_hours,
        minimum_score=0.30,
    )
    if not results:
        return FavoriteResolution("not_found", None)

    first = results[0]
    if first.score < 0.50:
        return FavoriteResolution("ambiguous", None, tuple(results[:4]))
    if len(results) > 1:
        second = results[1]
        if first.master_product_id != second.master_product_id and first.score - second.score < 0.07:
            return FavoriteResolution("ambiguous", None, tuple(results[:4]))
    return FavoriteResolution("resolved", first, tuple(results[1:4]))


def _snapshot_from_products(products: Iterable[Product]) -> FavoriteSnapshot:
    cheapest_by_store: dict[str, FavoriteOffer] = {}
    for product in products:
        if product.current_price <= 0:
            continue
        store_name = (
            product.store_record.name if product.store_record is not None else product.store
        )
        offer = FavoriteOffer(
            store_name=store_name,
            price=int(product.current_price),
            regular_price=(
                int(product.regular_price) if product.regular_price is not None else None
            ),
            url=product.url,
        )
        current = cheapest_by_store.get(store_name)
        if current is None or offer.price < current.price:
            cheapest_by_store[store_name] = offer

    offers = tuple(
        sorted(cheapest_by_store.values(), key=lambda item: (item.price, item.store_name.casefold()))
    )
    return FavoriteSnapshot(bool(offers), offers, offers[0] if offers else None)


def current_snapshot(
    session: Session,
    master_product_id: int,
    *,
    max_age_hours: int = 72,
) -> FavoriteSnapshot:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    products = list(
        session.scalars(
            select(Product)
            .options(selectinload(Product.store_record))
            .where(
                Product.master_product_id == master_product_id,
                Product.last_seen_at >= cutoff,
                Product.current_price > 0,
            )
        ).unique()
    )
    return _snapshot_from_products(products)


def _snapshot_for_runs(
    session: Session,
    master_product_id: int,
    run_ids: tuple[int, ...],
) -> FavoriteSnapshot:
    if not run_ids:
        return FavoriteSnapshot(False, (), None)
    products = list(
        session.scalars(
            select(Product)
            .join(PriceObservation, PriceObservation.product_id == Product.id)
            .options(selectinload(Product.store_record))
            .where(
                Product.master_product_id == master_product_id,
                PriceObservation.scrape_run_id.in_(run_ids),
                PriceObservation.price > 0,
            )
        ).unique()
    )
    return _snapshot_from_products(products)


def add_or_update_favorite(
    session: Session,
    *,
    chat_id: int,
    result: SearchResult,
    target_price: int | None = None,
) -> tuple[TelegramFavorite, bool]:
    favorite = session.scalar(
        select(TelegramFavorite).where(
            TelegramFavorite.chat_id == chat_id,
            TelegramFavorite.master_product_id == result.master_product_id,
        )
    )
    created = favorite is None
    now = utcnow()
    store_names = [offer.store_name for offer in result.offers]
    winner = result.winner

    if favorite is None:
        favorite = TelegramFavorite(
            chat_id=chat_id,
            master_product_id=result.master_product_id,
            target_price=target_price,
            notify_on_price_drop=True,
            notify_on_new_store=True,
            notify_on_winner_change=True,
            notify_on_back_in_stock=True,
            is_active=True,
            last_best_price=winner.price if winner else None,
            last_winner_store=winner.store_name if winner else None,
            last_store_names=store_names,
            was_available=bool(result.offers),
            last_evaluated_at=now,
        )
        session.add(favorite)
    else:
        favorite.is_active = True
        if target_price is not None:
            favorite.target_price = target_price
        favorite.last_best_price = winner.price if winner else favorite.last_best_price
        favorite.last_winner_store = winner.store_name if winner else favorite.last_winner_store
        favorite.last_store_names = store_names or list(favorite.last_store_names or [])
        favorite.was_available = bool(result.offers)
        favorite.last_evaluated_at = now
        favorite.updated_at = now

    session.flush()
    return favorite, created


def list_favorites(
    session: Session,
    *,
    chat_id: int,
    max_age_hours: int = 72,
) -> list[FavoriteView]:
    favorites = list(
        session.scalars(
            select(TelegramFavorite)
            .where(
                TelegramFavorite.chat_id == chat_id,
                TelegramFavorite.is_active.is_(True),
            )
            .order_by(TelegramFavorite.id)
        )
    )
    views: list[FavoriteView] = []
    for favorite in favorites:
        master = session.get(MasterProduct, favorite.master_product_id)
        if master is None:
            continue
        views.append(
            FavoriteView(
                favorite_id=int(favorite.id),
                master_product_id=int(master.id),
                canonical_name=master.canonical_name,
                volume_ml=master.volume_ml,
                target_price=favorite.target_price,
                snapshot=current_snapshot(
                    session,
                    int(master.id),
                    max_age_hours=max_age_hours,
                ),
            )
        )
    return views


def deactivate_favorite(session: Session, *, chat_id: int, favorite_id: int) -> bool:
    favorite = session.scalar(
        select(TelegramFavorite).where(
            TelegramFavorite.id == favorite_id,
            TelegramFavorite.chat_id == chat_id,
            TelegramFavorite.is_active.is_(True),
        )
    )
    if favorite is None:
        return False
    favorite.is_active = False
    favorite.updated_at = utcnow()
    session.flush()
    return True


def _format_favorite_alert(
    *,
    name: str,
    snapshot: FavoriteSnapshot,
    events: list[tuple[str, str]],
    target_price: int | None,
) -> str:
    lines = ["⭐ Alerta de favorito", "", name]
    lines.extend(f"• {message}" for _, message in events)
    if snapshot.winner is not None:
        lines.extend(
            [
                "",
                f"🥇 {snapshot.winner.store_name}: {format_clp(snapshot.winner.price)}",
            ]
        )
        for offer in snapshot.offers[1:4]:
            lines.append(f"• {offer.store_name}: {format_clp(offer.price)}")
        if target_price is not None:
            lines.append(f"🎯 Precio objetivo: {format_clp(target_price)}")
        if snapshot.winner.url.startswith(("http://", "https://")):
            lines.extend(["", snapshot.winner.url])
    return "\n".join(lines)[:4000]


def _event_payload(
    *,
    favorite: TelegramFavorite,
    snapshot: FavoriteSnapshot,
    events: list[tuple[str, str]],
    run_ids: tuple[int, ...],
) -> tuple[str, str]:
    winner = snapshot.winner
    raw = "|".join(
        [
            str(favorite.id),
            ",".join(str(item) for item in run_ids),
            ",".join(code for code, _ in events),
            str(winner.price if winner else "none"),
            winner.store_name if winner else "none",
            ",".join(snapshot.store_names),
        ]
    )
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"favorite:{favorite.id}:{digest[:32]}", digest


def evaluate_favorite_alerts(
    session: Session,
    *,
    run_ids: Iterable[int],
    coverage_complete: bool,
    minimum_drop_clp: int = 1,
) -> tuple[int, int]:
    normalized_run_ids = tuple(sorted({int(value) for value in run_ids}))
    favorites = list(
        session.scalars(
            select(TelegramFavorite)
            .where(TelegramFavorite.is_active.is_(True))
            .order_by(TelegramFavorite.id)
        )
    )
    queued = 0
    evaluated = 0
    now = utcnow()

    for favorite in favorites:
        master = session.get(MasterProduct, favorite.master_product_id)
        if master is None:
            continue
        snapshot = _snapshot_for_runs(session, int(master.id), normalized_run_ids)
        events: list[tuple[str, str]] = []
        previous_price = favorite.last_best_price
        previous_winner = favorite.last_winner_store
        previous_stores = set(str(value) for value in (favorite.last_store_names or []))

        if snapshot.available and snapshot.winner is not None:
            current_price = snapshot.winner.price
            current_winner = snapshot.winner.store_name
            current_stores = set(snapshot.store_names)

            if (
                favorite.notify_on_back_in_stock
                and favorite.last_evaluated_at is not None
                and not favorite.was_available
            ):
                events.append(("back_in_stock", "Volvió a estar disponible."))

            if (
                favorite.notify_on_price_drop
                and previous_price is not None
                and current_price < previous_price
                and previous_price - current_price >= max(1, minimum_drop_clp)
            ):
                events.append(
                    (
                        "price_drop",
                        f"Bajó {format_clp(previous_price - current_price)}: "
                        f"{format_clp(previous_price)} → {format_clp(current_price)}.",
                    )
                )

            if (
                favorite.target_price is not None
                and current_price <= favorite.target_price
                and (previous_price is None or previous_price > favorite.target_price)
            ):
                events.append(
                    (
                        "target_reached",
                        f"Alcanzó tu precio objetivo de {format_clp(favorite.target_price)}.",
                    )
                )

            new_stores = sorted(current_stores - previous_stores, key=str.casefold)
            if favorite.notify_on_new_store and previous_stores and new_stores:
                events.append(
                    (
                        "new_store",
                        "Ahora también aparece en: " + ", ".join(new_stores) + ".",
                    )
                )

            if (
                favorite.notify_on_winner_change
                and previous_winner
                and current_winner != previous_winner
            ):
                events.append(
                    (
                        "winner_change",
                        f"Cambió la tienda más barata: {previous_winner} → {current_winner}.",
                    )
                )

            favorite.last_best_price = current_price
            favorite.last_winner_store = current_winner
            favorite.last_store_names = sorted(current_stores, key=str.casefold)
            favorite.was_available = True
            favorite.last_evaluated_at = now
            favorite.updated_at = now
            evaluated += 1
        elif coverage_complete:
            favorite.was_available = False
            favorite.last_store_names = []
            favorite.last_winner_store = None
            favorite.last_evaluated_at = now
            favorite.updated_at = now
            evaluated += 1

        if not events:
            continue

        message = _format_favorite_alert(
            name=master.canonical_name,
            snapshot=snapshot,
            events=events,
            target_price=favorite.target_price,
        )
        deduplication_key, payload_hash = _event_payload(
            favorite=favorite,
            snapshot=snapshot,
            events=events,
            run_ids=normalized_run_ids,
        )
        existing = session.scalar(
            select(FavoriteAlert.id).where(
                FavoriteAlert.deduplication_key == deduplication_key
            )
        )
        if existing is not None:
            continue
        alert = FavoriteAlert(
            favorite_id=int(favorite.id),
            chat_id=int(favorite.chat_id),
            event_types=[code for code, _ in events],
            run_ids=list(normalized_run_ids),
            status="pending",
            deduplication_key=deduplication_key,
            payload_hash=payload_hash,
            message=message,
            current_price=snapshot.winner.price if snapshot.winner else None,
            winner_store=snapshot.winner.store_name if snapshot.winner else None,
        )
        session.add(alert)
        session.flush()
        queued += 1

    session.flush()
    return evaluated, queued


SendMessage = Callable[[str, str, str], None]


def deliver_pending_favorite_alerts(
    *,
    SessionLocal: sessionmaker,
    telegram_bot_token: str,
    send_message_fn: SendMessage,
    limit: int = 20,
) -> tuple[int, int]:
    with SessionLocal() as session:
        alert_ids = list(
            session.scalars(
                select(FavoriteAlert.id)
                .where(FavoriteAlert.status.in_(["pending", "failed"]))
                .order_by(FavoriteAlert.created_at, FavoriteAlert.id)
                .limit(max(1, limit))
            )
        )

    sent = failed = 0
    for alert_id in alert_ids:
        with SessionLocal() as session:
            alert = session.get(FavoriteAlert, alert_id)
            if alert is None or alert.status == "sent":
                continue
            chat_id = str(alert.chat_id)
            message = alert.message
        try:
            send_message_fn(telegram_bot_token, chat_id, message)
        except Exception as exc:
            with SessionLocal() as session:
                alert = session.get(FavoriteAlert, alert_id)
                if alert is not None:
                    alert.status = "failed"
                    alert.failed_at = utcnow()
                    alert.error_message = str(exc)[:2000]
                    session.commit()
            failed += 1
            continue

        with SessionLocal() as session:
            alert = session.get(FavoriteAlert, alert_id)
            if alert is not None:
                alert.status = "sent"
                alert.sent_at = utcnow()
                alert.failed_at = None
                alert.error_message = None
                session.commit()
        sent += 1
    return sent, failed
