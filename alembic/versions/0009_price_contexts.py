"""v5.5 price contexts, La Vinoteca and CAV diagnostic support."""

from alembic import op
import sqlalchemy as sa

revision = "0009_price_contexts"
down_revision = "0008_catalog_intelligence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("stores", sa.Column("comparison_enabled", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("stores", sa.Column("diagnostic_mode", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_index("ix_stores_comparison_enabled", "stores", ["comparison_enabled"])
    op.create_index("ix_stores_diagnostic_mode", "stores", ["diagnostic_mode"])

    op.create_table(
        "product_price_quotes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("price", sa.Integer(), nullable=False),
        sa.Column("regular_price", sa.Integer(), nullable=True),
        sa.Column("price_type", sa.String(length=30), nullable=False, server_default="PUBLIC"),
        sa.Column("audience_key", sa.String(length=80), nullable=False, server_default="public"),
        sa.Column("eligibility_required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("product_id", "price_type", "audience_key", name="uq_product_price_quote_context"),
    )
    op.create_index("ix_product_price_quotes_product_id", "product_price_quotes", ["product_id"])
    op.create_index("ix_product_price_quotes_price_type", "product_price_quotes", ["price_type"])
    op.create_index("ix_product_price_quotes_audience_key", "product_price_quotes", ["audience_key"])
    op.create_index("ix_product_price_quotes_eligibility_required", "product_price_quotes", ["eligibility_required"])
    op.create_index("ix_product_price_quotes_is_active", "product_price_quotes", ["is_active"])

    op.create_table(
        "price_quote_observations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("scrape_run_id", sa.Integer(), sa.ForeignKey("scrape_runs.id"), nullable=True),
        sa.Column("price", sa.Integer(), nullable=False),
        sa.Column("regular_price", sa.Integer(), nullable=True),
        sa.Column("price_type", sa.String(length=30), nullable=False, server_default="PUBLIC"),
        sa.Column("audience_key", sa.String(length=80), nullable=False, server_default="public"),
        sa.Column("eligibility_required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_price_quote_observations_product_id", "price_quote_observations", ["product_id"])
    op.create_index("ix_price_quote_observations_scrape_run_id", "price_quote_observations", ["scrape_run_id"])
    op.create_index("ix_price_quote_observations_price_type", "price_quote_observations", ["price_type"])
    op.create_index("ix_price_quote_observations_audience_key", "price_quote_observations", ["audience_key"])
    op.create_index("ix_price_quote_observations_observed_at", "price_quote_observations", ["observed_at"])

    op.create_table(
        "personal_opportunity_snapshots",
        sa.Column("master_product_id", sa.Integer(), sa.ForeignKey("master_products.id"), primary_key=True),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("classification", sa.String(length=30), nullable=False),
        sa.Column("winner_product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=True),
        sa.Column("winner_store_id", sa.Integer(), sa.ForeignKey("stores.id"), nullable=True),
        sa.Column("winner_price", sa.Integer(), nullable=True),
        sa.Column("winner_price_type", sa.String(length=30), nullable=False, server_default="PUBLIC"),
        sa.Column("winner_audience_key", sa.String(length=80), nullable=False, server_default="public"),
        sa.Column("saving_clp", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("saving_pct", sa.Float(), nullable=False, server_default="0"),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_personal_opportunity_snapshots_score", "personal_opportunity_snapshots", ["score"])
    op.create_index("ix_personal_opportunity_snapshots_classification", "personal_opportunity_snapshots", ["classification"])
    op.create_index("ix_personal_opportunity_snapshots_winner_product_id", "personal_opportunity_snapshots", ["winner_product_id"])
    op.create_index("ix_personal_opportunity_snapshots_winner_store_id", "personal_opportunity_snapshots", ["winner_store_id"])
    op.create_index("ix_personal_opportunity_snapshots_calculated_at", "personal_opportunity_snapshots", ["calculated_at"])

    # Backfill de precio público vigente. El historial previo continúa en
    # price_observations y desde v5.5 también se escribe en price_quote_observations.
    op.execute("""
        INSERT INTO product_price_quotes
            (product_id, price, regular_price, price_type, audience_key,
             eligibility_required, is_active, observed_at, updated_at)
        SELECT id, current_price, regular_price,
               CASE WHEN regular_price IS NOT NULL AND regular_price > current_price THEN 'SALE' ELSE 'PUBLIC' END,
               'public', false, true, COALESCE(last_seen_at, first_seen_at), COALESCE(last_seen_at, first_seen_at)
        FROM products
        WHERE current_price > 0
    """)

    op.alter_column("stores", "comparison_enabled", server_default=None)
    op.alter_column("stores", "diagnostic_mode", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_personal_opportunity_snapshots_calculated_at", table_name="personal_opportunity_snapshots")
    op.drop_index("ix_personal_opportunity_snapshots_winner_store_id", table_name="personal_opportunity_snapshots")
    op.drop_index("ix_personal_opportunity_snapshots_winner_product_id", table_name="personal_opportunity_snapshots")
    op.drop_index("ix_personal_opportunity_snapshots_classification", table_name="personal_opportunity_snapshots")
    op.drop_index("ix_personal_opportunity_snapshots_score", table_name="personal_opportunity_snapshots")
    op.drop_table("personal_opportunity_snapshots")
    op.drop_index("ix_price_quote_observations_observed_at", table_name="price_quote_observations")
    op.drop_index("ix_price_quote_observations_audience_key", table_name="price_quote_observations")
    op.drop_index("ix_price_quote_observations_price_type", table_name="price_quote_observations")
    op.drop_index("ix_price_quote_observations_scrape_run_id", table_name="price_quote_observations")
    op.drop_index("ix_price_quote_observations_product_id", table_name="price_quote_observations")
    op.drop_table("price_quote_observations")
    op.drop_index("ix_product_price_quotes_is_active", table_name="product_price_quotes")
    op.drop_index("ix_product_price_quotes_eligibility_required", table_name="product_price_quotes")
    op.drop_index("ix_product_price_quotes_audience_key", table_name="product_price_quotes")
    op.drop_index("ix_product_price_quotes_price_type", table_name="product_price_quotes")
    op.drop_index("ix_product_price_quotes_product_id", table_name="product_price_quotes")
    op.drop_table("product_price_quotes")
    op.drop_index("ix_stores_diagnostic_mode", table_name="stores")
    op.drop_index("ix_stores_comparison_enabled", table_name="stores")
    op.drop_column("stores", "diagnostic_mode")
    op.drop_column("stores", "comparison_enabled")
