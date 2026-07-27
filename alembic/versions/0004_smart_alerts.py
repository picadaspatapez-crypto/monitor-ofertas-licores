"""Prepare alert persistence for smart store-level notifications.

Revision ID: 0004_smart_alerts
Revises: 0003_scrape_run_observability
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0004_smart_alerts"
down_revision = "0003_scrape_run_observability"
branch_labels = None
depends_on = None


def _columns(bind, table: str) -> dict[str, dict]:
    return {column["name"]: column for column in inspect(bind).get_columns(table)}


def _index_names(bind, table: str) -> set[str]:
    return {index["name"] for index in inspect(bind).get_indexes(table)}


def _foreign_key_names(bind, table: str) -> set[str]:
    return {
        item["name"]
        for item in inspect(bind).get_foreign_keys(table)
        if item.get("name")
    }


def upgrade() -> None:
    bind = op.get_bind()
    columns = _columns(bind, "alerts")

    if "store_id" not in columns:
        op.add_column("alerts", sa.Column("store_id", sa.Integer(), nullable=True))
    if "scrape_run_id" not in columns:
        op.add_column(
            "alerts", sa.Column("scrape_run_id", sa.Integer(), nullable=True)
        )
    if "payload_hash" not in columns:
        op.add_column(
            "alerts", sa.Column("payload_hash", sa.String(length=64), nullable=True)
        )

    columns = _columns(bind, "alerts")
    if not columns["product_id"]["nullable"]:
        op.alter_column(
            "alerts",
            "product_id",
            existing_type=sa.Integer(),
            nullable=True,
        )
    if not columns["price"]["nullable"]:
        op.alter_column(
            "alerts",
            "price",
            existing_type=sa.Integer(),
            nullable=True,
        )

    foreign_keys = _foreign_key_names(bind, "alerts")
    if "fk_alerts_store_id_stores" not in foreign_keys:
        op.create_foreign_key(
            "fk_alerts_store_id_stores",
            "alerts",
            "stores",
            ["store_id"],
            ["id"],
        )
    if "fk_alerts_scrape_run_id_scrape_runs" not in foreign_keys:
        op.create_foreign_key(
            "fk_alerts_scrape_run_id_scrape_runs",
            "alerts",
            "scrape_runs",
            ["scrape_run_id"],
            ["id"],
        )

    indexes = _index_names(bind, "alerts")
    if "ix_alerts_store_id" not in indexes:
        op.create_index("ix_alerts_store_id", "alerts", ["store_id"])
    if "ix_alerts_scrape_run_id" not in indexes:
        op.create_index("ix_alerts_scrape_run_id", "alerts", ["scrape_run_id"])
    if "ix_alerts_payload_hash" not in indexes:
        op.create_index("ix_alerts_payload_hash", "alerts", ["payload_hash"])

    # Las alertas históricas de producto heredan la tienda para que las
    # consultas nuevas puedan considerar toda la tabla desde el primer deploy.
    bind.execute(
        sa.text(
            """
            UPDATE alerts AS a
            SET store_id = p.store_id
            FROM products AS p
            WHERE a.product_id = p.id
              AND a.store_id IS NULL
            """
        )
    )


def downgrade() -> None:
    # Conservador: no se eliminan columnas ni historial de alertas productivas.
    pass
