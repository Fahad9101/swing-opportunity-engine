from __future__ import annotations

import argparse
import json
import os
import time
import zipfile
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from app.core.config import SOE_1_1_RULES_PATH, get_settings, load_rules_for_version, rules_hash
from app.domain.soe_v1_1 import GuidanceAction, GuidanceClassification, GuidanceMetricRecord
from app.providers.sec_edgar import TICKER_MAP_URL
from app.services.fact_extraction_service import extract_guidance_facts
from app.services.guidance_ledger_service import GuidanceLedger
from app.services.source_document_service import SourceDocumentService, index_submissions_payload


SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
DEFAULT_TICKERS = [
    "ADBE", "CRM", "PANW", "CRWD", "DELL", "HPE", "MU", "QCOM",
    "WMT", "TGT", "LOW", "HD", "NKE", "ULTA", "FDX", "UPS",
    "UNH", "HUM", "ELV", "CVS", "MDT", "SYK", "LRCX", "KLAC",
]
_ACTION_PRIORITY = {
    GuidanceAction.WITHDRAW: 6,
    GuidanceAction.LOWER: 5,
    GuidanceAction.RAISE: 4,
    GuidanceAction.REAFFIRM: 3,
    GuidanceAction.INITIATE: 2,
    GuidanceAction.NONE: 1,
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SOE-1.1A targeted primary-source guidance validation")
    parser.add_argument("--tickers", default=",".join(DEFAULT_TICKERS))
    parser.add_argument("--lookback-days", type=int, default=650)
    parser.add_argument("--max-filings", type=int, default=14)
    parser.add_argument("--max-exhibits", type=int, default=4)
    parser.add_argument("--output-dir", default="validation-results/milestone-1.1a")
    return parser.parse_args()


def _sec_user_agent() -> str:
    value = os.environ.get("SEC_USER_AGENT", "").strip()
    if "@" not in value:
        raise RuntimeError("SEC_USER_AGENT must contain a real contact email for this live validation")
    return value


def _throttled_get(client: httpx.Client, url: str, state: dict[str, float]) -> httpx.Response:
    elapsed = time.monotonic() - state.get("last", 0.0)
    wait = 0.15 - elapsed
    if wait > 0:
        time.sleep(wait)
    response = client.get(url)
    state["last"] = time.monotonic()
    return response


def _ticker_map(client: httpx.Client, cache_dir: Path, state: dict[str, float]) -> dict[str, str]:
    path = cache_dir / "ticker_map.json"
    if path.exists() and datetime.now(UTC) - datetime.fromtimestamp(path.stat().st_mtime, UTC) < timedelta(hours=24):
        payload = json.loads(path.read_text(encoding="utf-8"))
    else:
        response = _throttled_get(client, TICKER_MAP_URL, state)
        response.raise_for_status()
        payload = response.json()
        path.write_text(json.dumps(payload), encoding="utf-8")
    fields = payload.get("fields") or []
    mapping: dict[str, str] = {}
    for values in payload.get("data") or []:
        row = dict(zip(fields, values, strict=False))
        ticker = str(row.get("ticker") or "").upper().replace(".", "-")
        if ticker and row.get("cik") is not None:
            mapping[ticker] = f"{int(row['cik']):010d}"
    return mapping


def _submissions_payload(
    cik: str,
    *,
    zip_path: Path,
    archive: zipfile.ZipFile | None,
    client: httpx.Client,
    cache_dir: Path,
    state: dict[str, float],
) -> dict:
    if archive is not None:
        try:
            return json.loads(archive.read(f"CIK{cik}.json"))
        except KeyError:
            pass
    path = cache_dir / f"submissions-CIK{cik}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    response = _throttled_get(client, SUBMISSIONS_URL.format(cik=cik), state)
    response.raise_for_status()
    payload = response.json()
    path.write_text(json.dumps(payload), encoding="utf-8")
    return payload


def _deduplicate(records: list[GuidanceMetricRecord]) -> tuple[list[GuidanceMetricRecord], int]:
    """Collapse exact same-snapshot duplicates while preserving conflicting evidence."""
    groups: dict[tuple, list[GuidanceMetricRecord]] = {}
    for record in records:
        key = (
            record.comparison_key,
            record.source_timestamp,
            record.low,
            record.high,
            record.midpoint,
            record.unit,
        )
        groups.setdefault(key, []).append(record)
    result: list[GuidanceMetricRecord] = []
    removed = 0
    for rows in groups.values():
        chosen = max(rows, key=lambda item: (_ACTION_PRIORITY[item.explicit_action], item.source_url))
        result.append(chosen)
        removed += len(rows) - 1
    result.sort(key=lambda item: (item.source_timestamp, item.metric.value, item.fiscal_period, item.accounting_basis))
    return result, removed


def _comparable_pair_count(ledger: GuidanceLedger, ticker: str) -> int:
    current, prior = ledger.current_and_prior(ticker)
    prior_keys = {item.comparison_key for item in prior if item.midpoint is not None}
    return sum(1 for item in current if item.midpoint is not None and item.comparison_key in prior_keys)


def _record_summary(record: GuidanceMetricRecord) -> dict[str, Any]:
    return {
        "metric": record.metric.value,
        "period": record.fiscal_period,
        "basis": record.accounting_basis,
        "low": record.low,
        "high": record.high,
        "midpoint": record.midpoint,
        "unit": record.unit,
        "action": record.explicit_action.value,
        "source_timestamp": record.source_timestamp.isoformat(),
        "source_url": record.source_url,
        "evidence": record.evidence_span,
    }


def _markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# SOE-1.1A — Evidence & Guidance Ledger Live Validation",
        "",
        f"Generated: {report['generated_at']}",
        f"Rules hash: `{report['rules_hash']}`",
        "",
        "## Exit gate",
        "",
        f"**{summary['exit_gate']}**",
        "",
        f"- Tickers attempted: {summary['tickers_attempted']}",
        f"- Tickers with extracted guidance facts: {summary['tickers_with_guidance_records']}",
        f"- Tickers with comparable primary-source guidance: {summary['tickers_with_comparable_guidance']}",
        f"- Non-null classifications among comparable names: {summary['classified_comparable_names']}",
        f"- Comparable-guidance coverage: {summary['classification_coverage_pct']:.1f}%",
        f"- Non-null assessments with complete provenance: {summary['provenance_complete_pct']:.1f}%",
        f"- SEC/provider errors: {summary['error_count']}",
        "",
        "Gate requires >=80% classification coverage among names with comparable primary-source guidance and 100% provenance on non-null classifications. A tiny denominator is reported as INSUFFICIENT_SAMPLE rather than treated as a pass.",
        "",
        "## Ticker audit",
        "",
        "| Ticker | Records | Comparable pairs | Classification | Deterioration | Rule path | Errors |",
        "| --- | ---: | ---: | --- | --- | --- | ---: |",
    ]
    for item in report["tickers"]:
        lines.append(
            f"| {item['ticker']} | {item['guidance_records']} | {item['comparable_pairs']} | {item['classification']} | {item['guidance_deterioration']} | {item['rule_path']} | {len(item['errors'])} |"
        )
    lines += ["", "## Null / error reasons", "", "```json", json.dumps(summary["reason_counts"], indent=2, sort_keys=True), "```", ""]
    return "\n".join(lines)


