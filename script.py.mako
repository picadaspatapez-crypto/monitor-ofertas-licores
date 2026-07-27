"""Add stores, scrape runs, alerts and compatibility columns.

This migration is intentionally defensive because the production database
already contains products and price_observations created by SQLAlchemy.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "0001_operational"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tables(bind) -> set[str]:
    return set(inspect(bind).get_table_names())


def _columns(bind, table: str) -> set[str]:
    return {column["name"] for column in inspect(bind).get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    tables = _tables(bind)

    if "stores" not in tables:
        op.create_table(
            "stores",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(120), nullable=False),
            sa.Column("slug", sa.String(120), nullable=False),
            sa.Column("base_url", sa.String(1000), nullable=False),
            sa.Column("connector_key", sa.String(120), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("requires_browser", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("country_code", sa.String(2), nullable=False, server_default="CL"),
            sa.Column("currency_code", sa.String(3), nullable=False, server_default="CLP"),
            sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("slug", name="uq_stores_slug"),
            sa.UniqueConstraint("connector_key", name="uq_stores_connector_key"),
        )
        op.create_index("ix_stores_slug", "stores", ["slug"])
        op.create_index("ix_stores_is_active", "stores", ["is_active"])

    bind.execute(
        sa.text(
            """
            INSERT INTO stores
                (name, slug, base_url, connector_key, is_active,
                 requires_browser, country_code, currency_code,
                 created_at, updated_at)
            VALUES
                ('Licor3B', 'licor3b', 'https://licor3b.cl/', 'licor3b',
                 TRUE, FALSE, 'CL', 'CLP', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT (slug) DO NOTHING
            """
        )
    )

    tables = _tables(bind)
    if "products" not in tables:
        op.create_table(
            "products",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("store", sa.String(80), nullable=False),
            sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id"), nullable=True),
            sa.Column("name", sa.String(500), nullable=False),
            sa.Column("url", sa.String(1000), nullable=False),
            sa.Column("current_price", sa.Integer(), nullable=False),
            sa.Column("regular_price", sa.Integer(), nullable=True),
            sa.Column("discount_pct", sa.Float(), nullable=False, server_default="0"),
            sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("store", "url", name="uq_product_store_url"),
        )
        op.create_index("ix_products_store", "products", ["store"])
        op.create_index("ix_products_store_id", "products", ["store_id"])

    tables = _tables(bind)
    if "products" in tables and "store_id" not in _columns(bind, "products"):
        op.add_column("products", sa.Column("store_id", sa.Integer(), nullable=True))
        op.create_foreign_key(
            "fk_products_store_id_stores",
            "products",
            "stores",
            ["store_id"],
            ["id"],
        )
        op.create_index("ix_products_store_id", "products", ["store_id"])
        bind.execute(
            sa.text(
                """
                UPDATE products
                SET store_id = (SELECT id FROM stores WHERE slug = 'licor3b')
                WHERE store = 'Licor3B' AND store_id IS NULL
                """
            )
        )

    if "scrape_runs" not in tables:
        op.create_table(
            "scrape_runs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id"), nullable=False),
            sa.Column("status", sa.String(30), nullable=False, server_default="running"),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("duration_ms", sa.Integer(), nullable=True),
            sa.Column("products_found", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("products_created", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("products_updated", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("products_failed", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("price_changes", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_scrape_runs_store_id", "scrape_runs", ["store_id"])
        op.create_index("ix_scrape_runs_status", "scrape_runs", ["status"])

    tables = _tables(bind)
    if "price_observations" not in tables:
        op.create_table(
            "price_observations",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=False),
            sa.Column("scrape_run_id", sa.Integer(), sa.ForeignKey("scrape_runs.id"), nullable=True),
            sa.Column("price", sa.Integer(), nullable=False),
            sa.Column("regular_price", sa.Integer(), nullable=True),
            sa.Column("discount_pct", sa.Float(), nullable=False, server_default="0"),
            sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_price_observations_product_id", "price_observations", ["product_id"])
        op.create_index("ix_price_observations_scrape_run_id", "price_observations", ["scrape_run_id"])

    tables = _tables(bind)
    if "price_observations" in tables and "scrape_run_id" not in _columns(bind, "price_observations"):
        op.add_column(
            "price_observations",
            sa.Column("scrape_run_id", sa.Integer(), nullable=True),
        )
        op.create_foreign_key(
            "fk_price_observations_scrape_run_id",
            "price_observations",
            "scrape_runs",
            ["scrape_run_id"],
            ["id"],
        )
        op.create_index(
            "ix_price_observations_scrape_run_id",
            "price_observations",
            ["scrape_run_id"],
        )

    tables = _tables(bind)
    if "alerts" not in tables:
        op.create_table(
            "alerts",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=False),
            sa.Column("alert_type", sa.String(50), nullable=False),
            sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
            sa.Column("channel", sa.String(30), nullable=False, server_default="telegram"),
            sa.Column("price", sa.Integer(), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("deduplication_key", sa.String(255), nullable=False),
            sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("deduplication_key", name="uq_alerts_deduplication_key"),
        )
        op.create_index("ix_alerts_product_id", "alerts", ["product_id"])
        op.create_index("ix_alerts_alert_type", "alerts", ["alert_type"])
        op.create_index("ix_alerts_status", "alerts", ["status"])


def downgrade() -> None:
    # Downgrade is deliberately conservative to avoid deleting production history.
    pass
