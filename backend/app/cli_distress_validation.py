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
from app.domain.distress_v1_1 import DistressClassification, DistressSectorAdapter
from app.providers.sec_distress import normalize_distress_companyfacts
from app.providers.sec_edgar import TICKER_MAP_URL
from app.services.distress_classifier import classify_distress
from app.services.distress_fact_extraction_service import extract_hard_distress_flags, finalize_hard_distress_screen
from app.services.distress_metric_service import derive_distress_inputs
from app.services.source_document_service import SourceDocumentService, index_submissions_payload


COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
_ALLOWED_SCREEN_FORMS = {"10-K", "10-Q", "8-K", "6-K"}
_NONFINANCIAL_ADAPTERS = {
    DistressSectorAdapter.CORPORATE,
    DistressSectorAdapter.UTILITY,
    DistressSectorAdapter.REIT,
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SOE-1.1B primary-source balance-sheet distress validation")
    parser.add_argument("--basket", default="validation/phase_1_1b_preregistered_basket_v1.json")
    parser.add_argument("--output-dir", default="validation-results/milestone-1.1b")
    parser.add_argument("--lookback-days", type=int, default=500)
    parser.add_argument("--max-event-filings", type=int, default=16)
    return parser.parse_args()


def _sec_user_agent() -> str:
    value = os.environ.get("SEC_USER_AGENT", "").strip()
    if "@" not in value:
        raise RuntimeError("SEC_USER_AGENT must contain a real contact email for live validation")
    return value


def _throttled_get(client: httpx.Client, url: str, state: dict[str, float]) -> httpx.Response:
    elapsed = time.monotonic() - state.get("last", 0.0)
    wait = 0.15 - elapsed
    if wait > 0:
        time.sleep(wait)
    response = client.get(url)
    state["last"] = time.monotonic()
    return response


def _cached_json(client: httpx.Client, url: str, path: Path, state: dict[str, float]) -> dict[str, Any]:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    response = _throttled_get(client, url, state)
    response.raise_for_status()
    payload = response.json()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return payload


def _ticker_map(client: httpx.Client, cache_dir: Path, state: dict[str, float]) -> dict[str, str]:
    path = cache_dir / "ticker_map.json"
    if path.exists() and datetime.now(UTC) - datetime.fromtimestamp(path.stat().st_mtime, UTC) < timedelta(hours=24):
        payload = json.loads(path.read_text(encoding="utf-8"))
    else:
        response = _throttled_get(client, TICKER_MAP_URL, state)
        response.raise_for_status()
        payload = response.json()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
    fields = payload.get("fields") or []
    mapping: dict[str, str] = {}
    for values in payload.get("data") or []:
        row = dict(zip(fields, values, strict=False))
        ticker = str(row.get("ticker") or "").upper().replace(".", "-")
        if ticker and row.get("cik") is not None:
            mapping[ticker] = f"{int(row['cik']):010d}"
    return mapping


def _bulk_or_live_payload(
    *,
    cik: str,
    archive: zipfile.ZipFile | None,
    member: str,
    live_url: str,
    client: httpx.Client,
    cache_path: Path,
    state: dict[str, float],
) -> dict[str, Any]:
    if archive is not None:
        try:
            return json.loads(archive.read(member))
        except KeyError:
            pass
    return _cached_json(client, live_url, cache_path, state)


def _screen_refs(submissions: dict[str, Any], *, ticker: str, cik: str, cutoff: date, max_event_filings: int):
    refs = index_submissions_payload(ticker, cik, submissions, allowed_forms=_ALLOWED_SCREEN_FORMS, limit=120)
    refs = [ref for ref in refs if ref.filing_date is not None and ref.filing_date >= cutoff]
    periodic = [ref for ref in refs if ref.form in {"10-K", "10-Q"}]
    if not periodic:
        return [], 1, ["NO_RECENT_PERIODIC_FILING"], 0
    latest_periodic = max(periodic, key=lambda item: (item.filing_date or date.min, item.accession))
    newer_events = [
        ref
        for ref in refs
        if ref.form in {"8-K", "6-K"} and (ref.filing_date or date.min) > (latest_periodic.filing_date or date.min)
    ]
    newer_events.sort(key=lambda item: (item.filing_date or date.min, item.accession))
    overflow = max(0, len(newer_events) - max_event_filings)
    selected = [latest_periodic] + newer_events[:max_event_filings]
    failures = [f"UNSCREENED_EVENT_OVERFLOW:{overflow}"] if overflow else []
    required_count = len(selected) + overflow
    return selected, required_count, failures, overflow


def _sufficient_inputs(adapter: DistressSectorAdapter, inputs) -> tuple[bool, list[str]]:
    """Identify names with enough evidence for at least one complete frozen rule path.

    Merely possessing one side of an adverse/safe decision is not sufficient.
    For example, debt plus 2.7x interest coverage can rule out the absolute <1x
    distress trigger but cannot establish either the paired leverage distress
    rule or a frozen safety path. Such a name remains outside the validation
    denominator until leverage/liquidity/runway evidence completes a rule path.
    This changes validation-denominator semantics only; classifier thresholds and
    investment rules are unchanged.
    """
    reasons: list[str] = []
    if inputs.hard_distress_flags:
        return True, ["verified_hard_distress_flag"]

    if adapter is DistressSectorAdapter.CORPORATE:
        if inputs.net_cash is True:
            reasons.append("verified_net_cash")
        if inputs.net_debt_to_ebitda is not None and inputs.interest_coverage is not None:
            reasons.append("complete_leverage_and_interest_coverage_pair")
        if inputs.liquidity_coverage is not None:
            reasons.append("verified_12m_liquidity_coverage")
        if inputs.trailing_fcf is not None and inputs.trailing_fcf < 0 and inputs.cash_runway_months is not None:
            reasons.append("negative_fcf_and_runway")
        # Absolute coverage alone is decisive only when it actually trips the
        # frozen <1x distress threshold; otherwise it is partial evidence.
        if (
            inputs.debt_outstanding is not None
            and inputs.debt_outstanding > 0
            and inputs.interest_coverage is not None
            and inputs.interest_coverage < 1.0
        ):
            reasons.append("absolute_interest_coverage_distress_path")
    elif adapter is DistressSectorAdapter.UTILITY:
        if inputs.net_debt_to_ebitda is not None and inputs.interest_coverage is not None:
            reasons.append("utility_complete_leverage_and_interest_coverage_pair")
        if inputs.liquidity_coverage is not None:
            reasons.append("utility_verified_12m_liquidity_coverage")
    elif adapter is DistressSectorAdapter.REIT:
        if inputs.debt_to_ebitdare is not None and inputs.fixed_charge_coverage is not None:
            reasons.append("reit_complete_debt_ebitdare_and_fixed_charge_coverage_pair")
        if inputs.liquidity_coverage is not None:
            reasons.append("reit_verified_12m_liquidity_coverage")
    elif adapter is DistressSectorAdapter.BANK:
        if inputs.regulatory_capital_breach is True or inputs.prompt_corrective_action_unresolved is True:
            reasons.append("bank_regulatory_breach_path")
        if inputs.cet1_ratio is not None and inputs.cet1_requirement_plus_buffer is not None:
            reasons.append("bank_cet1_pair")
    elif adapter is DistressSectorAdapter.INSURER:
        if inputs.insurer_solvency_ratio is not None and inputs.insurer_regulatory_action_threshold is not None:
            reasons.append("insurer_regulatory_solvency_pair")
    return bool(reasons), reasons


def _safe_input_integrity(assessment) -> bool:
    if assessment.classification is not DistressClassification.NOT_DISTRESSED:
        return True
    if not assessment.hard_flag_screen_complete:
        return False
    path = assessment.rule_path
    if path.endswith("corporate.net_cash_safe"):
        return assessment.sector_specific_metrics.get("net_cash") is True
    if path.endswith("corporate.leverage_coverage_safe") or path.endswith("utilities.leverage_coverage_safe"):
        return assessment.net_debt_to_ebitda is not None and assessment.interest_coverage is not None
    if path.endswith("corporate.liquidity_fcf_safe"):
        return assessment.liquidity_coverage is not None and assessment.debt_maturities_12m is not None and assessment.sector_specific_metrics.get("trailing_fcf") is not None
    if path.endswith("corporate.negative_fcf_runway_safe"):
        return assessment.cash_runway_months is not None and assessment.sector_specific_metrics.get("trailing_fcf") is not None
    if path.endswith("reits.leverage_coverage_safe"):
        return assessment.sector_specific_metrics.get("debt_to_ebitdare") is not None and assessment.sector_specific_metrics.get("fixed_charge_coverage") is not None
    if path.endswith("banks.cet1_excess_safe"):
        return assessment.sector_specific_metrics.get("cet1_ratio") is not None and assessment.sector_specific_metrics.get("cet1_requirement_plus_buffer") is not None
    if path.endswith("insurers.solvency_margin_safe"):
        return assessment.sector_specific_metrics.get("insurer_solvency_ratio") is not None and assessment.sector_specific_metrics.get("insurer_regulatory_action_threshold") is not None
    return False


def _write_report(output_dir: Path, payload: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "distress_validation.json").write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
    summary = payload["summary"]
    lines = [
        "# Phase 1.1B Balance-Sheet Distress Validation",
        "",
        f"- Basket: `{payload['basket_id']}`",
        f"- Model: `{payload['model_version']}`",
        f"- Rules hash: `{payload['rules_hash']}`",
        f"- Tickers attempted: **{summary['tickers_attempted']}**",
        f"- Non-financial names with sufficient inputs: **{summary['nonfinancial_sufficient_inputs']}**",
        f"- Non-financial classified: **{summary['nonfinancial_classified']}**",
        f"- Classification coverage: **{summary['classification_coverage_pct']:.2f}%**",
        f"- Financial corporate fallback count: **{summary['financial_corporate_fallback_count']}**",
        f"- False-safe missing-data count: **{summary['false_safe_missing_maturity_or_coverage_count']}**",
        f"- Non-null provenance complete: **{summary['provenance_complete_pct']:.2f}%**",
        f"- Provider/execution errors: **{summary['error_count']}**",
        f"- Exit gate: **{summary['exit_gate']}**",
        "",
        "## Classification counts",
        "",
    ]
    for key, value in sorted(payload["classification_counts"].items()):
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Per-name audit", ""])
    for row in payload["results"]:
        lines.append(
            f"- **{row['ticker']}** ({row['adapter']}): {row['classification']} | sufficient={row['sufficient_inputs']} | screen={row['hard_flag_screen_complete']} | path=`{row['rule_path']}`"
        )
    (output_dir / "PHASE_1_1B_DISTRESS_VALIDATION.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    args = _parse_args()
    user_agent = _sec_user_agent()
    rules = load_rules_for_version(SOE_1_1_RULES_PATH, "SOE-1.1.0")
    current_rules_hash = rules_hash(rules)
    settings = get_settings()
    basket_path = Path(args.basket)
    basket = json.loads(basket_path.read_text(encoding="utf-8"))
    entries = basket.get("entries") or []
    if not entries:
        raise RuntimeError("Phase 1.1B basket has no entries")

    cache_dir = Path(settings.cache_dir) / "phase-1.1b"
    cache_dir.mkdir(parents=True, exist_ok=True)
    state: dict[str, float] = {}
    headers = {"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"}
    cutoff = datetime.now(UTC).date() - timedelta(days=args.lookback_days)

    companyfacts_archive = zipfile.ZipFile(settings.sec_companyfacts_zip_path) if settings.sec_companyfacts_zip_path.exists() else None
    submissions_archive = zipfile.ZipFile(settings.sec_submissions_zip_path) if settings.sec_submissions_zip_path.exists() else None
    results: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    classification_counts: Counter[str] = Counter()

    with httpx.Client(timeout=30, headers=headers, follow_redirects=True) as client:
        ticker_map = _ticker_map(client, cache_dir, state)
        document_service = SourceDocumentService(
            cache_dir=cache_dir / "documents",
            user_agent=user_agent,
            timeout_seconds=30,
            min_request_interval_seconds=0.15,
        )
        try:
            for index, entry in enumerate(entries, start=1):
                ticker = str(entry["ticker"]).upper().replace(".", "-")
                adapter = DistressSectorAdapter(str(entry["adapter"]))
                print(f"[{index}/{len(entries)}] {ticker} ({adapter.value})", flush=True)
                cik = ticker_map.get(ticker)
                if not cik:
                    errors.append({"ticker": ticker, "stage": "ticker_map", "error": "CIK_NOT_FOUND"})
                    continue
                try:
                    companyfacts = _bulk_or_live_payload(
                        cik=cik,
                        archive=companyfacts_archive,
                        member=f"CIK{cik}.json",
                        live_url=COMPANYFACTS_URL.format(cik=cik),
                        client=client,
                        cache_path=cache_dir / f"companyfacts-CIK{cik}.json",
                        state=state,
                    )
                    submissions = _bulk_or_live_payload(
                        cik=cik,
                        archive=submissions_archive,
                        member=f"CIK{cik}.json",
                        live_url=SUBMISSIONS_URL.format(cik=cik),
                        client=client,
                        cache_path=cache_dir / f"submissions-CIK{cik}.json",
                        state=state,
                    )
                    raw = normalize_distress_companyfacts(ticker, companyfacts, sector_adapter=adapter, fetched_at=datetime.now(UTC))
                    refs, required_count, screen_failures, overflow = _screen_refs(
                        submissions,
                        ticker=ticker,
                        cik=cik,
                        cutoff=cutoff,
                        max_event_filings=args.max_event_filings,
                    )
                    screened = []
                    evidence: list[dict[str, Any]] = []
                    failed_urls = list(screen_failures)
                    for ref in refs:
                        try:
                            document = document_service.fetch(ref, rules_hash=current_rules_hash)
                            screened.append(document)
                            evidence.extend(extract_hard_distress_flags(document))
                        except (httpx.HTTPError, OSError, ValueError) as exc:
                            failed_urls.append(ref.source_url)
                            errors.append({"ticker": ticker, "stage": "hard_flag_document", "error": type(exc).__name__})
                    raw = finalize_hard_distress_screen(
                        raw,
                        screened_documents=screened,
                        evidence=evidence,
                        failed_document_urls=failed_urls,
                        required_document_count=required_count,
                    )
                    inputs = derive_distress_inputs(raw)
                    assessment = classify_distress(inputs, rules, rules_hash=current_rules_hash)
                    sufficient, sufficient_reasons = _sufficient_inputs(adapter, inputs)
                    nonnull_provenance = assessment.balance_sheet_distressed is None or bool(assessment.sources)
                    safe_integrity = _safe_input_integrity(assessment)
                    row = {
                        "ticker": ticker,
                        "adapter": adapter.value,
                        "cohort": entry.get("cohort"),
                        "classification": assessment.classification.value,
                        "balance_sheet_distressed": assessment.balance_sheet_distressed,
                        "rule_path": assessment.rule_path,
                        "reasons": assessment.reasons,
                        "sufficient_inputs": sufficient,
                        "sufficient_input_reasons": sufficient_reasons,
                        "hard_flag_screen_complete": assessment.hard_flag_screen_complete,
                        "hard_distress_flags": [item.value for item in assessment.hard_distress_flags],
                        "screened_document_count": len(screened),
                        "required_screen_document_count": required_count,
                        "screen_overflow_count": overflow,
                        "screen_failures": failed_urls,
                        "net_debt_to_ebitda": assessment.net_debt_to_ebitda,
                        "interest_coverage": assessment.interest_coverage,
                        "liquidity_coverage": assessment.liquidity_coverage,
                        "cash_runway_months": assessment.cash_runway_months,
                        "sources": assessment.sources,
                        "provenance_complete": nonnull_provenance,
                        "safe_input_integrity": safe_integrity,
                        "audit": assessment.audit,
                    }
                    results.append(row)
                    classification_counts[assessment.classification.value] += 1
                except (httpx.HTTPError, OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
                    errors.append({"ticker": ticker, "stage": "ticker_validation", "error": f"{type(exc).__name__}: {exc}"})
        finally:
            document_service.close()
            if companyfacts_archive is not None:
                companyfacts_archive.close()
            if submissions_archive is not None:
                submissions_archive.close()

    nonfinancial = [row for row in results if DistressSectorAdapter(row["adapter"]) in _NONFINANCIAL_ADAPTERS]
    sufficient_nonfinancial = [row for row in nonfinancial if row["sufficient_inputs"]]
    classified_nonfinancial = [row for row in sufficient_nonfinancial if row["classification"] != DistressClassification.UNKNOWN.value]
    coverage = 100.0 * len(classified_nonfinancial) / len(sufficient_nonfinancial) if sufficient_nonfinancial else 0.0

    financial_fallback = sum(
        1
        for row in results
        if row["cohort"] in {"banks", "insurers"} and row["adapter"] == DistressSectorAdapter.CORPORATE.value
    )
    false_safe = sum(1 for row in results if row["classification"] == DistressClassification.NOT_DISTRESSED.value and not row["safe_input_integrity"])
    nonnull = [row for row in results if row["classification"] != DistressClassification.UNKNOWN.value]
    provenance_complete = 100.0 * sum(1 for row in nonnull if row["provenance_complete"]) / len(nonnull) if nonnull else 100.0

    gate = basket.get("gate") or {}
    passed = (
        bool(sufficient_nonfinancial)
        and coverage >= float(gate.get("nonfinancial_sufficient_input_classification_coverage_pct_gte", 90.0))
        and financial_fallback == int(gate.get("financial_corporate_fallback_count_eq", 0))
        and false_safe == int(gate.get("false_safe_missing_maturity_or_coverage_count_eq", 0))
        and provenance_complete == float(gate.get("nonnull_provenance_complete_pct_eq", 100.0))
        and not errors
    )

    summary = {
        "tickers_attempted": len(entries),
        "tickers_with_results": len(results),
        "nonfinancial_sufficient_inputs": len(sufficient_nonfinancial),
        "nonfinancial_classified": len(classified_nonfinancial),
        "classification_coverage_pct": coverage,
        "financial_corporate_fallback_count": financial_fallback,
        "false_safe_missing_maturity_or_coverage_count": false_safe,
        "provenance_complete_pct": provenance_complete,
        "error_count": len(errors),
        "exit_gate": "PASS" if passed else "FAIL",
    }
    payload = {
        "phase": "1.1B",
        "model_version": "SOE-1.1.0",
        "rules_hash": current_rules_hash,
        "basket_id": basket.get("basket_id"),
        "basket_path": str(basket_path),
        "basket_gate": gate,
        "generated_at": datetime.now(UTC).isoformat(),
        "summary": summary,
        "classification_counts": dict(classification_counts),
        "errors": errors,
        "results": results,
    }
    _write_report(Path(args.output_dir), payload)
    print(json.dumps({"summary": summary}, indent=2), flush=True)
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())