"""Production data-quality persistence.

Revision ID: 0002
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("instruments") as batch:
        batch.alter_column("country", existing_type=sa.String(8), type_=sa.String(32), nullable=True)
        batch.alter_column("sector", existing_type=sa.String(100), nullable=True)
        batch.alter_column("industry", existing_type=sa.String(150), nullable=True)
        batch.alter_column("market_cap", existing_type=sa.Float(), nullable=True)
    op.create_table(
        "provider_errors", sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scan_run_id", sa.String(36), sa.ForeignKey("scan_runs.id"), nullable=False),
        sa.Column("provider", sa.String(100), nullable=False), sa.Column("code", sa.String(100), nullable=False),
        sa.Column("message", sa.Text(), nullable=False), sa.Column("retryable", sa.Boolean(), nullable=False),
        sa.Column("ticker", sa.String(32)), sa.Column("endpoint", sa.String(255)), sa.Column("status_code", sa.Integer()),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "validation_issues", sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scan_run_id", sa.String(36), sa.ForeignKey("scan_runs.id"), nullable=False),
        sa.Column("ticker", sa.String(32)), sa.Column("code", sa.String(100), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False), sa.Column("field", sa.String(100)),
        sa.Column("message", sa.Text(), nullable=False), sa.Column("observed_value", sa.JSON()),
        sa.Column("expected", sa.Text()), sa.Column("source", sa.String(100)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "corporate_events", sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scan_run_id", sa.String(36), sa.ForeignKey("scan_runs.id"), nullable=False),
        sa.Column("ticker", sa.String(16), sa.ForeignKey("instruments.ticker"), nullable=False),
        sa.Column("type", sa.String(64), nullable=False), sa.Column("title", sa.String(255), nullable=False),
        sa.Column("event_date", sa.String(10), nullable=False), sa.Column("timing", sa.String(32)),
        sa.Column("verified", sa.Boolean(), nullable=False), sa.Column("source", sa.String(100), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False), sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("stale", sa.Boolean(), nullable=False), sa.Column("normalized_data", sa.JSON(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("corporate_events")
    op.drop_table("validation_issues")
    op.drop_table("provider_errors")
    with op.batch_alter_table("instruments") as batch:
        batch.alter_column("market_cap", existing_type=sa.Float(), nullable=False)
        batch.alter_column("industry", existing_type=sa.String(150), nullable=False)
        batch.alter_column("sector", existing_type=sa.String(100), nullable=False)
        batch.alter_column("country", existing_type=sa.String(32), type_=sa.String(8), nullable=False)
