from __future__ import annotations

import logging
from datetime import UTC, datetime
from threading import Lock
from uuid import UUID, uuid4

from app.core.config import load_rules, rules_hash
from app.core.constants import MODEL_VERSION
from app.domain.enums import EvaluationStatus, RejectionCode, ScannerType, ScanStatus
from app.domain.schemas import DataCompleteness, OpportunityResult, ScanRunState
from app.orchestration.ranking import rank_opportunities
from app.persistence.database import SessionLocal
from app.persistence.repositories import ScanRepository
from app.providers.provider_registry import get_provider
from app.providers.errors import ProviderError
from app.scoring.balance_sheet_score import score_balance_sheet
from app.scoring.biotech_fundamental_score import score_biotech_fundamentals
from app.scoring.catalyst_score import score_catalyst
from app.scoring.fundamental_score import score_fundamentals
from app.scoring.liquidity_score import score_liquidity
from app.scoring.opportunity_score import calculate_opportunity_score
from app.scoring.penalties import build_penalties
from app.scoring.revision_score import score_revisions
from app.scoring.technical_score import score_technical
from app.scoring.valuation_score import score_valuation
from app.screeners.biotech_catalyst import BiotechCatalystScreener
from app.screeners.growth_pullback import GrowthPullbackScreener
from app.screeners.rerating import ReratingScreener
from app.services.regime_service import calculate_market_regime
from app.services.completeness_service import calculate_completeness
from app.services.data_quality_service import duplicate_symbol_issues, validate_candidate
from app.services.technical_service import build_market_snapshot
from app.services.universe_service import passes_universal_gate


logger = logging.getLogger(__name__)


class ScanManager:
    def __init__(self) -> None:
        self._states: dict[UUID, ScanRunState] = {}
        self._lock = Lock()

    def create(self) -> ScanRunState:
        state = ScanRunState(scan_run_id=uuid4(), status=ScanStatus.PENDING, stage="queued", progress=0, model_version=MODEL_VERSION, rules_hash=rules_hash(), started_at=datetime.now(UTC))
        with self._lock: self._states[state.scan_run_id] = state
        return state

    def get(self, scan_id: UUID) -> ScanRunState | None:
        with self._lock: return self._states.get(scan_id)

    def put(self, state: ScanRunState) -> None:
        with self._lock: self._states[state.scan_run_id] = state

    def latest_completed(self) -> ScanRunState | None:
        with self._lock:
            completed = [state for state in self._states.values() if state.status == ScanStatus.COMPLETED]
        return max(completed, key=lambda state: state.completed_at or state.started_at, default=None)


scan_manager = ScanManager()


def _available_points(components: dict) -> float:
    return sum((value.available_points if value.available_points is not None else value.maximum) for value in components.values() if value.available)


def _primary(matches):
    qualified = [item for item in matches if item.qualified]
    priority = {ScannerType.RERATING: 2, ScannerType.GROWTH_PULLBACK: 1, ScannerType.BIOTECH_CATALYST: 3}
    return max(qualified, key=lambda item: (item.conditions_met / item.conditions_total, priority[item.scanner]))


