from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.persistence.database import Base


class InstrumentORM(Base):
    __tablename__ = "instruments"
    ticker: Mapped[str] = mapped_column(String(16), primary_key=True)
    company_name: Mapped[str] = mapped_column(String(255))
    exchange: Mapped[str] = mapped_column(String(32))
    country: Mapped[str | None] = mapped_column(String(32))
    sector: Mapped[str | None] = mapped_column(String(100))
    industry: Mapped[str | None] = mapped_column(String(150))
    asset_type: Mapped[str] = mapped_column(String(32))
    market_cap: Mapped[float | None] = mapped_column(Float)
    is_biotech: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ScanRunORM(Base):
    __tablename__ = "scan_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    model_version: Mapped[str] = mapped_column(String(32))
    rules_hash: Mapped[str] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20))
    universe_count: Mapped[int] = mapped_column(Integer, default=0)
    stage2_count: Mapped[int] = mapped_column(Integer, default=0)
    stage3_count: Mapped[int] = mapped_column(Integer, default=0)
    fully_scored_count: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)


class MarketRegimeORM(Base):
    __tablename__ = "market_regimes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scan_run_id: Mapped[str] = mapped_column(ForeignKey("scan_runs.id"), unique=True)
    regime: Mapped[str] = mapped_column(String(10))
    regime_score: Mapped[int] = mapped_column(Integer)
    spy_data: Mapped[dict] = mapped_column(JSON)
    qqq_data: Mapped[dict] = mapped_column(JSON)
    iwm_data: Mapped[dict] = mapped_column(JSON)
    vix_data: Mapped[dict] = mapped_column(JSON)
    breadth_data: Mapped[dict] = mapped_column(JSON)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MarketSnapshotORM(Base):
    __tablename__ = "market_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scan_run_id: Mapped[str] = mapped_column(ForeignKey("scan_runs.id"))
    ticker: Mapped[str] = mapped_column(ForeignKey("instruments.ticker"))
    normalized_data: Mapped[dict] = mapped_column(JSON)
    source: Mapped[str] = mapped_column(String(100))
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    stale: Mapped[bool] = mapped_column(Boolean)
    __table_args__ = (UniqueConstraint("scan_run_id", "ticker"),)


class FundamentalSnapshotORM(Base):
    __tablename__ = "fundamental_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scan_run_id: Mapped[str] = mapped_column(ForeignKey("scan_runs.id"))
    ticker: Mapped[str] = mapped_column(ForeignKey("instruments.ticker"))
    normalized_data: Mapped[dict] = mapped_column(JSON)
    raw_source_json: Mapped[dict] = mapped_column(JSON)
    source: Mapped[str] = mapped_column(String(100))
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    stale: Mapped[bool] = mapped_column(Boolean)


class EstimateSnapshotORM(Base):
    __tablename__ = "estimate_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scan_run_id: Mapped[str] = mapped_column(ForeignKey("scan_runs.id"))
    ticker: Mapped[str] = mapped_column(ForeignKey("instruments.ticker"))
    normalized_data: Mapped[dict] = mapped_column(JSON)
    source: Mapped[str] = mapped_column(String(100))
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    stale: Mapped[bool] = mapped_column(Boolean)


class CatalystORM(Base):
    __tablename__ = "catalysts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scan_run_id: Mapped[str] = mapped_column(ForeignKey("scan_runs.id"))
    ticker: Mapped[str] = mapped_column(ForeignKey("instruments.ticker"))
    type: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(255))
    event_date: Mapped[str | None] = mapped_column(String(10))
    grade: Mapped[str] = mapped_column(String(1))
    materiality: Mapped[int] = mapped_column(Integer)
    surprise_potential: Mapped[int] = mapped_column(Integer)
    verified: Mapped[bool] = mapped_column(Boolean)
    source: Mapped[str] = mapped_column(String(100))
    source_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    summary: Mapped[str] = mapped_column(Text)
    normalized_data: Mapped[dict] = mapped_column(JSON)


