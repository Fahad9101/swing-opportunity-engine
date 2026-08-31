from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from app.core.config import rules_hash
from app.orchestration.scan_pipeline import run_full_scan, scan_manager
from app.persistence.database import SessionLocal, init_database
from app.persistence.orm_models import (
    CatalystORM,
    CorporateEventORM,
    FundamentalSnapshotORM,
    InstrumentORM,
    ProviderErrorORM,
    ScannerMatchORM,
    ValidationIssueORM,
)


def _value(value):
    return getattr(value, "value", value)


def _component_score(component):
    return None if component is None else component.score


def _opportunity_row(item) -> dict:
    return {
        "ticker": item.ticker,
        "company": item.company,
        "sector": item.sector,
        "is_biotech": item.is_biotech,
        "price": item.price,
        "market_cap": item.market_cap,
        "primary_scanner": _value(item.primary_scanner),
        "secondary_scanners": [_value(value) for value in item.secondary_scanners],
        "opportunity_score": item.scores.opportunity_score,
        "base_opportunity_score": item.scores.base_opportunity_score,
        "penalty_points": item.scores.penalty_points,
        "multi_scanner_bonus": item.scores.multi_scanner_bonus,
        "components": {
            "catalyst": _component_score(item.scores.catalyst),
            "fundamental": _component_score(item.scores.fundamental),
            "valuation": _component_score(item.scores.valuation),
            "technical": _component_score(item.scores.technical),
            "revisions": _component_score(item.scores.revisions),
            "balance_sheet": _component_score(item.scores.balance_sheet),
            "liquidity": _component_score(item.scores.liquidity),
        },
        "automatic_rejections": list(item.automatic_rejections),
        "data_completeness": item.data_completeness.model_dump(mode="json"),
    }


def _database_coverage(scan_run_id: str) -> dict:
    with SessionLocal() as session:
        scanner_tickers = set(
            session.scalars(
                select(ScannerMatchORM.ticker).where(ScannerMatchORM.scan_run_id == scan_run_id).distinct()
            ).all()
        )
        biotech_tickers = set(
            session.scalars(
                select(InstrumentORM.ticker).where(
                    InstrumentORM.ticker.in_(scanner_tickers),
                    InstrumentORM.is_biotech.is_(True),
                )
            ).all()
        ) if scanner_tickers else set()

        fundamentals = session.scalars(
            select(FundamentalSnapshotORM).where(FundamentalSnapshotORM.scan_run_id == scan_run_id)
        ).all()
        biotech_fundamentals = [row for row in fundamentals if row.ticker in biotech_tickers]

        runway_available = 0
        runway_preferred = 0
        runway_eligible_12_18 = 0
        runway_below_12 = 0
        runway_below_9 = 0
        financing_reviewed = 0
        financing_secured = 0
        for row in biotech_fundamentals:
            data = row.normalized_data or {}
            runway = data.get("cash_runway_months")
            financing = data.get("financing_secured")
            if runway is not None:
                runway_available += 1
                if runway >= 18:
                    runway_preferred += 1
                elif runway >= 12:
                    runway_eligible_12_18 += 1
                else:
                    runway_below_12 += 1
                    if runway < 9:
                        runway_below_9 += 1
            if financing is not None:
                financing_reviewed += 1
                financing_secured += int(bool(financing))

        event_rows = session.scalars(
            select(CorporateEventORM).where(CorporateEventORM.scan_run_id == scan_run_id)
        ).all()
        biotech_event_tickers = {row.ticker for row in event_rows if row.ticker in biotech_tickers}
        biotech_event_candidates = {
            row.ticker
            for row in event_rows
            if row.ticker in biotech_tickers and bool((row.normalized_data or {}).get("catalyst_candidate"))
        }

        catalyst_rows = session.scalars(
            select(CatalystORM).where(CatalystORM.scan_run_id == scan_run_id)
        ).all()
        biotech_scored_catalyst_tickers = {row.ticker for row in catalyst_rows if row.ticker in biotech_tickers}

        provider_rows = session.scalars(
            select(ProviderErrorORM).where(ProviderErrorORM.scan_run_id == scan_run_id)
        ).all()
        validation_rows = session.scalars(
            select(ValidationIssueORM).where(ValidationIssueORM.scan_run_id == scan_run_id)
        ).all()

        return {
            "universal_survivor_tickers_persisted": len(scanner_tickers),
            "biotech_universal_survivors": len(biotech_tickers),
            "biotech_fundamental_snapshots": len(biotech_fundamentals),
            "biotech_runway_available": runway_available,
            "biotech_runway_preferred_18m_plus": runway_preferred,
            "biotech_runway_12_to_18m": runway_eligible_12_18,
            "biotech_runway_below_12m": runway_below_12,
            "biotech_runway_below_9m": runway_below_9,
            "biotech_financing_reviewed": financing_reviewed,
            "biotech_financing_secured": financing_secured,
            "biotech_with_public_events": len(biotech_event_tickers),
            "biotech_with_public_catalyst_candidate_evidence": len(biotech_event_candidates),
            "biotech_with_scored_catalyst": len(biotech_scored_catalyst_tickers),
            "provider_error_count_persisted": len(provider_rows),
            "provider_errors_by_code": dict(Counter(row.code for row in provider_rows)),
            "provider_errors_by_provider": dict(Counter(row.provider for row in provider_rows)),
            "validation_issue_count_persisted": len(validation_rows),
            "validation_issues_by_code": dict(Counter(row.code for row in validation_rows)),
        }


