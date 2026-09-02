from datetime import UTC, datetime

import pytest

from app.domain.distress_v1_1 import DistressRawFacts, DistressSectorAdapter
from app.services.distress_metric_service import derive_distress_inputs


NOW = datetime(2026, 9, 2, tzinfo=UTC)
SOURCE = "https://www.sec.gov/Archives/edgar/data/1/test.htm"


def raw(**updates) -> DistressRawFacts:
    payload = {
        "ticker": "TEST",
        "sector_adapter": DistressSectorAdapter.CORPORATE,
        "as_of": NOW,
        "sources": [SOURCE],
    }
    payload.update(updates)
    return DistressRawFacts(**payload)


def test_derives_net_debt_to_ebitda_from_complete_liquid_assets():
    result = derive_distress_inputs(raw(debt=500.0, cash=100.0, marketable_securities=50.0, liquid_assets_complete=True, ebitda=100.0))
    assert result.net_cash is False
    assert result.net_debt_to_ebitda == pytest.approx(3.5)


def test_net_cash_can_be_proven_by_cash_alone_even_if_securities_incomplete():
    result = derive_distress_inputs(raw(debt=100.0, cash=120.0, ebitda=50.0))
    assert result.net_cash is True
    assert result.net_debt_to_ebitda is None


def test_incomplete_liquid_assets_cannot_create_adverse_leverage_ratio():
    result = derive_distress_inputs(raw(debt=500.0, cash=100.0, ebitda=100.0))
    assert result.net_cash is None
    assert result.net_debt_to_ebitda is None
    assert result.audit["leverage_suppressed_incomplete_liquid_assets"] is True


def test_explicit_total_liquid_assets_supports_leverage():
    result = derive_distress_inputs(raw(debt=500.0, liquid_assets_total=150.0, ebitda=100.0))
    assert result.net_cash is False
    assert result.net_debt_to_ebitda == pytest.approx(3.5)


@pytest.mark.parametrize("ebitda", [0.0, -1.0])
def test_nonpositive_ebitda_suppresses_leverage(ebitda):
    result = derive_distress_inputs(raw(debt=500.0, cash=100.0, marketable_securities=0.0, liquid_assets_complete=True, ebitda=ebitda))
    assert result.net_debt_to_ebitda is None
    assert result.audit["leverage_suppressed_nonpositive_ebitda"] is True


def test_interest_coverage_uses_ebit_not_ebitda():
    result = derive_distress_inputs(raw(ebit=75.0, ebitda=150.0, cash_interest_expense=25.0))
    assert result.interest_coverage == pytest.approx(3.0)


@pytest.mark.parametrize("interest", [None, 0.0, -1.0])
def test_invalid_interest_expense_keeps_coverage_null(interest):
    result = derive_distress_inputs(raw(ebit=75.0, cash_interest_expense=interest))
    assert result.interest_coverage is None


def test_liquidity_coverage_uses_complete_liquid_assets_committed_revolver_and_positive_fcf():
    result = derive_distress_inputs(
        raw(
            cash=100.0,
            marketable_securities=20.0,
            liquid_assets_complete=True,
            committed_undrawn_revolver=80.0,
            trailing_fcf=50.0,
            debt_maturities_12m=100.0,
        )
    )
    assert result.committed_liquidity == pytest.approx(250.0)
    assert result.liquidity_coverage == pytest.approx(2.5)


def test_negative_fcf_does_not_increase_committed_liquidity():
    result = derive_distress_inputs(
        raw(
            cash=100.0,
            marketable_securities=20.0,
            liquid_assets_complete=True,
            committed_undrawn_revolver=80.0,
            trailing_fcf=-50.0,
            debt_maturities_12m=100.0,
        )
    )
    assert result.committed_liquidity == pytest.approx(200.0)
    assert result.liquidity_coverage == pytest.approx(2.0)


def test_missing_revolver_or_incomplete_liquid_assets_keeps_liquidity_null():
    incomplete = derive_distress_inputs(raw(cash=100.0, committed_undrawn_revolver=80.0, debt_maturities_12m=100.0))
    no_revolver = derive_distress_inputs(raw(liquid_assets_total=100.0, debt_maturities_12m=100.0))
    assert incomplete.liquidity_coverage is None
    assert no_revolver.liquidity_coverage is None


@pytest.mark.parametrize("maturities", [None, 0.0, -1.0])
def test_unverified_or_nonpositive_maturities_keep_liquidity_coverage_null(maturities):
    result = derive_distress_inputs(
        raw(
            cash=100.0,
            marketable_securities=20.0,
            liquid_assets_complete=True,
            committed_undrawn_revolver=80.0,
            trailing_fcf=50.0,
            debt_maturities_12m=maturities,
        )
    )
    assert result.liquidity_coverage is None
    assert result.audit["liquidity_suppressed_without_positive_12m_maturities"] is True


def test_negative_fcf_runway_is_derived_only_from_complete_liquid_assets():
    result = derive_distress_inputs(raw(cash=100.0, marketable_securities=20.0, liquid_assets_complete=True, trailing_fcf=-80.0))
    assert result.cash_runway_months == pytest.approx(18.0)
    incomplete = derive_distress_inputs(raw(cash=100.0, trailing_fcf=-80.0))
    assert incomplete.cash_runway_months is None


def test_explicit_cash_runway_is_not_overwritten():
    result = derive_distress_inputs(raw(cash=100.0, trailing_fcf=-80.0, cash_runway_months=30.0))
    assert result.cash_runway_months == 30.0


def test_reit_bank_and_insurer_metrics_pass_through_without_corporate_substitution():
    result = derive_distress_inputs(
        raw(
            sector_adapter=DistressSectorAdapter.REIT,
            debt_to_ebitdare=6.0,
            fixed_charge_coverage=2.5,
            cet1_ratio=0.12,
            cet1_requirement_plus_buffer=0.09,
            insurer_solvency_ratio=3.0,
            insurer_regulatory_action_threshold=1.0,
        )
    )
    assert result.debt_to_ebitdare == 6.0
    assert result.fixed_charge_coverage == 2.5
    assert result.cet1_ratio == 0.12
    assert result.insurer_solvency_ratio == 3.0


def test_sources_are_deduplicated_for_provenance():
    result = derive_distress_inputs(raw(sources=[SOURCE, SOURCE]))
    assert result.sources == [SOURCE]
