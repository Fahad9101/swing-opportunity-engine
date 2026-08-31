from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from app.domain.schemas import FundamentalSnapshot, OHLCVBar
from app.scoring.valuation_score import score_valuation
from app.services.valuation_service import derive_historical_normalized_value, enrich_fundamental_valuation


def _history(metric: float = 25.0, revenue: float = 100.0):
    ends = [
        date(2024, 6, 30),
        date(2024, 9, 30),
        date(2024, 12, 31),
        date(2025, 3, 31),
        date(2025, 6, 30),
        date(2025, 9, 30),
        date(2025, 12, 31),
        date(2026, 3, 31),
    ]
    return {
        "net_income_quarters": [{"end": end.isoformat(), "val": metric} for end in ends],
        "revenue_quarters": [{"end": end.isoformat(), "val": revenue} for end in ends],
        "shares_instants": [{"end": end.isoformat(), "val": 10.0} for end in ends],
    }, ends


def _bars(ends, historical_price: float, current_price: float):
    fetched = datetime(2026, 8, 31, tzinfo=UTC)
    bars = []
    for end in ends:
        bars.append(
            OHLCVBar(
                date=end,
                open=historical_price,
                high=historical_price,
                low=historical_price,
                close=historical_price,
                volume=1_000_000,
                source="test",
                as_of=datetime.combine(end, datetime.min.time(), tzinfo=UTC),
                fetched_at=fetched,
            )
        )
    bars.append(
        OHLCVBar(
            date=date(2026, 8, 28),
            open=current_price,
            high=current_price,
            low=current_price,
            close=current_price,
            volume=1_000_000,
            source="test",
            as_of=datetime(2026, 8, 28, tzinfo=UTC),
            fetched_at=fetched,
        )
    )
    return bars


def _fundamental(history):
    stamp = datetime(2026, 8, 1, tzinfo=UTC)
    return FundamentalSnapshot(
        ticker="TEST",
        source="SEC EDGAR companyfacts",
        as_of=stamp,
        fetched_at=stamp,
        raw={"valuation_history": history},
    )


def _reference(target: float):
    stamp = datetime(2026, 8, 31, tzinfo=UTC)
    return SimpleNamespace(
        target_mean_price=target,
        target_low_price=target * 0.9,
        target_high_price=target * 1.1,
        analyst_opinions=12,
        source="test analyst target",
        as_of=stamp,
        fetched_at=stamp,
        stale=False,
    )


def test_historical_support_and_analyst_headroom_feed_independent_frozen_components():
    history, ends = _history(metric=25.0)
    bars = _bars(ends, historical_price=200.0, current_price=160.0)
    result = enrich_fundamental_valuation(_fundamental(history), bars, _reference(240.0))

    assert result.fundamental_undervaluation == pytest.approx(0.25)
    assert result.valuation_discount is True
    assert result.expected_swing_upside == pytest.approx(0.50)
    assert result.raw["valuation"]["historical"]["method"] == "HISTORICAL_MEDIAN_PE"
    assert result.raw["valuation"]["historical"]["observation_count"] == 4
    assert result.raw["valuation"]["expected_swing_upside_method"] == "CONSENSUS_TARGET_HEADROOM_PROXY_NOT_MILESTONE3_TARGET"

    score = score_valuation(result)
    assert score.available is True
    assert score.available_points == 20
    assert score.score == 18  # 12 upside + 6 support under frozen SOE bands


def test_historical_overvaluation_remains_negative_support_even_with_positive_analyst_headroom():
    history, ends = _history(metric=25.0)
    bars = _bars(ends, historical_price=200.0, current_price=250.0)
    result = enrich_fundamental_valuation(_fundamental(history), bars, _reference(305.0))

    assert result.fundamental_undervaluation == pytest.approx(-0.20)
    assert result.valuation_discount is False
    assert result.expected_swing_upside == pytest.approx(0.22)
    score = score_valuation(result)
    assert score.score == 6  # upside contributes; historical support correctly contributes zero


def test_price_to_sales_is_used_only_as_explicit_fallback_when_earnings_are_not_usable():
    history, ends = _history(metric=-10.0, revenue=100.0)
    bars = _bars(ends, historical_price=50.0, current_price=40.0)
    fundamental = _fundamental(history)

    historical = derive_historical_normalized_value(fundamental, bars, allow_sales_fallback=True)
    assert historical is not None
    assert historical["method"] == "HISTORICAL_MEDIAN_PS"
    assert historical["normalized_value_per_share"] == pytest.approx(50.0)

    no_fallback = derive_historical_normalized_value(fundamental, bars, allow_sales_fallback=False)
    assert no_fallback is None


def test_share_discontinuity_uses_current_share_basis_with_split_adjusted_prices():
    history, ends = _history(metric=25.0)
    # Mimic SEC pre/post-split and retrospectively restated instant share facts.
    history["shares_instants"] = [
        {"end": end.isoformat(), "val": 10.0 if index % 2 == 0 else 20.0}
        for index, end in enumerate(ends)
    ]
    # Latest/current basis is 20 shares.
    history["shares_instants"][-1]["val"] = 20.0
    bars = _bars(ends, historical_price=100.0, current_price=100.0)
    result = derive_historical_normalized_value(_fundamental(history), bars, allow_sales_fallback=True)

    assert result is not None
    assert result["share_basis"] == "CURRENT_SHARES_SPLIT_NORMALIZED"
    assert all(row["shares"] == 20.0 for row in result["observations"])


def test_analyst_target_can_supply_upside_proxy_without_manufacturing_fundamental_support():
    history, ends = _history(metric=25.0)
    # Remove enough history to fail the four-observation data-quality minimum.
    history["net_income_quarters"] = history["net_income_quarters"][-5:]
    history["revenue_quarters"] = history["revenue_quarters"][-5:]
    bars = _bars(ends, historical_price=100.0, current_price=100.0)
    result = enrich_fundamental_valuation(_fundamental(history), bars, _reference(125.0))

    assert result.fundamental_undervaluation is None
    assert result.valuation_discount is None
    assert result.expected_swing_upside == pytest.approx(0.25)
    score = score_valuation(result)
    assert score.available_points == 12
    assert score.score == 8


def test_stale_analyst_target_is_not_used_for_expected_swing_upside():
    history, ends = _history(metric=25.0)
    bars = _bars(ends, historical_price=200.0, current_price=160.0)
    reference = _reference(240.0)
    reference.stale = True
    result = enrich_fundamental_valuation(_fundamental(history), bars, reference)

    assert result.fundamental_undervaluation == pytest.approx(0.25)
    assert result.expected_swing_upside is None
    assert score_valuation(result).available_points == 8
