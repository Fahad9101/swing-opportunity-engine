"""Initial SOE-1.0.0 schema.

Revision ID: 0001
"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("instruments", sa.Column("ticker", sa.String(16), primary_key=True), sa.Column("company_name", sa.String(255), nullable=False), sa.Column("exchange", sa.String(32), nullable=False), sa.Column("country", sa.String(8), nullable=False), sa.Column("sector", sa.String(100), nullable=False), sa.Column("industry", sa.String(150), nullable=False), sa.Column("asset_type", sa.String(32), nullable=False), sa.Column("market_cap", sa.Float, nullable=False), sa.Column("is_biotech", sa.Boolean, nullable=False), sa.Column("active", sa.Boolean, nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("scan_runs", sa.Column("id", sa.String(36), primary_key=True), sa.Column("model_version", sa.String(32), nullable=False), sa.Column("rules_hash", sa.String(64), nullable=False), sa.Column("started_at", sa.DateTime(timezone=True), nullable=False), sa.Column("completed_at", sa.DateTime(timezone=True)), sa.Column("status", sa.String(20), nullable=False), sa.Column("universe_count", sa.Integer, nullable=False), sa.Column("stage2_count", sa.Integer, nullable=False), sa.Column("stage3_count", sa.Integer, nullable=False), sa.Column("fully_scored_count", sa.Integer, nullable=False), sa.Column("error_count", sa.Integer, nullable=False))
    op.create_table("market_regimes", sa.Column("id", sa.Integer, primary_key=True), sa.Column("scan_run_id", sa.String(36), sa.ForeignKey("scan_runs.id"), nullable=False, unique=True), sa.Column("regime", sa.String(10), nullable=False), sa.Column("regime_score", sa.Integer, nullable=False), sa.Column("spy_data", sa.JSON, nullable=False), sa.Column("qqq_data", sa.JSON, nullable=False), sa.Column("iwm_data", sa.JSON, nullable=False), sa.Column("vix_data", sa.JSON, nullable=False), sa.Column("breadth_data", sa.JSON, nullable=False), sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False))
    for table in ("market_snapshots", "fundamental_snapshots", "estimate_snapshots"):
        columns = [sa.Column("id", sa.Integer, primary_key=True), sa.Column("scan_run_id", sa.String(36), sa.ForeignKey("scan_runs.id"), nullable=False), sa.Column("ticker", sa.String(16), sa.ForeignKey("instruments.ticker"), nullable=False), sa.Column("normalized_data", sa.JSON, nullable=False)]
        if table == "fundamental_snapshots": columns.append(sa.Column("raw_source_json", sa.JSON, nullable=False))
        columns.extend([sa.Column("source", sa.String(100), nullable=False), sa.Column("as_of", sa.DateTime(timezone=True), nullable=False), sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False), sa.Column("stale", sa.Boolean, nullable=False)])
        op.create_table(table, *columns)
    op.create_table("catalysts", sa.Column("id", sa.Integer, primary_key=True), sa.Column("scan_run_id", sa.String(36), sa.ForeignKey("scan_runs.id"), nullable=False), sa.Column("ticker", sa.String(16), sa.ForeignKey("instruments.ticker"), nullable=False), sa.Column("type", sa.String(64), nullable=False), sa.Column("title", sa.String(255), nullable=False), sa.Column("event_date", sa.String(10)), sa.Column("grade", sa.String(1), nullable=False), sa.Column("materiality", sa.Integer, nullable=False), sa.Column("surprise_potential", sa.Integer, nullable=False), sa.Column("verified", sa.Boolean, nullable=False), sa.Column("source", sa.String(100), nullable=False), sa.Column("source_timestamp", sa.DateTime(timezone=True), nullable=False), sa.Column("summary", sa.Text, nullable=False), sa.Column("normalized_data", sa.JSON, nullable=False))
    op.create_table("scanner_matches", sa.Column("id", sa.Integer, primary_key=True), sa.Column("scan_run_id", sa.String(36), sa.ForeignKey("scan_runs.id"), nullable=False), sa.Column("ticker", sa.String(16), sa.ForeignKey("instruments.ticker"), nullable=False), sa.Column("scanner", sa.String(32), nullable=False), sa.Column("qualified", sa.Boolean, nullable=False), sa.Column("conditions_met", sa.Integer, nullable=False), sa.Column("conditions_total", sa.Integer, nullable=False), sa.Column("evidence", sa.JSON, nullable=False), sa.UniqueConstraint("scan_run_id", "ticker", "scanner"))
    op.create_table("opportunities", sa.Column("id", sa.Integer, primary_key=True), sa.Column("scan_run_id", sa.String(36), sa.ForeignKey("scan_runs.id"), nullable=False), sa.Column("ticker", sa.String(16), sa.ForeignKey("instruments.ticker"), nullable=False), sa.Column("primary_scanner", sa.String(32), nullable=False), sa.Column("secondary_scanners", sa.JSON, nullable=False), sa.Column("base_opportunity_score", sa.Float, nullable=False), sa.Column("penalty_points", sa.Integer, nullable=False), sa.Column("multi_scanner_bonus", sa.Integer, nullable=False), sa.Column("opportunity_score", sa.Float, nullable=False), sa.Column("catalyst_score", sa.Float), sa.Column("fundamental_score", sa.Float), sa.Column("valuation_score", sa.Float), sa.Column("technical_score", sa.Float), sa.Column("revision_score", sa.Float), sa.Column("balance_sheet_score", sa.Float), sa.Column("liquidity_score", sa.Float), sa.Column("automatic_rejections", sa.JSON, nullable=False), sa.Column("audit_json", sa.JSON, nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.UniqueConstraint("scan_run_id", "ticker"))


def downgrade() -> None:
    for table in ("opportunities", "scanner_matches", "catalysts", "estimate_snapshots", "fundamental_snapshots", "market_snapshots", "market_regimes", "scan_runs", "instruments"):
        op.drop_table(table)