class CorporateEventORM(Base):
    __tablename__ = "corporate_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scan_run_id: Mapped[str] = mapped_column(ForeignKey("scan_runs.id"))
    ticker: Mapped[str] = mapped_column(ForeignKey("instruments.ticker"))
    type: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(255))
    event_date: Mapped[str] = mapped_column(String(10))
    timing: Mapped[str | None] = mapped_column(String(32))
    verified: Mapped[bool] = mapped_column(Boolean)
    source: Mapped[str] = mapped_column(String(100))
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    stale: Mapped[bool] = mapped_column(Boolean)
    normalized_data: Mapped[dict] = mapped_column(JSON)


class ScannerMatchORM(Base):
    __tablename__ = "scanner_matches"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scan_run_id: Mapped[str] = mapped_column(ForeignKey("scan_runs.id"))
    ticker: Mapped[str] = mapped_column(ForeignKey("instruments.ticker"))
    scanner: Mapped[str] = mapped_column(String(32))
    qualified: Mapped[bool] = mapped_column(Boolean)
    conditions_met: Mapped[int] = mapped_column(Integer)
    conditions_total: Mapped[int] = mapped_column(Integer)
    evidence: Mapped[dict] = mapped_column(JSON)
    __table_args__ = (UniqueConstraint("scan_run_id", "ticker", "scanner"),)


class OpportunityORM(Base):
    __tablename__ = "opportunities"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scan_run_id: Mapped[str] = mapped_column(ForeignKey("scan_runs.id"))
    ticker: Mapped[str] = mapped_column(ForeignKey("instruments.ticker"))
    primary_scanner: Mapped[str] = mapped_column(String(32))
    secondary_scanners: Mapped[list] = mapped_column(JSON)
    base_opportunity_score: Mapped[float] = mapped_column(Float)
    penalty_points: Mapped[int] = mapped_column(Integer)
    multi_scanner_bonus: Mapped[int] = mapped_column(Integer)
    opportunity_score: Mapped[float] = mapped_column(Float)
    catalyst_score: Mapped[float | None] = mapped_column(Float)
    fundamental_score: Mapped[float | None] = mapped_column(Float)
    valuation_score: Mapped[float | None] = mapped_column(Float)
    technical_score: Mapped[float | None] = mapped_column(Float)
    revision_score: Mapped[float | None] = mapped_column(Float)
    balance_sheet_score: Mapped[float | None] = mapped_column(Float)
    liquidity_score: Mapped[float | None] = mapped_column(Float)
    automatic_rejections: Mapped[list] = mapped_column(JSON)
    audit_json: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint("scan_run_id", "ticker"),)


class ProviderErrorORM(Base):
    __tablename__ = "provider_errors"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scan_run_id: Mapped[str] = mapped_column(ForeignKey("scan_runs.id"))
    provider: Mapped[str] = mapped_column(String(100))
    code: Mapped[str] = mapped_column(String(100))
    message: Mapped[str] = mapped_column(Text)
    retryable: Mapped[bool] = mapped_column(Boolean)
    ticker: Mapped[str | None] = mapped_column(String(32))
    endpoint: Mapped[str | None] = mapped_column(String(255))
    status_code: Mapped[int | None] = mapped_column(Integer)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ValidationIssueORM(Base):
    __tablename__ = "validation_issues"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scan_run_id: Mapped[str] = mapped_column(ForeignKey("scan_runs.id"))
    ticker: Mapped[str | None] = mapped_column(String(32))
    code: Mapped[str] = mapped_column(String(100))
    severity: Mapped[str] = mapped_column(String(16))
    field: Mapped[str | None] = mapped_column(String(100))
    message: Mapped[str] = mapped_column(Text)
    observed_value: Mapped[dict | list | str | int | float | None] = mapped_column(JSON)
    expected: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
