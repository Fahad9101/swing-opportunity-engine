from __future__ import annotations

import argparse
import asyncio
import json
import random
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.core.config import SOE_1_1_RULES_PATH, load_rules, load_rules_for_version, rules_hash
from app.domain.enums import ScanStatus, ScannerType
from app.domain.schemas import Catalyst, CorporateEvent, EstimateSnapshot, FundamentalSnapshot, Instrument, MarketSnapshot
from app.orchestration.scan_pipeline import run_full_scan, scan_manager
from app.persistence.database import SessionLocal, init_database
from app.persistence.orm_models import (
    CatalystORM,
    CorporateEventORM,
    EstimateSnapshotORM,
    FundamentalSnapshotORM,
    InstrumentORM,
    MarketSnapshotORM,
    ProviderErrorORM,
    ScannerMatchORM,
)
from app.services.shadow_enrichment_service import ShadowStructuralEnricher, StructuralEnrichmentResult
from app.services.shadow_validation_service import (
    ShadowCandidateResult,
    apply_structural_inputs,
    assert_frozen_rule_equivalence,
    evaluate_captured_candidate,
    scanner_delta_violations,
    snapshot_fingerprint,
)
from app.services.universe_service import passes_universal_gate


DEFAULT_CONTRACT = "validation/phase_1_1e_shadow_contract_v1.json"
DEFAULT_OUTPUT_DIR = "validation-results/milestone-1.1e"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SOE-1.1E same-snapshot full-market shadow validation")
    parser.add_argument("--contract", default=DEFAULT_CONTRACT)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--provider", default="free_public")
    return parser.parse_args()


def _instrument(row: InstrumentORM) -> Instrument:
    return Instrument(
        ticker=row.ticker,
        company_name=row.company_name,
        exchange=row.exchange,
        country=row.country,
        sector=row.sector,
        industry=row.industry,
        asset_type=row.asset_type,
        market_cap=row.market_cap,
        is_biotech=row.is_biotech,
        active=row.active,
    )


def _shadow_dict(item: ShadowCandidateResult) -> dict[str, Any]:
    return {
        "ticker": item.ticker,
        "scanner_matches": item.scanner_matches,
        "qualified_scanners": item.qualified_scanners,
        "opportunity_score": item.opportunity_score,
        "base_opportunity_score": item.base_opportunity_score,
        "component_scores": item.component_scores,
        "fully_scored": item.fully_scored,
        "automatic_rejections": item.automatic_rejections,
        "promoted_catalysts": item.promoted_catalysts,
        "structural_inputs": item.structural_inputs,
    }


def _load_capture(scan_run_id: str) -> dict[str, Any]:
    with SessionLocal() as session:
        instruments = {row.ticker: _instrument(row) for row in session.execute(select(InstrumentORM)).scalars().all()}
        markets = {
            row.ticker: MarketSnapshot.model_validate(row.normalized_data)
            for row in session.execute(select(MarketSnapshotORM).where(MarketSnapshotORM.scan_run_id == scan_run_id)).scalars().all()
        }
        fundamentals = {
            row.ticker: FundamentalSnapshot.model_validate(row.normalized_data)
            for row in session.execute(select(FundamentalSnapshotORM).where(FundamentalSnapshotORM.scan_run_id == scan_run_id)).scalars().all()
        }
        estimates = {
            row.ticker: EstimateSnapshot.model_validate(row.normalized_data)
            for row in session.execute(select(EstimateSnapshotORM).where(EstimateSnapshotORM.scan_run_id == scan_run_id)).scalars().all()
        }
        catalysts: dict[str, list[Catalyst]] = defaultdict(list)
        for row in session.execute(select(CatalystORM).where(CatalystORM.scan_run_id == scan_run_id)).scalars().all():
            catalysts[row.ticker].append(Catalyst.model_validate(row.normalized_data))
        events: dict[str, list[CorporateEvent]] = defaultdict(list)
        for row in session.execute(select(CorporateEventORM).where(CorporateEventORM.scan_run_id == scan_run_id)).scalars().all():
            events[row.ticker].append(CorporateEvent.model_validate(row.normalized_data))
        persisted_matches = {}
        for row in session.execute(select(ScannerMatchORM).where(ScannerMatchORM.scan_run_id == scan_run_id)).scalars().all():
            persisted_matches[(row.ticker, row.scanner)] = {
                "qualified": row.qualified,
                "conditions_met": row.conditions_met,
                "conditions_total": row.conditions_total,
                "conditions": dict((row.evidence or {}).get("conditions") or {}),
                "evaluation_status": (row.evidence or {}).get("evaluation_status"),
                "incomplete_fields": list((row.evidence or {}).get("incomplete_fields") or []),
            }
        provider_errors = [
            {
                "provider": row.provider,
                "code": row.code,
                "message": row.message,
                "retryable": row.retryable,
                "ticker": row.ticker,
                "endpoint": row.endpoint,
                "status_code": row.status_code,
                "occurred_at": row.occurred_at.isoformat(),
            }
            for row in session.execute(select(ProviderErrorORM).where(ProviderErrorORM.scan_run_id == scan_run_id)).scalars().all()
        ]
    return {
        "instruments": instruments,
        "markets": markets,
        "fundamentals": fundamentals,
        "estimates": estimates,
        "catalysts": dict(catalysts),
        "events": dict(events),
        "persisted_matches": persisted_matches,
        "provider_errors": provider_errors,
    }


