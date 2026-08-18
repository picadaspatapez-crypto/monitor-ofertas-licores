import os
from dataclasses import dataclass


def _required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Falta la variable obligatoria: {name}")
    return value


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().casefold()
    if value in {"1", "true", "yes", "si", "sí", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(
        f"Valor inválido para {name}: {raw!r}. Usa true/false."
    )


def _positive_int(name: str, default: int, *, minimum: int = 1) -> int:
    value = int(os.getenv(name, str(default)))
    if value < minimum:
        raise RuntimeError(f"{name} debe ser mayor o igual a {minimum}.")
    return value


def _non_negative_int(name: str, default: int) -> int:
    value = int(os.getenv(name, str(default)))
    if value < 0:
        raise RuntimeError(f"{name} no puede ser negativo.")
    return value



def _csv_env(name: str, default: str) -> tuple[str, ...]:
    raw = os.getenv(name, default)
    values = []
    for part in raw.split(","):
        value = part.strip().casefold()
        if value and value not in values:
            values.append(value)
    return tuple(values)


def _percentage(name: str, default: float) -> float:
    """Lee un porcentaje humano, por ejemplo 5 para representar 5 %."""
    value = float(os.getenv(name, str(default)))
    if value < 0 or value > 100:
        raise RuntimeError(f"{name} debe estar entre 0 y 100.")
    return value / 100.0


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    telegram_chat_id: str
    database_url: str
    total_budget: int
    max_units_per_product: int
    min_target_margin: float
    delivery_commune: str
    alert_min_drop_pct: float
    alert_min_drop_amount: int
    telegram_digest_interval_hours: int
    alert_new_products: bool
    alert_price_increases: bool
    telegram_change_limit: int
    telegram_report_limit: int
    cross_store_match_min_confidence: float
    telegram_comparison_limit: int
    telegram_winner_change_limit: int
    favorite_min_drop_clp: int
    favorite_alert_limit: int
    availability_missing_threshold: int
    weekly_health_report: bool
    weekly_health_interval_hours: int
    opportunity_report_limit: int
    personal_price_audiences: tuple[str, ...]
    personal_alerts_enabled: bool
    personal_alert_min_drop_pct: float
    personal_alert_min_drop_amount: int
    personal_alert_min_advantage_clp: int
    personal_alert_limit: int
    commercial_alerts_enabled: bool
    commercial_alert_min_score: int
    commercial_min_history_observations: int
    commercial_rare_frequency_threshold: float
    commercial_near_historical_min_pct: float
    commercial_alert_limit: int

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            telegram_bot_token=_required("TELEGRAM_BOT_TOKEN"),
            telegram_chat_id=_required("TELEGRAM_CHAT_ID"),
            database_url=_required("DATABASE_URL"),
            total_budget=int(os.getenv("TOTAL_BUDGET", "100000")),
            max_units_per_product=int(os.getenv("MAX_UNITS_PER_PRODUCT", "3")),
            min_target_margin=float(os.getenv("MIN_TARGET_MARGIN", "0.20")),
            delivery_commune=os.getenv("DELIVERY_COMMUNE", "La Reina"),
            alert_min_drop_pct=_percentage("ALERT_MIN_DROP_PERCENT", 5.0),
            alert_min_drop_amount=_non_negative_int("ALERT_MIN_DROP_CLP", 1000),
            telegram_digest_interval_hours=_positive_int(
                "TELEGRAM_DIGEST_INTERVAL_HOURS", 24
            ),
            alert_new_products=_bool_env("ALERT_NEW_PRODUCTS", False),
            alert_price_increases=_bool_env("ALERT_PRICE_INCREASES", False),
            telegram_change_limit=_positive_int("TELEGRAM_CHANGE_LIMIT", 10),
            telegram_report_limit=_positive_int("TELEGRAM_REPORT_LIMIT", 30),
            cross_store_match_min_confidence=_percentage(
                "CROSS_STORE_MATCH_MIN_CONFIDENCE_PERCENT", 86.0
            ),
            telegram_comparison_limit=_positive_int(
                "TELEGRAM_COMPARISON_LIMIT", 30
            ),
            telegram_winner_change_limit=_positive_int(
                "TELEGRAM_WINNER_CHANGE_LIMIT", 10
            ),
            favorite_min_drop_clp=_non_negative_int(
                "FAVORITE_MIN_DROP_CLP", 10
            ),
            favorite_alert_limit=_positive_int(
                "FAVORITE_ALERT_LIMIT", 20
            ),
            availability_missing_threshold=_positive_int(
                "AVAILABILITY_MISSING_THRESHOLD", 2
            ),
            weekly_health_report=_bool_env("WEEKLY_HEALTH_REPORT", True),
            weekly_health_interval_hours=_positive_int(
                "WEEKLY_HEALTH_INTERVAL_HOURS", 168
            ),
            opportunity_report_limit=_positive_int(
                "OPPORTUNITY_REPORT_LIMIT", 20
            ),
            personal_price_audiences=_csv_env(
                "PERSONAL_PRICE_AUDIENCES", "cav_member"
            ),
            personal_alerts_enabled=_bool_env(
                "PERSONAL_ALERTS_ENABLED", True
            ),
            personal_alert_min_drop_pct=_percentage(
                "PERSONAL_ALERT_MIN_DROP_PERCENT", 5.0
            ),
            personal_alert_min_drop_amount=_non_negative_int(
                "PERSONAL_ALERT_MIN_DROP_CLP", 1000
            ),
            personal_alert_min_advantage_clp=_non_negative_int(
                "PERSONAL_ALERT_MIN_ADVANTAGE_CLP", 1000
            ),
            personal_alert_limit=_positive_int(
                "PERSONAL_ALERT_LIMIT", 10
            ),
            commercial_alerts_enabled=_bool_env(
                "COMMERCIAL_ALERTS_ENABLED", True
            ),
            commercial_alert_min_score=_positive_int(
                "COMMERCIAL_ALERT_MIN_SCORE", 85
            ),
            commercial_min_history_observations=_positive_int(
                "COMMERCIAL_MIN_HISTORY_OBSERVATIONS", 6
            ),
            commercial_rare_frequency_threshold=_percentage(
                "COMMERCIAL_RARE_FREQUENCY_PERCENT", 15.0
            ),
            commercial_near_historical_min_pct=_percentage(
                "COMMERCIAL_NEAR_HISTORICAL_MIN_PERCENT", 3.0
            ),
            commercial_alert_limit=_positive_int(
                "COMMERCIAL_ALERT_LIMIT", 8
            ),
        )
