from datetime import UTC, datetime

from app.cli_distress_validation import _sufficient_inputs
from app.domain.distress_v1_1 import DistressHardFlag, DistressInputs, DistressSectorAdapter


NOW = datetime(2026, 9, 2, tzinfo=UTC)


def metrics(adapter=DistressSectorAdapter.CORPORATE, **updates):
    payload = {"ticker": "TEST", "sector_adapter": adapter, "as_of": NOW}
    payload.update(updates)
    return DistressInputs(**payload)


def test_absolute_coverage_above_distress_threshold_is_partial_not_sufficient():
    sufficient, reasons = _sufficient_inputs(
        DistressSectorAdapter.CORPORATE,
        metrics(debt_outstanding=100.0, interest_coverage=2.7),
    )
    assert sufficient is False
    assert reasons == []


def test_absolute_coverage_below_one_is_a_complete_distress_path():
    sufficient, reasons = _sufficient_inputs(
        DistressSectorAdapter.CORPORATE,
        metrics(debt_outstanding=100.0, interest_coverage=0.9),
    )
    assert sufficient is True
    assert "absolute_interest_coverage_distress_path" in reasons


def test_complete_leverage_coverage_pair_counts_as_sufficient_even_in_gray_zone():
    sufficient, reasons = _sufficient_inputs(
        DistressSectorAdapter.CORPORATE,
        metrics(net_debt_to_ebitda=4.0, interest_coverage=4.0),
    )
    assert sufficient is True
    assert "complete_leverage_and_interest_coverage_pair" in reasons


def test_verified_hard_flag_is_sufficient():
    sufficient, reasons = _sufficient_inputs(
        DistressSectorAdapter.CORPORATE,
        metrics(hard_distress_flags=[DistressHardFlag.GOING_CONCERN]),
    )
    assert sufficient is True
    assert reasons == ["verified_hard_distress_flag"]


def test_bank_never_counts_corporate_leverage_as_sufficient():
    sufficient, reasons = _sufficient_inputs(
        DistressSectorAdapter.BANK,
        metrics(
            adapter=DistressSectorAdapter.BANK,
            net_debt_to_ebitda=9.0,
            interest_coverage=0.5,
        ),
    )
    assert sufficient is False
    assert reasons == []
