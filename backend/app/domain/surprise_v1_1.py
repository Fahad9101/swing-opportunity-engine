from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from app.domain.catalyst_v1_1 import CatalystEventFamily, CatalystExtractionMethod


class SurpriseOutcomeClass(StrEnum):
    HARD_BINARY = "hard_binary"
    ESTIMATE_RESET = "estimate_reset_event"
    INFORMATIONAL = "informational"


class ClinicalExpectationClass(StrEnum):
    UNRESOLVED_PIVOTAL_OR_REGULATORY = "unresolved_pivotal_or_regulatory"
    PHASE2_OR_DERISKED_LABEL_EXPANSION = "phase2_or_derisked_label_expansion"
    CONFIRMATORY_ADMINISTRATIVE = "confirmatory_administrative"


class TransactionExpectationClass(StrEnum):
    UNRESOLVED_MATERIAL_BINARY_CONTINGENCY = "unresolved_material_binary_contingency"
    MULTIPLE_PLAUSIBLE_ECONOMIC_OUTCOMES = "multiple_plausible_economic_outcomes"
    ADMINISTRATIVE = "administrative"


class SurprisePotentialInput(BaseModel):
    ticker: str
    event_id: str
    event_family: CatalystEventFamily
    event_type: str
    source: str
    source_url: str
    source_timestamp: datetime
    verified: bool = True
    catalyst_candidate: bool = True

    # Carries the already-deterministic materiality exposure result into the
    # valuation-concentration factor. Missing exposure must stay missing.
    economic_exposure_score: int | None = Field(default=None, ge=0, le=3)

    # Earnings/guidance expectation evidence. The range is mandatory for this
    # framework; prior consensus is optional and only adds an instability test.
    analyst_consensus: float | None = None
    analyst_low: float | None = None
    analyst_high: float | None = None
    prior_consensus: float | None = None

    # Clinical/regulatory uncertainty is only scoreable when prior clinical
    # evidence was actually reviewed. The class itself is direction-neutral.
    prior_clinical_evidence_available: bool | None = None
    clinical_expectation_class: ClinicalExpectationClass | None = None

    # Transaction/legal/financing uncertainty requires an explicit contingency
    # classification; no event text is silently treated as binary.
    transaction_expectation_class: TransactionExpectationClass | None = None

    extraction_method: CatalystExtractionMethod = CatalystExtractionMethod.STRUCTURED
    evidence_spans: list[str] = Field(default_factory=list)
    structured_provenance: dict[str, Any] = Field(default_factory=dict)


class SurprisePotentialAssessment(BaseModel):
    model_version: str
    rules_hash: str
    ticker: str
    event_id: str
    event_family: CatalystEventFamily
    event_type: str

    outcome_binaryity: int | None = Field(default=None, ge=0, le=2)
    expectation_uncertainty: int | None = Field(default=None, ge=0, le=2)
    analyst_dispersion_fraction: float | None = Field(default=None, ge=0.0)
    consensus_instability_fraction: float | None = Field(default=None, ge=0.0)
    valuation_concentration: int | None = Field(default=None, ge=0, le=1)
    surprise_score: int | None = Field(default=None, ge=0, le=5)
    surprise_ready: bool = False

    # This score measures uncertainty/dispersion/contingency only. It is never a
    # prediction that the catalyst will be positive or negative.
    directional_prediction: bool = False

    missing_fields: list[str] = Field(default_factory=list)
    rule_path: str
    reasons: list[str] = Field(default_factory=list)
    source: str
    source_url: str
    source_timestamp: datetime
    extraction_method: CatalystExtractionMethod
    evidence_spans: list[str] = Field(default_factory=list)
    structured_provenance: dict[str, Any] = Field(default_factory=dict)
