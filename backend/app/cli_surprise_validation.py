from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.config import SOE_1_1_RULES_PATH, load_rules_for_version, rules_hash
from app.domain.catalyst_surprise_v1_1 import CatalystSurpriseInput
from app.domain.catalyst_v1_1 import CatalystEventFamily, CatalystExtractionMethod
from app.providers.errors import ProviderError
from app.providers.yahoo_analyst import YahooAnalystEstimateProvider
from app.providers.yahoo_surprise_consensus import YahooSurpriseConsensusProvider
from app.services.cache_service import JsonFileCache
from app.services.catalyst_surprise_service import assess_surprise_potential


DEFAULT_BASKET = "validation/phase_1_1d_preregistered_basket_v1.json"
DEFAULT_MATERIALITY = "validation-results/milestone-1.1c/catalyst_materiality_validation.json"
DEFAULT_OUTPUT_DIR = "validation-results/milestone-1.1d"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SOE-1.1D live surprise/re-rating validation")
    parser.add_argument("--basket", default=DEFAULT_BASKET)
    parser.add_argument("--materiality", default=DEFAULT_MATERIALITY)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def _load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _inherited_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for row in payload.get("results") or []:
        if isinstance(row, dict) and row.get("id"):
            rows[str(row["id"])] = row
    return rows


def _inherited_provenance_complete(assessment: dict[str, Any] | None) -> bool:
    if not assessment:
        return False
    provenance = assessment.get("structured_provenance") or {}
    return bool(
        assessment.get("materiality") is not None
        and assessment.get("catalyst_candidate") is True
        and assessment.get("economic_exposure_score") is not None
        and assessment.get("source") == "SEC EDGAR"
        and str(assessment.get("source_url") or "").startswith("https://www.sec.gov/Archives/edgar/data/")
        and assessment.get("source_timestamp")
        and assessment.get("evidence_spans")
        and provenance.get("accession")
        and provenance.get("document_id")
        and provenance.get("content_hash")
    )


