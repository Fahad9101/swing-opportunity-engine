from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from app.cli_final_full_market_validation import _opportunity_row
from app.core.config import rules_hash
from app.orchestration.scan_pipeline import run_full_scan, scan_manager
from app.persistence.database import SessionLocal, init_database
from app.persistence.orm_models import (
    CatalystORM,
    CorporateEventORM,
    EstimateSnapshotORM,
    FundamentalSnapshotORM,
    OpportunityORM,
    ProviderErrorORM,
    ScannerMatchORM,
    ValidationIssueORM,
)


def _value(value):
    return getattr(value, "value", value)


def _present(data: dict, field: str) -> bool:
    return data.get(field) is not None


def _diagnostics(scan_run_id: str) -> dict:
    with SessionLocal() as session:
        scanner_rows = session.scalars(
            select(ScannerMatchORM).where(ScannerMatchORM.scan_run_id == scan_run_id)
        ).all()
        incomplete_fields: dict[str, Counter] = defaultdict(Counter)
        incomplete_rows: Counter = Counter()
        for row in scanner_rows:
            evidence = row.evidence or {}
            if evidence.get("evaluation_status") != "DATA_INCOMPLETE":
                continue
            incomplete_rows[row.scanner] += 1
            for field in evidence.get("incomplete_fields") or []:
                incomplete_fields[row.scanner][field] += 1

        fundamentals = session.scalars(
            select(FundamentalSnapshotORM).where(FundamentalSnapshotORM.scan_run_id == scan_run_id)
        ).all()
        fundamental_fields = [
            "guidance_deterioration",
            "balance_sheet_distressed",
            "valuation_discount",
            "expected_swing_upside",
            "fundamental_undervaluation",
            "institutional_ownership",
            "short_float",
            "cash_runway_months",
            "financing_secured",
            "fcf_growth",
            "operating_margin_expansion_bps",
            "forward_ebitda_growth",
        ]
        fundamental_availability = {
            field: sum(_present(row.normalized_data or {}, field) for row in fundamentals)
            for field in fundamental_fields
        }

        estimates = session.scalars(
            select(EstimateSnapshotORM).where(EstimateSnapshotORM.scan_run_id == scan_run_id)
        ).all()
        estimate_fields = [
            "forward_eps_growth",
            "eps_up_revisions",
            "eps_down_revisions",
            "eps_revision_30d",
            "eps_revision_90d",
            "forward_revenue",
            "revenue_up_revisions",
            "revenue_down_revisions",
            "forward_ebitda",
            "ebitda_up_revisions",
            "ebitda_down_revisions",
        ]
        estimate_availability = {
            field: sum(_present(row.normalized_data or {}, field) for row in estimates)
            for field in estimate_fields
        }

        opportunities = session.scalars(
            select(OpportunityORM).where(OpportunityORM.scan_run_id == scan_run_id)
        ).all()
        component_fields = {
            "catalyst": "catalyst_score",
            "fundamental": "fundamental_score",
            "valuation": "valuation_score",
            "technical": "technical_score",
            "revisions": "revision_score",
            "balance_sheet": "balance_sheet_score",
            "liquidity": "liquidity_score",
        }
        component_unavailable = {
            component: sum(getattr(row, column) is None for row in opportunities)
            for component, column in component_fields.items()
        }

        events = session.scalars(
            select(CorporateEventORM).where(CorporateEventORM.scan_run_id == scan_run_id)
        ).all()
        catalyst_candidate_events = [row for row in events if bool((row.normalized_data or {}).get("catalyst_candidate"))]
        catalyst_missing_score_fields: Counter = Counter()
        for row in catalyst_candidate_events:
            for field in (row.normalized_data or {}).get("missing_score_fields") or []:
                catalyst_missing_score_fields[field] += 1
        scored_catalysts = session.scalars(
            select(CatalystORM).where(CatalystORM.scan_run_id == scan_run_id)
        ).all()

        provider_errors = session.scalars(
            select(ProviderErrorORM).where(ProviderErrorORM.scan_run_id == scan_run_id)
        ).all()
        validation_issues = session.scalars(
            select(ValidationIssueORM).where(ValidationIssueORM.scan_run_id == scan_run_id)
        ).all()

        yahoo_errors = [row for row in provider_errors if row.provider == "yahoo_combined_prototype"]
        yahoo_auth_or_rate = [row for row in yahoo_errors if row.code in {"PROVIDER_AUTH_ERROR", "PROVIDER_RATE_LIMITED"}]

        structural = []
        if opportunities and component_unavailable["catalyst"] == len(opportunities):
            structural.append(
                "All scanner-qualified opportunities lack the frozen Catalyst Score because structured free/public events do not supply materiality and surprise/re-rating potential."
            )
        if fundamental_availability["guidance_deterioration"] == 0:
            structural.append(
                "Guidance deterioration remains unavailable because SOE-1.0.0 contains no frozen deterministic text-to-guidance classifier; no new heuristic was invented."
            )
        if fundamental_availability["balance_sheet_distressed"] == 0:
            structural.append(
                "Growth-Pullback balance-sheet distress state remains unavailable because SOE-1.0.0 contains no frozen cross-sector distress classifier; no new threshold was invented."
            )

        return {
            "scanner_incomplete_rows": dict(incomplete_rows),
            "scanner_incomplete_fields": {scanner: dict(counter) for scanner, counter in incomplete_fields.items()},
            "fundamental_snapshot_count": len(fundamentals),
            "fundamental_field_availability": fundamental_availability,
            "estimate_snapshot_count": len(estimates),
            "estimate_field_availability": estimate_availability,
            "opportunity_count": len(opportunities),
            "opportunity_component_unavailable": component_unavailable,
            "corporate_event_count": len(events),
            "catalyst_candidate_event_count": len(catalyst_candidate_events),
            "catalyst_candidate_missing_score_fields": dict(catalyst_missing_score_fields),
            "scored_catalyst_count": len(scored_catalysts),
            "provider_error_count": len(provider_errors),
            "provider_errors_by_code": dict(Counter(row.code for row in provider_errors)),
            "provider_errors_by_provider": dict(Counter(row.provider for row in provider_errors)),
            "provider_errors_by_status": dict(Counter(str(row.status_code) for row in provider_errors if row.status_code is not None)),
            "yahoo_combined_error_count": len(yahoo_errors),
            "yahoo_combined_auth_or_rate_error_count": len(yahoo_auth_or_rate),
            "validation_issue_count": len(validation_issues),
            "validation_issues_by_code": dict(Counter(row.code for row in validation_issues)),
            "structural_free_stack_blockers": structural,
        }


