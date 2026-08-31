from app.domain.enums import EvaluationStatus, ScannerType
from app.domain.schemas import Catalyst, EstimateSnapshot, FundamentalSnapshot, Instrument, MarketSnapshot, ScannerMatch
from app.screeners.base import BaseScreener, count_conditions
from app.services.estimate_service import has_strong_negative_revision_trend


class GrowthPullbackScreener(BaseScreener):
    def evaluate(self, instrument: Instrument, market: MarketSnapshot, fundamental: FundamentalSnapshot | None, estimates: EstimateSnapshot | None, catalysts: list[Catalyst] | None, rules: dict) -> ScannerMatch:
        config = rules["growth"]
        large_cap = instrument.market_cap is not None and instrument.market_cap >= config["large_cap_market_cap"]
        min_revenue_growth = config["large_cap_min_revenue_growth"] if large_cap else config["normal_min_revenue_growth"]
        revenue_ok = None if fundamental is None or fundamental.revenue_growth is None else fundamental.revenue_growth >= min_revenue_growth
        driver_values = {
            "forward_eps_growth": None if estimates is None or estimates.forward_eps_growth is None else estimates.forward_eps_growth >= config["min_forward_eps_growth"],
            "fcf_growth": None if fundamental is None or fundamental.fcf_growth is None else fundamental.fcf_growth >= config["min_fcf_growth"],
            "margin_expansion": None if fundamental is None or fundamental.operating_margin_expansion_bps is None else fundamental.operating_margin_expansion_bps >= config["min_margin_expansion_bps"],
            "forward_ebitda_growth": None if fundamental is None or fundamental.forward_ebitda_growth is None else fundamental.forward_ebitda_growth >= config["min_forward_ebitda_growth"],
        }
        if any(value is True for value in driver_values.values()):
            at_least_one_driver = True
        elif all(value is False for value in driver_values.values()):
            at_least_one_driver = False
        else:
            at_least_one_driver = None
        no_guidance_deterioration = None if fundamental is None or fundamental.guidance_deterioration is None else not fundamental.guidance_deterioration
        negative_revisions = has_strong_negative_revision_trend(estimates)
        no_negative_revisions = None if negative_revisions is None else not negative_revisions
        balance_sheet_ok = None if fundamental is None or fundamental.balance_sheet_distressed is None else not fundamental.balance_sheet_distressed
        conditions = {"revenue_growth": revenue_ok, "growth_driver": at_least_one_driver, "no_guidance_deterioration": no_guidance_deterioration, "no_strong_negative_revisions": no_negative_revisions, "balance_sheet_not_distressed": balance_sheet_ok}
        met, total = count_conditions(conditions)
        preferred = rules["technical"]["preferred_pullback_min"] <= market.pullback_from_50d_high_pct <= rules["technical"]["preferred_pullback_max"]
        sweet_spot = rules["technical"]["sweet_spot_pullback_min"] <= market.pullback_from_50d_high_pct <= rules["technical"]["sweet_spot_pullback_max"]
        required = [revenue_ok, at_least_one_driver, no_guidance_deterioration, no_negative_revisions, balance_sheet_ok]
        qualified = all(value is True for value in required)
        unknown = [name for name, value in conditions.items() if value is None]
        incomplete = not qualified and not any(value is False for value in required) and bool(unknown)
        return ScannerMatch(scanner=ScannerType.GROWTH_PULLBACK, qualified=qualified, conditions=conditions, conditions_met=met, conditions_total=total, evidence={"driver_conditions": driver_values, "pullback_pct": market.pullback_from_50d_high_pct, "preferred_pullback": preferred, "sweet_spot": sweet_spot, "large_cap_threshold_used": large_cap}, evaluation_status=EvaluationStatus.DATA_INCOMPLETE if incomplete else EvaluationStatus.COMPLETE, incomplete_fields=unknown if incomplete else [])
