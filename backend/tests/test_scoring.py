from datetime import date, timedelta

import pytest

from app.domain.schemas import ScoreComponent
from app.scoring.catalyst_score import _timing_score
from app.scoring.opportunity_score import calculate_opportunity_score, multi_scanner_bonus
from app.scoring.revision_score import breadth_points
from app.scoring.technical_score import pullback_points, rsi_points


@pytest.mark.parametrize("rsi,expected", [(34.99, 0), (35, 1), (38, 2), (42, 3), (58, 3), (58.01, 2), (65, 2), (65.01, 1), (70, 1), (70.01, 0)])
def test_rsi_boundaries(rsi, expected):
    assert rsi_points(rsi) == expected


@pytest.mark.parametrize("pct,expected", [(0.0299, 1), (0.03, 2), (0.05, 4), (0.15, 4), (0.20, 3), (0.30, 1), (0.3001, 0)])
def test_pullback_boundaries(pct, expected):
    assert pullback_points(pct) == expected


@pytest.mark.parametrize("days,expected", [(3, 3), (4, 5), (14, 5), (15, 5), (35, 5), (36, 3), (56, 3), (57, 0)])
def test_catalyst_timing_boundaries(days, expected):
    assert _timing_score(days) == expected


def test_revision_denominator_zero_is_unavailable():
    assert breadth_points(None) is None


@pytest.mark.parametrize("count,expected", [(1, 0), (2, 2), (3, 3), (5, 3)])
def test_multi_scanner_bonus(count, expected):
    assert multi_scanner_bonus(count) == expected


def components(score):
    maxima = {"catalyst": 25, "fundamental": 20, "valuation": 20, "technical": 15, "revisions": 10, "balance_sheet": 5, "liquidity": 5}
    return {name: ScoreComponent(score=value if name == "catalyst" else 0, maximum=maximum) for name, maximum, value in [(key, val, score) for key, val in maxima.items()]}


def test_component_sum_equals_base_score():
    values = {name: ScoreComponent(score=score, maximum=maximum) for name, score, maximum in [("catalyst", 18, 25), ("fundamental", 16, 20), ("valuation", 12, 20), ("technical", 13, 15), ("revisions", 8, 10), ("balance_sheet", 5, 5), ("liquidity", 5, 5)]}
    result = calculate_opportunity_score(values, -3, 2)
    assert result.base_opportunity_score == 77
    assert result.opportunity_score == 76


def test_score_clamps_at_zero_and_100():
    zeroes = {name: ScoreComponent(score=0, maximum=maximum) for name, maximum in [("catalyst", 25), ("fundamental", 20), ("valuation", 20), ("technical", 15), ("revisions", 10), ("balance_sheet", 5), ("liquidity", 5)]}
    assert calculate_opportunity_score(zeroes, -20, 1).opportunity_score == 0
    full = {name: item.model_copy(update={"score": item.maximum}) for name, item in zeroes.items()}
    assert calculate_opportunity_score(full, 0, 3).opportunity_score == 100

