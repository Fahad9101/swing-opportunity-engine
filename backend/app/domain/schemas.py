from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import AssetType, CatalystGrade, DataQualitySeverity, EvaluationStatus, Regime, ScannerType, ScanStatus


class Provenance(BaseModel):
    source: str
    as_of: datetime
    fetched_at: datetime
    stale: bool = False


class FieldProvenance(BaseModel):
    source: str
    as_of: datetime | None = None
    fetched_at: datetime
    stale: bool = False
    raw_field: str | None = None


class Instrument(BaseModel):
    ticker: str
    company_name: str
    exchange: str
    country: str | None = "US"
    sector: str | None
    industry: str | None
    asset_type: AssetType = AssetType.COMMON_STOCK
    market_cap: float | None
    is_biotech: bool = False
    active: bool = True
    source: str | None = None
    as_of: datetime | None = None
    fetched_at: datetime | None = None
    stale: bool = False
    symbol_source: str | None = None
    provider_symbol: str | None = None


class OHLCVBar(BaseModel):
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: float
    source: str | None = None
    as_of: datetime | None = None
    fetched_at: datetime | None = None
    stale: bool = False


class MarketSnapshot(Provenance):
    ticker: str
    price: float
    previous_close: float
    volume: float
    avg_volume_20d: float
    avg_dollar_volume_20d: float
    relative_volume: float
    sma20: float | None
    sma50: float | None
    sma200: float | None
    sma50_slope_20d: float | None
    sma200_slope_20d: float | None
    rsi14: float | None
    atr14: float | None
    high20d: float
    high50d: float
    high52w: float
    low52w: float
    return1d: float
    return3d: float | None
    return5d: float | None
    return20d: float | None
    distance_from_sma20_pct: float | None
    distance_from_sma50_pct: float | None
    distance_from_sma200_pct: float | None
    pullback_from_50d_high_pct: float
    trading_days: int
    stable_sessions: int = 0
    new_52w_low_last_10: bool = False
    low_volume_pullback: bool = False
    accumulation_evidence: bool = False
    reversal_rvol: bool = False
    field_provenance: dict[str, FieldProvenance] = Field(default_factory=dict)


class FundamentalSnapshot(Provenance):
    ticker: str
    revenue: float | None = None
    revenue_growth: float | None = None
    revenue_growth_qoq: float | None = None
    forward_revenue_growth: float | None = None
    eps_growth: float | None = None
    eps: float | None = None
    forward_eps: float | None = None
    fcf_growth: float | None = None
    forward_ebitda_growth: float | None = None
    operating_margin: float | None = None
    operating_margin_prior: float | None = None
    gross_margin: float | None = None
    gross_margin_prior: float | None = None
    operating_margin_expansion_bps: float | None = None
    fcf: float | None = None
    ebitda: float | None = None
    cash: float | None = None
    debt: float | None = None
    net_debt: float | None = None
    interest_coverage: float | None = None
    shares_outstanding: float | None = None
    cash_runway_months: float | None = None
    financing_secured: bool | None = None
    institutional_ownership: float | None = None
    short_float: float | None = None
    business_quality_score: int | None = None
    clinical_evidence_quality: int | None = None
    pipeline_event_importance: int | None = None
    external_validation: int | None = None
    balance_sheet_distressed: bool | None = None
    guidance_deterioration: bool | None = None
    valuation_discount: bool | None = None
    expected_swing_upside: float | None = None
    fundamental_undervaluation: float | None = None
    raw: dict[str, Any] = Field(default_factory=dict)
    field_provenance: dict[str, FieldProvenance] = Field(default_factory=dict)


class EstimateSnapshot(Provenance):
    ticker: str
    forward_eps_growth: float | None = None
    eps_up_revisions: int | None = None
    eps_down_revisions: int | None = None
    revenue_up_revisions: int | None = None
    revenue_down_revisions: int | None = None
    ebitda_up_revisions: int | None = None
    ebitda_down_revisions: int | None = None
    eps_revision_magnitude: float | None = None
    revenue_revision_magnitude: float | None = None
    analyst_count: int | None = None
    forward_revenue: float | None = None
    forward_ebitda: float | None = None
    eps_revision_30d: float | None = None
    eps_revision_90d: float | None = None
    revenue_revision_30d: float | None = None
    revenue_revision_90d: float | None = None
    ebitda_revision_30d: float | None = None
    ebitda_revision_90d: float | None = None
    field_provenance: dict[str, FieldProvenance] = Field(default_factory=dict)