def main() -> int:
    args = _parse_args()
    user_agent = _sec_user_agent()
    settings = get_settings()
    rules = load_rules_for_version(SOE_1_1_RULES_PATH, "SOE-1.1.0")
    r_hash = rules_hash(rules)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = settings.cache_dir / "sec-guidance-v1-1a"
    cache_dir.mkdir(parents=True, exist_ok=True)
    tickers = [value.strip().upper().replace(".", "-") for value in args.tickers.split(",") if value.strip()]

    client = httpx.Client(
        timeout=30,
        headers={"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"},
        follow_redirects=True,
    )
    request_state = {"last": 0.0}
    archive = None
    if settings.sec_submissions_zip_path.exists():
        archive = zipfile.ZipFile(settings.sec_submissions_zip_path)
    document_service = SourceDocumentService(
        cache_dir=cache_dir / "documents",
        user_agent=user_agent,
        client=client,
        min_request_interval_seconds=0.15,
    )

    cutoff = date.today() - timedelta(days=args.lookback_days)
    ticker_results: list[dict[str, Any]] = []
    error_count = 0
    try:
        mapping = _ticker_map(client, cache_dir, request_state)
        for ticker in tickers:
            errors: list[str] = []
            records: list[GuidanceMetricRecord] = []
            policies = []
            documents_fetched = 0
            filings_considered = 0
            cik = mapping.get(ticker)
            if not cik:
                errors.append("CIK_NOT_FOUND")
            else:
                try:
                    submissions = _submissions_payload(
                        cik,
                        zip_path=settings.sec_submissions_zip_path,
                        archive=archive,
                        client=client,
                        cache_dir=cache_dir,
                        state=request_state,
                    )
                    filings = index_submissions_payload(ticker, cik, submissions, limit=max(args.max_filings * 2, 20))
                    filings = [item for item in filings if item.filing_date is None or item.filing_date >= cutoff][: args.max_filings]
                    filings_considered = len(filings)
                    for filing in reversed(filings):
                        try:
                            refs = document_service.filing_documents(filing, max_exhibits=args.max_exhibits)
                        except (httpx.HTTPError, ValueError, json.JSONDecodeError) as exc:
                            refs = [filing]
                            errors.append(f"INDEX:{filing.accession}:{type(exc).__name__}")
                        for ref in refs:
                            try:
                                document = document_service.fetch(ref, rules_hash=r_hash)
                                documents_fetched += 1
                                extraction = extract_guidance_facts(document, rules_hash=r_hash)
                                records.extend(extraction.records)
                                if extraction.policy_evidence:
                                    policies.append(extraction.policy_evidence)
                            except (httpx.HTTPError, ValueError, OSError) as exc:
                                errors.append(f"DOC:{ref.accession}:{ref.primary_document}:{type(exc).__name__}")
                except (httpx.HTTPError, ValueError, OSError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
                    errors.append(f"SUBMISSIONS:{type(exc).__name__}")

            records, duplicate_count = _deduplicate(records)
            ledger = GuidanceLedger(records)
            comparable_pairs = _comparable_pair_count(ledger, ticker) if records else 0
            policy = max(policies, key=lambda item: item.source_timestamp) if policies else None
            if records or policy:
                assessment = ledger.assess(ticker, rules, rules_hash=r_hash, policy=policy)
                classification = assessment.classification.value
                deterioration = assessment.guidance_deterioration
                rule_path = assessment.rule_path
                reasons = assessment.reasons
                sources = assessment.sources
                current, prior = ledger.current_and_prior(ticker)
                current_summary = [_record_summary(item) for item in current]
                prior_summary = [_record_summary(item) for item in prior]
            else:
                assessment = None
                classification = GuidanceClassification.UNKNOWN.value
                deterioration = None
                rule_path = "guidance_v1_1.no_extracted_primary_guidance"
                reasons = ["No supported primary-source guidance fact was extracted in the validation window."]
                sources = []
                current_summary = []
                prior_summary = []

            error_count += len(errors)
            ticker_results.append(
                {
                    "ticker": ticker,
                    "cik": cik,
                    "filings_considered": filings_considered,
                    "documents_fetched": documents_fetched,
                    "guidance_records": len(records),
                    "duplicates_removed": duplicate_count,
                    "comparable_pairs": comparable_pairs,
                    "classification": classification,
                    "guidance_deterioration": deterioration,
                    "rule_path": rule_path,
                    "reasons": reasons,
                    "sources": sources,
                    "current": current_summary,
                    "prior": prior_summary,
                    "errors": errors,
                }
            )
    finally:
        document_service.close()
        if archive is not None:
            archive.close()
        client.close()

    comparable = [item for item in ticker_results if item["comparable_pairs"] > 0]
    classified_comparable = [item for item in comparable if item["guidance_deterioration"] is not None]
    non_null = [item for item in ticker_results if item["guidance_deterioration"] is not None]
    provenance_complete = [item for item in non_null if item["sources"] and item["rule_path"].startswith("guidance_v1_1.")]
    coverage = len(classified_comparable) / len(comparable) if comparable else 0.0
    provenance_pct = len(provenance_complete) / len(non_null) if non_null else 0.0
    reason_counts = Counter(reason for item in ticker_results for reason in item["reasons"])
    if len(comparable) < 10:
        exit_gate = "INSUFFICIENT_SAMPLE"
    elif coverage >= float(rules["validation_v1_1"]["minimum_guidance_classification_coverage_with_comparable_guidance"]) and provenance_pct == 1.0:
        exit_gate = "PASS"
    else:
        exit_gate = "FAIL"

    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "model_version": "SOE-1.1.0",
        "phase": "1.1A",
        "rules_hash": r_hash,
        "default_runtime_model_unchanged": True,
        "summary": {
            "exit_gate": exit_gate,
            "tickers_attempted": len(tickers),
            "tickers_with_guidance_records": sum(item["guidance_records"] > 0 for item in ticker_results),
            "tickers_with_comparable_guidance": len(comparable),
            "classified_comparable_names": len(classified_comparable),
            "classification_coverage_pct": coverage * 100,
            "non_null_assessments": len(non_null),
            "provenance_complete_pct": provenance_pct * 100,
            "error_count": error_count,
            "reason_counts": dict(reason_counts),
        },
        "tickers": ticker_results,
    }
    json_path = output_dir / "guidance_validation.json"
    md_path = output_dir / "PHASE_1_1A_GUIDANCE_VALIDATION.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True, default=str), encoding="utf-8")
    md_path.write_text(_markdown(report), encoding="utf-8")
    print(json.dumps(report["summary"], indent=2, sort_keys=True))
    print(f"JSON: {json_path}")
    print(f"Report: {md_path}")
    return 0 if exit_gate == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
