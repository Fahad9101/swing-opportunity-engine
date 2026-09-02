from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from app.domain.soe_v1_1 import SOE_1_1_MODEL_VERSION


class DistressSectorAdapter(str, Enum):
    CORPORATE = "corporate"
    UTILITY = "utilities"
    REIT = "reits"
    BANK = "banks"
    INSURER = "insurers"


class DistressClassification(str, Enum):
    DISTRESSED = "DISTRESSED"
    NOT_DISTRESSED = "NOT_DISTRESSED"
    UNKNOWN = "UNKNOWN"


class DistressHardFlag(str, Enum):
    GOING_CONCERN = "going_concern"
    BANKRUPTCY_OR_RESTRUCTURING = "bankruptcy_or_restructuring"
    PAYMENT_DEFAULT = "payment_default"
    UNRESOLVED_COVENANT_BREACH = "unresolved_covenant_breach"
    UNRESOLVED_SOLVENCY_RELIABILITY_ISSUE = "unresolved_solvency_reliability_issue"
    EXPLICIT_12M_OBLIGATION_SHORTFALL_WITHOUT_COMMITTED_FINANCING = (
        "explicit_12m_obligation_shortfall_without_committed_financing"
    )


class DistressRawFacts(BaseModel):
    """Validated primary-source facts used only to derive distress metrics.

    Missing facts stay null. `liquid_assets_complete` means the cash +
    marketable-securities input is complete enough to support adverse arithmetic.
    `hard_flag_screen_complete` means the required recent primary SEC forms were
    successfully screened for universal hard-distress overrides; without it a
    numerically safe result cannot become NOT_DISTRESSED.
    """

    ticker: str
    sector_adapter: DistressSectorAdapter
    as_of: datetime = Field(default_factory=lambda: datetime.now(UTC))
    hard_distress_flags: list[DistressHardFlag] = Field(default_factory=list)
    hard_flag_screen_complete: bool = False

    debt: float | None = None
    cash: float | None = None
    marketable_securities: float | None = None
    liquid_assets_total: float | None = None
    liquid_assets_complete: bool = False
    ebitda: float | None = None
    ebit: float | None = None
    cash_interest_expense: float | None = None
    trailing_fcf: float | None = None
    committed_undrawn_revolver: float | None = None
    debt_maturities_12m: float | None = None
    financing_secured: bool | None = None
    cash_runway_months: float | None = None

    debt_to_ebitdare: float | None = None
    fixed_charge_coverage: float | None = None

    regulatory_capital_breach: bool | None = None
    prompt_corrective_action_unresolved: bool | None = None
    cet1_ratio: float | None = None
    cet1_requirement_plus_buffer: float | None = None

    insurer_solvency_ratio: float | None = None
    insurer_regulatory_action_threshold: float | None = None

    sources: list[str] = Field(default_factory=list)
    audit: dict[str, Any] = Field(default_factory=dict)


class DistressInputs(BaseModel):
    ticker: str
    sector_adapter: DistressSectorAdapter
    as_of: datetime
    hard_distress_flags: list[DistressHardFlag] = Field(default_factory=list)
    hard_flag_screen_complete: bool = False

    net_cash: bool | None = None
    debt_outstanding: float | None = None
    net_debt_to_ebitda: float | None = None
    interest_coverage: float | None = None
    liquidity_coverage: float | None = None
    cash_runway_months: float | None = None
    financing_secured: bool | None = None
    debt_maturities_12m: float | None = None
    committed_liquidity: float | None = None
    trailing_fcf: float | None = None

    debt_to_ebitdare: float | None = None
    fixed_charge_coverage: float | None = None

    regulatory_capital_breach: bool | None = None
    prompt_corrective_action_unresolved: bool | None = None
    cet1_ratio: float | None = None
    cet1_requirement_plus_buffer: float | None = None

    insurer_solvency_ratio: float | None = None
    insurer_regulatory_action_threshold: float | None = None

    sources: list[str] = Field(default_factory=list)
    audit: dict[str, Any] = Field(default_factory=dict)


class DistressAssessment(BaseModel):
    assessment_id: UUID = Field(default_factory=uuid4)
    model_version: str = SOE_1_1_MODEL_VERSION
    rules_hash: str
    scan_run_id: UUID | None = None
    ticker: str
    sector_adapter: DistressSectorAdapter
    as_of: datetime
    hard_distress_flags: list[DistressHardFlag] = Field(default_factory=list)
    hard_flag_screen_complete: bool = False

    net_debt_to_ebitda: float | None = None
    interest_coverage: float | None = None
    liquidity_coverage: float | None = None
    cash_runway_months: float | None = None
    financing_secured: bool | None = None
    debt_maturities_12m: float | None = None
    committed_liquidity: float | None = None
    sector_specific_metrics: dict[str, Any] = Field(default_factory=dict)

    classification: DistressClassification
    balance_sheet_distressed: bool | None
    rule_path: str
    reasons: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    audit: dict[str, Any] = Field(default_factory=dict)
