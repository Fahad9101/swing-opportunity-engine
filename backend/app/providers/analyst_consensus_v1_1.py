from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.domain.catalyst_surprise_v1_1 import AnalystConsensusContext, SurpriseExpectationMetric
from app.services.catalyst_materiality_service import normalize_event_type


def _raw(value: Any) -> Any:
    if isinstance(value, dict) and "raw" in value:
        return value.get("raw")
    return value


def _float(value: Any) -> float | None:
    value = _raw(value)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    value = _raw(value)
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _quote_result(payload: dict[str, Any]) -> dict[str, Any] | None:
    quote_summary = payload.get("quoteSummary")
    if not isinstance(quote_summary, dict):
        return None
    results = quote_summary.get("result")
    if not isinstance(results, list) or not results or not isinstance(results[0], dict):
        return None
    return results[0]


def _period_for_event(event_type: str) -> str | None:
    canonical = normalize_event_type(event_type)
    if canonical == "quarterly_earnings":
        return "0q"
    if canonical == "formal_full_year_guidance_update":
        return "0y"
    return None


def _period(trend: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    return next((row for row in trend if row.get("period") == name), None)


def _context(
    ticker: str,
    row: dict[str, Any],
    *,
    period: str,
    metric: SurpriseExpectationMetric,
    fetched_at: datetime,
    stale: bool,
) -> AnalystConsensusContext | None:
    if metric == SurpriseExpectationMetric.EPS:
        estimate = row.get("earningsEstimate") or {}
        trend = row.get("epsTrend") or {}
        average = _float(estimate.get("avg"))
        high = _float(estimate.get("high"))
        low = _float(estimate.get("low"))
        current = _float(trend.get("current"))
        old_90d = _float(trend.get("90daysAgo"))
        analyst_count = _int(estimate.get("numberOfAnalysts"))
        raw_fields = {
            "average": f"earningsTrend.trend[{period}].earningsEstimate.avg",
            "high": f"earningsTrend.trend[{period}].earningsEstimate.high",
            "low": f"earningsTrend.trend[{period}].earningsEstimate.low",
            "current_estimate": f"earningsTrend.trend[{period}].epsTrend.current",
            "estimate_90d_ago": f"earningsTrend.trend[{period}].epsTrend.90daysAgo",
            "analyst_count": f"earningsTrend.trend[{period}].earningsEstimate.numberOfAnalysts",
        }
    else:
        estimate = row.get("revenueEstimate") or {}
        average = _float(estimate.get("avg"))
        high = _float(estimate.get("high"))
        low = _float(estimate.get("low"))
        current = average
        old_90d = None
        analyst_count = _int(estimate.get("numberOfAnalysts"))
        raw_fields = {
            "average": f"earningsTrend.trend[{period}].revenueEstimate.avg",
            "high": f"earningsTrend.trend[{period}].revenueEstimate.high",
            "low": f"earningsTrend.trend[{period}].revenueEstimate.low",
            "analyst_count": f"earningsTrend.trend[{period}].revenueEstimate.numberOfAnalysts",
        }

    values = {
        "average": average,
        "high": high,
        "low": low,
        "current_estimate": current,
        "estimate_90d_ago": old_90d,
        "analyst_count": analyst_count,
    }
    if all(value is None for value in values.values()):
        return None

    source = "Yahoo Finance quoteSummary earningsTrend (prototype-only)"
    provenance = {key: raw_fields[key] for key, value in values.items() if value is not None and key in raw_fields}
    return AnalystConsensusContext(
        ticker=ticker,
        period=period,
        metric=metric,
        average=average,
        high=high,
        low=low,
        current_estimate=current,
        estimate_90d_ago=old_90d,
        analyst_count=analyst_count,
        source=source,
        source_timestamp=fetched_at,
        stale=stale,
        field_provenance=provenance,
    )


def normalize_yahoo_surprise_consensus(
    ticker: str,
    payload: dict[str, Any],
    *,
    event_type: str,
    fetched_at: datetime,
    max_age_hours: int = 48,
) -> tuple[AnalystConsensusContext | None, AnalystConsensusContext | None]:
    """Return EPS and revenue expectation contexts without assigning a score.

    This parser is additive to the existing estimate adapter. It deliberately
    preserves missing high/low or 90-day evidence as null so the deterministic
    1.1D scorer can apply the locked fallback logic without fabrication.
    """

    period_name = _period_for_event(event_type)
    if period_name is None:
        return None, None

    result = _quote_result(payload)
    if result is None:
        return None, None
    earnings_trend = result.get("earningsTrend")
    if not isinstance(earnings_trend, dict):
        return None, None
    trend = earnings_trend.get("trend")
    if not isinstance(trend, list):
        return None, None
    rows = [row for row in trend if isinstance(row, dict)]
    row = _period(rows, period_name)
    if row is None:
        return None, None

    stale = datetime.now(UTC) - fetched_at > timedelta(hours=max_age_hours)
    eps = _context(
        ticker,
        row,
        period=period_name,
        metric=SurpriseExpectationMetric.EPS,
        fetched_at=fetched_at,
        stale=stale,
    )
    revenue = _context(
        ticker,
        row,
        period=period_name,
        metric=SurpriseExpectationMetric.REVENUE,
        fetched_at=fetched_at,
        stale=stale,
    )
    return eps, revenue
