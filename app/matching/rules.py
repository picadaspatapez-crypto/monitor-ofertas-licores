from __future__ import annotations

import argparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import create_database
from app.matching import build_product_signature
from app.models import MatchingRule


def rule_key(value: str) -> str:
    signature = build_product_signature(value)
    return signature.comparison_key


def canonical_pair(left: str, right: str) -> tuple[str, str]:
    left_key, right_key = rule_key(left), rule_key(right)
    return tuple(sorted((left_key, right_key)))


def add_matching_rule(
    session: Session,
    *,
    rule_type: str,
    left: str,
    right: str,
    notes: str | None = None,
) -> MatchingRule:
    normalized_type = rule_type.strip().casefold()
    if normalized_type not in {"equivalence", "exclusion"}:
        raise ValueError("rule_type debe ser equivalence o exclusion")
    left_key, right_key = canonical_pair(left, right)
    rule = session.scalar(
        select(MatchingRule).where(
            MatchingRule.rule_type == normalized_type,
            MatchingRule.left_key == left_key,
            MatchingRule.right_key == right_key,
        )
    )
    if rule is None:
        rule = MatchingRule(
            rule_type=normalized_type,
            left_key=left_key,
            right_key=right_key,
            notes=notes,
            is_active=True,
        )
        session.add(rule)
    else:
        rule.is_active = True
        rule.notes = notes or rule.notes
    session.flush()
    return rule


def _main() -> int:
    parser = argparse.ArgumentParser(description="Administra reglas manuales de matching")
    parser.add_argument("rule_type", choices=("equivalence", "exclusion"))
    parser.add_argument("left")
    parser.add_argument("right")
    parser.add_argument("--notes", default=None)
    args = parser.parse_args()

    import os

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("Falta DATABASE_URL")
    engine, SessionLocal = create_database(database_url)
    try:
        with SessionLocal() as session:
            rule = add_matching_rule(
                session,
                rule_type=args.rule_type,
                left=args.left,
                right=args.right,
                notes=args.notes,
            )
            session.commit()
            print(f"Regla #{rule.id} guardada: {rule.rule_type} · {rule.left_key} ↔ {rule.right_key}")
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
