from datetime import date

from app.domain.enums import CatalystGrade, EvaluationStatus, ScannerType
from app.domain.schemas import Catalyst, EstimateSnapshot, FundamentalSnapshot, Instrument, MarketSnapshot, ScannerMatch
from app.screeners.base import BaseScreener, count_conditions


class BiotechCatalystScreener(BaseScreener):
    def evaluate(self, instrument: Instrument, market: MarketSnapshot, fundamental: FundamentalSnapshot | None, estimates: EstimateSnapshot | None, catalysts: list[Catalyst] | None, rules: dict) -> ScannerMatch:
        biotech = rules["biotech"]
        runway = None if fundamental is None else fundamental.cash_runway_months
        financing_secured = None if fundamental is None else fundamental.financing_secured
        runway_reject = runway is not None and runway < biotech["automatic_reject_cash_runway_months"] and financing_secured is False
        runway_ok = None if runway is None else (runway >= biotech["standard_min_cash_runway_months"] or financing_secured is True)
        path1 = bool(market.sma200 and market.price > market.sma200)
        path2 = bool(market.sma50 and market.sma200 and market.price > market.sma50 and market.price >= 0.8 * market.sma200)
        verified_grade_a = [item for item in (catalysts or []) if item.verified and item.grade == CatalystGrade.A and item.event_date]
        days = min(((item.event_date - date.today()).days for item in verified_grade_a), default=None)
        path3 = bool(days is not None and 0 <= days <= biotech["catalyst_exception_days"] and market.stable_sessions >= biotech["catalyst_exception_min_stable_sessions"] and not market.new_52w_low_last_10 and market.rsi14 is not None and market.rsi14 >= biotech["catalyst_exception_min_rsi"])
        has_non_speculative = None if catalysts is None else any(item.verified and item.grade in {CatalystGrade.A, CatalystGrade.B} for item in catalysts)
        conditions = {"is_biotech": instrument.is_biotech, "cash_runway_eligible": runway_ok, "technical_path_1": path1, "technical_path_2": path2, "catalyst_exception_path_3": path3, "verified_grade_a_or_b_catalyst": has_non_speculative}
        met, total = count_conditions(conditions)
        qualified = instrument.is_biotech and not runway_reject and runway_ok is True and (path1 or path2 or path3) and has_non_speculative is True
        unknown = [name for name, value in conditions.items() if value is None]
        incomplete = instrument.is_biotech and not runway_reject and not qualified and bool(unknown)
        return ScannerMatch(scanner=ScannerType.BIOTECH_CATALYST, qualified=qualified, conditions=conditions, conditions_met=met, conditions_total=total, evidence={"cash_runway_months": runway, "financing_secured": financing_secured, "runway_reject": runway_reject, "nearest_grade_a_days": days}, evaluation_status=EvaluationStatus.DATA_INCOMPLETE if incomplete else EvaluationStatus.COMPLETE, incomplete_fields=unknown if incomplete else [])
