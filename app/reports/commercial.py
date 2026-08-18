from __future__ import annotations

from app.analyzers.comparison import PriceComparison
from app.reports.telegram import clp


def event_label(event: str) -> str:
    return {
        "NEW_HISTORICAL_MIN": "🚨 Nuevo mínimo histórico",
        "AT_HISTORICAL_MIN": "🏆 En mínimo histórico",
        "NEAR_HISTORICAL_MIN": "📉 Cerca del mínimo histórico",
        "RARE_OFFER": "🔥 Oferta poco frecuente",
        "MARKET_LEADER": "🥇 Líder de mercado",
    }.get(str(event or "NORMAL"), "🧠 Inteligencia comercial")


def build_commercial_signal_message(comparison: PriceComparison) -> str:
    winner = comparison.winner
    if winner is None:
        return ""
    lines = [
        event_label(comparison.price_event),
        "",
        comparison.canonical_name,
        f"{winner.store_name}: {clp(winner.price)}",
    ]
    if comparison.winner_previous_price and comparison.winner_previous_price != winner.price:
        lines.append(f"Precio anterior en esa publicación: {clp(comparison.winner_previous_price)}")
    if comparison.previous_historical_min:
        lines.append(f"Mínimo histórico anterior: {clp(comparison.previous_historical_min)}")
    if comparison.historical_gap_clp > 0:
        lines.append(
            f"Nuevo piso: {clp(comparison.historical_gap_clp)} "
            f"({comparison.historical_gap_pct:.1%}) bajo el anterior"
        )
    if comparison.runner_up is not None and comparison.saving_clp > 0:
        lines.append(
            f"Segundo mejor: {comparison.runner_up.store_name} {clp(comparison.runner_up.price)}"
        )
        lines.append(
            f"Ventaja de mercado: {clp(comparison.saving_clp)} ({comparison.saving_pct:.1%})"
        )
    if comparison.history_avg_90d:
        delta = (winner.price - comparison.history_avg_90d) / comparison.history_avg_90d
        lines.append(
            f"Vs. promedio 90 días: {delta:+.1%} "
            f"(promedio {clp(round(comparison.history_avg_90d))})"
        )
    if comparison.rarity_frequency_90d is not None and comparison.history_observations_90d:
        lines.append(
            f"Zona de piso observada: {comparison.rarity_frequency_90d:.0%} "
            f"de {comparison.history_observations_90d} observaciones"
        )
    lines.extend(
        [
            f"🔥 Opportunity Score v2: {comparison.opportunity_score:.0f}/100 · {comparison.opportunity_classification}",
            f"Motivo: {comparison.intelligence_reason}",
            winner.url,
        ]
    )
    return "\n".join(lines)


def build_commercial_radar_message(items: list[PriceComparison], *, title: str = "Radar comercial") -> str:
    if not items:
        return "🧠 No hay señales comerciales destacadas en este momento."
    lines = [f"🧠 {title}", ""]
    for index, item in enumerate(items, start=1):
        winner = item.winner
        if winner is None:
            continue
        lines.extend(
            [
                f"{index}. {item.canonical_name}",
                f"{event_label(item.price_event)} · {winner.store_name} {clp(winner.price)}",
                f"Score v2: {item.opportunity_score:.0f}/100 · ahorro {item.saving_pct:.1%}",
            ]
        )
        if item.rarity_frequency_90d is not None and item.history_observations_90d:
            lines.append(
                f"Frecuencia cerca del piso: {item.rarity_frequency_90d:.0%} / {item.history_observations_90d} obs."
            )
        lines.append("")
    return "\n".join(lines).rstrip()[:4000]
