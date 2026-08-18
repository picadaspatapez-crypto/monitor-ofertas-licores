from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CommercialComponents:
    """Componentes del Opportunity Score v2.

    Los valores se expresan en el rango 0..1. La rareza sólo debe recibir peso
    cuando existe suficiente historia; el caller es responsable de degradarla a
    cero cuando la muestra es insuficiente.
    """

    market_saving: float
    history_position: float
    rarity: float
    match_confidence: float
    freshness: float
    scarcity: float


@dataclass(frozen=True)
class CommercialSignal:
    event: str
    reason: str
    historical_gap_clp: int = 0
    historical_gap_pct: float = 0.0


def _unit(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def commercial_opportunity_score(components: CommercialComponents) -> float:
    """Opportunity Score v2, orientado a precio realmente excepcional.

    La versión 5.8 reduce ligeramente el peso del ahorro entre tiendas y del
    histórico para reservar 15 % a la rareza observada del precio. Matching y
    frescura siguen teniendo suficiente peso para impedir que un dato dudoso
    parezca una gran oportunidad.
    """

    value = 100.0 * (
        0.30 * _unit(components.market_saving)
        + 0.25 * _unit(components.history_position)
        + 0.15 * _unit(components.rarity)
        + 0.15 * _unit(components.match_confidence)
        + 0.10 * _unit(components.freshness)
        + 0.05 * _unit(components.scarcity)
    )
    return round(value, 1)


def rarity_score(*, observations: int, at_or_below_current: int, minimum_observations: int = 6) -> tuple[float, float | None]:
    """Devuelve (score, frecuencia) para un precio actual.

    ``frecuencia`` es la fracción de observaciones históricas previas que
    estuvieron al mismo precio o más baratas. Una frecuencia pequeña implica
    que el precio actual ha sido poco frecuente. Con poca historia el score se
    neutraliza para evitar declarar rareza con una muestra débil.
    """

    observations = max(0, int(observations))
    at_or_below_current = max(0, min(int(at_or_below_current), observations))
    if observations <= 0:
        return 0.0, None
    frequency = at_or_below_current / observations
    if observations < max(1, int(minimum_observations)):
        return 0.0, frequency
    return round(_unit(1.0 - frequency), 4), frequency


def classify_commercial_signal(
    *,
    current_price: int,
    previous_historical_min: int | None,
    historical_min: int | None,
    observations_90d: int,
    rarity_frequency_90d: float | None,
    rarity_score_value: float,
    saving_pct: float,
    minimum_observations: int = 6,
    rare_frequency_threshold: float = 0.15,
    near_historical_min_pct: float = 0.03,
) -> CommercialSignal:
    current = max(0, int(current_price))
    previous = int(previous_historical_min) if previous_historical_min else None
    historical = int(historical_min) if historical_min else None

    if previous and current > 0 and current < previous:
        gap = previous - current
        pct = gap / previous if previous > 0 else 0.0
        return CommercialSignal(
            event="NEW_HISTORICAL_MIN",
            reason=(
                f"nuevo mínimo histórico: ${current:,} queda ${gap:,} "
                f"({pct:.1%}) bajo el mínimo anterior de ${previous:,}"
            ).replace(",", "."),
            historical_gap_clp=gap,
            historical_gap_pct=pct,
        )

    enough_history = observations_90d >= max(1, int(minimum_observations))
    if (
        enough_history
        and rarity_frequency_90d is not None
        and rarity_frequency_90d <= max(0.0, min(1.0, rare_frequency_threshold))
        and rarity_score_value >= 0.70
    ):
        return CommercialSignal(
            event="RARE_OFFER",
            reason=(
                f"oferta poco frecuente: sólo {rarity_frequency_90d:.0%} de "
                f"{observations_90d} observaciones de 90 días estuvieron en la zona "
                f"del mínimo (hasta 5% sobre el piso)"
            ),
        )

    if historical and current > 0 and current <= historical:
        return CommercialSignal(
            event="AT_HISTORICAL_MIN",
            reason=f"precio actual iguala el mínimo histórico de ${historical:,}".replace(",", "."),
        )

    if historical and current > 0 and historical > 0:
        distance = (current - historical) / historical
        if 0 < distance <= max(0.0, near_historical_min_pct):
            return CommercialSignal(
                event="NEAR_HISTORICAL_MIN",
                reason=(
                    f"precio a {distance:.1%} del mínimo histórico de ${historical:,}"
                ).replace(",", "."),
            )

    if saving_pct >= 0.15:
        return CommercialSignal(
            event="MARKET_LEADER",
            reason=f"líder de mercado con {saving_pct:.1%} de ventaja frente al segundo precio",
        )

    return CommercialSignal(event="NORMAL", reason="sin señal comercial excepcional")
