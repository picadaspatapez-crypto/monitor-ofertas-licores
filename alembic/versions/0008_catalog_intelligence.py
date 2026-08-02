"""v5.4 catalog intelligence, availability and matching rules."""

from alembic import op
import sqlalchemy as sa

revision = "0008_catalog_intelligence"
down_revision = "0007_telegram_favorites"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("products", sa.Column("sku", sa.String(length=120), nullable=True))
    op.add_column("products", sa.Column("ean", sa.String(length=32), nullable=True))
    op.add_column(
        "products",
        sa.Column("is_available", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "products",
        sa.Column("missing_streak", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("products", sa.Column("last_available_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("products", sa.Column("unavailable_since", sa.DateTime(timezone=True), nullable=True))
    op.add_column("products", sa.Column("reactivated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("products", sa.Column("last_confirmed_run_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_products_last_confirmed_run",
        "products",
        "scrape_runs",
        ["last_confirmed_run_id"],
        ["id"],
    )
    op.create_index("ix_products_sku", "products", ["sku"])
    op.create_index("ix_products_ean", "products", ["ean"])
    op.create_index("ix_products_is_available", "products", ["is_available"])
    op.create_index("ix_products_last_confirmed_run_id", "products", ["last_confirmed_run_id"])

    op.create_table(
        "matching_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("rule_type", sa.String(length=30), nullable=False),
        sa.Column("left_key", sa.String(length=500), nullable=False),
        sa.Column("right_key", sa.String(length=500), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("rule_type", "left_key", "right_key", name="uq_matching_rule_pair"),
    )
    op.create_index("ix_matching_rules_rule_type", "matching_rules", ["rule_type"])
    op.create_index("ix_matching_rules_left_key", "matching_rules", ["left_key"])
    op.create_index("ix_matching_rules_right_key", "matching_rules", ["right_key"])
    op.create_index("ix_matching_rules_is_active", "matching_rules", ["is_active"])

    op.create_table(
        "master_price_statistics",
        sa.Column("master_product_id", sa.Integer(), sa.ForeignKey("master_products.id"), primary_key=True),
        sa.Column("current_best_price", sa.Integer(), nullable=True),
        sa.Column("min_30d", sa.Integer(), nullable=True),
        sa.Column("avg_30d", sa.Float(), nullable=True),
        sa.Column("median_30d", sa.Float(), nullable=True),
        sa.Column("min_90d", sa.Integer(), nullable=True),
        sa.Column("avg_90d", sa.Float(), nullable=True),
        sa.Column("median_90d", sa.Float(), nullable=True),
        sa.Column("historical_min", sa.Integer(), nullable=True),
        sa.Column("observations_30d", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("observations_90d", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("observations_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("discount_frequency_90d", sa.Float(), nullable=False, server_default="0"),
        sa.Column("days_at_current_price", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "opportunity_snapshots",
        sa.Column("master_product_id", sa.Integer(), sa.ForeignKey("master_products.id"), primary_key=True),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("classification", sa.String(length=30), nullable=False),
        sa.Column("winner_product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=True),
        sa.Column("winner_store_id", sa.Integer(), sa.ForeignKey("stores.id"), nullable=True),
        sa.Column("winner_price", sa.Integer(), nullable=True),
        sa.Column("saving_clp", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("saving_pct", sa.Float(), nullable=False, server_default="0"),
        sa.Column("match_confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("history_position", sa.Float(), nullable=False, server_default="0"),
        sa.Column("freshness_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("scarcity_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_opportunity_snapshots_score", "opportunity_snapshots", ["score"])
    op.create_index("ix_opportunity_snapshots_classification", "opportunity_snapshots", ["classification"])
    op.create_index("ix_opportunity_snapshots_winner_product_id", "opportunity_snapshots", ["winner_product_id"])
    op.create_index("ix_opportunity_snapshots_winner_store_id", "opportunity_snapshots", ["winner_store_id"])
    op.create_index("ix_opportunity_snapshots_calculated_at", "opportunity_snapshots", ["calculated_at"])

    # Existing rows are known valid observations at migration time.
    op.execute("UPDATE products SET last_available_at = COALESCE(last_seen_at, first_seen_at) WHERE last_available_at IS NULL")
    op.alter_column("products", "is_available", server_default=None)
    op.alter_column("products", "missing_streak", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_opportunity_snapshots_calculated_at", table_name="opportunity_snapshots")
    op.drop_index("ix_opportunity_snapshots_winner_store_id", table_name="opportunity_snapshots")
    op.drop_index("ix_opportunity_snapshots_winner_product_id", table_name="opportunity_snapshots")
    op.drop_index("ix_opportunity_snapshots_classification", table_name="opportunity_snapshots")
    op.drop_index("ix_opportunity_snapshots_score", table_name="opportunity_snapshots")
    op.drop_table("opportunity_snapshots")
    op.drop_table("master_price_statistics")
    op.drop_index("ix_matching_rules_is_active", table_name="matching_rules")
    op.drop_index("ix_matching_rules_right_key", table_name="matching_rules")
    op.drop_index("ix_matching_rules_left_key", table_name="matching_rules")
    op.drop_index("ix_matching_rules_rule_type", table_name="matching_rules")
    op.drop_table("matching_rules")
    op.drop_index("ix_products_last_confirmed_run_id", table_name="products")
    op.drop_index("ix_products_is_available", table_name="products")
    op.drop_index("ix_products_ean", table_name="products")
    op.drop_index("ix_products_sku", table_name="products")
    op.drop_constraint("fk_products_last_confirmed_run", "products", type_="foreignkey")
    for column in (
        "last_confirmed_run_id", "reactivated_at", "unavailable_since",
        "last_available_at", "missing_streak", "is_available", "ean", "sku",
    ):
        op.drop_column("products", column)
