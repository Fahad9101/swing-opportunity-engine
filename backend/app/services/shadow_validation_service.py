from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from app.domain.enums import EvaluationStatus, RejectionCode, ScannerType
from app.domain.schemas import Catalyst, CorporateEvent, EstimateSnapshot, FundamentalSnapshot, Instrument, MarketSnapshot
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
from app.services.catalyst_evidence_service import promote_scoring_ready_event


FROZEN_RULE_SECTIONS = (
    "universe",
    "technical",
    "growth",
    "rerating",
    "biotech",
    "catalyst",
    "opportunity",
    "scores",
    "market_regime",
    "penalties",
    "data_quality",
)

_ALLOWED_GROWTH_DELTAS = {"no_guidance_deterioration", "balance_sheet_not_distressed"}
_ALLOWED_BIOTECH_DELTAS = {"verified_grade_a_or_b_catalyst", "catalyst_exception_path_3"}


@dataclass(frozen=True)
class CatalystStructuralOverride:
    materiality: int | None = None
    surprise_potential: int | None = None
    evidence_id: str | None = None
    reasons: tuple[str, ...] = ()


@dataclass
class ShadowCandidateResult:
    ticker: str
    scanner_matches: dict[str, dict[str, Any]]
    qualified_scanners: list[str]
    opportunity_score: float | None
    base_opportunity_score: float | None
    component_scores: dict[str, float | None]
    fully_scored: bool
    automatic_rejections: list[str]
    promoted_catalysts: int = 0
    structural_inputs: dict[str, Any] = field(default_factory=dict)


def assert_frozen_rule_equivalence(v1_rules: dict[str, Any], v1_1_rules: dict[str, Any]) -> None:
    """Fail closed if SOE-1.1 changes any SOE-1.0 rule outside structural additions."""
    mismatches = [section for section in FROZEN_RULE_SECTIONS if v1_rules.get(section) != v1_1_rules.get(section)]
    if mismatches:
        raise ValueError(f"Frozen SOE-1.0 rule sections differ in SOE-1.1: {', '.join(mismatches)}")


