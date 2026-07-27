"""Add unified catalog search fields.

Revision ID: 0005_search_catalog
Revises: 0004_smart_alerts
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0005_search_catalog"
down_revision = "0004_smart_alerts"
branch_labels = None
depends_on = None


def _columns(bind, table: str) -> set[str]:
    return {column["name"] for column in inspect(bind).get_columns(table)}


def _index_names(bind, table: str) -> set[str]:
    return {index["name"] for index in inspect(bind).get_indexes(table)}


def upgrade() -> None:
    bind = op.get_bind()
    columns = _columns(bind, "master_products")

    if "variant" not in columns:
        op.add_column(
            "master_products",
            sa.Column("variant", sa.String(length=255), nullable=True),
        )
    if "package_quantity" not in columns:
        op.add_column(
            "master_products",
            sa.Column(
                "package_quantity",
                sa.Integer(),
                nullable=False,
                server_default="1",
            ),
        )
    if "aliases" not in columns:
        op.add_column(
            "master_products",
            sa.Column("aliases", sa.JSON(), nullable=True),
        )
    if "search_text" not in columns:
        op.add_column(
            "master_products",
            sa.Column("search_text", sa.Text(), nullable=True),
        )

    indexes = _index_names(bind, "master_products")
    if "ix_master_products_variant" not in indexes:
        op.create_index(
            "ix_master_products_variant",
            "master_products",
            ["variant"],
        )

    # Backfill mínimo para que el buscador funcione antes del siguiente scrape.
    bind.execute(
        sa.text(
            """
            UPDATE master_products
            SET search_text = LOWER(CONCAT_WS(' ', canonical_name, normalized_key, brand)),
                aliases = COALESCE(aliases, '[]'::json),
                package_quantity = COALESCE(package_quantity, 1)
            WHERE search_text IS NULL
               OR aliases IS NULL
               OR package_quantity IS NULL
            """
        )
    )


def downgrade() -> None:
    # Conservador: no elimina el índice ni los campos de catálogo en producción.
    pass
