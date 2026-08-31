from __future__ import annotations

from datetime import UTC, datetime

from app.domain.schemas import FieldProvenance, MarketSnapshot, OHLCVBar
from app.services.trading_calendar_service import is_eod_stale


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _sma(closes: list[float], period: int, offset: int = 0) -> float | None:
    end = len(closes) - offset
    start = end - period
    return _mean(closes[start:end]) if start >= 0 and end > start else None


def _return(closes: list[float], sessions: int) -> float | None:
    if len(closes) <= sessions or closes[-sessions - 1] == 0:
        return None
    return closes[-1] / closes[-sessions - 1] - 1


def calculate_rsi(closes: list[float], period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    changes = [closes[i] - closes[i - 1] for i in range(len(closes) - period, len(closes))]
    avg_gain = _mean([max(change, 0) for change in changes])
    avg_loss = _mean([max(-change, 0) for change in changes])
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calculate_atr(bars: list[OHLCVBar], period: int = 14) -> float | None:
    if len(bars) < period + 1:
        return None
    true_ranges: list[float] = []
    for index in range(len(bars) - period, len(bars)):
        bar = bars[index]
        previous_close = bars[index - 1].close
        true_ranges.append(max(bar.high - bar.low, abs(bar.high - previous_close), abs(bar.low - previous_close)))
    return _mean(true_ranges)


def build_market_snapshot(ticker: str, bars: list[OHLCVBar], source: str, rules: dict) -> MarketSnapshot:
    if len(bars) < 2:
        raise ValueError("At least two OHLCV bars are required")
    bars = sorted(bars, key=lambda item: item.date)
    closes = [bar.close for bar in bars]
    volumes = [bar.volume for bar in bars]
    price = closes[-1]
    avg_volume = _mean(volumes[-20:])
    avg_dollar_volume = _mean([bar.close * bar.volume for bar in bars[-20:]])
    sma20, sma50, sma200 = _sma(closes, 20), _sma(closes, 50), _sma(closes, 200)
    prior_sma50, prior_sma200 = _sma(closes, 50, 20), _sma(closes, 200, 20)
    distance = lambda value: (price - value) / value if value else None
    high20 = max(bar.high for bar in bars[-20:])
    high50 = max(bar.high for bar in bars[-50:])
    lookback = bars[-252:]
    high52 = max(bar.high for bar in lookback)
    low52 = min(bar.low for bar in lookback)
    returns = [bars[i].close / bars[i - 1].close - 1 for i in range(1, len(bars))]
    stable_sessions = 0
    atr = calculate_atr(bars)
    for bar in reversed(bars[-20:]):
        if atr is not None and abs(bar.close - price) <= 2 * atr:
            stable_sessions += 1
        else:
            break
    low_volume_pullback = (_return(closes, 5) or 0) < 0 and _mean(volumes[-5:]) < rules["technical"]["low_volume_pullback_ratio"] * avg_volume
    up_volume = sum(bars[i].volume for i in range(max(1, len(bars) - 20), len(bars)) if returns[i - 1] > 0)
    down_volume = sum(bars[i].volume for i in range(max(1, len(bars) - 20), len(bars)) if returns[i - 1] < 0)
    accumulation = down_volume > 0 and up_volume / down_volume >= rules["technical"]["accumulation_up_down_ratio"]
    relative_volume = volumes[-1] / avg_volume if avg_volume else 0
    now = datetime.now(UTC)
    as_of = datetime.combine(bars[-1].date, datetime.min.time(), tzinfo=UTC)
    stale = is_eod_stale(as_of, now)
    technical_fields = (
        "price", "previous_close", "volume", "avg_volume_20d", "avg_dollar_volume_20d", "relative_volume",
        "sma20", "sma50", "sma200", "sma50_slope_20d", "sma200_slope_20d", "rsi14", "atr14",
        "high20d", "high50d", "high52w", "low52w", "return1d", "return3d", "return5d", "return20d",
        "distance_from_sma20_pct", "distance_from_sma50_pct", "distance_from_sma200_pct", "pullback_from_50d_high_pct",
    )
    provenance = {field: FieldProvenance(source=source, as_of=as_of, fetched_at=now, stale=stale, raw_field="daily_ohlcv") for field in technical_fields}
    return MarketSnapshot(
        ticker=ticker, price=price, previous_close=closes[-2], volume=volumes[-1], avg_volume_20d=avg_volume,
        avg_dollar_volume_20d=avg_dollar_volume, relative_volume=relative_volume, sma20=sma20, sma50=sma50,
        sma200=sma200, sma50_slope_20d=((sma50 - prior_sma50) / prior_sma50 if sma50 and prior_sma50 else None),
        sma200_slope_20d=((sma200 - prior_sma200) / prior_sma200 if sma200 and prior_sma200 else None),
        rsi14=calculate_rsi(closes), atr14=atr, high20d=high20, high50d=high50, high52w=high52, low52w=low52,
        return1d=closes[-1] / closes[-2] - 1, return3d=_return(closes, 3), return5d=_return(closes, 5), return20d=_return(closes, 20),
        distance_from_sma20_pct=distance(sma20), distance_from_sma50_pct=distance(sma50), distance_from_sma200_pct=distance(sma200),
        pullback_from_50d_high_pct=(high50 - price) / high50, trading_days=len(bars), stable_sessions=stable_sessions,
        new_52w_low_last_10=min(bar.low for bar in bars[-10:]) <= low52, low_volume_pullback=low_volume_pullback,
        accumulation_evidence=accumulation, reversal_rvol=returns[-1] > 0 and relative_volume >= rules["technical"]["reversal_min_relative_volume"],
        source=source, as_of=as_of, fetched_at=now, stale=stale, field_provenance=provenance,
    )
