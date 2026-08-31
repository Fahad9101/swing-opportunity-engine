from __future__ import annotations

from datetime import UTC, datetime, timedelta
from math import isclose
from typing import Any

from app.domain.enums import AssetType, DataQualitySeverity
from app.domain.schemas import FundamentalSnapshot, Instrument, MarketSnapshot, OHLCVBar, ValidationIssue
from app.services.trading_calendar_service import is_eod_stale


def _issue(code: str, message: str, *, ticker: str | None, field: str | None = None, value: Any = None, expected: str | None = None, source: str | None = None, severity: DataQualitySeverity = DataQualitySeverity.WARNING) -> ValidationIssue:
    return ValidationIssue(code=code, severity=severity, message=message, ticker=ticker, field=field, observed_value=value, expected=expected, source=source, created_at=datetime.now(UTC))


def validate_candidate(instrument: Instrument, market: MarketSnapshot, bars: list[OHLCVBar], fundamental: FundamentalSnapshot | None, rules: dict[str, Any]) -> list[ValidationIssue]:
    config = rules["data_quality"]["validation"]
    issues: list[ValidationIssue] = []
    ticker = instrument.ticker
    name_upper = instrument.company_name.upper()
    depositary_name = "DEPOSITARY" in name_upper or " ADR" in name_upper or " ADS" in name_upper
    if depositary_name and instrument.asset_type == AssetType.COMMON_STOCK:
        issues.append(_issue("ADR_COMMON_STOCK_CONFUSION", "Security name indicates a depositary receipt but asset type is common stock.", ticker=ticker, field="asset_type", value=instrument.asset_type.value, expected="ADR", source=instrument.source, severity=DataQualitySeverity.ERROR))
    if instrument.provider_symbol and instrument.provider_symbol.upper().replace(".", "-") != ticker.upper().replace(".", "-"):
        issues.append(_issue("PROVIDER_SYMBOL_MISMATCH", "Provider symbol does not canonically match normalized ticker.", ticker=ticker, field="provider_symbol", value=instrument.provider_symbol, expected=ticker, source=instrument.source, severity=DataQualitySeverity.ERROR))
    if market.price <= 0:
        issues.append(_issue("NEGATIVE_OR_ZERO_PRICE", "Price must be positive.", ticker=ticker, field="price", value=market.price, expected="> 0", source=market.source, severity=DataQualitySeverity.ERROR))
    for field in ("volume", "avg_volume_20d", "avg_dollar_volume_20d", "relative_volume", "atr14"):
        value = getattr(market, field)
        if value is not None and value < 0:
            issues.append(_issue("NEGATIVE_NONNEGATIVE_FIELD", "Field cannot be negative.", ticker=ticker, field=field, value=value, expected=">= 0", source=market.source, severity=DataQualitySeverity.ERROR))
    if instrument.market_cap is not None and instrument.market_cap < 0:
        issues.append(_issue("NEGATIVE_MARKET_CAP", "Market capitalization cannot be negative.", ticker=ticker, field="market_cap", value=instrument.market_cap, expected=">= 0", source=instrument.source, severity=DataQualitySeverity.ERROR))
    if market.rsi14 is not None and not 0 <= market.rsi14 <= 100:
        issues.append(_issue("RSI_OUT_OF_RANGE", "RSI must be between 0 and 100.", ticker=ticker, field="rsi14", value=market.rsi14, expected="0..100", source=market.source, severity=DataQualitySeverity.ERROR))
    if is_eod_stale(market.as_of):
        issues.append(_issue("STALE_PRICE", "Latest market price exceeds the configured freshness window.", ticker=ticker, field="price", value=market.as_of.isoformat(), expected="same trading day", source=market.source))
    closes = [bar.close for bar in sorted(bars, key=lambda item: item.date)]
    tolerance = config["sma_relative_tolerance"]
    for period, observed in ((20, market.sma20), (50, market.sma50), (200, market.sma200)):
        if len(closes) >= period and observed is not None:
            expected = sum(closes[-period:]) / period
            if not isclose(observed, expected, rel_tol=tolerance, abs_tol=tolerance):
                issues.append(_issue("SMA_INCONSISTENCY", "Stored SMA does not match normalized closes.", ticker=ticker, field=f"sma{period}", value=observed, expected=str(expected), source=market.source, severity=DataQualitySeverity.ERROR))
    if fundamental:
        for field in ("revenue_growth", "revenue_growth_qoq", "forward_revenue_growth", "eps_growth", "fcf_growth", "forward_ebitda_growth"):
            value = getattr(fundamental, field)
            if value is not None and abs(value) > config["max_abs_growth_rate"]:
                issues.append(_issue("IMPOSSIBLE_PERCENTAGE", "Growth rate exceeds the validation bound.", ticker=ticker, field=field, value=value, expected=f"absolute value <= {config['max_abs_growth_rate']}", source=fundamental.source, severity=DataQualitySeverity.ERROR))
        for field in ("gross_margin", "gross_margin_prior", "operating_margin", "operating_margin_prior"):
            value = getattr(fundamental, field)
            if value is not None and abs(value) > config["max_abs_margin"]:
                issues.append(_issue("IMPOSSIBLE_PERCENTAGE", "Margin exceeds the validation bound.", ticker=ticker, field=field, value=value, expected=f"absolute value <= {config['max_abs_margin']}", source=fundamental.source, severity=DataQualitySeverity.ERROR))
        if instrument.market_cap is not None and fundamental.shares_outstanding not in (None, 0):
            implied = market.price * fundamental.shares_outstanding
            relative_error = abs(instrument.market_cap - implied) / max(abs(instrument.market_cap), abs(implied))
            if relative_error > config["market_cap_relative_tolerance"]:
                issues.append(_issue("MARKET_CAP_INCONSISTENCY", "Reported market cap is inconsistent with price times shares outstanding.", ticker=ticker, field="market_cap", value=instrument.market_cap, expected=f"approximately {implied}", source=fundamental.source))
    jump = config["split_jump_threshold"]
    for previous, current in zip(bars, bars[1:]):
        if previous.close and abs(current.close / previous.close - 1) >= jump:
            issues.append(_issue("POSSIBLE_SPLIT_ADJUSTMENT_PROBLEM", "Large one-session price discontinuity may indicate unadjusted split history.", ticker=ticker, field="close", value={"date": current.date.isoformat(), "previous": previous.close, "current": current.close}, expected="split-adjusted OHLCV", source=market.source))
            break
    return issues


def duplicate_symbol_issues(instruments: list[Instrument]) -> list[ValidationIssue]:
    seen: set[str] = set()
    issues: list[ValidationIssue] = []
    for item in instruments:
        if item.ticker in seen:
            issues.append(_issue("DUPLICATE_TICKER", "Duplicate ticker found in normalized universe.", ticker=item.ticker, source=item.source, severity=DataQualitySeverity.ERROR))
        seen.add(item.ticker)
    return issues


def detect_null_to_zero(*, ticker: str, raw: dict[str, Any], normalized: Any, field_map: dict[str, str], source: str) -> list[ValidationIssue]:
    """Detect the specific, prohibited normalization of a provider null into numeric zero."""
    issues: list[ValidationIssue] = []
    for normalized_field, raw_field in field_map.items():
        if raw.get(raw_field) is None and getattr(normalized, normalized_field, None) == 0:
            issues.append(_issue("NULL_CONVERTED_TO_ZERO", "Provider null was converted to zero during normalization.", ticker=ticker, field=normalized_field, value=0, expected="null", source=source, severity=DataQualitySeverity.ERROR))
    return issues