def _baseline_replay_concordance(result: ShadowCandidateResult, persisted: dict[tuple[str, str], dict[str, Any]]) -> list[str]:
    issues: list[str] = []
    for scanner, replay in result.scanner_matches.items():
        stored = persisted.get((result.ticker, scanner))
        if stored is None:
            issues.append(f"{scanner}:missing_persisted_match")
            continue
        for field in ("qualified", "conditions_met", "conditions_total", "conditions", "evaluation_status", "incomplete_fields"):
            if stored.get(field) != replay.get(field):
                issues.append(f"{scanner}:{field}")
    return issues


def _growth_needs_structural(result: ShadowCandidateResult) -> bool:
    conditions = result.scanner_matches[ScannerType.GROWTH_PULLBACK.value]["conditions"]
    return bool(
        conditions.get("revenue_growth") is True
        and conditions.get("growth_driver") is True
        and conditions.get("no_strong_negative_revisions") is True
    )


def _biotech_prequalified(result: ShadowCandidateResult) -> bool:
    conditions = result.scanner_matches[ScannerType.BIOTECH_CATALYST.value]["conditions"]
    technical = any(
        conditions.get(key) is True
        for key in ("technical_path_1", "technical_path_2", "catalyst_exception_path_3")
    )
    return bool(conditions.get("is_biotech") is True and conditions.get("cash_runway_eligible") is True and technical)


def _candidate_inputs(
    ticker: str,
    capture: dict[str, Any],
    enrichment: StructuralEnrichmentResult | None,
) -> tuple[FundamentalSnapshot | None, list[Catalyst] | None, int, dict[str, Any]]:
    original_fundamental = capture["fundamentals"].get(ticker)
    original_catalysts = list(capture["catalysts"].get(ticker, []))
    events = list(capture["events"].get(ticker, []))
    if enrichment is None:
        return original_fundamental, (original_catalysts or None), 0, {}
    guidance_value = enrichment.guidance_deterioration if enrichment.guidance else (original_fundamental.guidance_deterioration if original_fundamental else None)
    distress_value = enrichment.balance_sheet_distressed if enrichment.distress else (original_fundamental.balance_sheet_distressed if original_fundamental else None)
    enriched_fundamental, promoted, promoted_count = apply_structural_inputs(
        original_fundamental,
        events,
        guidance_deterioration=guidance_value,
        balance_sheet_distressed=distress_value,
        catalyst_overrides=enrichment.catalyst_overrides,
    )
    combined = list(original_catalysts)
    existing_keys = {(item.type, item.title, item.event_date) for item in combined}
    for catalyst in promoted or []:
        key = (catalyst.type, catalyst.title, catalyst.event_date)
        if key not in existing_keys:
            combined.append(catalyst)
            existing_keys.add(key)
    structural = {
        "guidance_deterioration": guidance_value,
        "balance_sheet_distressed": distress_value,
        "guidance": enrichment.guidance,
        "distress": enrichment.distress,
        "catalysts": enrichment.catalysts,
        "errors": enrichment.errors,
    }
    return enriched_fundamental, (combined or None), promoted_count, structural


