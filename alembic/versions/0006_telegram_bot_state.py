"""Persist Telegram long-polling state.

Revision ID: 0006_telegram_bot_state
Revises: 0005_search_catalog
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0006_telegram_bot_state"
down_revision = "0005_search_catalog"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "telegram_bot_state" not in inspector.get_table_names():
        op.create_table(
            "telegram_bot_state",
            sa.Column("key", sa.String(length=120), primary_key=True),
            sa.Column("value", sa.Text(), nullable=False),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )


def downgrade() -> None:
    # Conservador: mantiene el offset para evitar reprocesar mensajes al revertir.
    pass
