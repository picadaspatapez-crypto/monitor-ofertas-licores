import os
from dataclasses import dataclass


def _required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Falta la variable obligatoria: {name}")
    return value


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    telegram_chat_id: str
    database_url: str
    max_product_price: int
    total_budget: int
    max_units_per_product: int
    min_target_margin: float
    delivery_commune: str

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            telegram_bot_token=_required("TELEGRAM_BOT_TOKEN"),
            telegram_chat_id=_required("TELEGRAM_CHAT_ID"),
            database_url=_required("DATABASE_URL"),
            max_product_price=int(os.getenv("MAX_PRODUCT_PRICE", "30000")),
            total_budget=int(os.getenv("TOTAL_BUDGET", "100000")),
            max_units_per_product=int(os.getenv("MAX_UNITS_PER_PRODUCT", "3")),
            min_target_margin=float(os.getenv("MIN_TARGET_MARGIN", "0.20")),
            delivery_commune=os.getenv("DELIVERY_COMMUNE", "La Reina"),
        )