async def run_full_scan(scan_id: UUID, provider_name: str | None = None) -> ScanRunState:
    rules = load_rules()
    state = scan_manager.get(scan_id)
    if state is None: raise KeyError(scan_id)
    universal_passes = 0
    scanner_candidates = 0
    technical_survivors = 0
    fully_scored = 0
    domain_totals = {"market": 0, "fundamental": 0, "estimate": 0, "calendar": 0}
    domain_missing = {"market": 0, "fundamental": 0, "estimate": 0, "calendar": 0}
    scanner_match_counts = {scanner.value: 0 for scanner in ScannerType}
    scanner_incomplete_counts = {scanner.value: 0 for scanner in ScannerType}
    with SessionLocal() as session:
        repo = ScanRepository(session)
        repo.create_run(state)
        try:
            provider = get_provider(provider_name)
            state.status, state.stage, state.progress = ScanStatus.RUNNING, "market_regime", 0.05
            scan_manager.put(state)
            index_snapshots = {}
            for ticker in ("SPY", "QQQ", "IWM"):
                index_snapshots[ticker] = build_market_snapshot(ticker, await provider.get_ohlcv(ticker), provider.name, rules)
            vix_data = await provider.get_vix_data() if hasattr(provider, "get_vix_data") else None
            vix_value = vix_data.get("value") if vix_data else await provider.get_vix()
            regime = calculate_market_regime(index_snapshots["SPY"], index_snapshots["QQQ"], index_snapshots["IWM"], vix_value, await provider.get_breadth_pct(), rules, vix_metadata=vix_data)
            state.market_regime = regime
            repo.save_regime(state.scan_run_id, regime)

            state.stage, state.progress = "universe", 0.15
            instruments = await provider.list_instruments()
            state.universe_count = len(instruments)
            if hasattr(provider, "prefetch_market_data"):
                try:
                    await provider.prefetch_market_data(instruments)
                except ProviderError as exc:
                    error = {**exc.as_dict(), "occurred_at": datetime.now(UTC).isoformat()}
                    state.provider_errors.append(error)
                    repo.save_provider_error(state.scan_run_id, error)
            for issue in duplicate_symbol_issues(instruments):
                state.validation_issues.append(issue.model_dump(mode="json"))
                repo.save_validation_issue(state.scan_run_id, issue)
            initial_provider_errors = provider.drain_provider_errors() if hasattr(provider, "drain_provider_errors") else getattr(provider, "provider_errors", [])
            for error in initial_provider_errors:
                state.provider_errors.append(error)
                repo.save_provider_error(state.scan_run_id, error)
            if hasattr(provider, "prefetch_calendar"):
                try:
                    await provider.prefetch_calendar()
                except ProviderError as exc:
                    error = {**exc.as_dict(), "occurred_at": datetime.now(UTC).isoformat()}
                    state.provider_errors.append(error)
                    repo.save_provider_error(state.scan_run_id, error)
                calendar_provider_errors = provider.drain_provider_errors() if hasattr(provider, "drain_provider_errors") else []
                for error in calendar_provider_errors:
                    state.provider_errors.append(error)
                    repo.save_provider_error(state.scan_run_id, error)
            for instrument in instruments: repo.upsert_instrument(instrument)
            repo.commit()

            screeners = [ReratingScreener(), GrowthPullbackScreener(), BiotechCatalystScreener()]
            opportunities: list[OpportunityResult] = []
            async def optional_provider_call(awaitable, default, ticker: str):
                try:
                    return await awaitable
                except ProviderError as exc:
                    error = {**exc.as_dict(), "occurred_at": datetime.now(UTC).isoformat()}
                    state.provider_errors.append(error)
                    repo.save_provider_error(state.scan_run_id, error)
                    logger.warning("optional_provider_failure scan_run_id=%s ticker=%s provider=%s code=%s", state.scan_run_id, ticker, exc.provider, exc.code)
                    return default
            for index, instrument in enumerate(instruments):
                try:
                    bars = await provider.get_ohlcv(instrument.ticker)
                    market = build_market_snapshot(instrument.ticker, bars, provider.name, rules)
                    repo.save_market(state.scan_run_id, market)
                    for issue in validate_candidate(instrument, market, bars, None, rules):
                        state.validation_issues.append(issue.model_dump(mode="json"))
                        repo.save_validation_issue(state.scan_run_id, issue)
                    gate = passes_universal_gate(instrument, market, rules)
                    if not gate.passed:
                        repo.commit()
                        continue
                    universal_passes += 1
                    technical_ready = all(value is not None for value in (market.sma20, market.sma50, market.sma200, market.rsi14, market.atr14))
                    technical_survivors += int(technical_ready)
                    fundamental = await optional_provider_call(provider.get_fundamentals(instrument.ticker), None, instrument.ticker)
                    estimates = await optional_provider_call(provider.get_estimates(instrument.ticker), None, instrument.ticker)
                    catalysts = await optional_provider_call(provider.get_catalysts(instrument.ticker), None, instrument.ticker)
                    calendar_events = await optional_provider_call(provider.get_calendar_events(instrument.ticker), [], instrument.ticker) if hasattr(provider, "get_calendar_events") else []
                    if hasattr(provider, "drain_provider_errors"):
                        for error in provider.drain_provider_errors():
                            state.provider_errors.append(error)
                            repo.save_provider_error(state.scan_run_id, error)
                    for issue in validate_candidate(instrument, market, bars, fundamental, rules):
                        if issue.code in {"STALE_PRICE", "SMA_INCONSISTENCY", "POSSIBLE_SPLIT_ADJUSTMENT_PROBLEM", "NEGATIVE_OR_ZERO_PRICE", "NEGATIVE_MARKET_CAP", "NEGATIVE_NONNEGATIVE_FIELD", "RSI_OUT_OF_RANGE", "ADR_COMMON_STOCK_CONFUSION", "PROVIDER_SYMBOL_MISMATCH"}:
                            continue
                        state.validation_issues.append(issue.model_dump(mode="json"))
                        repo.save_validation_issue(state.scan_run_id, issue)
                    for event in calendar_events: repo.save_corporate_event(state.scan_run_id, event)
                    for domain, missing in (("market", False), ("fundamental", fundamental is None), ("estimate", estimates is None), ("calendar", not catalysts and not calendar_events)):
                        domain_totals[domain] += 1
                        domain_missing[domain] += int(missing)
                    if fundamental: repo.save_fundamental(state.scan_run_id, fundamental)
                    if estimates: repo.save_estimates(state.scan_run_id, estimates)
                    for catalyst in (catalysts or []): repo.save_catalyst(state.scan_run_id, catalyst)
                    matches = [screener.evaluate(instrument, market, fundamental, estimates, catalysts, rules) for screener in screeners]
                    for match in matches: repo.save_scanner_match(state.scan_run_id, instrument.ticker, match)
                    for match in matches:
                        if match.evaluation_status == EvaluationStatus.DATA_INCOMPLETE:
                            scanner_incomplete_counts[match.scanner.value] += 1
                    qualified = [match for match in matches if match.qualified]
                    for match in qualified:
                        scanner_match_counts[match.scanner.value] += 1
                    if not qualified:
                        repo.commit()
                        continue
                    scanner_candidates += 1
                    fundamental_score = score_biotech_fundamentals(fundamental) if instrument.is_biotech else score_fundamentals(fundamental)
                    components = {
                        "catalyst": score_catalyst(catalysts or []),
                        "fundamental": fundamental_score,
                        "valuation": score_valuation(fundamental),
                        "technical": score_technical(market, rules),
                        "revisions": score_revisions(estimates),
                        "balance_sheet": score_balance_sheet(instrument, fundamental),
                        "liquidity": score_liquidity(market, fundamental),
                    }
                    penalty_flags = fundamental.raw.get("penalty_flags", []) if fundamental else []
                    penalties = build_penalties(penalty_flags, rules)
                    penalty_points = sum(item.points for item in penalties)
                    scores = calculate_opportunity_score(components, penalty_points, len(qualified))
                    fully_scored += int(all(component.available for component in components.values()))
                    primary = _primary(matches)
                    rejections: list[str] = []
                    if instrument.is_biotech and fundamental and fundamental.cash_runway_months is not None and fundamental.cash_runway_months < rules["biotech"]["automatic_reject_cash_runway_months"] and fundamental.financing_secured is False:
                        rejections.append(RejectionCode.BIOTECH_RUNWAY_BELOW_9M.value)
                    completeness = calculate_completeness(market=market, fundamental=fundamental, estimates=estimates, catalysts=catalysts, calendar_events=calendar_events, available_score_points=_available_points(components))
                    opportunity = OpportunityResult(ticker=instrument.ticker, company=instrument.company_name, sector=instrument.sector, is_biotech=instrument.is_biotech, price=market.price, market_cap=instrument.market_cap, primary_scanner=primary.scanner, secondary_scanners=[item.scanner for item in qualified if item.scanner != primary.scanner], scores=scores, market_regime=regime.regime, scanner_conditions=matches, penalties=penalties, automatic_rejections=rejections, data_completeness=completeness, created_at=datetime.now(UTC))
                    opportunities.append(opportunity)
                    repo.save_opportunity(state.scan_run_id, opportunity)
                    repo.commit()
                except ProviderError as exc:
                    session.rollback()
                    state.error_count += 1
                    error = {**exc.as_dict(), "occurred_at": datetime.now(UTC).isoformat()}
                    state.provider_errors.append(error)
                    state.errors.append({"ticker": instrument.ticker, "code": exc.code, "message": exc.message})
                    repo.save_provider_error(state.scan_run_id, error)
                    repo.commit()
                    logger.warning("provider_ticker_failure scan_run_id=%s ticker=%s provider=%s code=%s", state.scan_run_id, instrument.ticker, exc.provider, exc.code)
                except Exception as exc:
                    session.rollback()
                    state.error_count += 1
                    state.errors.append({"ticker": instrument.ticker, "code": "TICKER_PROCESSING_ERROR", "message": str(exc)})
                    logger.exception("ticker_failure scan_run_id=%s ticker=%s", state.scan_run_id, instrument.ticker)
                state.progress = 0.20 + 0.70 * ((index + 1) / max(1, len(instruments)))
                state.candidate_count = len(opportunities)
                scan_manager.put(state)
            state.opportunities = rank_opportunities(opportunities)
            state.universal_pass_count = universal_passes
            state.technical_survivor_count = technical_survivors
            state.fully_scored_count = fully_scored
            state.scanner_match_counts = scanner_match_counts
            state.scanner_incomplete_counts = scanner_incomplete_counts
            state.missing_data_rates = {domain: round(100 * domain_missing[domain] / domain_totals[domain], 2) if domain_totals[domain] else 0.0 for domain in domain_totals}
            state.status, state.stage, state.progress, state.completed_at = ScanStatus.COMPLETED, "completed", 1.0, datetime.now(UTC)
            repo.update_run_progress(state, universal_passes, scanner_candidates)
            scan_manager.put(state)
            logger.info("scan_complete scan_run_id=%s model_version=%s rules_hash=%s universe=%s universal_passes=%s candidates=%s failures=%s", state.scan_run_id, state.model_version, state.rules_hash, state.universe_count, universal_passes, len(opportunities), state.error_count)
            return state
        except Exception as exc:
            session.rollback()
            state.status, state.stage, state.completed_at = ScanStatus.FAILED, "failed", datetime.now(UTC)
            state.error_count += 1
            state.errors.append({"code": "SCAN_FAILURE", "message": str(exc)})
            try: repo.update_run_progress(state, universal_passes, scanner_candidates)
            except Exception: session.rollback()
            scan_manager.put(state)
            logger.exception("scan_failure scan_run_id=%s", state.scan_run_id)
            return state
