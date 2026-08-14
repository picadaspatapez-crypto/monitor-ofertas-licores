from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone

from sqlalchemy import select

from app.database import create_database
from app.intelligence.canonical import register_alias
from app.matching.rules import add_matching_rule
from app.models import MatchingReview, Product


def resolve_review(session, *, review_id: int, decision: str, notes: str | None = None) -> MatchingReview:
    row = session.get(MatchingReview, int(review_id))
    if row is None:
        raise ValueError(f"No existe review #{review_id}")
    left = session.get(Product, int(row.left_product_id))
    right = session.get(Product, int(row.right_product_id))
    if left is None or right is None:
        raise ValueError("El par ya no tiene ambas publicaciones disponibles")
    decision = decision.strip().casefold()
    if decision not in {"confirm", "reject"}:
        raise ValueError("decision debe ser confirm o reject")
    if decision == "confirm":
        add_matching_rule(session, rule_type="equivalence", left=left.name, right=right.name, notes=notes)
        row.status = "confirmed"
        if left.master_product_id:
            register_alias(session, master_product_id=int(left.master_product_id), alias_text=right.name, source="manual_review", confirmed=True)
        if right.master_product_id:
            register_alias(session, master_product_id=int(right.master_product_id), alias_text=left.name, source="manual_review", confirmed=True)
    else:
        add_matching_rule(session, rule_type="exclusion", left=left.name, right=right.name, notes=notes)
        row.status = "rejected"
    row.resolution_notes = notes
    row.resolved_at = datetime.now(timezone.utc)
    session.flush()
    return row


def _main() -> int:
    parser = argparse.ArgumentParser(description="Revisa candidatos ambiguos de Matching 2.0")
    sub = parser.add_subparsers(dest="command", required=True)
    list_cmd = sub.add_parser("list")
    list_cmd.add_argument("--limit", type=int, default=20)
    resolve_cmd = sub.add_parser("resolve")
    resolve_cmd.add_argument("review_id", type=int)
    resolve_cmd.add_argument("decision", choices=("confirm", "reject"))
    resolve_cmd.add_argument("--notes", default=None)
    args = parser.parse_args()

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("Falta DATABASE_URL")
    engine, SessionLocal = create_database(database_url)
    try:
        with SessionLocal() as session:
            if args.command == "list":
                rows = list(session.scalars(
                    select(MatchingReview)
                    .where(MatchingReview.status == "pending")
                    .order_by(MatchingReview.confidence.desc(), MatchingReview.id)
                    .limit(max(1, min(args.limit, 100)))
                ))
                for row in rows:
                    left = session.get(Product, row.left_product_id)
                    right = session.get(Product, row.right_product_id)
                    print(f"#{row.id} {row.confidence:.3f} · {left.store if left else '?'}: {left.name if left else '?'}")
                    print(f"   vs {right.store if right else '?'}: {right.name if right else '?'}")
                    print(f"   {row.proposed_method}: {row.reason or '-'}")
                if not rows:
                    print("No hay matches pendientes de revisión.")
            else:
                row = resolve_review(session, review_id=args.review_id, decision=args.decision, notes=args.notes)
                session.commit()
                print(f"Review #{row.id}: {row.status}")
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
