"""Add collector observability metrics to scrape runs.

Revision ID: 0003_scrape_run_observability
Revises: 0002_master_products
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_scrape_run_observability"
down_revision = "0002_master_products"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("scrape_runs", sa.Column("sections_discovered", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("scrape_runs", sa.Column("sections_visited", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("scrape_runs", sa.Column("sections_succeeded", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("scrape_runs", sa.Column("sections_failed", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("scrape_runs", sa.Column("pages_visited", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("scrape_runs", sa.Column("cards_seen", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("scrape_runs", sa.Column("duplicates_removed", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("scrape_runs", sa.Column("structural_warnings", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("scrape_runs", sa.Column("health_status", sa.String(length=30), nullable=True))
    op.add_column("scrape_runs", sa.Column("health_score", sa.Integer(), nullable=True))
    op.add_column("scrape_runs", sa.Column("metrics_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    for column in (
        "metrics_json", "health_score", "health_status", "structural_warnings",
        "duplicates_removed", "cards_seen", "pages_visited", "sections_failed",
        "sections_succeeded", "sections_visited", "sections_discovered",
    ):
        op.drop_column("scrape_runs", column)
