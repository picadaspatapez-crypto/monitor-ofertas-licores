from __future__ import annotations

import argparse
import os

from app.database import create_database
from app.search.engine import search_products
from app.search.formatting import format_clp, format_datetime_cl


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Buscar productos en el catálogo unificado.")
    parser.add_argument("query", nargs="+", help="Nombre, marca, variante o volumen.")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--max-age-hours", type=int, default=72)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("Falta la variable obligatoria: DATABASE_URL")

    engine, SessionLocal = create_database(database_url)
    try:
        with SessionLocal() as session:
            results = search_products(
                session,
                " ".join(args.query),
                limit=args.limit,
                max_age_hours=args.max_age_hours,
            )
        if not results:
            print("No se encontraron coincidencias.")
            return 1
        for index, result in enumerate(results, 1):
            print(f"{index}. {result.canonical_name} · coincidencia {result.score * 100:.0f}%")
            for offer in result.offers:
                print(
                    f"   {offer.store_name}: {format_clp(offer.price)} "
                    f"· actualizado {format_datetime_cl(offer.last_seen_at)}"
                )
                print(f"   {offer.url}")
            if result.runner_up:
                print(
                    f"   Mejor: {result.winner.store_name}; ahorro "
                    f"{format_clp(result.saving_clp)} ({result.saving_pct * 100:.1f}%)"
                )
            print()
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
