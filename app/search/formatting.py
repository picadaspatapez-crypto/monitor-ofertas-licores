from __future__ import annotations

from datetime import datetime

from app.search.engine import SearchResult


def format_clp(value: int) -> str:
    return "$" + f"{int(value):,}".replace(",", ".")


def format_datetime_cl(value: datetime) -> str:
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
            }
            for offer in result.offers
        ],
    }
