from datetime import UTC, date, datetime, timedelta

import pytest

from app.domain.enums import CatalystGrade
from app.domain.schemas import Catalyst, EstimateSnapshot, FundamentalSnapshot
from app.screeners.biotech_catalyst import BiotechCatalystScreener
from app.screeners.growth_pullback import GrowthPullbackScreener
from app.screeners.rerating import ReratingScreener


def provenance():
    now = datetime.now(UTC)
    return dict(source="test", as_of=now, fetched_at=now)


def normal_fundamental(**updates):
    values = dict(ticker="TEST", revenue_growth=0.15, revenue_growth_qoq=0.02, fcf_growth=0.15, forward_ebitda_growth=0.15, operating_margin=0.12, operating_margin_prior=0.10, operating_margin_expansion_bps=100, cash=100, debt=20, balance_sheet_distressed=False, guidance_deterioration=False, valuation_discount=True, **provenance())
    values.update(updates)
    return FundamentalSnapshot(**values)


def estimates(**updates):
    values = dict(ticker="TEST", forward_eps_growth=0.16, eps_up_revisions=8, eps_down_revisions=2, revenue_up_revisions=7, revenue_down_revisions=3, ebitda_up_revisions=6, ebitda_down_revisions=3, **provenance())
    values.update(updates)
    return EstimateSnapshot(**values)


def test_rerating_three_of_six_fails(instrument, market, rules):
    fundamental = normal_fundamental(operating_margin=None, operating_margin_prior=None, fcf_growth=None, forward_ebitda_growth=None, valuation_discount=False)
    result = ReratingScreener().evaluate(instrument, market, fundamental, estimates(), [], rules)
    assert result.conditions_met == 3
    assert result.qualified is False


def test_rerating_four_of_six_passes(instrument, market, rules):
    fundamental = normal_fundamental(operating_margin=None, operating_margin_prior=None, fcf_growth=None, forward_ebitda_growth=None)
    result = ReratingScreener().evaluate(instrument, market, fundamental, estimates(), [], rules)
    assert result.conditions_met == 4
    assert result.qualified is True


@pytest.mark.parametrize("growth,passed", [(0.1499, False), (0.15, True)])
def test_growth_boundary_normal(instrument, market, rules, growth, passed):
    result = GrowthPullbackScreener().evaluate(instrument, market, normal_fundamental(revenue_growth=growth), estimates(), [], rules)
    assert result.qualified is passed


@pytest.mark.parametrize("growth,passed", [(0.0999, False), (0.10, True)])
def test_growth_boundary_large_cap(instrument, market, rules, growth, passed):
    large = instrument.model_copy(update={"market_cap": 20_000_000_000})
    result = GrowthPullbackScreener().evaluate(large, market, normal_fundamental(revenue_growth=growth), estimates(), [], rules)
    assert result.qualified is passed


def biotech_catalyst():
    now = datetime.now(UTC)
    return Catalyst(ticker="TEST", type="CLINICAL", title="Verified test catalyst", event_date=date.today() + timedelta(days=21), grade=CatalystGrade.A, materiality=10, surprise_potential=4, verified=True, source_timestamp=now, summary="test", source="test", as_of=now, fetched_at=now)


@pytest.mark.parametrize("runway,secured,passed", [(8.9, False, False), (8.9, True, True), (12.0, False, True)])
def test_biotech_runway_boundaries(instrument, market, rules, runway, secured, passed):
    bio = instrument.model_copy(update={"is_biotech": True, "market_cap": 1_000_000_000})
    fundamental = normal_fundamental(cash_runway_months=runway, financing_secured=secured)
    result = BiotechCatalystScreener().evaluate(bio, market, fundamental, None, [biotech_catalyst()], rules)
    assert result.qualified is passed


def test_grade_c_cannot_qualify(instrument, market, rules):
    bio = instrument.model_copy(update={"is_biotech": True})
    catalyst = biotech_catalyst().model_copy(update={"grade": CatalystGrade.C})
    result = BiotechCatalystScreener().evaluate(bio, market, normal_fundamental(cash_runway_months=18), None, [catalyst], rules)
    assert result.qualified is False

