"""v5.6 activate personal pricing and CAV member comparisons."""

from alembic import op
import sqlalchemy as sa

revision = "0010_personal_pricing_activation"
down_revision = "0009_price_contexts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "stores",
        sa.Column(
            "personal_comparison_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_index(
        "ix_stores_personal_comparison_enabled",
        "stores",
        ["personal_comparison_enabled"],
    )

    op.add_column("personal_opportunity_snapshots", sa.Column("public_reference_price", sa.Integer(), nullable=True))
    op.add_column("personal_opportunity_snapshots", sa.Column("personal_advantage_clp", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("personal_opportunity_snapshots", sa.Column("personal_advantage_pct", sa.Float(), nullable=False, server_default="0"))
    op.add_column("personal_opportunity_snapshots", sa.Column("history_position", sa.Float(), nullable=False, server_default="0.5"))
    op.add_column("personal_opportunity_snapshots", sa.Column("match_confidence", sa.Float(), nullable=False, server_default="1"))
    op.add_column("personal_opportunity_snapshots", sa.Column("freshness_score", sa.Float(), nullable=False, server_default="1"))
    op.add_column("personal_opportunity_snapshots", sa.Column("scarcity_score", sa.Float(), nullable=False, server_default="0"))

    op.create_table(
        "price_context_statistics",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("price_type", sa.String(length=30), nullable=False),
        sa.Column("audience_key", sa.String(length=80), nullable=False),
        sa.Column("current_price", sa.Integer(), nullable=True),
        sa.Column("min_30d", sa.Integer(), nullable=True),
        sa.Column("avg_30d", sa.Float(), nullable=True),
        sa.Column("min_90d", sa.Integer(), nullable=True),
        sa.Column("avg_90d", sa.Float(), nullable=True),
        sa.Column("historical_min", sa.Integer(), nullable=True),
        sa.Column("observations_30d", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("observations_90d", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("observations_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("days_at_current_price", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "product_id",
            "price_type",
            "audience_key",
            name="uq_price_context_statistic_context",
        ),
    )
    op.create_index("ix_price_context_statistics_product_id", "price_context_statistics", ["product_id"])
    op.create_index("ix_price_context_statistics_price_type", "price_context_statistics", ["price_type"])
    op.create_index("ix_price_context_statistics_audience_key", "price_context_statistics", ["audience_key"])
    op.create_index("ix_price_context_statistics_updated_at", "price_context_statistics", ["updated_at"])

    # CAV deja de ser diagnóstico. Sigue fuera del comparador público, pero sus
    # precios MEMBER pueden competir en la vista personal.
    op.execute(
        """
        UPDATE stores
        SET diagnostic_mode = false,
            comparison_enabled = false,
            personal_comparison_enabled = true
        WHERE connector_key = 'cav' OR slug = 'cav'
        """
    )

    op.alter_column("stores", "personal_comparison_enabled", server_default=None)
    for column in (
        "personal_advantage_clp",
        "personal_advantage_pct",
        "history_position",
        "match_confidence",
        "freshness_score",
        "scarcity_score",
    ):
        op.alter_column("personal_opportunity_snapshots", column, server_default=None)


def downgrade() -> None:
    op.drop_index("ix_price_context_statistics_updated_at", table_name="price_context_statistics")
    op.drop_index("ix_price_context_statistics_audience_key", table_name="price_context_statistics")
    op.drop_index("ix_price_context_statistics_price_type", table_name="price_context_statistics")
    op.drop_index("ix_price_context_statistics_product_id", table_name="price_context_statistics")
    op.drop_table("price_context_statistics")

    op.drop_column("personal_opportunity_snapshots", "scarcity_score")
    op.drop_column("personal_opportunity_snapshots", "freshness_score")
    op.drop_column("personal_opportunity_snapshots", "match_confidence")
    op.drop_column("personal_opportunity_snapshots", "history_position")
    op.drop_column("personal_opportunity_snapshots", "personal_advantage_pct")
    op.drop_column("personal_opportunity_snapshots", "personal_advantage_clp")
    op.drop_column("personal_opportunity_snapshots", "public_reference_price")

    op.drop_index("ix_stores_personal_comparison_enabled", table_name="stores")
    op.drop_column("stores", "personal_comparison_enabled")