def _write_report(output_dir: Path, payload: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "surprise_validation.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    summary = payload["summary"]
    lines = [
        "# Phase 1.1D Surprise / Re-Rating Validation",
        "",
        f"- Exit gate: **{summary['exit_gate']}**",
        f"- Targets attempted: {summary['targets_attempted']}",
        f"- Inherited 1.1C verified candidates: {summary['inherited_verified_candidates']}",
        f"- Targets with live consensus context: {summary['live_consensus_context_targets']}",
        f"- Targets with usable expectation evidence: {summary['usable_expectation_evidence_targets']}",
        f"- Surprise scores among sufficient evidence: {summary['surprise_scored_sufficient_events']}",
        f"- Surprise-score coverage: {summary['surprise_coverage_pct']:.1f}%",
        f"- Inherited provenance complete: {summary['inherited_provenance_complete_pct']:.1f}%",
        f"- Non-directional reason present: {summary['non_directional_reason_pct']:.1f}%",
        f"- Provider errors: {summary['provider_error_count']}",
        "",
        "This is a live structural/provider validation using current-period analyst consensus. It is not a historical pre-event backtest and does not infer the direction of any surprise.",
        "",
        "## Null / error reasons",
    ]
    null_reasons: dict[str, int] = payload.get("null_reasons") or {}
    if null_reasons:
        for reason, count in sorted(null_reasons.items(), key=lambda item: (-item[1], item[0])):
            lines.append(f"- {reason}: {count}")
    else:
        lines.append("- None")
    (output_dir / "PHASE_1_1D_SURPRISE_VALIDATION.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


async def run_validation(
    *,
    basket_path: str | Path = DEFAULT_BASKET,
    materiality_path: str | Path = DEFAULT_MATERIALITY,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
) -> tuple[dict[str, Any], bool]:
    basket = _load_json(basket_path)
    inherited_payload = _load_json(materiality_path)
    inherited = _inherited_map(inherited_payload)
    guardrails = basket["validation_guardrails"]
    rules = load_rules_for_version(SOE_1_1_RULES_PATH, "SOE-1.1.0")
    candidate_rules_hash = rules_hash(rules)
    results: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory(prefix="soe-1.1d-consensus-") as cache_dir:
        analyst = YahooAnalystEstimateProvider(cache=JsonFileCache(Path(cache_dir)), rules=rules)
        consensus_provider = YahooSurpriseConsensusProvider(analyst)

        for target in basket.get("targets") or []:
            target_id = str(target["id"])
            ticker = str(target["ticker"]).upper()
            event_type = str(target["target_event_type"])
            inherited_row = inherited.get(target_id)
            inherited_assessment = (inherited_row or {}).get("assessment")
            row: dict[str, Any] = {
                "id": target_id,
                "ticker": ticker,
                "target_event_type": event_type,
                "inherited_materiality_found": inherited_assessment is not None,
                "inherited_provenance_complete": _inherited_provenance_complete(inherited_assessment),
                "live_consensus_context": False,
                "usable_expectation_evidence": False,
                "surprise_scored": False,
                "assessment": None,
                "provider_error": None,
            }

            if not inherited_assessment:
                results.append(row)
                continue

            try:
                eps, revenue = await consensus_provider.get_consensus(ticker, event_type=event_type)
            except ProviderError as exc:
                row["provider_error"] = f"{exc.code}: {exc}"
                results.append(row)
                continue
            except Exception as exc:  # validation harness must preserve unexpected provider failures
                row["provider_error"] = f"{type(exc).__name__}: {exc}"
                results.append(row)
                continue

            row["live_consensus_context"] = eps is not None or revenue is not None
            input_model = CatalystSurpriseInput(
                ticker=ticker,
                event_id=str(inherited_assessment["event_id"]),
                event_family=CatalystEventFamily(inherited_assessment["event_family"]),
                event_type=event_type,
                economic_exposure_score=inherited_assessment.get("economic_exposure_score"),
                catalyst_candidate=bool(inherited_assessment.get("catalyst_candidate")),
                verified=bool((inherited_row or {}).get("sufficient_primary_evidence")),
                eps_consensus=eps,
                revenue_consensus=revenue,
                source=str(inherited_assessment["source"]),
                source_url=str(inherited_assessment["source_url"]),
                source_timestamp=_parse_timestamp(str(inherited_assessment["source_timestamp"])),
                extraction_method=CatalystExtractionMethod(inherited_assessment["extraction_method"]),
                evidence_spans=list(inherited_assessment.get("evidence_spans") or []),
                structured_provenance=dict(inherited_assessment.get("structured_provenance") or {}),
            )
            assessment = assess_surprise_potential(input_model, rules, rules_hash=candidate_rules_hash)
            row["assessment"] = assessment.model_dump(mode="json")
            row["usable_expectation_evidence"] = assessment.expectation_uncertainty is not None
            row["surprise_scored"] = assessment.surprise_potential is not None
            results.append(row)

    inherited_verified = [
        row for row in results
        if row["inherited_materiality_found"] and row["inherited_provenance_complete"]
    ]
    live_context = [row for row in results if row["live_consensus_context"]]
    sufficient = [
        row for row in results
        if row["inherited_provenance_complete"] and row["usable_expectation_evidence"]
    ]
    scored_sufficient = [row for row in sufficient if row["surprise_scored"]]
    coverage = len(scored_sufficient) / len(sufficient) if sufficient else 0.0

    scored = [row for row in results if row["surprise_scored"]]
    inherited_provenance_pct = (
        len(inherited_verified) / len(results) * 100.0 if results else 0.0
    )
    non_directional_count = 0
    for row in scored:
        reasons = (row.get("assessment") or {}).get("reasons") or []
        if "surprise_potential_is_non_directional" in reasons:
            non_directional_count += 1
    non_directional_pct = (
        non_directional_count / len(scored) * 100.0 if scored else 0.0
    )
    errors = [row for row in results if row["provider_error"]]

    null_reasons: dict[str, int] = {}
    for row in results:
        assessment = row.get("assessment") or {}
        if row["surprise_scored"]:
            continue
        reasons = assessment.get("missing_fields") or []
        if not reasons:
            if row["provider_error"]:
                reasons = ["provider_error"]
            elif not row["inherited_materiality_found"]:
                reasons = ["missing_inherited_materiality"]
            elif not row["live_consensus_context"]:
                reasons = ["missing_live_consensus_context"]
            else:
                reasons = ["unclassified_null"]
        for reason in reasons:
            null_reasons[str(reason)] = null_reasons.get(str(reason), 0) + 1

    pass_gate = bool(
        coverage >= float(guardrails["minimum_surprise_coverage_with_sufficient_evidence"])
        and len(sufficient) >= int(guardrails["minimum_targets_with_usable_expectation_evidence"])
        and (
            not guardrails.get("require_inherited_materiality_provenance", True)
            or inherited_provenance_pct == 100.0
        )
        and (
            not guardrails.get("require_non_directional_reason", True)
            or non_directional_pct == 100.0
        )
        and not errors
    )

    summary = {
        "targets_attempted": len(results),
        "inherited_verified_candidates": len(inherited_verified),
        "live_consensus_context_targets": len(live_context),
        "usable_expectation_evidence_targets": len(sufficient),
        "surprise_scored_sufficient_events": len(scored_sufficient),
        "surprise_coverage_pct": coverage * 100.0,
        "inherited_provenance_complete_pct": inherited_provenance_pct,
        "non_directional_reason_pct": non_directional_pct,
        "provider_error_count": len(errors),
        "exit_gate": "PASS" if pass_gate else "FAIL",
    }
    payload = {
        "basket_id": basket["basket_id"],
        "model_version": "SOE-1.1.0",
        "phase": "1.1D",
        "generated_at": datetime.now(UTC).isoformat(),
        "default_runtime_model_unchanged": True,
        "rules_hash": candidate_rules_hash,
        "guardrails": guardrails,
        "validation_scope": "live current-period consensus structural/provider validation; not a historical pre-event backtest",
        "summary": summary,
        "null_reasons": null_reasons,
        "results": results,
    }
    _write_report(Path(output_dir), payload)
    return payload, pass_gate


def main() -> int:
    args = _parse_args()
    payload, passed = asyncio.run(
        run_validation(
            basket_path=args.basket,
            materiality_path=args.materiality,
            output_dir=args.output_dir,
        )
    )
    print(json.dumps(payload["summary"], indent=2, sort_keys=True), flush=True)
    print(f"Validation artifacts: {args.output_dir}", flush=True)
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
