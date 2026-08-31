from app.domain.enums import EvaluationStatus, ScannerType
from app.domain.schemas import Catalyst, EstimateSnapshot, FundamentalSnapshot, Instrument, MarketSnapshot, ScannerMatch
from app.screeners.base import BaseScreener, count_conditions
from app.services.estimate_service import has_positive_revision_trend
from app.services.fundamental_service import has_improving_fcf_or_ebitda, has_improving_margin


class ReratingScreener(BaseScreener):
    def evaluate(self, instrument: Instrument, market: MarketSnapshot, fundamental: FundamentalSnapshot | None, estimates: EstimateSnapshot | None, catalysts: list[Catalyst] | None, rules: dict) -> ScannerMatch:
        max_below = rules["technical"]["max_below_sma50_pct"]
        technical_ok = bool(market.sma200 and market.sma50 and market.price > market.sma200 and market.price >= market.sma50 * (1 - max_below))
        conditions = {
            "forward_eps_growth": None if estimates is None or estimates.forward_eps_growth is None else estimates.forward_eps_growth > rules["rerating"]["min_forward_eps_growth"],
            "revenue_growth_qoq": None if fundamental is None or fundamental.revenue_growth_qoq is None else fundamental.revenue_growth_qoq > 0,
            "margin_improving": has_improving_margin(fundamental),
            "fcf_or_ebitda_improving": has_improving_fcf_or_ebitda(fundamental),
            "positive_revisions": has_positive_revision_trend(estimates),
            "valuation_discount": None if fundamental is None else fundamental.valuation_discount,
        }
        met, total = count_conditions(conditions)
        required = rules["rerating"]["min_conditions_required"]
        unknown = [name for name, value in conditions.items() if value is None]
        qualified = technical_ok and met >= required
        incomplete = technical_ok and not qualified and met + len(unknown) >= required
        return ScannerMatch(scanner=ScannerType.RERATING, qualified=qualified, conditions=conditions, conditions_met=met, conditions_total=total, evidence={"technical_requirement": technical_ok, "price": market.price, "sma50": market.sma50, "sma200": market.sma200}, evaluation_status=EvaluationStatus.DATA_INCOMPLETE if incomplete else EvaluationStatus.COMPLETE, incomplete_fields=unknown if incomplete else [])
