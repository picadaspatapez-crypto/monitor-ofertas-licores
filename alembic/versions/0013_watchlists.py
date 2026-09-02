"""v6.0.0 watchlists and persistent watch condition state."""

from alembic import op
import sqlalchemy as sa

revision = "0013_watchlists"
down_revision = "0012_commercial_intelligence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "telegram_favorites",
        sa.Column("min_opportunity_score", sa.Float(), nullable=True),
    )
    op.add_column(
        "telegram_favorites",
        sa.Column(
            "notify_on_new_historical_min",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "telegram_favorites",
        sa.Column("min_personal_advantage_clp", sa.Integer(), nullable=True),
    )
    op.add_column(
        "telegram_favorites",
        sa.Column("watch_state", sa.JSON(), nullable=True),
    )
    op.alter_column(
        "telegram_favorites",
        "notify_on_new_historical_min",
        server_default=None,
    )


def downgrade() -> None:
    op.drop_column("telegram_favorites", "watch_state")
    op.drop_column("telegram_favorites", "min_personal_advantage_clp")
    op.drop_column("telegram_favorites", "notify_on_new_historical_min")
    op.drop_column("telegram_favorites", "min_opportunity_score")
