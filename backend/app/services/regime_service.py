from __future__ import annotations

from datetime import UTC, datetime

from app.domain.enums import Regime
from app.domain.schemas import MarketRegimeResult, MarketSnapshot


def calculate_market_regime(spy: MarketSnapshot, qqq: MarketSnapshot, iwm: MarketSnapshot, vix: float | None, breadth_pct: float | None, rules: dict, *, vix_metadata: dict | None = None, breadth_metadata: dict | None = None) -> MarketRegimeResult:
    config = rules["market_regime"]
    spy_green = bool(spy.sma50 and spy.sma200 and spy.price > spy.sma50 > spy.sma200)
    qqq_green = bool(qqq.sma50 and qqq.sma200 and qqq.price > qqq.sma50 > qqq.sma200)
    both_below_200 = bool(spy.sma200 and qqq.sma200 and spy.price < spy.sma200 and qqq.price < qqq.sma200)
    vix_stress = vix is not None and vix >= config["red_vix_min"]
    breadth_stress = breadth_pct is not None and breadth_pct < config["red_breadth_max_pct"]
    no_volatility_stress = vix is None or vix < config["green_vix_max"]
    breadth_ok = breadth_pct is None or breadth_pct >= config["green_breadth_min_pct"]
    reasons: list[str] = []
    if both_below_200 or vix_stress or breadth_stress:
        regime, score = Regime.RED, 0
        if both_below_200: reasons.append("SPY_AND_QQQ_BELOW_SMA200")
        if vix_stress: reasons.append("VIX_STRESS")
        if breadth_stress: reasons.append("BREADTH_STRESS")
    elif spy_green and qqq_green and no_volatility_stress and breadth_ok:
        regime, score = Regime.GREEN, 100
        reasons.append("SPY_AND_QQQ_CONFIRMED_UPTRENDS")
        reasons.append("NO_VOLATILITY_STRESS")
    else:
        regime, score = Regime.YELLOW, 50
        reasons.append("MIXED_MARKET_CONDITIONS")
    compact = lambda item: {"price": item.price, "sma50": item.sma50, "sma200": item.sma200, "source": item.source, "as_of": item.as_of.isoformat(), "fetched_at": item.fetched_at.isoformat(), "stale": item.stale}
    vix_data = {"value": vix, **(vix_metadata or {})}
    breadth_data = {"pct_above_sma50": breadth_pct, "breadth_available": breadth_pct is not None, **(breadth_metadata or {})}
    return MarketRegimeResult(regime=regime, regime_score=score, spy_data=compact(spy), qqq_data=compact(qqq), iwm_data=compact(iwm), vix_data=vix_data, breadth_data=breadth_data, timestamp=datetime.now(UTC), reasons=reasons, breadth_available=breadth_pct is not None)