def _canonical(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return _canonical(value.model_dump(mode="json"))
    if isinstance(value, dict):
        return {str(key): _canonical(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    return value


def snapshot_fingerprint(records: list[dict[str, Any]]) -> str:
    """Hash a captured replay input after sorting by ticker and canonicalizing JSON."""
    ordered = sorted((_canonical(row) for row in records), key=lambda row: (str(row.get("ticker", "")), json.dumps(row, sort_keys=True)))
    payload = json.dumps(ordered, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def catalyst_event_key(event: CorporateEvent) -> str:
    event_date = event.event_date.isoformat() if event.event_date else ""
    return "|".join(
        (
            event.ticker.upper(),
            event.type.strip().lower(),
            event_date,
            " ".join(event.title.lower().split()),
        )
    )


def apply_structural_inputs(
    fundamental: FundamentalSnapshot | None,
    corporate_events: list[CorporateEvent] | None,
    *,
    guidance_deterioration: bool | None,
    balance_sheet_distressed: bool | None,
    catalyst_overrides: dict[str, CatalystStructuralOverride] | None = None,
) -> tuple[FundamentalSnapshot | None, list[Catalyst] | None, int]:
    """Inject only the four SOE-1.1 structural outputs into a captured snapshot.

    No market, estimate, growth, valuation, technical, liquidity, penalty, or
    scanner threshold input is changed here. Missing structural evidence remains
    null and cannot be promoted into a scored catalyst.
    """
    enriched_fundamental = None
    if fundamental is not None:
        enriched_fundamental = fundamental.model_copy(
            update={
                "guidance_deterioration": guidance_deterioration,
                "balance_sheet_distressed": balance_sheet_distressed,
            }
        )

    promoted: list[Catalyst] = []
    overrides = catalyst_overrides or {}
    for event in corporate_events or []:
        override = overrides.get(catalyst_event_key(event))
        if override is None:
            continue
        missing: list[str] = []
        if override.materiality is None:
            missing.append("materiality")
        if override.surprise_potential is None:
            missing.append("surprise_potential")
        scoring_ready = bool(
            event.catalyst_candidate
            and event.verified
            and not event.stale
            and event.date_confidence is not None
            and not missing
        )
        enriched_event = event.model_copy(
            update={
                "materiality": override.materiality,
                "surprise_potential": override.surprise_potential,
                "missing_score_fields": missing,
                "scoring_ready": scoring_ready,
            }
        )
        catalyst = promote_scoring_ready_event(enriched_event)
        if catalyst is not None:
            promoted.append(catalyst)

    return enriched_fundamental, (promoted or None), len(promoted)


def _match_row(match) -> dict[str, Any]:
    return {
        "qualified": bool(match.qualified),
        "conditions": dict(match.conditions),
        "conditions_met": int(match.conditions_met),
        "conditions_total": int(match.conditions_total),
        "evaluation_status": match.evaluation_status.value,
        "incomplete_fields": list(match.incomplete_fields),
        "evidence": dict(match.evidence),
    }


def _primary(matches):
    qualified = [item for item in matches if item.qualified]
    priority = {ScannerType.RERATING: 2, ScannerType.GROWTH_PULLBACK: 1, ScannerType.BIOTECH_CATALYST: 3}
    return max(qualified, key=lambda item: (item.conditions_met / item.conditions_total, priority[item.scanner]))


def evaluate_captured_candidate(
    instrument: Instrument,
    market: MarketSnapshot,
    fundamental: FundamentalSnapshot | None,
    estimates: EstimateSnapshot | None,
    catalysts: list[Catalyst] | None,
    rules: dict[str, Any],
    *,
    promoted_catalysts: int = 0,
    structural_inputs: dict[str, Any] | None = None,
) -> ShadowCandidateResult:
    """Replay unchanged SOE scanners/scores against one captured market snapshot."""
    screeners = (ReratingScreener(), GrowthPullbackScreener(), BiotechCatalystScreener())
    matches = [screener.evaluate(instrument, market, fundamental, estimates, catalysts, rules) for screener in screeners]
    match_rows = {match.scanner.value: _match_row(match) for match in matches}
    qualified = [match for match in matches if match.qualified]
    if not qualified:
        return ShadowCandidateResult(
            ticker=instrument.ticker,
            scanner_matches=match_rows,
            qualified_scanners=[],
            opportunity_score=None,
            base_opportunity_score=None,
            component_scores={
                "catalyst": None,
                "fundamental": None,
                "valuation": None,
                "technical": None,
                "revisions": None,
                "balance_sheet": None,
                "liquidity": None,
            },
            fully_scored=False,
            automatic_rejections=[],
            promoted_catalysts=promoted_catalysts,
            structural_inputs=structural_inputs or {},
        )

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
    rejections: list[str] = []
    if (
        instrument.is_biotech
        and fundamental
        and fundamental.cash_runway_months is not None
        and fundamental.cash_runway_months < rules["biotech"]["automatic_reject_cash_runway_months"]
        and fundamental.financing_secured is False
    ):
        rejections.append(RejectionCode.BIOTECH_RUNWAY_BELOW_9M.value)

    _primary(matches)  # exercise the same deterministic primary-selection path as production
    return ShadowCandidateResult(
        ticker=instrument.ticker,
        scanner_matches=match_rows,
        qualified_scanners=[match.scanner.value for match in qualified],
        opportunity_score=scores.opportunity_score,
        base_opportunity_score=scores.base_opportunity_score,
        component_scores={name: component.score for name, component in components.items()},
        fully_scored=all(component.available for component in components.values()),
        automatic_rejections=rejections,
        promoted_catalysts=promoted_catalysts,
        structural_inputs=structural_inputs or {},
    )


def scanner_delta_violations(baseline: ShadowCandidateResult, candidate: ShadowCandidateResult) -> list[str]:
    """Return any scanner-condition changes outside SOE-1.1's four structural fields."""
    violations: list[str] = []
    for scanner in (ScannerType.RERATING.value, ScannerType.GROWTH_PULLBACK.value, ScannerType.BIOTECH_CATALYST.value):
        before = baseline.scanner_matches[scanner]["conditions"]
        after = candidate.scanner_matches[scanner]["conditions"]
        changed = {key for key in set(before) | set(after) if before.get(key) != after.get(key)}
        allowed: set[str]
        if scanner == ScannerType.GROWTH_PULLBACK.value:
            allowed = _ALLOWED_GROWTH_DELTAS
        elif scanner == ScannerType.BIOTECH_CATALYST.value:
            allowed = _ALLOWED_BIOTECH_DELTAS
        else:
            allowed = set()
        unexpected = sorted(changed - allowed)
        if unexpected:
            violations.append(f"{scanner}:{','.join(unexpected)}")
    return violations


def summarize_resolution(baseline: list[ShadowCandidateResult], candidate: list[ShadowCandidateResult]) -> dict[str, Any]:
    by_ticker = {item.ticker: item for item in baseline}
    candidate_by_ticker = {item.ticker: item for item in candidate}
    common = sorted(set(by_ticker) & set(candidate_by_ticker))
    violations: dict[str, list[str]] = {}
    growth_resolved = {"true": 0, "false": 0, "null": 0}
    biotech_newly_qualified = 0
    fully_scored_before = 0
    fully_scored_after = 0
    for ticker in common:
        before, after = by_ticker[ticker], candidate_by_ticker[ticker]
        issue = scanner_delta_violations(before, after)
        if issue:
            violations[ticker] = issue
        growth = after.scanner_matches[ScannerType.GROWTH_PULLBACK.value]["conditions"]
        for key in _ALLOWED_GROWTH_DELTAS:
            value = growth.get(key)
            growth_resolved["true" if value is True else "false" if value is False else "null"] += 1
        biotech_before = baseline_status = before.scanner_matches[ScannerType.BIOTECH_CATALYST.value]["qualified"]
        biotech_after = after.scanner_matches[ScannerType.BIOTECH_CATALYST.value]["qualified"]
        biotech_newly_qualified += int(not biotech_before and biotech_after)
        fully_scored_before += int(before.fully_scored)
        fully_scored_after += int(after.fully_scored)
    return {
        "tickers_compared": len(common),
        "scanner_delta_violation_count": len(violations),
        "scanner_delta_violations": violations,
        "growth_structural_condition_states": growth_resolved,
        "biotech_newly_qualified": biotech_newly_qualified,
        "fully_scored_before": fully_scored_before,
        "fully_scored_after": fully_scored_after,
    }
