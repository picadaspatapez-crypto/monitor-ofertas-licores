from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.search.engine import SearchResult


def format_clp(value: int) -> str:
    return "$" + f"{int(value):,}".replace(",", ".")


def format_datetime_cl(value: datetime) -> str:
    try:
        return value.astimezone(ZoneInfo("America/Santiago")).strftime("%d-%m-%Y %H:%M")
    except Exception:
        return value.astimezone().strftime("%d-%m-%Y %H:%M")


def result_to_dict(result: SearchResult) -> dict:
    return {
        "master_product_id": result.master_product_id,
        "canonical_name": result.canonical_name,
        "brand": result.brand,
        "variant": result.variant,
        "volume_ml": result.volume_ml,
        "package_quantity": result.package_quantity,
        "score_percent": round(result.score * 100, 1),
        "saving_clp": result.saving_clp,
        "saving_pct": round(result.saving_pct * 100, 1),
        "winner_store": result.winner.store_name,
        "min_30d": result.min_30d,
        "avg_30d": result.avg_30d,
        "min_90d": result.min_90d,
        "avg_90d": result.avg_90d,
        "historical_min": result.historical_min,
        "days_at_current_price": result.days_at_current_price,
        "opportunity_score": result.opportunity_score,
        "opportunity_classification": result.opportunity_classification,
        "price_mode": result.price_mode,
        "public_reference_price": result.public_reference_price,
        "personal_advantage_clp": result.personal_advantage_clp,
        "personal_advantage_pct": round(result.personal_advantage_pct * 100, 1),
        "offers": [
            {
                "product_id": offer.product_id,
                "store_name": offer.store_name,
                "product_name": offer.product_name,
                "price": offer.price,
                "regular_price": offer.regular_price,
                "discount_pct": round(offer.discount_pct * 100, 1),
                "url": offer.url,
                "last_seen_at": offer.last_seen_at.isoformat(),
                "price_type": offer.price_type,
                "audience_key": offer.audience_key,
                "eligibility_required": offer.eligibility_required,
                "is_public_market": offer.is_public_market,
            }
            for offer in result.offers
        ],
    }
