from __future__ import annotations

from app.analyzers.comparison import ComparisonAnalysis, PriceComparison
from app.reports.telegram import clp


ITEMS_PER_MESSAGE = 10


def _confidence_text(value: float) -> str:
    return f"{value:.0%}"


def _comparison_lines(position: int, comparison: PriceComparison) -> list[str]:
    winner = comparison.winner
    runner_up = comparison.runner_up
    if winner is None or runner_up is None:
        return []
    lines = [f"{position}. {comparison.canonical_name}"]
    for offer_index, offer in enumerate(comparison.offers):
        prefix = "🥇" if offer_index == 0 else f"{offer_index + 1}."
        lines.append(f"{prefix} {offer.store_name}: {clp(offer.price)}")
    lines.extend(
        [
            f"Ahorro: {clp(comparison.saving_clp)} ({comparison.saving_pct:.1%}) frente al segundo",
            f"Confianza del match: {_confidence_text(comparison.confidence)}",
            f"Comprar más barato: {winner.url}",
        ]
    )
    if len(comparison.offers) > 2:
        most_expensive = comparison.offers[-1]
        total_saving = most_expensive.price - winner.price
        total_pct = total_saving / most_expensive.price if most_expensive.price else 0.0
        lines.insert(
            -2,
            f"Ahorro frente al más caro: {clp(total_saving)} ({total_pct:.1%})",
        )
    return lines


def build_comparison_summary_message(analysis: ComparisonAnalysis) -> str:
    return "\n".join(
        [
            "🛒 Comparador entre tiendas",
            "",
            f"📦 Publicaciones revisadas: {analysis.current_products}",
            f"🧩 Grupos maestros: {analysis.master_groups}",
            f"✅ Productos equivalentes verificados: {analysis.verified_matches}",
            f"💰 Oportunidades con diferencia de precio: {len(analysis.opportunities)}",
            f"🔄 Cambios de tienda ganadora: {len(analysis.winner_changes)}",
            f"🤝 Empates de precio: {analysis.ties}",
            f"🛡️ Grupos excluidos por baja confianza: {analysis.unverified_groups}",
            "",
            "Solo se comparan productos con volumen verificado y variante compatible.",
            "Packs, cajas y formatos ambiguos quedan fuera del ranking automático.",
        ]
    )


def build_comparison_ranking_messages(
    analysis: ComparisonAnalysis,
    *,
    limit: int = 20,
) -> list[str]:
    selected = list(analysis.opportunities[: max(1, limit)])
    messages: list[str] = []
    for start in range(0, len(selected), ITEMS_PER_MESSAGE):
        group = selected[start : start + ITEMS_PER_MESSAGE]
        lines = [
            f"🏷️ Mejores diferencias {start + 1}-{start + len(group)} de {len(selected)}",
            "",
        ]
        for position, comparison in enumerate(group, start=start + 1):
            lines.extend(_comparison_lines(position, comparison))
            lines.append("")
        messages.append("\n".join(lines).rstrip())
    return messages


def build_winner_changes_message(
    analysis: ComparisonAnalysis,
    *,
    limit: int = 10,
) -> str | None:
    selected = list(analysis.winner_changes[: max(1, limit)])
    if not selected:
        return None
    lines = ["🔄 Cambió la tienda más barata", ""]
    for comparison in selected:
        winner = comparison.winner
        if winner is None:
            continue
        lines.extend(
            [
                f"• {comparison.canonical_name}",
                f"  Antes: {comparison.previous_winner_store_name or 'otra tienda'}",
                f"  Ahora: {winner.store_name} a {clp(winner.price)}",
                f"  Ventaja actual: {clp(comparison.saving_clp)} ({comparison.saving_pct:.1%})",
                f"  {winner.url}",
                "",
            ]
        )
    return "\n".join(lines).rstrip()