def _markdown(report: dict) -> str:
    funnel = report["funnel"]
    coverage = report["coverage"]
    lines = [
        "# Milestone 2.5 — Final Free/Public Full-Market Validation",
        "",
        f"Generated: {report['generated_at']}",
        f"Model: `{report['model_version']}`",
        f"Rules hash: `{report['rules_hash']}`",
        f"Scan run ID: `{report['scan_run_id']}`",
        "",
        "## Outcome",
        "",
        f"Scan status: **{report['status']}**. Market regime: **{report['market_regime']}**. ",
        "No SOE investment threshold, scanner rule, score weight, classification, or Investment Execution Engine logic is changed by this validation runner.",
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
        "## Missing-data rates",
        "",
        "| Domain | Missing rate |",
        "| --- | ---: |",
    ]
    for key, value in report["missing_data_rates"].items():
        lines.append(f"| {key} | {value:.2f}% |")

    lines.extend([
        "",
        "## Biotech public-data coverage",
        "",
        "| Metric | Result |",
        "| --- | ---: |",
        f"| Biotech universal survivors | {coverage['biotech_universal_survivors']} |",
        f"| Fundamental snapshots | {coverage['biotech_fundamental_snapshots']} |",
        f"| Runway available | {coverage['biotech_runway_available']} |",
        f"| Runway ≥18 months | {coverage['biotech_runway_preferred_18m_plus']} |",
        f"| Runway 12–<18 months | {coverage['biotech_runway_12_to_18m']} |",
        f"| Runway <12 months | {coverage['biotech_runway_below_12m']} |",
        f"| Runway <9 months | {coverage['biotech_runway_below_9m']} |",
        f"| Financing status reviewed | {coverage['biotech_financing_reviewed']} |",
        f"| Completed/secured financing detected | {coverage['biotech_financing_secured']} |",
        f"| With public event evidence | {coverage['biotech_with_public_events']} |",
        f"| With catalyst-candidate public evidence | {coverage['biotech_with_public_catalyst_candidate_evidence']} |",
        f"| With fully scored catalyst | {coverage['biotech_with_scored_catalyst']} |",
        "",
        "## Provider / validation health",
        "",
        f"Persisted provider errors: **{coverage['provider_error_count_persisted']}**  ",
        f"Persisted validation issues: **{coverage['validation_issue_count_persisted']}**  ",
        f"Ticker-processing errors: **{report['ticker_error_count']}**",
        "",
        "Provider errors by code:",
        "",
        "```json",
        json.dumps(coverage["provider_errors_by_code"], indent=2, sort_keys=True),
        "```",
        "",
        "Validation issues by code:",
        "",
        "```json",
        json.dumps(coverage["validation_issues_by_code"], indent=2, sort_keys=True),
        "```",
        "",
        "## Top 20 discovery opportunities",
        "",
    ])

    top = report["top_20"]
    if not top:
        lines.append("No scanner-qualified opportunities were produced. No Top 20 is manufactured from rejected or DATA_INCOMPLETE securities.")
    else:
        lines.extend([
            "| Rank | Ticker | Scanner | Opportunity Score | Catalyst | Fundamental | Valuation | Technical | Revisions | Balance Sheet | Liquidity |",
            "| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ])
        for rank, item in enumerate(top, start=1):
            c = item["components"]
            def fmt(value):
                return "NA" if value is None else f"{value:.2f}"
            lines.append(
                f"| {rank} | {item['ticker']} | {item['primary_scanner']} | {fmt(item['opportunity_score'])} | "
                f"{fmt(c['catalyst'])} | {fmt(c['fundamental'])} | {fmt(c['valuation'])} | {fmt(c['technical'])} | "
                f"{fmt(c['revisions'])} | {fmt(c['balance_sheet'])} | {fmt(c['liquidity'])} |"
            )

    lines.extend([
        "",
        "## Frozen-rule integrity",
        "",
        "This run uses the repository's existing `SOE-1.0.0` rules and production provider adapters. The validation runner only reports outputs; it does not alter investment rules or start Milestone 3.",
        "",
    ])
    return "\n".join(lines)


async def _run(json_out: Path, markdown_out: Path) -> int:
    init_database()
    state = scan_manager.create()
    result = await run_full_scan(state.scan_run_id, provider_name="free_public")
    scan_run_id = str(result.scan_run_id)
    coverage = _database_coverage(scan_run_id)
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
        "provider_errors_in_memory": result.provider_errors,
        "validation_issues_in_memory_count": len(result.validation_issues),
        "coverage": coverage,
        "top_20": opportunities[:20],
        "all_opportunities": opportunities,
    }
    json_out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    markdown_out.write_text(_markdown(report), encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "scan_run_id": scan_run_id,
        "universe_size": report["funnel"]["universe_size"],
        "universal_passes": report["funnel"]["universal_passes"],
        "technical_survivors": report["funnel"]["technical_survivors"],
        "scanner_matches": report["funnel"]["scanner_matches"],
        "scanner_data_incomplete": report["funnel"]["scanner_data_incomplete"],
        "candidate_count": report["funnel"]["candidate_count"],
        "fully_scored_count": report["funnel"]["fully_scored_count"],
        "missing_data_rates": report["missing_data_rates"],
        "coverage": coverage,
        "top_20": [item["ticker"] for item in report["top_20"]],
    }, indent=2, default=str))
    return 0 if report["status"] == "COMPLETED" else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the final Milestone 2.5 free/public full-market validation")
    parser.add_argument("--json-out", type=Path, default=Path("final_full_market_validation.json"))
    parser.add_argument("--markdown-out", type=Path, default=Path("MILESTONE_2_5_FINAL_FULL_MARKET_REPORT.md"))
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_run(args.json_out, args.markdown_out)))


if __name__ == "__main__":
    main()
