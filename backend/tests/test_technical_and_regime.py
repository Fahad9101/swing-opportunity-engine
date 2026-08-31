from datetime import date, timedelta

from app.domain.enums import Regime
from app.domain.schemas import OHLCVBar
from app.services.regime_service import calculate_market_regime
from app.services.technical_service import build_market_snapshot, calculate_atr, calculate_rsi
from conftest import market_factory


def test_indicators_calculate_from_ohlcv(rules):
    bars = []
    start = date(2025, 1, 1)
    for index in range(260):
        close = 100 + index * 0.2
        bars.append(OHLCVBar(date=start + timedelta(days=index), open=close - 0.1, high=close + 1, low=close - 1, close=close, volume=1_000_000 + index))
    snapshot = build_market_snapshot("TEST", bars, "test", rules)
    assert snapshot.sma20 is not None
    assert snapshot.sma50 is not None
    assert snapshot.sma200 is not None
    assert snapshot.rsi14 == 100
    assert snapshot.atr14 is not None
    assert snapshot.avg_dollar_volume_20d > 0


def test_missing_rsi_history_is_none():
    assert calculate_rsi([1, 2, 3], 14) is None


def test_green_regime(rules):
    spy = market_factory(ticker="SPY", price=520, sma50=500, sma200=470)
    qqq = market_factory(ticker="QQQ", price=480, sma50=460, sma200=430)
    iwm = market_factory(ticker="IWM")
    result = calculate_market_regime(spy, qqq, iwm, 18, 55, rules)
    assert result.regime == Regime.GREEN


def test_red_regime_both_indices_below_200(rules):
    spy = market_factory(ticker="SPY", price=430, sma50=450, sma200=470)
    qqq = market_factory(ticker="QQQ", price=390, sma50=410, sma200=430)
    result = calculate_market_regime(spy, qqq, market_factory(ticker="IWM"), 22, 50, rules)
    assert result.regime == Regime.RED


def test_yellow_regime_mixed(rules):
    spy = market_factory(ticker="SPY", price=480, sma50=490, sma200=470)
    qqq = market_factory(ticker="QQQ", price=450, sma50=440, sma200=430)
    result = calculate_market_regime(spy, qqq, market_factory(ticker="IWM"), 22, 50, rules)
    assert result.regime == Regime.YELLOW

