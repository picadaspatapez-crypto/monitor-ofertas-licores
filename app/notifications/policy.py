from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable

from app.analyzers import CatalogAnalysis
from app.domain import SavedProduct
from app.models import Alert
from app.reports.telegram import (
    build_incident_message,
    build_new_products_message,
    build_price_drops_message,
    build_price_increases_message,
    build_ranking_messages,
    build_smart_summary_message,
    ranked_best_prices,
)


@dataclass(frozen=True)
class SmartAlertContext:
    store_id: int | None
    run_id: int
    store_name: str
    previous_health_status: str | None
    previous_product_count: int | None
    min_drop_pct: float
    min_drop_amount: int
    digest_interval_hours: int
    alert_new_products: bool
    alert_price_increases: bool
    max_change_items: int
    report_limit: int
    last_ranking_alert: Alert | None = None
    last_incident_alert: Alert | None = None
    now: datetime | None = None


@dataclass(frozen=True)
class NotificationBundle:
    store_id: int | None
    run_id: int | None
    alert_type: str
    deduplication_key: str
    payload_hash: str
    reason: str
    messages: tuple[str, ...]
    product_id: int | None = None
    price: int | None = None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _hash_payload(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def ranking_fingerprint(items: Iterable[SavedProduct], *, limit: int = 30) -> str:
    ranked = ranked_best_prices(list(items))[:limit]
    payload = [
        {
            "position": position,
            "product_id": int(saved.product.id),
            "price": saved.item.current_price,
            "regular_price": saved.item.regular_price,
            "discount_pct": round(saved.item.discount_pct, 6),
        }
        for position, saved in enumerate(ranked, start=1)
    ]
    return _hash_payload(payload)


def _alert_age(alert: Alert | None, now: datetime) -> timedelta | None:
    if alert is None or alert.sent_at is None:
        return None
    sent_at = alert.sent_at
    if sent_at.tzinfo is None:
        sent_at = sent_at.replace(tzinfo=timezone.utc)
    return now - sent_at


def _ranking_is_due(
    *,
    fingerprint: str,
    last_alert: Alert | None,
    interval_hours: int,
    now: datetime,
) -> tuple[bool, str]:
    if last_alert is None:
        return True, "primer ranking inteligente"
    if last_alert.payload_hash != fingerprint:
        return True, "cambió el ranking de mejores precios"
    age = _alert_age(last_alert, now)
    if age is None or age >= timedelta(hours=max(1, interval_hours)):
        return True, f"refresco periódico de {max(1, interval_hours)} horas"
    return False, "ranking sin cambios dentro del intervalo"


def _qualifying_drops(
    items: Iterable[SavedProduct],
    *,
    min_drop_pct: float,
    min_drop_amount: int,
) -> list[SavedProduct]:
    selected = []
    for saved in items:
        if not saved.price_dropped or saved.previous_price is None:
            continue
        saving = saved.previous_price - saved.item.current_price
        drop_pct = abs(saved.price_change_pct)
        if drop_pct >= min_drop_pct or saving >= min_drop_amount:
            selected.append(saved)
    return sorted(
        selected,
        key=lambda saved: (
            -abs(saved.price_change_pct),
            -(saved.previous_price - saved.item.current_price),
            saved.item.name.casefold(),
        ),
    )


def _qualifying_increases(items: Iterable[SavedProduct]) -> list[SavedProduct]:
    return sorted(
        (saved for saved in items if saved.price_increased),
        key=lambda saved: (
            -saved.price_change_pct,
            -saved.price_change_amount,
            saved.item.name.casefold(),
        ),
    )


def _incident_payload(analysis: CatalogAnalysis) -> dict:
    stats = analysis.collection_stats
    return {
        "health_status": stats.health_status,
        "sections_failed": stats.sections_failed,
        "structural_warnings": stats.structural_warnings,
        "problems": [
            {
                "key": section.key,
                "status": section.status,
                "warning": section.structural_warning,
                "error": section.error_message,
            }
            for section in stats.section_stats
            if section.status != "success" or section.structural_warning
        ],
    }


def _incident_is_due(
    *,
    payload_hash: str,
    last_alert: Alert | None,
    now: datetime,
    reminder_hours: int = 24,
) -> bool:
    if last_alert is None or last_alert.payload_hash != payload_hash:
        return True
    age = _alert_age(last_alert, now)
    return age is None or age >= timedelta(hours=reminder_hours)


def build_smart_notification_bundles(
    *,
    items: list[SavedProduct],
    analysis: CatalogAnalysis,
    context: SmartAlertContext,
) -> list[NotificationBundle]:
    now = context.now or _utcnow()
    stats = analysis.collection_stats
    event_bundles: list[NotificationBundle] = []
    reasons: list[str] = []

    drops = _qualifying_drops(
        items,
        min_drop_pct=context.min_drop_pct,
        min_drop_amount=context.min_drop_amount,
    )[: context.max_change_items]
    if drops:
        payload = [
            {
                "product_id": int(saved.product.id),
                "previous": saved.previous_price,
                "current": saved.item.current_price,
            }
            for saved in drops
        ]
        payload_hash = _hash_payload(payload)
        event_bundles.append(
            NotificationBundle(
                store_id=context.store_id,
                run_id=context.run_id,
                alert_type="price_drop",
                deduplication_key=f"price-drop:{context.store_id}:{context.run_id}:{payload_hash[:20]}",
                payload_hash=payload_hash,
                reason=f"{len(drops)} bajas que superan el umbral inteligente",
                messages=(
                    build_price_drops_message(
                        store_name=context.store_name,
                        items=drops,
                        min_drop_pct=context.min_drop_pct,
                        min_drop_amount=context.min_drop_amount,
                    ),
                ),
                product_id=int(drops[0].product.id),
                price=drops[0].item.current_price,
            )
        )
        reasons.append(f"{len(drops)} bajas relevantes")

    if context.alert_price_increases:
        increases = _qualifying_increases(items)[: context.max_change_items]
        if increases:
            payload = [
                {
                    "product_id": int(saved.product.id),
                    "previous": saved.previous_price,
                    "current": saved.item.current_price,
                }
                for saved in increases
            ]
            payload_hash = _hash_payload(payload)
            event_bundles.append(
                NotificationBundle(
                    store_id=context.store_id,
                    run_id=context.run_id,
                    alert_type="price_increase",
                    deduplication_key=f"price-increase:{context.store_id}:{context.run_id}:{payload_hash[:20]}",
                    payload_hash=payload_hash,
                    reason=f"{len(increases)} alzas observadas",
                    messages=(
                        build_price_increases_message(
                            store_name=context.store_name,
                            items=increases,
                        ),
                    ),
                    product_id=int(increases[0].product.id),
                    price=increases[0].item.current_price,
                )
            )
            reasons.append(f"{len(increases)} alzas")

    # En un catálogo recién incorporado todos los productos son nuevos. Por eso
    # el aviso se habilita solo si existe una ejecución histórica comparable.
    if context.alert_new_products and context.previous_product_count:
        new_items = sorted(
            (saved for saved in items if saved.is_new),
            key=lambda saved: saved.item.name.casefold(),
        )[: context.max_change_items]
        if new_items:
            payload = [int(saved.product.id) for saved in new_items]
            payload_hash = _hash_payload(payload)
            event_bundles.append(
                NotificationBundle(
                    store_id=context.store_id,
                    run_id=context.run_id,
                    alert_type="new_product",
                    deduplication_key=f"new-products:{context.store_id}:{context.run_id}:{payload_hash[:20]}",
                    payload_hash=payload_hash,
                    reason=f"{len(new_items)} productos nuevos",
                    messages=(
                        build_new_products_message(
                            store_name=context.store_name,
                            items=new_items,
                        ),
                    ),
                    product_id=int(new_items[0].product.id),
                    price=new_items[0].item.current_price,
                )
            )
            reasons.append(f"{len(new_items)} productos nuevos")

    incident_payload = _incident_payload(analysis)
    has_incident = (
        stats.health_status != "HEALTHY"
        or stats.sections_failed > 0
        or stats.structural_warnings > 0
    )
    if has_incident:
        payload_hash = _hash_payload(incident_payload)
        health_transition = (
            stats.health_status != "HEALTHY"
            and context.previous_health_status != stats.health_status
        )
        if health_transition or _incident_is_due(
            payload_hash=payload_hash,
            last_alert=context.last_incident_alert,
            now=now,
        ):
            event_bundles.append(
                NotificationBundle(
                    store_id=context.store_id,
                    run_id=context.run_id,
                    alert_type="collector_incident",
                    deduplication_key=f"collector-incident:{context.store_id}:{context.run_id}:{payload_hash[:20]}",
                    payload_hash=payload_hash,
                    reason=f"collector {stats.health_status}",
                    messages=(
                        build_incident_message(
                            store_name=context.store_name,
                            analysis=analysis,
                            recovery=False,
                        ),
                    ),
                )
            )
            reasons.append(f"collector {stats.health_status}")
    elif context.previous_health_status and context.previous_health_status != "HEALTHY":
        payload_hash = _hash_payload(
            {
                "previous": context.previous_health_status,
                "current": stats.health_status,
            }
        )
        event_bundles.append(
            NotificationBundle(
                store_id=context.store_id,
                run_id=context.run_id,
                alert_type="collector_recovery",
                deduplication_key=f"collector-recovery:{context.store_id}:{context.run_id}",
                payload_hash=payload_hash,
                reason=f"recuperación desde {context.previous_health_status}",
                messages=(
                    build_incident_message(
                        store_name=context.store_name,
                        analysis=analysis,
                        recovery=True,
                    ),
                ),
            )
        )
        reasons.append("collector recuperado")

    fingerprint = ranking_fingerprint(items, limit=context.report_limit)
    ranking_due, ranking_reason = _ranking_is_due(
        fingerprint=fingerprint,
        last_alert=context.last_ranking_alert,
        interval_hours=context.digest_interval_hours,
        now=now,
    )
    if ranking_due:
        ranking_messages = build_ranking_messages(
            store_name=context.store_name,
            items=items,
            report_limit=context.report_limit,
        )
        if ranking_messages:
            event_bundles.append(
                NotificationBundle(
                    store_id=context.store_id,
                    run_id=context.run_id,
                    alert_type="ranking_digest",
                    deduplication_key=f"ranking-digest:{context.store_id}:{context.run_id}:{fingerprint[:20]}",
                    payload_hash=fingerprint,
                    reason=ranking_reason,
                    messages=tuple(ranking_messages),
                )
            )
            reasons.append(ranking_reason)

    if not event_bundles:
        return []

    summary_hash = _hash_payload(
        {
            "run_id": context.run_id,
            "reasons": reasons,
            "health": stats.health_status,
            "drops": len(drops),
        }
    )
    summary = NotificationBundle(
        store_id=context.store_id,
        run_id=context.run_id,
        alert_type="smart_summary",
        deduplication_key=f"smart-summary:{context.store_id}:{context.run_id}",
        payload_hash=summary_hash,
        reason="; ".join(reasons),
        messages=(
            build_smart_summary_message(
                store_name=context.store_name,
                analysis=analysis,
                reasons=reasons,
                qualifying_drops=len(drops),
                min_drop_pct=context.min_drop_pct,
                min_drop_amount=context.min_drop_amount,
                digest_interval_hours=context.digest_interval_hours,
            ),
        ),
    )
    return [summary, *event_bundles]
