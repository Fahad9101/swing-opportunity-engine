from datetime import UTC, datetime

import pytest

from app.core.config import SOE_1_1_RULES_PATH, load_rules_for_version, rules_hash
from app.domain.distress_v1_1 import (
    DistressClassification,
    DistressHardFlag,
    DistressInputs,
    DistressSectorAdapter,
)
from app.services.distress_classifier import classify_distress


RULES = load_rules_for_version(SOE_1_1_RULES_PATH, "SOE-1.1.0")
RULES_HASH = rules_hash(RULES)
NOW = datetime(2026, 9, 2, tzinfo=UTC)
SOURCE = "https://www.sec.gov/Archives/edgar/data/1/test.htm"


def metrics(adapter: DistressSectorAdapter, **updates) -> DistressInputs:
    payload = {
        "ticker": "TEST",
        "sector_adapter": adapter,
        "as_of": NOW,
        "sources": [SOURCE],
    }
    payload.update(updates)
    return DistressInputs(**payload)


def classify(item: DistressInputs):
    return classify_distress(item, RULES, rules_hash=RULES_HASH)


@pytest.mark.parametrize("flag", list(DistressHardFlag))
def test_every_universal_hard_override_is_distressed(flag):
    result = classify(metrics(DistressSectorAdapter.CORPORATE, hard_distress_flags=[flag]))
    assert result.classification is DistressClassification.DISTRESSED
    assert result.balance_sheet_distressed is True
    assert result.rule_path == "balance_sheet_distress_v1_1.universal_hard_override"
    assert result.sources == [SOURCE]


@pytest.mark.parametrize(
    "kwargs,expected",
    [
        ({"net_debt_to_ebitda": 5.01, "interest_coverage": 1.99}, True),
        ({"net_debt_to_ebitda": 5.00, "interest_coverage": 1.99}, None),
        ({"net_debt_to_ebitda": 5.01, "interest_coverage": 2.00}, None),
        ({"debt_outstanding": 1.0, "interest_coverage": 0.99}, True),
        ({"debt_outstanding": 1.0, "interest_coverage": 1.00}, None),
        ({"liquidity_coverage": 0.99, "financing_secured": None}, True),
        ({"liquidity_coverage": 0.99, "financing_secured": False}, True),
        ({"liquidity_coverage": 0.99, "financing_secured": True}, None),
        ({"trailing_fcf": -1.0, "cash_runway_months": 11.99, "financing_secured": None}, True),
        ({"trailing_fcf": -1.0, "cash_runway_months": 12.00, "financing_secured": None}, None),
        ({"net_cash": True}, False),
        ({"net_debt_to_ebitda": 3.00, "interest_coverage": 3.00}, False),
        ({"net_debt_to_ebitda": 3.01, "interest_coverage": 3.00}, None),
        ({"net_debt_to_ebitda": 3.00, "interest_coverage": 2.99}, None),
        ({"liquidity_coverage": 1.50, "trailing_fcf": 1.0}, False),
        ({"liquidity_coverage": 1.499, "trailing_fcf": 1.0}, None),
        ({"liquidity_coverage": 1.50, "trailing_fcf": 0.0}, None),
        ({"trailing_fcf": -1.0, "cash_runway_months": 18.0}, False),
        ({"trailing_fcf": -1.0, "cash_runway_months": 17.99}, None),
        ({}, None),
        ({"net_debt_to_ebitda": 7.0, "interest_coverage": 3.0}, None),
        ({"net_debt_to_ebitda": 2.0, "interest_coverage": 1.5}, None),
    ],
)
def test_corporate_frozen_boundaries(kwargs, expected):
    result = classify(metrics(DistressSectorAdapter.CORPORATE, **kwargs))
    assert result.balance_sheet_distressed is expected


@pytest.mark.parametrize(
    "kwargs,expected",
    [
        ({"net_debt_to_ebitda": 7.01, "interest_coverage": 1.49}, True),
        ({"net_debt_to_ebitda": 7.00, "interest_coverage": 1.49}, None),
        ({"net_debt_to_ebitda": 7.01, "interest_coverage": 1.50}, None),
        ({"liquidity_coverage": 0.99, "financing_secured": None}, True),
        ({"net_debt_to_ebitda": 5.50, "interest_coverage": 2.00}, False),
        ({"net_debt_to_ebitda": 5.51, "interest_coverage": 2.00}, None),
        ({"net_debt_to_ebitda": 5.50, "interest_coverage": 1.99}, None),
    ],
)
def test_utility_frozen_boundaries(kwargs, expected):
    result = classify(metrics(DistressSectorAdapter.UTILITY, **kwargs))
    assert result.balance_sheet_distressed is expected


