from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.persistence.database import Base


class SourceDocumentORM(Base):
    __tablename__ = "source_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    model_version: Mapped[str] = mapped_column(String(32), index=True)
    rules_hash: Mapped[str] = mapped_column(String(64))
    scan_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    cik: Mapped[str] = mapped_column(String(10))
    accession: Mapped[str] = mapped_column(String(32), index=True)
    form: Mapped[str] = mapped_column(String(16))
    source_url: Mapped[str] = mapped_column(Text)
    source_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    stale: Mapped[bool] = mapped_column(Boolean, default=False)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    normalized_data: Mapped[dict] = mapped_column(JSON)


class GuidanceMetricRecordORM(Base):
    __tablename__ = "guidance_metric_records"

    record_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    model_version: Mapped[str] = mapped_column(String(32), index=True)
    rules_hash: Mapped[str] = mapped_column(String(64))
    scan_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    fiscal_period: Mapped[str] = mapped_column(String(32), index=True)
    metric: Mapped[str] = mapped_column(String(32), index=True)
    accounting_basis: Mapped[str] = mapped_column(String(32))
    low: Mapped[float | None] = mapped_column(Float, nullable=True)
    high: Mapped[float | None] = mapped_column(Float, nullable=True)
    midpoint: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str] = mapped_column(String(32))
    source: Mapped[str] = mapped_column(String(100))
    source_url: Mapped[str] = mapped_column(Text)
    source_accession: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    explicit_action: Mapped[str] = mapped_column(String(16))
    verified: Mapped[bool] = mapped_column(Boolean)
    supersedes_record_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    extraction_method: Mapped[str] = mapped_column(String(40))
    evidence_span: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_document_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    stale: Mapped[bool] = mapped_column(Boolean, default=False)
    normalized_data: Mapped[dict] = mapped_column(JSON)


class GuidanceAssessmentORM(Base):
    __tablename__ = "guidance_assessments"

    assessment_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    model_version: Mapped[str] = mapped_column(String(32), index=True)
    rules_hash: Mapped[str] = mapped_column(String(64))
    scan_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    classification: Mapped[str] = mapped_column(String(32))
    guidance_deterioration: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    rule_path: Mapped[str] = mapped_column(String(120))
    reasons: Mapped[list] = mapped_column(JSON)
    sources: Mapped[list] = mapped_column(JSON)
    normalized_data: Mapped[dict] = mapped_column(JSON)
