"""v5.7 canonical catalog, matching review queue and data quality engine."""

from alembic import op
import sqlalchemy as sa

revision = "0011_canonical_matching_quality"
down_revision = "0010_personal_pricing_activation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("master_products", sa.Column("canonical_fingerprint", sa.String(length=700), nullable=True))
    op.add_column("master_products", sa.Column("abv_pct", sa.Float(), nullable=True))
    op.add_column("master_products", sa.Column("vintage_year", sa.Integer(), nullable=True))
    op.add_column("master_products", sa.Column("identity_confidence", sa.Float(), nullable=False, server_default="0.5"))
    op.create_index("ix_master_products_canonical_fingerprint", "master_products", ["canonical_fingerprint"])
    op.create_index("ix_master_products_abv_pct", "master_products", ["abv_pct"])
    op.create_index("ix_master_products_vintage_year", "master_products", ["vintage_year"])

    op.add_column("products", sa.Column("abv_pct", sa.Float(), nullable=True))
    op.add_column("products", sa.Column("vintage_year", sa.Integer(), nullable=True))
    op.add_column("products", sa.Column("package_quantity", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("products", sa.Column("data_quality_score", sa.Integer(), nullable=False, server_default="100"))
    op.add_column("products", sa.Column("data_quality_status", sa.String(length=30), nullable=False, server_default="CLEAN"))
    op.add_column("products", sa.Column("data_quality_issues", sa.JSON(), nullable=True))
    op.add_column("products", sa.Column("excluded_from_comparison", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_index("ix_products_abv_pct", "products", ["abv_pct"])
    op.create_index("ix_products_vintage_year", "products", ["vintage_year"])
    op.create_index("ix_products_data_quality_score", "products", ["data_quality_score"])
    op.create_index("ix_products_data_quality_status", "products", ["data_quality_status"])
    op.create_index("ix_products_excluded_from_comparison", "products", ["excluded_from_comparison"])

    op.add_column("product_matches", sa.Column("evidence_json", sa.JSON(), nullable=True))

    op.create_table(
        "canonical_aliases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("master_product_id", sa.Integer(), sa.ForeignKey("master_products.id"), nullable=False),
        sa.Column("alias_text", sa.String(length=500), nullable=False),
        sa.Column("alias_key", sa.String(length=500), nullable=False),
        sa.Column("source", sa.String(length=120), nullable=False, server_default="observed"),
        sa.Column("is_confirmed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("master_product_id", "alias_key", name="uq_canonical_alias_master_key"),
    )
    op.create_index("ix_canonical_aliases_master_product_id", "canonical_aliases", ["master_product_id"])
    op.create_index("ix_canonical_aliases_alias_key", "canonical_aliases", ["alias_key"])
    op.create_index("ix_canonical_aliases_source", "canonical_aliases", ["source"])
    op.create_index("ix_canonical_aliases_is_confirmed", "canonical_aliases", ["is_confirmed"])

    op.create_table(
        "matching_review_queue",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("left_product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("right_product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("proposed_method", sa.String(length=80), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="pending"),
        sa.Column("resolution_notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("left_product_id", "right_product_id", name="uq_matching_review_pair"),
    )
    op.create_index("ix_matching_review_queue_left_product_id", "matching_review_queue", ["left_product_id"])
    op.create_index("ix_matching_review_queue_right_product_id", "matching_review_queue", ["right_product_id"])
    op.create_index("ix_matching_review_queue_confidence", "matching_review_queue", ["confidence"])
    op.create_index("ix_matching_review_queue_status", "matching_review_queue", ["status"])

    op.create_table(
        "data_quality_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("scrape_run_id", sa.Integer(), sa.ForeignKey("scrape_runs.id"), nullable=True),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("issues", sa.JSON(), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_data_quality_events_product_id", "data_quality_events", ["product_id"])
    op.create_index("ix_data_quality_events_scrape_run_id", "data_quality_events", ["scrape_run_id"])
    op.create_index("ix_data_quality_events_score", "data_quality_events", ["score"])
    op.create_index("ix_data_quality_events_status", "data_quality_events", ["status"])
    op.create_index("ix_data_quality_events_observed_at", "data_quality_events", ["observed_at"])

    # Conservative backfill: existing data stays comparable until it is reassessed
    # by the v5.7 quality engine on the next healthy run.
    op.alter_column("master_products", "identity_confidence", server_default=None)
    for column in ("package_quantity", "data_quality_score", "data_quality_status", "excluded_from_comparison"):
        op.alter_column("products", column, server_default=None)


def downgrade() -> None:
    for index in (
        "ix_data_quality_events_observed_at", "ix_data_quality_events_status", "ix_data_quality_events_score",
        "ix_data_quality_events_scrape_run_id", "ix_data_quality_events_product_id",
    ):
        op.drop_index(index, table_name="data_quality_events")
    op.drop_table("data_quality_events")
    for index in (
        "ix_matching_review_queue_status", "ix_matching_review_queue_confidence",
        "ix_matching_review_queue_right_product_id", "ix_matching_review_queue_left_product_id",
    ):
        op.drop_index(index, table_name="matching_review_queue")
    op.drop_table("matching_review_queue")
    for index in (
        "ix_canonical_aliases_is_confirmed", "ix_canonical_aliases_source",
        "ix_canonical_aliases_alias_key", "ix_canonical_aliases_master_product_id",
    ):
        op.drop_index(index, table_name="canonical_aliases")
    op.drop_table("canonical_aliases")
    op.drop_column("product_matches", "evidence_json")
    for index in (
        "ix_products_excluded_from_comparison", "ix_products_data_quality_status",
        "ix_products_data_quality_score", "ix_products_vintage_year", "ix_products_abv_pct",
    ):
        op.drop_index(index, table_name="products")
    for column in (
        "excluded_from_comparison", "data_quality_issues", "data_quality_status", "data_quality_score",
        "package_quantity", "vintage_year", "abv_pct",
    ):
        op.drop_column("products", column)
    for index in (
        "ix_master_products_vintage_year", "ix_master_products_abv_pct", "ix_master_products_canonical_fingerprint",
    ):
        op.drop_index(index, table_name="master_products")
    for column in ("identity_confidence", "vintage_year", "abv_pct", "canonical_fingerprint"):
        op.drop_column("master_products", column)