def _markdown(report: dict) -> str:
    funnel = report["funnel"]
    d = report["diagnostics"]
    lines = [
        "# Milestone 2.5J — Free-Data Reliability & Scoring-Completeness Hardening",
        "",
        f"Generated: {report['generated_at']}",
        f"Model: `{report['model_version']}`",
        f"Rules hash: `{report['rules_hash']}`",
        f"Scan run ID: `{report['scan_run_id']}`",
        "",
        "## Integrity result",
        "",
        "This validation changes no SOE-1.0.0 investment threshold, score weight, scanner condition, classification, or Investment Execution Engine v1.7.2 logic.",
        "The Yahoo change is transport-only: one shared authenticated/cache payload per ticker, serialized requests, deterministic throttling, and explicit 429 backoff.",
        "",
        "## Full-market funnel",
        "",
        "| Metric | Result |",
        "| --- | ---: |",
        f"| Universe | {funnel['universe_size']} |",
        f"| Universal-gate survivors | {funnel['universal_passes']} |",
        f"| Technical-ready survivors | {funnel['technical_survivors']} |",
        f"| Re-Rating qualified | {funnel['scanner_matches'].get('RERATING', 0)} |",
        f"| Growth Pullback qualified | {funnel['scanner_matches'].get('GROWTH_PULLBACK', 0)} |",
        f"| Biotech/Catalyst qualified | {funnel['scanner_matches'].get('BIOTECH_CATALYST', 0)} |",
        f"| Deduplicated opportunities | {funnel['candidate_count']} |",
        f"| Fully scored opportunities | {funnel['fully_scored_count']} |",
        "",
        "## Provider reliability",
        "",
        f"Total provider errors: **{d['provider_error_count']}**  ",
        f"Shared Yahoo errors: **{d['yahoo_combined_error_count']}**  ",
        f"Yahoo authentication/rate-limit errors: **{d['yahoo_combined_auth_or_rate_error_count']}**",
        "",
        "```json",
        json.dumps(d["provider_errors_by_code"], indent=2, sort_keys=True),
        "```",
        "",
        "## Exact DATA_INCOMPLETE fields",
        "",
    ]
    for scanner in ("RERATING", "GROWTH_PULLBACK", "BIOTECH_CATALYST"):
        lines.extend([
            f"### {scanner}",
            "",
            f"Incomplete rows: **{d['scanner_incomplete_rows'].get(scanner, 0)}**",
            "",
            "```json",
            json.dumps(d["scanner_incomplete_fields"].get(scanner, {}), indent=2, sort_keys=True),
            "```",
            "",
        ])

    lines.extend([
        "## Field availability among persisted snapshots",
        "",
        f"Fundamental snapshots: **{d['fundamental_snapshot_count']}**",
        "",
        "```json",
        json.dumps(d["fundamental_field_availability"], indent=2, sort_keys=True),
        "```",
        "",
        f"Estimate snapshots: **{d['estimate_snapshot_count']}**",
        "",
        "```json",
        json.dumps(d["estimate_field_availability"], indent=2, sort_keys=True),
        "```",
        "",
        "## Scoring completeness",
        "",
        f"Scanner-qualified opportunities: **{d['opportunity_count']}**",
        "",
        "Unavailable components across those opportunities:",
        "",
        "```json",
        json.dumps(d["opportunity_component_unavailable"], indent=2, sort_keys=True),
        "```",
        "",
        f"Corporate events persisted: **{d['corporate_event_count']}**  ",
        f"Catalyst-candidate events: **{d['catalyst_candidate_event_count']}**  ",
        f"Fully scored catalysts: **{d['scored_catalyst_count']}**",
        "",
        "Missing fields on catalyst-candidate events:",
        "",
        "```json",
        json.dumps(d["catalyst_candidate_missing_score_fields"], indent=2, sort_keys=True),
        "```",
        "",
        "## Structural free-stack blockers",
        "",
    ])
    if d["structural_free_stack_blockers"]:
        for item in d["structural_free_stack_blockers"]:
            lines.append(f"- {item}")
    else:
        lines.append("- None identified by this diagnostic pass.")

    lines.extend([
        "",
        "## Top 20 discovery opportunities",
        "",
        "| Rank | Ticker | Scanner | Opportunity Score | Catalyst | Fundamental | Valuation | Technical | Revisions | Balance Sheet | Liquidity |",
        "| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ])
    for rank, item in enumerate(report["top_20"], start=1):
        c = item["components"]
        fmt = lambda value: "NA" if value is None else f"{value:.2f}"
        lines.append(
            f"| {rank} | {item['ticker']} | {item['primary_scanner']} | {fmt(item['opportunity_score'])} | {fmt(c['catalyst'])} | "
            f"{fmt(c['fundamental'])} | {fmt(c['valuation'])} | {fmt(c['technical'])} | {fmt(c['revisions'])} | "
            f"{fmt(c['balance_sheet'])} | {fmt(c['liquidity'])} |"
        )

    lines.extend([
        "",
        "## Milestone 2.5 decision gate",
        "",
        "Milestone 2.5J is a data-layer validation milestone only. If the shared Yahoo adapter is operationally stable but the Catalyst Score remains structurally unavailable, the report must say so explicitly rather than manufacturing materiality/surprise values. Any future change to those frozen scoring inputs belongs in a separately approved model version, not a silent SOE-1.0.0 modification.",
        "",
    ])
    return "\n".join(lines)


async def _run(json_out: Path, markdown_out: Path) -> int:
    init_database()
    state = scan_manager.create()
    result = await run_full_scan(state.scan_run_id, provider_name="free_public")
    scan_run_id = str(result.scan_run_id)
    diagnostics = _diagnostics(scan_run_id)
    opportunities = [_opportunity_row(item) for item in result.opportunities]
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "scan_run_id": scan_run_id,
        "status": _value(result.status),
        "stage": result.stage,
        "model_version": result.model_version,
        "rules_hash": result.rules_hash,
        "rules_hash_runtime": rules_hash(),
        "market_regime": _value(result.market_regime.regime) if result.market_regime else None,
        "breadth_available": bool(result.market_regime.breadth_available) if result.market_regime else False,
        "funnel": {
            "universe_size": result.universe_count,
            "universal_passes": result.universal_pass_count,
            "technical_survivors": result.technical_survivor_count,
            "scanner_matches": result.scanner_match_counts,
            "scanner_data_incomplete": result.scanner_incomplete_counts,
            "candidate_count": len(result.opportunities),
            "fully_scored_count": result.fully_scored_count,
        },
        "missing_data_rates": result.missing_data_rates,
        "ticker_error_count": result.error_count,
        "ticker_errors": result.errors,
        "diagnostics": diagnostics,
        "top_20": opportunities[:20],
        "all_opportunities": opportunities,
    }
    json_out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    markdown_out.write_text(_markdown(report), encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "scan_run_id": scan_run_id,
        "funnel": report["funnel"],
        "missing_data_rates": report["missing_data_rates"],
        "yahoo_combined_auth_or_rate_error_count": diagnostics["yahoo_combined_auth_or_rate_error_count"],
        "scanner_incomplete_fields": diagnostics["scanner_incomplete_fields"],
        "opportunity_component_unavailable": diagnostics["opportunity_component_unavailable"],
        "scored_catalyst_count": diagnostics["scored_catalyst_count"],
        "structural_free_stack_blockers": diagnostics["structural_free_stack_blockers"],
        "top_20": [item["ticker"] for item in report["top_20"]],
    }, indent=2, default=str))
    return 0 if report["status"] == "COMPLETED" else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Milestone 2.5J free-data reliability and scoring-completeness validation")
    parser.add_argument("--json-out", type=Path, default=Path("milestone_2_5j_validation.json"))
    parser.add_argument("--markdown-out", type=Path, default=Path("MILESTONE_2_5J_REPORT.md"))
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_run(args.json_out, args.markdown_out)))


if __name__ == "__main__":
    main()
