from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.analyzers.comparison import ComparisonAnalysis
from app.models import Alert
from app.notifications.policy import NotificationBundle
from app.reports.comparison import (
    build_comparison_ranking_messages,
    build_comparison_summary_message,
    build_winner_changes_message,
)


@dataclass(frozen=True)
class ComparisonAlertContext:
    run_ids: tuple[int, ...]
    digest_interval_hours: int
    report_limit: int
    winner_change_limit: int
    last_digest_alert: Alert | None = None
    now: datetime | None = None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _hash_payload(payload: object) -> str:
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def comparison_fingerprint(
    analysis: ComparisonAnalysis,
    *,
    limit: int,
) -> str:
    payload = [
        {
            "master_id": item.master_product_id,
            "winner_store_id": item.winner.store_id if item.winner else None,
            "winner_price": item.winner.price if item.winner else None,
            "runner_up_store_id": item.runner_up.store_id if item.runner_up else None,
            "runner_up_price": item.runner_up.price if item.runner_up else None,
            "saving_clp": item.saving_clp,
            "confidence": round(item.confidence, 4),
            "opportunity_score": round(item.opportunity_score, 1),
        }
        for item in analysis.opportunities[: max(1, limit)]
    ]
    return _hash_payload(payload)


def _alert_age(alert: Alert | None, now: datetime) -> timedelta | None:
    if alert is None or alert.sent_at is None:
        return None
    sent_at = alert.sent_at
    if sent_at.tzinfo is None:
        sent_at = sent_at.replace(tzinfo=timezone.utc)
    return now - sent_at


def build_comparison_notification_bundles(
    *,
    analysis: ComparisonAnalysis,
    context: ComparisonAlertContext,
) -> list[NotificationBundle]:
    now = context.now or _utcnow()
    run_key = "-".join(str(run_id) for run_id in sorted(context.run_ids)) or "none"
    bundles: list[NotificationBundle] = []

    winner_message = build_winner_changes_message(
        analysis,
        limit=context.winner_change_limit,
    )
    if winner_message:
        winner_payload = [
            {
                "master_id": item.master_product_id,
                "previous_store": item.previous_winner_store_id,
                "current_store": item.winner.store_id if item.winner else None,
                "price": item.winner.price if item.winner else None,
            }
            for item in analysis.winner_changes[: context.winner_change_limit]
        ]
        winner_hash = _hash_payload(winner_payload)
        first = analysis.winner_changes[0]
        bundles.append(
            NotificationBundle(
                store_id=None,
                run_id=None,
                alert_type="cross_store_winner_change",
                deduplication_key=f"cross-store-winner:{run_key}:{winner_hash[:20]}",
                payload_hash=winner_hash,
                reason=f"{len(winner_payload)} productos cambiaron de tienda ganadora",
                messages=(winner_message,),
                product_id=first.winner.product_id if first.winner else None,
                price=first.winner.price if first.winner else None,
            )
        )

    fingerprint = comparison_fingerprint(analysis, limit=context.report_limit)
    last = context.last_digest_alert
    age = _alert_age(last, now)
    due_reason: str | None = None
    if last is None:
        due_reason = "primer comparador entre tiendas"
    elif last.payload_hash != fingerprint:
        due_reason = "cambió el ranking comparativo"
    elif age is None or age >= timedelta(hours=max(1, context.digest_interval_hours)):
        due_reason = f"refresco comparativo de {max(1, context.digest_interval_hours)} horas"

    if due_reason:
        messages = [build_comparison_summary_message(analysis)]
        messages.extend(
            build_comparison_ranking_messages(
                analysis,
                limit=context.report_limit,
            )
        )
        bundles.append(
            NotificationBundle(
                store_id=None,
                run_id=None,
                alert_type="cross_store_digest",
                deduplication_key=f"cross-store-digest:{run_key}:{fingerprint[:20]}",
                payload_hash=fingerprint,
                reason=due_reason,
                messages=tuple(messages),
                product_id=(
                    analysis.opportunities[0].winner.product_id
                    if analysis.opportunities and analysis.opportunities[0].winner
                    else None
                ),
                price=(
                    analysis.opportunities[0].winner.price
                    if analysis.opportunities and analysis.opportunities[0].winner
                    else None
                ),
            )
        )

    return bundles
