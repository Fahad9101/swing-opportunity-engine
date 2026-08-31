from __future__ import annotations

from app.domain.schemas import Catalyst, CorporateEvent, DataCompleteness, EstimateSnapshot, FundamentalSnapshot, MarketSnapshot


MARKET_FIELDS = (
    "price", "previous_close", "volume", "avg_volume_20d", "avg_dollar_volume_20d", "relative_volume",
    "sma20", "sma50", "sma200", "sma50_slope_20d", "sma200_slope_20d", "rsi14", "atr14",
    "high20d", "high50d", "high52w", "low52w", "return1d", "return3d", "return5d", "return20d",
)
FUNDAMENTAL_FIELDS = (
    "revenue", "revenue_growth", "revenue_growth_qoq", "forward_revenue_growth", "eps", "forward_eps", "eps_growth",
    "gross_margin", "operating_margin", "operating_margin_expansion_bps", "fcf", "ebitda", "cash", "debt",
    "net_debt", "interest_coverage", "shares_outstanding", "institutional_ownership", "short_float",
)
ESTIMATE_FIELDS = (
    "forward_eps_growth", "forward_revenue", "forward_ebitda", "eps_revision_30d", "eps_revision_90d",
    "revenue_revision_30d", "revenue_revision_90d", "ebitda_revision_30d", "ebitda_revision_90d",
    "eps_up_revisions", "eps_down_revisions", "revenue_up_revisions", "revenue_down_revisions",
    "ebitda_up_revisions", "ebitda_down_revisions", "analyst_count",
)


def _ratio(model, fields: tuple[str, ...]) -> tuple[float, list[str]]:
    if model is None:
        return 0.0, list(fields)
    missing = [field for field in fields if getattr(model, field, None) is None]
    return 100.0 * (len(fields) - len(missing)) / len(fields), missing


def calculate_completeness(*, market: MarketSnapshot, fundamental: FundamentalSnapshot | None, estimates: EstimateSnapshot | None, catalysts: list[Catalyst] | None, calendar_events: list[CorporateEvent] | None = None, available_score_points: float) -> DataCompleteness:
    market_pct, market_missing = _ratio(market, MARKET_FIELDS)
    fundamental_pct, fundamental_missing = _ratio(fundamental, FUNDAMENTAL_FIELDS)
    estimate_pct, estimate_missing = _ratio(estimates, ESTIMATE_FIELDS)
    calendar_events = calendar_events or []
    catalyst_fields = ("event_date", "type", "verified")
    if catalysts:
        available = sum(1 for field in catalyst_fields if any(getattr(item, field, None) is not None for item in catalysts))
        catalyst_pct = 100.0 * available / len(catalyst_fields)
        catalyst_missing = [field for field in catalyst_fields if not any(getattr(item, field, None) is not None for item in catalysts)]
    elif calendar_events:
        available = sum(1 for field in catalyst_fields if any(getattr(item, field, None) is not None for item in calendar_events))
        catalyst_pct = 100.0 * available / len(catalyst_fields)
        catalyst_missing = [field for field in catalyst_fields if not any(getattr(item, field, None) is not None for item in calendar_events)]
    else:
        catalyst_pct, catalyst_missing = 0.0, list(catalyst_fields)
    stale_fields: list[str] = []
    for prefix, model in (("market", market), ("fundamental", fundamental), ("estimate", estimates)):
        if model is not None and model.stale:
            stale_fields.append(prefix)
        if model is not None:
            stale_fields.extend(f"{prefix}.{field}" for field, provenance in model.field_provenance.items() if provenance.stale)
    stale_fields.extend(f"calendar.{item.type}" for item in (catalysts or []) if item.stale)
    stale_fields.extend(f"calendar.{item.type}" for item in calendar_events if item.stale)
    # Equal domain weighting is a data-quality metric only; it does not affect the Opportunity Score.
    overall = (market_pct + fundamental_pct + estimate_pct + catalyst_pct) / 4
    return DataCompleteness(
        market_data=market_pct == 100, fundamentals=fundamental_pct == 100, estimates=estimate_pct == 100,
        catalyst_data=catalyst_pct == 100, available_score_points=available_score_points,
        market_data_pct=round(market_pct, 2), fundamental_pct=round(fundamental_pct, 2), estimate_pct=round(estimate_pct, 2),
        catalyst_pct=round(catalyst_pct, 2), overall_pct=round(overall, 2), stale_fields=sorted(set(stale_fields)),
        missing_fields={"market": market_missing, "fundamental": fundamental_missing, "estimate": estimate_missing, "calendar": catalyst_missing},
        availability={
            "market": "available",
            "fundamentals": "unavailable" if fundamental is None else ("available" if not fundamental_missing else "partial"),
            "estimates": "unavailable" if estimates is None else ("available" if not estimate_missing else "partial"),
            "scored_catalysts": "unavailable" if catalysts is None else "available",
            "calendar": "available" if calendar_events else "unavailable",
        },
    )
