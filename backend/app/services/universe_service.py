from __future__ import annotations

from app.domain.enums import RejectionCode
from app.domain.schemas import GateResult, Instrument, MarketSnapshot


def passes_universal_gate(instrument: Instrument, market: MarketSnapshot, rules: dict) -> GateResult:
    universe = rules["universe"]
    rejected: list[str] = []
    if not instrument.active:
        rejected.append(RejectionCode.INACTIVE_SECURITY)
    if instrument.exchange not in universe["allowed_exchanges"]:
        rejected.append(RejectionCode.INVALID_EXCHANGE)
    if instrument.asset_type.value not in universe["allowed_asset_types"]:
        rejected.append(RejectionCode.INVALID_ASSET_TYPE)
    if market.price < universe["min_price"]:
        rejected.append(RejectionCode.PRICE_TOO_LOW)
    min_cap = universe["biotech_min_market_cap"] if instrument.is_biotech else universe["min_market_cap"]
    if instrument.market_cap is None:
        rejected.append(RejectionCode.DATA_INSUFFICIENT)
    elif instrument.market_cap < min_cap:
        rejected.append(RejectionCode.MARKET_CAP_TOO_LOW)
    min_adv = universe["biotech_min_avg_dollar_volume"] if instrument.is_biotech else universe["min_avg_dollar_volume"]
    if market.avg_dollar_volume_20d < min_adv:
        rejected.append(RejectionCode.LIQUIDITY_TOO_LOW)
    if market.trading_days < universe["min_trading_days"]:
        rejected.append(RejectionCode.INSUFFICIENT_HISTORY)
    return GateResult(passed=not rejected, rejection_codes=[str(code) for code in rejected])
