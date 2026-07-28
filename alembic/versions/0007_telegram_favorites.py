"""Add Telegram favorites and personalized alert queue.

Revision ID: 0007_telegram_favorites
Revises: 0006_telegram_bot_state
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0007_telegram_favorites"
down_revision = "0006_telegram_bot_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())

    if "telegram_favorites" not in tables:
        op.create_table(
            "telegram_favorites",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("chat_id", sa.BigInteger(), nullable=False),
            sa.Column("master_product_id", sa.Integer(), nullable=False),
            sa.Column("target_price", sa.Integer(), nullable=True),
            sa.Column("notify_on_price_drop", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("notify_on_new_store", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("notify_on_winner_change", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("notify_on_back_in_stock", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("last_best_price", sa.Integer(), nullable=True),
            sa.Column("last_winner_store", sa.String(length=120), nullable=True),
            sa.Column("last_store_names", sa.JSON(), nullable=True),
            sa.Column("was_available", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("last_evaluated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["master_product_id"], ["master_products.id"]),
            sa.UniqueConstraint(
                "chat_id",
                "master_product_id",
                name="uq_telegram_favorite_chat_master",
            ),
        )
        op.create_index("ix_telegram_favorites_chat_id", "telegram_favorites", ["chat_id"])
        op.create_index(
            "ix_telegram_favorites_master_product_id",
            "telegram_favorites",
            ["master_product_id"],
        )
        op.create_index("ix_telegram_favorites_is_active", "telegram_favorites", ["is_active"])

    tables = set(inspect(bind).get_table_names())
    if "favorite_alerts" not in tables:
        op.create_table(
            "favorite_alerts",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("favorite_id", sa.Integer(), nullable=False),
            sa.Column("chat_id", sa.BigInteger(), nullable=False),
            sa.Column("event_types", sa.JSON(), nullable=False),
            sa.Column("run_ids", sa.JSON(), nullable=True),
            sa.Column("status", sa.String(length=30), nullable=False, server_default="pending"),
            sa.Column("deduplication_key", sa.String(length=255), nullable=False),
            sa.Column("payload_hash", sa.String(length=64), nullable=False),
            sa.Column("message", sa.Text(), nullable=False),
            sa.Column("current_price", sa.Integer(), nullable=True),
            sa.Column("winner_store", sa.String(length=120), nullable=True),
            sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["favorite_id"], ["telegram_favorites.id"]),
            sa.UniqueConstraint("deduplication_key", name="uq_favorite_alert_deduplication_key"),
        )
        op.create_index("ix_favorite_alerts_favorite_id", "favorite_alerts", ["favorite_id"])
        op.create_index("ix_favorite_alerts_chat_id", "favorite_alerts", ["chat_id"])
        op.create_index("ix_favorite_alerts_status", "favorite_alerts", ["status"])
        op.create_index("ix_favorite_alerts_payload_hash", "favorite_alerts", ["payload_hash"])


def downgrade() -> None:
    # Conservador: no borra favoritos ni historial de avisos al revertir.
    pass
