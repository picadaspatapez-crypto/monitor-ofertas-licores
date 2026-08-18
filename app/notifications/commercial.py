from __future__ import annotations

from dataclasses import dataclass
import hashlib

from app.analyzers.comparison import ComparisonAnalysis, PriceComparison
from app.notifications.policy import NotificationBundle
from app.reports.commercial import build_commercial_signal_message


@dataclass(frozen=True)
class CommercialAlertContext:
    enabled: bool = True
    minimum_score: float = 85.0
    rare_frequency_threshold: float = 0.15
    minimum_history_observations: int = 6
    limit: int = 8


def _is_new_drop_into_signal(item: PriceComparison) -> bool:
    if item.winner is None:
        return False
    previous = item.winner_previous_price
    return previous is not None and int(previous) > int(item.winner.price)


def build_commercial_notification_bundles(
    analysis: ComparisonAnalysis,
    *,
    context: CommercialAlertContext,
) -> list[NotificationBundle]:
    if not context.enabled:
        return []

    selected: list[PriceComparison] = []
    for item in analysis.opportunities:
        if item.winner is None:
            continue
        if item.price_event == "NEW_HISTORICAL_MIN":
            selected.append(item)
            continue
        if (
            item.price_event == "RARE_OFFER"
            and item.opportunity_score >= context.minimum_score
            and item.history_observations_90d >= context.minimum_history_observations
            and item.rarity_frequency_90d is not None
            and item.rarity_frequency_90d <= context.rare_frequency_threshold
            and _is_new_drop_into_signal(item)
        ):
            selected.append(item)

    event_priority = {"NEW_HISTORICAL_MIN": 0, "RARE_OFFER": 1}
    selected.sort(
        key=lambda item: (
            event_priority.get(item.price_event, 9),
            -item.opportunity_score,
            -item.historical_gap_pct,
            -item.saving_pct,
        )
    )

    bundles: list[NotificationBundle] = []
    for item in selected[: max(1, int(context.limit))]:
        winner = item.winner
        assert winner is not None
        kind = "historical-min" if item.price_event == "NEW_HISTORICAL_MIN" else "rare-offer"
        # Clave estable entre runs: el mismo producto al mismo precio no vuelve a
        # notificarse aunque el digest general cambie.
        dedup = f"commercial:{kind}:{item.master_product_id}:{winner.price}"
        message = build_commercial_signal_message(item)
        if not message:
            continue
        bundles.append(
            NotificationBundle(
                store_id=winner.store_id,
                run_id=None,
                alert_type=(
                    "commercial_new_historical_min"
                    if item.price_event == "NEW_HISTORICAL_MIN"
                    else "commercial_rare_offer"
                ),
                deduplication_key=dedup,
                payload_hash=hashlib.sha256(message.encode("utf-8")).hexdigest(),
                reason=item.intelligence_reason,
                messages=(message,),
                product_id=winner.product_id,
                price=winner.price,
            )
        )
    return bundles
