from app.domain.schemas import MarketSnapshot, ScoreComponent


def pullback_points(pct: float) -> int:
    pct *= 100
    if pct < 3: return 1
    if pct < 5: return 2
    if pct <= 15: return 4
    if pct <= 20: return 3
    if pct <= 30: return 1
    return 0


def rsi_points(rsi: float | None) -> int | None:
    if rsi is None: return None
    if 42 <= rsi <= 58: return 3
    if 38 <= rsi < 42 or 58 < rsi <= 65: return 2
    if 35 <= rsi < 38 or 65 < rsi <= 70: return 1
    return 0


def score_technical(market: MarketSnapshot, rules: dict) -> ScoreComponent:
    if market.sma200 is None:
        trend = 0
    elif market.sma50 and market.price > market.sma200 and market.sma50 > market.sma200 and (market.sma50_slope_20d or 0) > 0 and (market.sma200_slope_20d or 0) > 0:
        trend = 4
    elif market.price > market.sma200:
        trend = 3
    elif abs(market.price / market.sma200 - 1) <= rules["technical"]["around_sma200_pct"]:
        trend = 1
    else:
        trend = 0
    volume = min(4, (2 if market.low_volume_pullback else 0) + (1 if market.accumulation_evidence else 0) + (1 if market.reversal_rvol else 0))
    rsi = rsi_points(market.rsi14)
    parts = {"trend": trend, "pullback": pullback_points(market.pullback_from_50d_high_pct), "rsi": rsi, "volume": volume}
    return ScoreComponent(score=sum(value or 0 for value in parts.values()), maximum=15, available_points=15 if rsi is not None else 12, components=parts)
