from __future__ import annotations

import os

from app.database import create_database
from app.search.catalog import refresh_search_catalog


def main() -> int:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("Falta la variable obligatoria: DATABASE_URL")
    engine, SessionLocal = create_database(database_url)
    try:
        with SessionLocal() as session:
            summary = refresh_search_catalog(session)
            session.commit()
        print(
            "Índice de búsqueda actualizado: "
            f"maestros={summary.masters_seen}, "
            f"modificados={summary.masters_updated}, "
            f"alias={summary.aliases_indexed}.",
            flush=True,
        )
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