class Catalyst(Provenance):
    ticker: str
    type: str
    title: str
    event_date: date | None = None
    window_start: date | None = None
    window_end: date | None = None
    grade: CatalystGrade
    materiality: int = Field(ge=0, le=10)
    surprise_potential: int = Field(ge=0, le=5)
    verified: bool
    source_timestamp: datetime
    summary: str


class CorporateEvent(Provenance):
    ticker: str
    type: str
    title: str
    event_date: date
    timing: str | None = None
    verified: bool = True
    field_provenance: dict[str, FieldProvenance] = Field(default_factory=dict)


class GateResult(BaseModel):
    passed: bool
    rejection_codes: list[str] = Field(default_factory=list)


class ScannerMatch(BaseModel):
    scanner: ScannerType
    qualified: bool
    conditions: dict[str, bool | None]
    conditions_met: int
    conditions_total: int
    evidence: dict[str, Any] = Field(default_factory=dict)
    evaluation_status: EvaluationStatus = EvaluationStatus.COMPLETE
    incomplete_fields: list[str] = Field(default_factory=list)


class ScoreComponent(BaseModel):
    score: float | None
    maximum: float
    components: dict[str, Any] = Field(default_factory=dict)
    available: bool = True
    available_points: float | None = None


class Penalty(BaseModel):
    code: str
    reason: str
    points: int = Field(le=0)
    source: str
    timestamp: datetime


class DataCompleteness(BaseModel):
    market_data: bool
    fundamentals: bool
    estimates: bool
    catalyst_data: bool
    available_score_points: float
    total_score_points: float = 100
    market_data_pct: float | None = None
    fundamental_pct: float | None = None
    estimate_pct: float | None = None
    catalyst_pct: float | None = None
    overall_pct: float | None = None
    stale_fields: list[str] = Field(default_factory=list)
    missing_fields: dict[str, list[str]] = Field(default_factory=dict)
    availability: dict[str, str] = Field(default_factory=dict)

    @property
    def ratio(self) -> float:
        return self.available_score_points / self.total_score_points


class ScoreBreakdown(BaseModel):
    catalyst: ScoreComponent
    fundamental: ScoreComponent
    valuation: ScoreComponent
    technical: ScoreComponent
    revisions: ScoreComponent
    balance_sheet: ScoreComponent
    liquidity: ScoreComponent
    base_opportunity_score: float
    penalty_points: int
    multi_scanner_bonus: int
    opportunity_score: float


class MarketRegimeResult(BaseModel):
    regime: Regime
    regime_score: int
    spy_data: dict[str, Any]
    qqq_data: dict[str, Any]
    iwm_data: dict[str, Any]
    vix_data: dict[str, Any]
    breadth_data: dict[str, Any]
    timestamp: datetime
    reasons: list[str]
    breadth_available: bool = False


class OpportunityResult(BaseModel):
    ticker: str
    company: str
    sector: str | None
    is_biotech: bool
    price: float | None = None
    market_cap: float | None = None
    primary_scanner: ScannerType
    secondary_scanners: list[ScannerType]
    scores: ScoreBreakdown
    market_regime: Regime
    scanner_conditions: list[ScannerMatch]
    penalties: list[Penalty]
    automatic_rejections: list[str]
    data_completeness: DataCompleteness
    created_at: datetime


class ScanRunState(BaseModel):
    scan_run_id: UUID
    status: ScanStatus
    stage: str
    progress: float = Field(ge=0, le=1)
    model_version: str
    rules_hash: str
    universe_count: int = 0
    universal_pass_count: int = 0
    technical_survivor_count: int = 0
    candidate_count: int = 0
    fully_scored_count: int = 0
    scanner_match_counts: dict[str, int] = Field(default_factory=dict)
    scanner_incomplete_counts: dict[str, int] = Field(default_factory=dict)
    error_count: int = 0
    started_at: datetime
    completed_at: datetime | None = None
    opportunities: list[OpportunityResult] = Field(default_factory=list)
    market_regime: MarketRegimeResult | None = None
    errors: list[dict[str, Any]] = Field(default_factory=list)
    provider_errors: list[dict[str, Any]] = Field(default_factory=list)
    validation_issues: list[dict[str, Any]] = Field(default_factory=list)
    missing_data_rates: dict[str, float] = Field(default_factory=dict)

    model_config = ConfigDict(arbitrary_types_allowed=True)


class ProviderErrorRecord(BaseModel):
    provider: str
    code: str
    message: str
    retryable: bool
    ticker: str | None = None
    endpoint: str | None = None
    status_code: int | None = None
    occurred_at: datetime


class ValidationIssue(BaseModel):
    code: str
    severity: DataQualitySeverity
    message: str
    ticker: str | None = None
    field: str | None = None
    observed_value: Any = None
    expected: str | None = None
    source: str | None = None
    created_at: datetime
