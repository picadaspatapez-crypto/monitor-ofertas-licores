"""v5.8 commercial intelligence 2.0 and historical-low signals."""

from alembic import op
import sqlalchemy as sa

revision = "0012_commercial_intelligence"
down_revision = "0011_canonical_matching_quality"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("master_price_statistics", sa.Column("low_price_frequency_90d", sa.Float(), nullable=False, server_default="0"))
    op.alter_column("master_price_statistics", "low_price_frequency_90d", server_default=None)

    op.add_column("opportunity_snapshots", sa.Column("score_version", sa.String(length=20), nullable=False, server_default="v2"))
    op.add_column("opportunity_snapshots", sa.Column("rarity_score", sa.Float(), nullable=False, server_default="0"))
    op.add_column("opportunity_snapshots", sa.Column("rarity_frequency_90d", sa.Float(), nullable=True))
    op.add_column("opportunity_snapshots", sa.Column("history_observations_90d", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("opportunity_snapshots", sa.Column("previous_historical_min", sa.Integer(), nullable=True))
    op.add_column("opportunity_snapshots", sa.Column("price_event", sa.String(length=40), nullable=False, server_default="NORMAL"))
    op.add_column("opportunity_snapshots", sa.Column("historical_gap_clp", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("opportunity_snapshots", sa.Column("historical_gap_pct", sa.Float(), nullable=False, server_default="0"))
    op.add_column("opportunity_snapshots", sa.Column("intelligence_reason", sa.Text(), nullable=True))
    op.create_index("ix_opportunity_snapshots_price_event", "opportunity_snapshots", ["price_event"])

    for column in (
        "score_version", "rarity_score", "history_observations_90d", "price_event",
        "historical_gap_clp", "historical_gap_pct",
    ):
        op.alter_column("opportunity_snapshots", column, server_default=None)


def downgrade() -> None:
    op.drop_index("ix_opportunity_snapshots_price_event", table_name="opportunity_snapshots")
    for column in (
        "intelligence_reason", "historical_gap_pct", "historical_gap_clp", "price_event",
        "previous_historical_min", "history_observations_90d", "rarity_frequency_90d",
        "rarity_score", "score_version",
    ):
        op.drop_column("opportunity_snapshots", column)
    op.drop_column("master_price_statistics", "low_price_frequency_90d")
