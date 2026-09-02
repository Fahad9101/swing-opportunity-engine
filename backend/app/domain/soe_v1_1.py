from __future__ import annotations

from datetime import UTC, date, datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator


SOE_1_1_MODEL_VERSION = "SOE-1.1.0"


class GuidanceMetric(str, Enum):
    REVENUE = "revenue"
    EPS = "eps"
    EBITDA = "ebitda"
    FCF = "fcf"
    GROSS_MARGIN = "gross_margin"
    OPERATING_MARGIN = "operating_margin"


class GuidanceAction(str, Enum):
    RAISE = "RAISE"
    REAFFIRM = "REAFFIRM"
    LOWER = "LOWER"
    WITHDRAW = "WITHDRAW"
    INITIATE = "INITIATE"
    NONE = "NONE"


class GuidanceClassification(str, Enum):
    DETERIORATED = "DETERIORATED"
    NOT_DETERIORATED = "NOT_DETERIORATED"
    UNKNOWN = "UNKNOWN"


class ExtractionMethod(str, Enum):
    STRUCTURED = "structured"
    DETERMINISTIC_TEXT = "deterministic_text"
    LLM_EXTRACT_THEN_VALIDATE = "llm_extract_then_validate"


class SecDocumentReference(BaseModel):
    ticker: str
    cik: str
    accession: str
    form: str
    filing_date: date | None = None
    primary_document: str
    source_url: str


class SourceDocument(BaseModel):
    document_id: str
    model_version: str = SOE_1_1_MODEL_VERSION
    rules_hash: str
    ticker: str
    cik: str
    accession: str
    form: str
    filing_date: date | None = None
    source: str = "SEC EDGAR"
    source_url: str
    source_timestamp: datetime
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    stale: bool = False
    content_hash: str
    cache_path: str | None = None
    content_type: str | None = None
    content: str | None = Field(default=None, exclude=True)


class GuidanceMetricRecord(BaseModel):
    record_id: UUID = Field(default_factory=uuid4)
    model_version: str = SOE_1_1_MODEL_VERSION
    rules_hash: str
    scan_run_id: UUID | None = None
    ticker: str
    fiscal_period: str
    metric: GuidanceMetric
    accounting_basis: str
    low: float | None = None
    high: float | None = None
    midpoint: float | None = None
    unit: str
    source: str
    source_url: str
    source_accession: str | None = None
    source_timestamp: datetime
    explicit_action: GuidanceAction = GuidanceAction.NONE
    verified: bool = True
    supersedes_record_id: UUID | None = None
    extraction_method: ExtractionMethod = ExtractionMethod.DETERMINISTIC_TEXT
    evidence_span: str | None = None
    source_document_hash: str | None = None
    as_of: datetime
    fetched_at: datetime
    stale: bool = False

    @model_validator(mode="after")
    def derive_midpoint(self) -> "GuidanceMetricRecord":
        if self.midpoint is None and self.low is not None and self.high is not None:
            self.midpoint = (self.low + self.high) / 2
        if self.low is not None and self.high is not None and self.low > self.high:
            raise ValueError("Guidance low cannot exceed high")
        return self

    @property
    def comparison_key(self) -> tuple[str, str, str]:
        return (self.metric.value, self.fiscal_period, self.accounting_basis)


class GuidancePolicyEvidence(BaseModel):
    ticker: str
    standing_no_guidance_policy: bool
    verified: bool = True
    source: str
    source_url: str
    source_timestamp: datetime
    evidence_span: str | None = None


class GuidanceMetricDelta(BaseModel):
    metric: GuidanceMetric
    fiscal_period: str
    accounting_basis: str
    current_record_id: UUID
    prior_record_id: UUID
    current_midpoint: float | None
    prior_midpoint: float | None
    delta_pct: float | None = None
    delta_bps: float | None = None
    material_threshold: float
    small_cut_threshold: float
    material_cut: bool = False
    small_cut: bool = False
    comparable: bool = True
    reason: str | None = None


class GuidanceAssessment(BaseModel):
    assessment_id: UUID = Field(default_factory=uuid4)
    model_version: str = SOE_1_1_MODEL_VERSION
    rules_hash: str
    scan_run_id: UUID | None = None
    ticker: str
    as_of: datetime
    current_guidance_record_ids: list[UUID] = Field(default_factory=list)
    prior_guidance_record_ids: list[UUID] = Field(default_factory=list)
    comparable_metrics: list[GuidanceMetric] = Field(default_factory=list)
    metric_deltas: list[GuidanceMetricDelta] = Field(default_factory=list)
    explicit_cut_or_withdrawal: bool = False
    classification: GuidanceClassification
    guidance_deterioration: bool | None
    rule_path: str
    reasons: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    audit: dict[str, Any] = Field(default_factory=dict)


class GuidanceExtractionResult(BaseModel):
    ticker: str
    document_id: str
    records: list[GuidanceMetricRecord] = Field(default_factory=list)
    policy_evidence: GuidancePolicyEvidence | None = None
    rejected_candidates: list[dict[str, Any]] = Field(default_factory=list)