@pytest.mark.parametrize(
    "kwargs,expected",
    [
        ({"debt_to_ebitdare": 8.01, "fixed_charge_coverage": 1.49}, True),
        ({"debt_to_ebitdare": 8.00, "fixed_charge_coverage": 1.49}, None),
        ({"debt_to_ebitdare": 8.01, "fixed_charge_coverage": 1.50}, None),
        ({"liquidity_coverage": 0.99, "financing_secured": False}, True),
        ({"debt_to_ebitdare": 6.50, "fixed_charge_coverage": 2.00}, False),
        ({"debt_to_ebitdare": 6.51, "fixed_charge_coverage": 2.00}, None),
        ({"debt_to_ebitdare": 6.50, "fixed_charge_coverage": 1.99}, None),
    ],
)
def test_reit_frozen_boundaries(kwargs, expected):
    result = classify(metrics(DistressSectorAdapter.REIT, **kwargs))
    assert result.balance_sheet_distressed is expected


@pytest.mark.parametrize(
    "kwargs,expected",
    [
        ({"regulatory_capital_breach": True}, True),
        ({"prompt_corrective_action_unresolved": True}, True),
        ({"cet1_ratio": 0.099, "cet1_requirement_plus_buffer": 0.10}, True),
        ({"cet1_ratio": 0.10, "cet1_requirement_plus_buffer": 0.10}, None),
        ({"cet1_ratio": 0.125, "cet1_requirement_plus_buffer": 0.10}, False),
        ({"cet1_ratio": 0.1249, "cet1_requirement_plus_buffer": 0.10}, None),
    ],
)
def test_bank_uses_only_regulatory_capital_adapter(kwargs, expected):
    result = classify(metrics(DistressSectorAdapter.BANK, **kwargs))
    assert result.balance_sheet_distressed is expected


@pytest.mark.parametrize(
    "kwargs,expected",
    [
        ({"insurer_solvency_ratio": 0.99, "insurer_regulatory_action_threshold": 1.0}, True),
        ({"insurer_solvency_ratio": 1.0, "insurer_regulatory_action_threshold": 1.0}, None),
        ({"insurer_solvency_ratio": 1.5, "insurer_regulatory_action_threshold": 1.0}, False),
        ({"insurer_solvency_ratio": 1.499, "insurer_regulatory_action_threshold": 1.0}, None),
        ({"insurer_solvency_ratio": 2.0, "insurer_regulatory_action_threshold": None}, None),
    ],
)
def test_insurer_regulatory_threshold_adapter(kwargs, expected):
    result = classify(metrics(DistressSectorAdapter.INSURER, **kwargs))
    assert result.balance_sheet_distressed is expected


def test_financials_are_not_classified_with_corporate_leverage_thresholds():
    bank = classify(
        metrics(
            DistressSectorAdapter.BANK,
            net_debt_to_ebitda=20.0,
            interest_coverage=0.1,
        )
    )
    insurer = classify(
        metrics(
            DistressSectorAdapter.INSURER,
            net_debt_to_ebitda=20.0,
            interest_coverage=0.1,
        )
    )
    assert bank.balance_sheet_distressed is None
    assert insurer.balance_sheet_distressed is None


def test_missing_primary_source_provenance_cannot_be_called_safe():
    result = classify(
        DistressInputs(
            ticker="TEST",
            sector_adapter=DistressSectorAdapter.CORPORATE,
            as_of=NOW,
            net_cash=True,
            sources=[],
        )
    )
    assert result.classification is DistressClassification.UNKNOWN
    assert result.balance_sheet_distressed is None
    assert result.rule_path == "balance_sheet_distress_v1_1.missing_provenance"


def test_unknown_is_null_not_false():
    result = classify(metrics(DistressSectorAdapter.CORPORATE))
    assert result.classification is DistressClassification.UNKNOWN
    assert result.balance_sheet_distressed is None
