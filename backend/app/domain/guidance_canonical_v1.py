from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator

from app.domain.soe_v1_1 import ExtractionMethod, GuidanceAction, GuidanceMetric


GUIDANCE_EVIDENCE_SCHEMA_VERSION = "guidance-evidence-v1"


class GuidanceUnit(str, Enum):
    USD = "USD"
    USD_THOUSAND = "USD_THOUSAND"
    USD_MILLION = "USD_MILLION"
    USD_BILLION = "USD_BILLION"
    USD_PER_SHARE = "USD_PER_SHARE"
    PERCENT = "PERCENT"
    FRACTION = "FRACTION"
    BASIS_POINTS = "BASIS_POINTS"
    UNKNOWN = "UNKNOWN"


class GuidancePeriodKind(str, Enum):
    FULL_YEAR = "FULL_YEAR"
    QUARTER = "QUARTER"
    LONG_TERM = "LONG_TERM"
    UNKNOWN = "UNKNOWN"


class GuidanceScopeKind(str, Enum):
    COMPANY = "COMPANY"
    SEGMENT = "SEGMENT"
    PRODUCT = "PRODUCT"
    UNKNOWN = "UNKNOWN"


class GuidanceValueKind(str, Enum):
    ABSOLUTE_LEVEL = "ABSOLUTE_LEVEL"
    DELTA = "DELTA"
    GROWTH_RATE = "GROWTH_RATE"
    QUALITATIVE = "QUALITATIVE"
    UNKNOWN = "UNKNOWN"


class GuidanceFactRole(str, Enum):
    CURRENT = "CURRENT"
    QUOTED_PRIOR = "QUOTED_PRIOR"
    ACTUAL = "ACTUAL"
    LONG_TERM_TARGET = "LONG_TERM_TARGET"
    UNKNOWN = "UNKNOWN"


class GuidanceInvariantCode(str, Enum):
    INVALID_RANGE = "INVALID_RANGE"
    UNIT_METRIC_MISMATCH = "UNIT_METRIC_MISMATCH"
    NON_ABSOLUTE_VALUE = "NON_ABSOLUTE_VALUE"
    METRIC_VALUE_LOCALITY_MISMATCH = "METRIC_VALUE_LOCALITY_MISMATCH"
    PERIOD_AUTHORITY_MISMATCH = "PERIOD_AUTHORITY_MISMATCH"
    PERIOD_KIND_MISMATCH = "PERIOD_KIND_MISMATCH"
    NON_COMPANY_SCOPE = "NON_COMPANY_SCOPE"
    HISTORICAL_ACTUAL = "HISTORICAL_ACTUAL"
    LONG_TERM_TARGET = "LONG_TERM_TARGET"
    AMBIGUOUS_EVIDENCE = "AMBIGUOUS_EVIDENCE"


class EvidenceBinding(BaseModel):
    full_text: str
    metric_text: str | None = None
    value_text: str | None = None
    period_text: str | None = None
    action_text: str | None = None
    metric_start: int | None = None
    metric_end: int | None = None
    value_start: int | None = None
    value_end: int | None = None
    period_start: int | None = None
    period_end: int | None = None


class GuidanceProvenance(BaseModel):
    document_id: str | None = None
    source: str
    source_url: str
    source_accession: str | None = None
    source_timestamp: datetime
    source_document_hash: str | None = None
    evidence: EvidenceBinding


class TypedGuidanceFact(BaseModel):
    fact_id: UUID = Field(default_factory=uuid4)
    schema_version: str = GUIDANCE_EVIDENCE_SCHEMA_VERSION
    ticker: str
    metric: GuidanceMetric
    raw_metric_label: str | None = None
    fiscal_period: str
    authoritative_period: str | None = None
    period_kind: GuidancePeriodKind
    accounting_basis: str = "UNSPECIFIED"
    scope_kind: GuidanceScopeKind = GuidanceScopeKind.COMPANY
    scope_label: str | None = None
    value_kind: GuidanceValueKind = GuidanceValueKind.ABSOLUTE_LEVEL
    role: GuidanceFactRole = GuidanceFactRole.CURRENT
    low: float | None = None
    high: float | None = None
    unit: GuidanceUnit = GuidanceUnit.UNKNOWN
    explicit_action: GuidanceAction = GuidanceAction.NONE
    extraction_method: ExtractionMethod = ExtractionMethod.DETERMINISTIC_TEXT
    provenance: list[GuidanceProvenance] = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_range(self) -> "TypedGuidanceFact":
        if self.low is not None and self.high is not None and self.low > self.high:
            raise ValueError("Guidance low cannot exceed high")
        return self


class GuidanceInvariantViolation(BaseModel):
    code: GuidanceInvariantCode
    message: str
    quarantine: bool = True


class ValidatedGuidanceFact(BaseModel):
    fact: TypedGuidanceFact
    violations: list[GuidanceInvariantViolation] = Field(default_factory=list)
    accepted: bool


class CanonicalGuidanceFact(BaseModel):
    canonical_id: UUID = Field(default_factory=uuid4)
    schema_version: str = GUIDANCE_EVIDENCE_SCHEMA_VERSION
    ticker: str
    metric: GuidanceMetric
    fiscal_period: str
    period_kind: GuidancePeriodKind
    accounting_basis: str
    scope_kind: GuidanceScopeKind
    scope_label: str | None = None
    value_kind: GuidanceValueKind
    role: GuidanceFactRole
    low: float | None = None
    high: float | None = None
    unit: GuidanceUnit
    explicit_action: GuidanceAction
    source_fact_ids: list[UUID] = Field(default_factory=list)
    provenance: list[GuidanceProvenance] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def semantic_key(self) -> tuple:
        return (
            self.ticker,
            self.metric.value,
            self.fiscal_period,
            self.accounting_basis,
            self.scope_kind.value,
            self.scope_label or "",
            self.value_kind.value,
            self.role.value,
            self.low,
            self.high,
            self.unit.value,
            self.explicit_action.value,
        )


class CanonicalizationResult(BaseModel):
    accepted: list[CanonicalGuidanceFact] = Field(default_factory=list)
    quarantined: list[ValidatedGuidanceFact] = Field(default_factory=list)
