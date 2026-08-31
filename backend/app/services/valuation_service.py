from __future__ import annotations

import math
from datetime import UTC, date, datetime
from statistics import median
from typing import Any, Protocol

from app.domain.schemas import FieldProvenance, FundamentalSnapshot, OHLCVBar


# Data-quality requirements for deriving a normalized historical multiple.
# These are not SOE investment thresholds and do not change the frozen rules.
MIN_HISTORY_OBSERVATIONS = 4
MAX_BAR_LAG_DAYS = 7
MAX_SHARE_STALENESS_DAYS = 140


class ValuationReferenceLike(Protocol):
    target_mean_price: float | None
    target_low_price: float | None
    target_high_price: float | None
    analyst_opinions: int | None
    source: str
    as_of: datetime
    fetched_at: datetime
    stale: bool


def _as_date(value: Any) -> date | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)).date()
    except ValueError:
        return None


def _valid_number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _dedupe_rows(rows: list[dict[str, Any]]) -> list[tuple[date, float]]:
    by_end: dict[date, float] = {}
    for row in rows:
        end = _as_date(row.get("end"))
        value = _valid_number(row.get("val"))
        if end is None or value is None:
            continue
        by_end[end] = value
    return sorted(by_end.items())


def _ttm_series(rows: list[dict[str, Any]]) -> list[tuple[date, float]]:
    quarterly = _dedupe_rows(rows)
    output: list[tuple[date, float]] = []
    for index in range(3, len(quarterly)):
        window = quarterly[index - 3 : index + 1]
        gaps = [(window[pos][0] - window[pos - 1][0]).days for pos in range(1, len(window))]
        if any(gap < 50 or gap > 130 for gap in gaps):
            continue
        output.append((window[-1][0], sum(value for _, value in window)))
    return output


def _shares_for_end(rows: list[dict[str, Any]], end: date) -> float | None:
    shares = _dedupe_rows(rows)
    eligible = [(row_end, value) for row_end, value in shares if row_end <= end and value > 0]
    if not eligible:
        return None
    row_end, value = eligible[-1]
    if (end - row_end).days > MAX_SHARE_STALENESS_DAYS:
        return None
    return value


def _price_for_end(bars: list[OHLCVBar], end: date) -> float | None:
    eligible = [bar for bar in bars if bar.date <= end and 0 <= (end - bar.date).days <= MAX_BAR_LAG_DAYS]
    if not eligible:
        return None
    price = eligible[-1].close
    return price if price > 0 and math.isfinite(price) else None


def _multiple_observations(
    metric_rows: list[dict[str, Any]],
    shares_rows: list[dict[str, Any]],
    bars: list[OHLCVBar],
    *,
    earnings: bool,
) -> tuple[list[dict[str, float | str]], tuple[date, float, float] | None]:
    ttm = _ttm_series(metric_rows)
    if not ttm:
        return [], None

    current_end, current_metric = ttm[-1]
    current_shares = _shares_for_end(shares_rows, current_end)
    current = (current_end, current_metric, current_shares) if current_shares is not None else None

    observations: list[dict[str, float | str]] = []
    for end, metric in ttm[:-1]:
        if metric <= 0:
            continue
        shares = _shares_for_end(shares_rows, end)
        price = _price_for_end(bars, end)
        if shares is None or price is None:
            continue
        denominator = metric
        multiple = (price * shares) / denominator
        if multiple <= 0 or not math.isfinite(multiple):
            continue
        observations.append(
            {
                "period_end": end.isoformat(),
                "price": price,
                "shares": shares,
                "ttm_metric": metric,
                "multiple": multiple,
                "metric": "P/E" if earnings else "P/S",
            }
        )
    return observations[-8:], current


def derive_historical_normalized_value(
    fundamental: FundamentalSnapshot,
    bars: list[OHLCVBar],
    *,
    allow_sales_fallback: bool,
) -> dict[str, Any] | None:
    history = fundamental.raw.get("valuation_history") if isinstance(fundamental.raw, dict) else None
    if not isinstance(history, dict) or not bars:
        return None
    shares_rows = history.get("shares_instants") or []
    if not isinstance(shares_rows, list):
        return None

    net_income_rows = history.get("net_income_quarters") or []
    if isinstance(net_income_rows, list):
        observations, current = _multiple_observations(net_income_rows, shares_rows, bars, earnings=True)
        if current is not None and current[1] > 0 and len(observations) >= MIN_HISTORY_OBSERVATIONS:
            current_end, current_income, current_shares = current
            normalized_multiple = median(float(row["multiple"]) for row in observations)
            normalized_value = normalized_multiple * current_income / current_shares
            if normalized_value > 0 and math.isfinite(normalized_value):
                return {
                    "method": "HISTORICAL_MEDIAN_PE",
                    "normalized_multiple": normalized_multiple,
                    "normalized_value_per_share": normalized_value,
                    "current_metric_period_end": current_end.isoformat(),
                    "current_ttm_metric": current_income,
                    "current_shares": current_shares,
                    "observation_count": len(observations),
                    "observations": observations,
                }

    if allow_sales_fallback:
        revenue_rows = history.get("revenue_quarters") or []
        if isinstance(revenue_rows, list):
            observations, current = _multiple_observations(revenue_rows, shares_rows, bars, earnings=False)
            if current is not None and current[1] > 0 and len(observations) >= MIN_HISTORY_OBSERVATIONS:
                current_end, current_revenue, current_shares = current
                normalized_multiple = median(float(row["multiple"]) for row in observations)
                normalized_value = normalized_multiple * current_revenue / current_shares
                if normalized_value > 0 and math.isfinite(normalized_value):
                    return {
                        "method": "HISTORICAL_MEDIAN_PS",
                        "normalized_multiple": normalized_multiple,
                        "normalized_value_per_share": normalized_value,
                        "current_metric_period_end": current_end.isoformat(),
                        "current_ttm_metric": current_revenue,
                        "current_shares": current_shares,
                        "observation_count": len(observations),
                        "observations": observations,
                    }
    return None


