"""add master products and matching

Revision ID: 0002_master_products
Revises: 0001_operational
Create Date: 2026-07-26
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "0002_master_products"
down_revision: Union[str, None] = "0001_operational"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tables(bind) -> set[str]:
    return set(inspect(bind).get_table_names())


def _columns(bind, table: str) -> set[str]:
    return {column["name"] for column in inspect(bind).get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    tables = _tables(bind)

    if "master_products" not in tables:
        op.create_table(
            "master_products",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("canonical_name", sa.String(500), nullable=False),
            sa.Column("normalized_key", sa.String(500), nullable=False),
            sa.Column("brand", sa.String(255), nullable=True),
            sa.Column("category", sa.String(120), nullable=True),
            sa.Column("subcategory", sa.String(120), nullable=True),
            sa.Column("volume_ml", sa.Integer(), nullable=True),
            sa.Column("ean", sa.String(20), nullable=True),
            sa.Column("status", sa.String(30), nullable=False, server_default="active"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("normalized_key", name="uq_master_products_normalized_key"),
        )
        op.create_index("ix_master_products_normalized_key", "master_products", ["normalized_key"])
        op.create_index("ix_master_products_brand", "master_products", ["brand"])
        op.create_index("ix_master_products_category", "master_products", ["category"])
        op.create_index("ix_master_products_volume_ml", "master_products", ["volume_ml"])
        op.create_index("ix_master_products_ean", "master_products", ["ean"])
        op.create_index("ix_master_products_status", "master_products", ["status"])

    if "products" in _tables(bind) and "master_product_id" not in _columns(bind, "products"):
        op.add_column("products", sa.Column("master_product_id", sa.Integer(), nullable=True))
        op.create_foreign_key(
            "fk_products_master_product_id",
            "products",
            "master_products",
            ["master_product_id"],
            ["id"],
        )
        op.create_index("ix_products_master_product_id", "products", ["master_product_id"])

    if "product_matches" not in _tables(bind):
        op.create_table(
            "product_matches",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("store_product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=False),
            sa.Column("master_product_id", sa.Integer(), sa.ForeignKey("master_products.id"), nullable=False),
            sa.Column("confidence", sa.Float(), nullable=False, server_default="1"),
            sa.Column("matching_method", sa.String(50), nullable=False, server_default="exact_normalized"),
            sa.Column("review_status", sa.String(30), nullable=False, server_default="automatic"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("store_product_id", name="uq_product_matches_store_product"),
        )
        op.create_index("ix_product_matches_store_product_id", "product_matches", ["store_product_id"])
        op.create_index("ix_product_matches_master_product_id", "product_matches", ["master_product_id"])
        op.create_index("ix_product_matches_review_status", "product_matches", ["review_status"])


def downgrade() -> None:
    # Conservador: no elimina historial ni relaciones en producción.
    pass
