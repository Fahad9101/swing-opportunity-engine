from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from app.domain.enums import CatalystGrade


class CatalystEventFamily(StrEnum):
    EARNINGS_GUIDANCE = "earnings_guidance"
    CLINICAL_REGULATORY = "clinical_regulatory"
    TRANSACTION_LEGAL_FINANCING = "transaction_legal_financing"
    CORPORATE_STRATEGIC = "corporate_strategic"


class CatalystExposureBasis(StrEnum):
    COMPANY_WIDE = "company_wide"
    REVENUE = "revenue"
    EBITDA = "ebitda"
    OPERATING_INCOME = "operating_income"
    FCF = "fcf"
    ASSET_VALUE = "asset_value"
    SEGMENT_CONTRIBUTION = "segment_contribution"
    BIOTECH_PIPELINE_VALUE = "biotech_pipeline_value"
    DOMINANT_SINGLE_ASSET = "dominant_single_asset"


class CatalystConsequenceClass(StrEnum):
    BINARY_PERMISSION_VIABILITY = "binary_permission_viability"
    MATERIAL_ESTIMATE_OR_EXECUTION_CHANGE = "material_estimate_or_execution_change"
    INFORMATIONAL = "informational"


class CatalystExtractionMethod(StrEnum):
    STRUCTURED = "structured"
    DETERMINISTIC_TEXT = "deterministic_text"
    LLM_EXTRACT_THEN_VALIDATE = "llm_extract_then_validate"


class CatalystMaterialityInput(BaseModel):
    ticker: str
    event_id: str
    event_family: CatalystEventFamily
    event_type: str
    source: str
    source_url: str
    source_timestamp: datetime
    event_date: date | None = None
    window_start: date | None = None
    window_end: date | None = None
    date_confidence: CatalystGrade | None = None
    verified: bool = True
    company_wide: bool | None = None
    is_biotech: bool = False
    economic_exposure_basis: CatalystExposureBasis | None = None
    economic_exposure_fraction: float | None = Field(default=None, ge=0.0, le=1.0)
    biotech_pipeline_value_fraction: float | None = Field(default=None, ge=0.0, le=1.0)
    dominant_single_asset: bool | None = None
    consequence_class: CatalystConsequenceClass | None = None
    formal_guidance_action: bool | None = None
    extraction_method: CatalystExtractionMethod = CatalystExtractionMethod.STRUCTURED
    evidence_spans: list[str] = Field(default_factory=list)
    structured_provenance: dict[str, Any] = Field(default_factory=dict)


class CatalystMaterialityAssessment(BaseModel):
    model_version: str
    rules_hash: str
    ticker: str
    event_id: str
    event_family: CatalystEventFamily
    event_type: str
    event_class_base: int | None = Field(default=None, ge=0, le=5)
    economic_exposure_score: int | None = Field(default=None, ge=0, le=3)
    economic_exposure_basis: CatalystExposureBasis | None = None
    economic_exposure_value: float | None = None
    consequence_severity: int | None = Field(default=None, ge=0, le=2)
    materiality: int | None = Field(default=None, ge=0, le=10)
    materiality_ready: bool = False
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