def enrich_fundamental_valuation(
    fundamental: FundamentalSnapshot,
    bars: list[OHLCVBar],
    reference: ValuationReferenceLike | None,
    *,
    allow_historical: bool = True,
    allow_sales_fallback: bool = True,
) -> FundamentalSnapshot:
    """Populate the frozen SOE valuation inputs from free/public data.

    `fundamental_undervaluation` is derived only from the security's own
    historical median P/E, falling back to P/S when appropriate. Therefore the
    frozen Re-Rating `valuation_discount` condition retains its original
    meaning: current price is below a normalized/historical valuation anchor.

    `expected_swing_upside` is a discovery-stage valuation-headroom proxy, not
    a Milestone-3 T2 target. When both anchors exist it uses the lower of the
    historical normalized value and the analyst consensus mean target. This is
    intentionally conservative and prevents a 12-month target from overriding
    self-relative valuation. If only the analyst target exists, that target is
    used as the proxy while fundamental valuation support remains unavailable.
    """
    if not bars:
        return fundamental
    current_price = bars[-1].close
    if current_price <= 0 or not math.isfinite(current_price):
        return fundamental

    historical = derive_historical_normalized_value(
        fundamental,
        bars,
        allow_sales_fallback=allow_sales_fallback,
    ) if allow_historical else None

    normalized_value = _valid_number((historical or {}).get("normalized_value_per_share"))
    fundamental_undervaluation = (
        normalized_value / current_price - 1
        if normalized_value is not None and normalized_value > 0
        else None
    )
    valuation_discount = fundamental_undervaluation > 0 if fundamental_undervaluation is not None else None

    target_mean = None
    reference_stale = True
    if reference is not None:
        target_mean = _valid_number(reference.target_mean_price)
        if target_mean is not None and target_mean <= 0:
            target_mean = None
        reference_stale = reference.stale
    consensus_upside = (
        target_mean / current_price - 1
        if target_mean is not None and not reference_stale
        else None
    )

    expected_swing_upside = None
    expected_anchor = None
    if consensus_upside is not None:
        expected_anchor = target_mean
        if normalized_value is not None:
            expected_anchor = min(target_mean, normalized_value)
        expected_swing_upside = expected_anchor / current_price - 1

    raw = dict(fundamental.raw)
    raw["valuation"] = {
        "historical": historical,
        "current_market_price": current_price,
        "consensus_target_mean": target_mean,
        "consensus_target_low": getattr(reference, "target_low_price", None) if reference else None,
        "consensus_target_high": getattr(reference, "target_high_price", None) if reference else None,
        "analyst_opinions": getattr(reference, "analyst_opinions", None) if reference else None,
        "consensus_target_upside": consensus_upside,
        "expected_swing_value_anchor": expected_anchor,
        "expected_swing_upside_method": (
            "LOWER_OF_HISTORICAL_NORMALIZED_VALUE_AND_CONSENSUS_TARGET"
            if consensus_upside is not None and normalized_value is not None
            else "CONSENSUS_TARGET_HEADROOM_PROXY"
            if consensus_upside is not None
            else None
        ),
        "milestone3_target": False,
    }

    provenance = dict(fundamental.field_provenance)
    market_fetched_at = max((bar.fetched_at for bar in bars if bar.fetched_at is not None), default=fundamental.fetched_at)
    market_as_of = bars[-1].as_of or datetime.combine(bars[-1].date, datetime.min.time(), tzinfo=UTC)
    fetched_at = max(fundamental.fetched_at, market_fetched_at)
    stale = fundamental.stale or bars[-1].stale

    if fundamental_undervaluation is not None and historical is not None:
        source = "SEC EDGAR companyfacts + Yahoo Finance historical EOD prices (prototype valuation normalization)"
        raw_field = f"valuation_history->{historical['method']}"
        provenance["fundamental_undervaluation"] = FieldProvenance(
            source=source,
            as_of=fundamental.as_of,
            fetched_at=fetched_at,
            stale=stale,
            raw_field=raw_field,
        )
        provenance["valuation_discount"] = FieldProvenance(
            source=source,
            as_of=fundamental.as_of,
            fetched_at=fetched_at,
            stale=stale,
            raw_field=raw_field,
        )

    if expected_swing_upside is not None and reference is not None:
        expected_fetched_at = max(fetched_at, reference.fetched_at)
        expected_as_of = min(market_as_of, reference.as_of)
        source = (
            "Yahoo Finance analyst target + SEC/Yahoo historical valuation anchor (prototype discovery headroom)"
            if normalized_value is not None
            else "Yahoo Finance analyst target (prototype discovery headroom)"
        )
        provenance["expected_swing_upside"] = FieldProvenance(
            source=source,
            as_of=expected_as_of,
            fetched_at=expected_fetched_at,
            stale=stale or reference.stale,
            raw_field="financialData.targetMeanPrice constrained by historical normalized value when available",
        )
        fetched_at = expected_fetched_at
        stale = stale or reference.stale

    return fundamental.model_copy(
        update={
            "valuation_discount": valuation_discount,
            "fundamental_undervaluation": fundamental_undervaluation,
            "expected_swing_upside": expected_swing_upside,
            "raw": raw,
            "field_provenance": provenance,
            "fetched_at": fetched_at,
            "stale": stale,
        }
    )
