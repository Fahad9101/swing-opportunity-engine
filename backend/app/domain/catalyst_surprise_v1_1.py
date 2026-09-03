from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from app.domain.catalyst_v1_1 import CatalystEventFamily, CatalystExtractionMethod


class SurpriseExpectationMetric(StrEnum):
    EPS = "eps"
    REVENUE = "revenue"


class ClinicalExpectationState(StrEnum):
    UNRESOLVED_PIVOTAL_OR_REGULATORY = "unresolved_pivotal_or_regulatory"
    PHASE2_OR_DERISKED_LABEL_EXPANSION = "phase2_or_derisked_label_expansion"
    CONFIRMATORY_ADMINISTRATIVE = "confirmatory_administrative"


class TransactionContingencyState(StrEnum):
    UNRESOLVED_MATERIAL_BINARY_CONTINGENCY = "unresolved_material_binary_contingency"
    MULTIPLE_PLAUSIBLE_ECONOMIC_OUTCOMES = "multiple_plausible_economic_outcomes"
    ADMINISTRATIVE = "administrative"


class AnalystConsensusContext(BaseModel):
    ticker: str
    period: str
    metric: SurpriseExpectationMetric
    average: float | None = None
    high: float | None = None
    low: float | None = None
    current_estimate: float | None = None
    estimate_90d_ago: float | None = None
    analyst_count: int | None = Field(default=None, ge=0)
    source: str
    source_timestamp: datetime
    stale: bool = False
    field_provenance: dict[str, Any] = Field(default_factory=dict)


class CatalystSurpriseInput(BaseModel):
    ticker: str
    event_id: str
    event_family: CatalystEventFamily
    event_type: str
    economic_exposure_score: int | None = Field(default=None, ge=0, le=3)
    catalyst_candidate: bool = True
    verified: bool = True
    eps_consensus: AnalystConsensusContext | None = None
    revenue_consensus: AnalystConsensusContext | None = None
    clinical_expectation_state: ClinicalExpectationState | None = None
    transaction_contingency_state: TransactionContingencyState | None = None
    source: str
    source_url: str
    source_timestamp: datetime
    extraction_method: CatalystExtractionMethod = CatalystExtractionMethod.STRUCTURED
    evidence_spans: list[str] = Field(default_factory=list)
    structured_provenance: dict[str, Any] = Field(default_factory=dict)


class CatalystSurpriseAssessment(BaseModel):
    model_version: str
    rules_hash: str
    ticker: str
    event_id: str
    event_family: CatalystEventFamily
    event_type: str
    outcome_binaryity: int | None = Field(default=None, ge=0, le=2)
    expectation_uncertainty: int | None = Field(default=None, ge=0, le=2)
    expectation_uncertainty_basis: str | None = None
    expectation_metric: SurpriseExpectationMetric | None = None
    expectation_value: float | None = None
    valuation_concentration: int | None = Field(default=None, ge=0, le=1)
    surprise_potential: int | None = Field(default=None, ge=0, le=5)
    surprise_ready: bool = False
    catalyst_candidate: bool = False
    missing_fields: list[str] = Field(default_factory=list)
    rule_path: str
    reasons: list[str] = Field(default_factory=list)
    source: str
    source_url: str
    source_timestamp: datetime
    extraction_method: CatalystExtractionMethod
    evidence_spans: list[str] = Field(default_factory=list)
    structured_provenance: dict[str, Any] = Field(default_factory=dict)
    expectation_provenance: dict[str, Any] = Field(default_factory=dict)
