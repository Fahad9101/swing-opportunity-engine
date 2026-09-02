from datetime import UTC, datetime

from app.cli_distress_validation import _gray_zone_reasons, _sufficient_inputs
from app.core.config import SOE_1_1_RULES_PATH, load_rules_for_version
from app.domain.distress_v1_1 import DistressHardFlag, DistressInputs, DistressSectorAdapter


NOW = datetime(2026, 9, 2, tzinfo=UTC)
RULES = load_rules_for_version(SOE_1_1_RULES_PATH, "SOE-1.1.0")


def metrics(adapter=DistressSectorAdapter.CORPORATE, **updates):
    payload = {"ticker": "TEST", "sector_adapter": adapter, "as_of": NOW}
    payload.update(updates)
    return DistressInputs(**payload)


def sufficient(adapter, values):
    return _sufficient_inputs(adapter, values, RULES)


def test_absolute_coverage_above_distress_threshold_is_partial_not_sufficient():
    ok, reasons = sufficient(
        DistressSectorAdapter.CORPORATE,
        metrics(debt_outstanding=100.0, interest_coverage=2.7),
    )
    assert ok is False
    assert reasons == []


def test_absolute_coverage_below_one_is_a_complete_distress_path():
    ok, reasons = sufficient(
        DistressSectorAdapter.CORPORATE,
        metrics(debt_outstanding=100.0, interest_coverage=0.9),
    )
    assert ok is True
    assert "absolute_interest_coverage_distress_path" in reasons


def test_corporate_safe_pair_is_decision_eligible():
    values = metrics(net_debt_to_ebitda=2.9, interest_coverage=4.0)
    ok, reasons = sufficient(DistressSectorAdapter.CORPORATE, values)
    assert ok is True
    assert "leverage_coverage_safe_path" in reasons
    assert _gray_zone_reasons(DistressSectorAdapter.CORPORATE, values, RULES) == []


def test_complete_corporate_pair_in_gray_zone_is_not_in_coverage_denominator():
    values = metrics(net_debt_to_ebitda=3.1155, interest_coverage=6.82)
    ok, reasons = sufficient(DistressSectorAdapter.CORPORATE, values)
    assert ok is False
    assert reasons == []
    assert _gray_zone_reasons(DistressSectorAdapter.CORPORATE, values, RULES) == [
        "corporate_leverage_coverage_gray_zone"
    ]


def test_complete_utility_pair_in_gray_zone_is_not_in_coverage_denominator():
    values = metrics(
        adapter=DistressSectorAdapter.UTILITY,
        net_debt_to_ebitda=5.853,
        interest_coverage=2.81,
    )
    ok, reasons = sufficient(DistressSectorAdapter.UTILITY, values)
    assert ok is False
    assert reasons == []
    assert _gray_zone_reasons(DistressSectorAdapter.UTILITY, values, RULES) == [
        "utility_leverage_coverage_gray_zone"
    ]


def test_verified_hard_flag_is_sufficient():
    ok, reasons = sufficient(
        DistressSectorAdapter.CORPORATE,
        metrics(hard_distress_flags=[DistressHardFlag.GOING_CONCERN]),
    )
    assert ok is True
    assert reasons == ["verified_hard_distress_flag"]


def test_bank_mid_buffer_zone_is_not_decision_eligible():
    values = metrics(
        adapter=DistressSectorAdapter.BANK,
        cet1_ratio=0.115,
        cet1_requirement_plus_buffer=0.10,
    )
    ok, reasons = sufficient(DistressSectorAdapter.BANK, values)
    assert ok is False
    assert reasons == []
    assert _gray_zone_reasons(DistressSectorAdapter.BANK, values, RULES) == ["bank_cet1_gray_zone"]


def test_bank_never_counts_corporate_leverage_as_sufficient():
    ok, reasons = sufficient(
        DistressSectorAdapter.BANK,
        metrics(
            adapter=DistressSectorAdapter.BANK,
            net_debt_to_ebitda=9.0,
            interest_coverage=0.5,
        ),
    )
    assert ok is False
    assert reasons == []