def _evaluate_all(
    tickers: list[str],
    capture: dict[str, Any],
    rules: dict[str, Any],
    enrichment: dict[str, StructuralEnrichmentResult] | None = None,
) -> list[ShadowCandidateResult]:
    results: list[ShadowCandidateResult] = []
    for ticker in tickers:
        fundamental, catalysts, promoted_count, structural = _candidate_inputs(ticker, capture, (enrichment or {}).get(ticker))
        results.append(
            evaluate_captured_candidate(
                capture["instruments"][ticker],
                capture["markets"][ticker],
                fundamental,
                capture["estimates"].get(ticker),
                catalysts,
                rules,
                promoted_catalysts=promoted_count,
                structural_inputs=structural,
            )
        )
    return results


def _coverage(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _manual_audit_pool(enrichment: dict[str, StructuralEnrichmentResult]) -> list[dict[str, Any]]:
    pool: list[dict[str, Any]] = []
    for ticker, item in sorted(enrichment.items()):
        if item.guidance and item.guidance_deterioration is not None:
            pool.append({
                "ticker": ticker,
                "domain": "guidance",
                "classification": item.guidance_deterioration,
                "rule_path": item.guidance.get("rule_path"),
                "evidence": item.guidance,
                "manual_concordant": None,
                "manual_notes": None,
            })
        if item.distress and item.balance_sheet_distressed is not None:
            pool.append({
                "ticker": ticker,
                "domain": "balance_sheet_distress",
                "classification": item.balance_sheet_distressed,
                "rule_path": item.distress.get("rule_path"),
                "evidence": item.distress,
                "manual_concordant": None,
                "manual_notes": None,
            })
        for event in item.catalysts:
            if event.get("materiality") is not None:
                pool.append({
                    "ticker": ticker,
                    "domain": "catalyst_materiality",
                    "classification": event.get("materiality"),
                    "rule_path": event.get("materiality_rule_path"),
                    "evidence": event,
                    "manual_concordant": None,
                    "manual_notes": None,
                })
            if event.get("surprise_potential") is not None:
                pool.append({
                    "ticker": ticker,
                    "domain": "catalyst_surprise",
                    "classification": event.get("surprise_potential"),
                    "rule_path": event.get("surprise_rule_path"),
                    "evidence": event,
                    "manual_concordant": None,
                    "manual_notes": None,
                })
    return pool


def _markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    automated = report["automated_gates"]
    lines = [
        "# SOE-1.1E — Same-Snapshot Full-Market Shadow Validation",
        "",
        f"Generated: {report['generated_at']}",
        f"Baseline: `{report['baseline_model']}` / `{report['baseline_rules_hash']}`",
        f"Candidate: `{report['candidate_model']}` / `{report['candidate_rules_hash']}`",
        f"Snapshot: `{report['captured_snapshot_fingerprint']}`",
        "",
        "## Current decision",
        "",
        f"**{summary['decision']}**",
        "",
        f"- Universe: {summary['universe_count']}",
        f"- Universal-gate survivors: {summary['universal_survivors']}",
        f"- Growth structural targets: {summary['growth_structural_targets']}",
        f"- Catalyst enrichment targets: {summary['catalyst_enrichment_targets']}",
        f"- Fully scored opportunities: {summary['fully_scored_baseline']} -> {summary['fully_scored_candidate']}",
        f"- Guidance comparable coverage: {summary['guidance_coverage_pct']}",
        f"- Nonfinancial distress coverage: {summary['distress_coverage_pct']}",
        f"- Catalyst materiality coverage: {summary['materiality_coverage_pct']}",
        f"- Catalyst surprise coverage: {summary['surprise_coverage_pct']}",
        f"- Manual audit queue: {summary['manual_audit_sample_size']} / required {summary['manual_audit_required']}",
        "",
        "## Automated gates",
        "",
    ]
    for name, value in automated.items():
        lines.append(f"- {name}: **{'PASS' if value else 'FAIL'}**")
    lines += ["", "## Top 20 complete-score candidates", "", "| Rank | Ticker | Score | Scanners |", "| ---: | --- | ---: | --- |"]
    for index, row in enumerate(report["top_20_complete"], start=1):
        lines.append(f"| {index} | {row['ticker']} | {row['opportunity_score']:.2f} | {', '.join(row['qualified_scanners'])} |")
    lines += ["", "The report is not an activation approval while the manual audit queue remains unresolved. Milestone 3 stays blocked.", ""]
    return "\n".join(lines)


async def run_shadow_validation(*, contract_path: str | Path, output_dir: str | Path, provider_name: str) -> tuple[dict[str, Any], bool]:
    contract = json.loads(Path(contract_path).read_text(encoding="utf-8"))
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)

    baseline_rules = load_rules()
    candidate_rules = load_rules_for_version(SOE_1_1_RULES_PATH, "SOE-1.1.0")
    assert_frozen_rule_equivalence(baseline_rules, candidate_rules)
    baseline_hash = rules_hash(baseline_rules)
    candidate_hash = rules_hash(candidate_rules)

    init_database()
    state = scan_manager.create()
    state = await run_full_scan(state.scan_run_id, provider_name=provider_name)
    if state.status != ScanStatus.COMPLETED:
        raise RuntimeError(f"Baseline full-market capture failed: {state.errors[-5:]}")
    scan_run_id = str(state.scan_run_id)
    capture = _load_capture(scan_run_id)

    universal_tickers: list[str] = []
    gate_mismatches: list[str] = []
    for ticker, market in capture["markets"].items():
        instrument = capture["instruments"][ticker]
        before = passes_universal_gate(instrument, market, baseline_rules).passed
        after = passes_universal_gate(instrument, market, candidate_rules).passed
        if before != after:
            gate_mismatches.append(ticker)
        if before:
            universal_tickers.append(ticker)
    universal_tickers.sort()

    snapshot_rows = []
    for ticker in universal_tickers:
        snapshot_rows.append({
            "ticker": ticker,
            "instrument": capture["instruments"][ticker].model_dump(mode="json"),
            "market": capture["markets"][ticker].model_dump(mode="json"),
            "fundamental": capture["fundamentals"].get(ticker).model_dump(mode="json") if capture["fundamentals"].get(ticker) else None,
            "estimates": capture["estimates"].get(ticker).model_dump(mode="json") if capture["estimates"].get(ticker) else None,
            "catalysts": [item.model_dump(mode="json") for item in capture["catalysts"].get(ticker, [])],
            "corporate_events": [item.model_dump(mode="json") for item in capture["events"].get(ticker, [])],
        })
    fingerprint = snapshot_fingerprint(snapshot_rows)

    baseline_results = _evaluate_all(universal_tickers, capture, baseline_rules)
    baseline_by_ticker = {item.ticker: item for item in baseline_results}
    replay_issues = {
        ticker: issues
        for ticker, item in baseline_by_ticker.items()
        if (issues := _baseline_replay_concordance(item, capture["persisted_matches"]))
    }

    growth_targets = [ticker for ticker, item in baseline_by_ticker.items() if _growth_needs_structural(item)]
    enrichment: dict[str, StructuralEnrichmentResult] = {}
    enricher = ShadowStructuralEnricher(rules=candidate_rules, rules_hash=candidate_hash)
    try:
        for index, ticker in enumerate(growth_targets, start=1):
            print(f"[1.1E growth {index}/{len(growth_targets)}] {ticker}", flush=True)
            item = await enricher.enrich(
                capture["instruments"][ticker],
                capture["fundamentals"].get(ticker),
                list(capture["events"].get(ticker, [])),
                need_guidance=True,
                need_distress=True,
                need_catalyst=False,
            )
            enrichment[ticker] = item

        preliminary = _evaluate_all(universal_tickers, capture, candidate_rules, enrichment)
        preliminary_by_ticker = {item.ticker: item for item in preliminary}
        catalyst_targets = []
        for ticker, item in preliminary_by_ticker.items():
            has_candidate_event = any(event.catalyst_candidate for event in capture["events"].get(ticker, []))
            if has_candidate_event and (item.qualified_scanners or _biotech_prequalified(item)):
                catalyst_targets.append(ticker)
        catalyst_targets.sort()

        for index, ticker in enumerate(catalyst_targets, start=1):
            print(f"[1.1E catalyst {index}/{len(catalyst_targets)}] {ticker}", flush=True)
            existing = enrichment.get(ticker) or StructuralEnrichmentResult(ticker=ticker)
            overrides, rows, errors = await enricher.assess_earnings_catalysts(
                ticker,
                list(capture["events"].get(ticker, [])),
            )
            existing.catalyst_overrides.update(overrides)
            existing.catalysts.extend(rows)
            existing.errors.extend(errors)
            enrichment[ticker] = existing
    finally:
        enricher.close()

    candidate_results = _evaluate_all(universal_tickers, capture, candidate_rules, enrichment)
    candidate_by_ticker = {item.ticker: item for item in candidate_results}

    scanner_violations = {
        ticker: issues
        for ticker in universal_tickers
        if (issues := scanner_delta_violations(baseline_by_ticker[ticker], candidate_by_ticker[ticker]))
    }

    growth_fields = {}
    for field_name in ("no_guidance_deterioration", "balance_sheet_not_distressed"):
        states = Counter()
        resolved_from_null = Counter()
        for ticker in growth_targets:
            before = baseline_by_ticker[ticker].scanner_matches[ScannerType.GROWTH_PULLBACK.value]["conditions"].get(field_name)
            after = candidate_by_ticker[ticker].scanner_matches[ScannerType.GROWTH_PULLBACK.value]["conditions"].get(field_name)
            states["true" if after is True else "false" if after is False else "null"] += 1
            if before is None:
                resolved_from_null["true" if after is True else "false" if after is False else "null"] += 1
        growth_fields[field_name] = {"candidate_states": dict(states), "from_baseline_null": dict(resolved_from_null)}
    growth_newly_qualified = [
        ticker for ticker in growth_targets
        if not baseline_by_ticker[ticker].scanner_matches[ScannerType.GROWTH_PULLBACK.value]["qualified"]
        and candidate_by_ticker[ticker].scanner_matches[ScannerType.GROWTH_PULLBACK.value]["qualified"]
    ]

    biotech_changes = []
    for ticker in universal_tickers:
        before = baseline_by_ticker[ticker].scanner_matches[ScannerType.BIOTECH_CATALYST.value]["qualified"]
        after = candidate_by_ticker[ticker].scanner_matches[ScannerType.BIOTECH_CATALYST.value]["qualified"]
        if before != after:
            biotech_changes.append({
                "ticker": ticker,
                "baseline_qualified": before,
                "candidate_qualified": after,
                "candidate_conditions": candidate_by_ticker[ticker].scanner_matches[ScannerType.BIOTECH_CATALYST.value]["conditions"],
                "catalyst_evidence": (enrichment.get(ticker) or StructuralEnrichmentResult(ticker=ticker)).catalysts,
            })

    guidance_comparable = [item for item in enrichment.values() if item.guidance.get("sufficient_comparable_guidance") is True]
    guidance_classified = [item for item in guidance_comparable if item.guidance_deterioration is not None]
    distress_sufficient = [item for item in enrichment.values() if item.distress.get("sufficient_decision_evidence") is True]
    distress_classified = [item for item in distress_sufficient if item.balance_sheet_distressed is not None]
    catalyst_rows = [row for item in enrichment.values() for row in item.catalysts]
    catalyst_primary = [row for row in catalyst_rows if row.get("sufficient_primary_evidence") is True]
    catalyst_materiality = [row for row in catalyst_primary if row.get("materiality") is not None]
    catalyst_surprise = [row for row in catalyst_primary if row.get("surprise_potential") is not None]

    guidance_coverage = _coverage(len(guidance_classified), len(guidance_comparable))
    distress_coverage = _coverage(len(distress_classified), len(distress_sufficient))
    materiality_coverage = _coverage(len(catalyst_materiality), len(catalyst_primary))
    surprise_coverage = _coverage(len(catalyst_surprise), len(catalyst_primary))

    fully_before = sum(item.fully_scored for item in baseline_results)
    fully_after = sum(item.fully_scored for item in candidate_results)
    top_complete = sorted(
        [item for item in candidate_results if item.fully_scored and item.opportunity_score is not None and item.qualified_scanners],
        key=lambda item: (item.opportunity_score or -1, len(item.qualified_scanners), item.component_scores.get("technical") or -1),
        reverse=True,
    )[:20]

    deltas = []
    for ticker in universal_tickers:
        before, after = baseline_by_ticker[ticker], candidate_by_ticker[ticker]
        component_delta = {}
        for component in before.component_scores:
            left, right = before.component_scores.get(component), after.component_scores.get(component)
            component_delta[component] = (right - left) if left is not None and right is not None else None
        if (
            before.qualified_scanners != after.qualified_scanners
            or before.fully_scored != after.fully_scored
            or before.opportunity_score != after.opportunity_score
            or any(value is not None and value != 0 for value in component_delta.values())
        ):
            deltas.append({
                "ticker": ticker,
                "baseline_qualified_scanners": before.qualified_scanners,
                "candidate_qualified_scanners": after.qualified_scanners,
                "baseline_score": before.opportunity_score,
                "candidate_score": after.opportunity_score,
                "score_delta": (after.opportunity_score - before.opportunity_score) if before.opportunity_score is not None and after.opportunity_score is not None else None,
                "baseline_fully_scored": before.fully_scored,
                "candidate_fully_scored": after.fully_scored,
                "component_delta": component_delta,
                "structural_inputs": after.structural_inputs,
            })

    null_reasons = Counter()
    enrichment_errors = []
    for ticker, item in enrichment.items():
        if item.guidance and item.guidance_deterioration is None:
            null_reasons[f"guidance:{item.guidance.get('rule_path')}"] += 1
        if item.distress and item.balance_sheet_distressed is None:
            null_reasons[f"distress:{item.distress.get('rule_path')}"] += 1
        for row in item.catalysts:
            if row.get("materiality") is None:
                null_reasons[f"catalyst_materiality:{row.get('missing_reason') or row.get('materiality_rule_path')}"] += 1
            if row.get("surprise_potential") is None:
                null_reasons[f"catalyst_surprise:{row.get('consensus_error') or row.get('surprise_rule_path') or 'not_scored'}"] += 1
        enrichment_errors.extend({"ticker": ticker, "error": error} for error in item.errors)

    audit_pool = _manual_audit_pool(enrichment)
    random.Random(fingerprint).shuffle(audit_pool)
    required_audit = int(contract["acceptance_gates"]["manual_audit_minimum_sample"])
    audit_queue = audit_pool[:required_audit]

    guidance_gate = guidance_coverage is not None and guidance_coverage >= float(contract["acceptance_gates"]["minimum_guidance_classification_coverage_with_comparable_guidance"])
    distress_gate = distress_coverage is not None and distress_coverage >= float(contract["acceptance_gates"]["minimum_nonfinancial_distress_coverage_with_sufficient_inputs"])
    materiality_gate = materiality_coverage is not None and materiality_coverage >= float(contract["acceptance_gates"]["minimum_materiality_coverage_with_sufficient_evidence"])
    surprise_gate = surprise_coverage is not None and surprise_coverage >= float(contract["acceptance_gates"]["minimum_surprise_coverage_with_sufficient_evidence"])
    automated_gates = {
        "frozen_rule_equivalence": True,
        "universal_gate_equality": not gate_mismatches,
        "baseline_replay_concordance": not replay_issues,
        "scanner_delta_integrity": not scanner_violations,
        "guidance_coverage": guidance_gate,
        "nonfinancial_distress_coverage": distress_gate,
        "catalyst_materiality_coverage": materiality_gate,
        "catalyst_surprise_coverage": surprise_gate,
        "manual_audit_sample_available": len(audit_queue) >= required_audit,
    }
    automated_pass = all(automated_gates.values())
    decision = "PENDING_MANUAL_AUDIT" if automated_pass else "FAIL"

    summary = {
        "decision": decision,
        "universe_count": state.universe_count,
        "universal_survivors": len(universal_tickers),
        "growth_structural_targets": len(growth_targets),
        "growth_newly_qualified": len(growth_newly_qualified),
        "catalyst_enrichment_targets": len({ticker for ticker, item in enrichment.items() if item.catalysts}),
        "fully_scored_baseline": fully_before,
        "fully_scored_candidate": fully_after,
        "guidance_comparable_denominator": len(guidance_comparable),
        "guidance_classified": len(guidance_classified),
        "guidance_coverage_pct": round(guidance_coverage * 100, 2) if guidance_coverage is not None else None,
        "distress_sufficient_denominator": len(distress_sufficient),
        "distress_classified": len(distress_classified),
        "distress_coverage_pct": round(distress_coverage * 100, 2) if distress_coverage is not None else None,
        "catalyst_primary_evidence_denominator": len(catalyst_primary),
        "materiality_scored": len(catalyst_materiality),
        "materiality_coverage_pct": round(materiality_coverage * 100, 2) if materiality_coverage is not None else None,
        "surprise_scored": len(catalyst_surprise),
        "surprise_coverage_pct": round(surprise_coverage * 100, 2) if surprise_coverage is not None else None,
        "manual_audit_population": len(audit_pool),
        "manual_audit_sample_size": len(audit_queue),
        "manual_audit_required": required_audit,
        "baseline_provider_errors": len(capture["provider_errors"]),
        "enrichment_errors": len(enrichment_errors),
    }

    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "phase": "1.1E",
        "contract_id": contract["contract_id"],
        "baseline_model": "SOE-1.0.0",
        "candidate_model": "SOE-1.1.0",
        "baseline_rules_hash": baseline_hash,
        "candidate_rules_hash": candidate_hash,
        "baseline_scan_run_id": scan_run_id,
        "captured_snapshot_fingerprint": fingerprint,
        "single_market_capture": True,
        "default_runtime_model_unchanged": True,
        "investment_execution_engine_unchanged": True,
        "summary": summary,
        "automated_gates": automated_gates,
        "universal_gate_mismatches": gate_mismatches,
        "baseline_replay_issues": replay_issues,
        "scanner_delta_violations": scanner_violations,
        "growth_resolution": {
            "fields": growth_fields,
            "newly_qualified_tickers": growth_newly_qualified,
        },
        "biotech_qualification_changes": biotech_changes,
        "catalyst_score_distribution": {
            "materiality": dict(Counter(str(row["materiality"]) for row in catalyst_materiality)),
            "surprise_potential": dict(Counter(str(row["surprise_potential"]) for row in catalyst_surprise)),
        },
        "top_20_complete": [_shadow_dict(item) for item in top_complete],
        "per_name_deltas": deltas,
        "baseline_provider_errors": capture["provider_errors"],
        "enrichment_errors": enrichment_errors,
        "null_reason_distribution": dict(null_reasons),
        "manual_audit": {
            "status": "PENDING",
            "required_sample": required_audit,
            "minimum_rule_concordance": contract["acceptance_gates"]["manual_audit_minimum_rule_concordance"],
            "sampling_method": "Deterministic random shuffle seeded by captured snapshot SHA-256; first N classifications selected without score/outcome filtering.",
            "sample": audit_queue,
        },
        "baseline_replay": [_shadow_dict(item) for item in baseline_results],
        "candidate_replay": [_shadow_dict(item) for item in candidate_results],
    }

    (output / "shadow_validation.json").write_text(json.dumps(report, indent=2, sort_keys=True, default=str), encoding="utf-8")
    (output / "manual_audit_queue.json").write_text(json.dumps(report["manual_audit"], indent=2, sort_keys=True, default=str), encoding="utf-8")
    (output / "PHASE_1_1E_SHADOW_VALIDATION.md").write_text(_markdown(report), encoding="utf-8")
    (output / "captured_snapshot_manifest.json").write_text(
        json.dumps({"fingerprint": fingerprint, "scan_run_id": scan_run_id, "tickers": universal_tickers}, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, sort_keys=True), flush=True)
    return report, automated_pass


def main() -> int:
    args = _parse_args()
    _, automated_pass = asyncio.run(
        run_shadow_validation(contract_path=args.contract, output_dir=args.output_dir, provider_name=args.provider)
    )
    return 0 if automated_pass else 2


if __name__ == "__main__":
    raise SystemExit(main())
