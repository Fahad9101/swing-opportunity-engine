from __future__ import annotations

import argparse
import json
import os
import time
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from app.core.config import SOE_1_1_RULES_PATH, get_settings, load_rules_for_version, rules_hash
from app.domain.catalyst_v1_1 import CatalystMaterialityAssessment
from app.providers.sec_edgar import TICKER_MAP_URL
from app.services.catalyst_materiality_service import assess_materiality
from app.services.catalyst_primary_evidence_service import extract_sec_catalyst_candidates
from app.services.source_document_service import SourceDocumentService, index_submissions_payload


SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
_ALLOWED_FORMS = {"8-K", "6-K"}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SOE-1.1C live catalyst-materiality validation")
    parser.add_argument("--basket", default="validation/phase_1_1c_preregistered_basket_v1.json")
    parser.add_argument("--output-dir", default="validation-results/milestone-1.1c")
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def _sec_user_agent() -> str:
    value = os.environ.get("SEC_USER_AGENT", "").strip()
    if "@" not in value:
        raise RuntimeError("SEC_USER_AGENT must contain a real contact email for live SEC validation")
    return value


def _throttled_get(client: httpx.Client, url: str, state: dict[str, float]) -> httpx.Response:
    elapsed = time.monotonic() - state.get("last", 0.0)
    wait = 0.15 - elapsed
    if wait > 0:
        time.sleep(wait)
    response = client.get(url)
    state["last"] = time.monotonic()
    return response


def _ticker_map(client: httpx.Client, cache_dir: Path, state: dict[str, float], *, force: bool) -> dict[str, str]:
    path = cache_dir / "ticker_map.json"
    fresh = path.exists() and datetime.now(UTC) - datetime.fromtimestamp(path.stat().st_mtime, UTC) < timedelta(hours=24)
    if fresh and not force:
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
    client: httpx.Client,
    cache_dir: Path,
    state: dict[str, float],
    force: bool,
) -> dict[str, Any]:
    path = cache_dir / f"submissions-CIK{cik}.json"
    if path.exists() and not force:
        return json.loads(path.read_text(encoding="utf-8"))
    response = _throttled_get(client, SUBMISSIONS_URL.format(cik=cik), state)
    response.raise_for_status()
    payload = response.json()
    path.write_text(json.dumps(payload), encoding="utf-8")
    return payload


def _provenance_complete(assessment: CatalystMaterialityAssessment) -> bool:
    if assessment.materiality is None:
        return False
    provenance = assessment.structured_provenance
    return bool(
        assessment.rules_hash
        and assessment.source == "SEC EDGAR"
        and assessment.source_url.startswith("https://www.sec.gov/Archives/edgar/data/")
        and assessment.source_timestamp
        and assessment.evidence_spans
        and provenance.get("accession")
        and provenance.get("document_id")
        and provenance.get("content_hash")
    )


def _serialize_assessment(assessment: CatalystMaterialityAssessment | None) -> dict[str, Any] | None:
    return assessment.model_dump(mode="json") if assessment is not None else None


def _target_result(target: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": target["id"],
        "ticker": str(target["ticker"]).upper(),
        "target_event_type": target["target_event_type"],
        "role": target.get("role", "candidate"),
        "is_biotech": bool(target.get("is_biotech", False)),
        "primary_evidence_found": False,
        "sufficient_primary_evidence": False,
        "materiality_scored": False,
        "provenance_complete": False,
        "assessment": None,
        "error": None,
    }


def _write_report(output_dir: Path, payload: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "catalyst_materiality_validation.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    summary = payload["summary"]
    lines = [
        "# Phase 1.1C Catalyst Materiality Validation",
        "",
        f"- Basket: `{payload['basket_id']}`",
        f"- Model: `{payload['model_version']}`",
        f"- Rules hash: `{payload['rules_hash']}`",
        f"- Targets attempted: **{summary['targets_attempted']}**",
        f"- Primary evidence targets found: **{summary['primary_evidence_targets_found']}**",
        f"- Sufficient primary-evidence events: **{summary['sufficient_primary_evidence_events']}**",
        f"- Materiality-scored sufficient events: **{summary['materiality_scored_sufficient_events']}**",
        f"- Materiality coverage: **{summary['materiality_coverage_pct']:.2f}%**",
        f"- Distinct scored event types: **{summary['distinct_scored_event_types']}**",
        f"- Provenance complete: **{summary['provenance_complete_pct']:.2f}%**",
        f"- Administrative/unverified events scored: **{summary['administrative_or_unverified_scored']}**",
        f"- Errors: **{summary['error_count']}**",
        f"- Exit gate: **{summary['exit_gate']}**",
        "",
        "## Target audit",
        "",
        "| ID | Ticker | Target | Evidence | Sufficient | Materiality | Rule path |",
        "| --- | --- | --- | --- | --- | ---: | --- |",
    ]
    for row in payload["results"]:
        assessment = row.get("assessment") or {}
        materiality = assessment.get("materiality")
        lines.append(
            f"| {row['id']} | {row['ticker']} | {row['target_event_type']} | "
            f"{'yes' if row['primary_evidence_found'] else 'no'} | "
            f"{'yes' if row['sufficient_primary_evidence'] else 'no'} | "
            f"{materiality if materiality is not None else '—'} | {assessment.get('rule_path', '—')} |"
        )
    (output_dir / "PHASE_1_1C_CATALYST_MATERIALITY_VALIDATION.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (output_dir / "catalyst_materiality_validation.log").write_text(
        "\n".join(
            [
                f"basket={payload['basket_id']}",
                f"targets_attempted={summary['targets_attempted']}",
                f"primary_evidence_targets_found={summary['primary_evidence_targets_found']}",
                f"sufficient_primary_evidence_events={summary['sufficient_primary_evidence_events']}",
                f"materiality_scored_sufficient_events={summary['materiality_scored_sufficient_events']}",
                f"materiality_coverage_pct={summary['materiality_coverage_pct']}",
                f"distinct_scored_event_types={summary['distinct_scored_event_types']}",
                f"provenance_complete_pct={summary['provenance_complete_pct']}",
                f"administrative_or_unverified_scored={summary['administrative_or_unverified_scored']}",
                f"error_count={summary['error_count']}",
                f"exit_gate={summary['exit_gate']}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> int:
    args = _parse_args()
    basket_path = Path(args.basket)
    basket = json.loads(basket_path.read_text(encoding="utf-8"))
    guardrails = basket["validation_guardrails"]
    targets = list(basket["targets"])
    output_dir = Path(args.output_dir)
    settings = get_settings()
    cache_dir = Path(settings.cache_dir) / "phase_1_1c"
    cache_dir.mkdir(parents=True, exist_ok=True)

    rules = load_rules_for_version(SOE_1_1_RULES_PATH, "SOE-1.1.0")
    candidate_rules_hash = rules_hash(rules)
    sec_user_agent = _sec_user_agent()
    client = httpx.Client(
        timeout=20.0,
        headers={"User-Agent": sec_user_agent, "Accept-Encoding": "gzip, deflate"},
        follow_redirects=True,
    )
    throttle_state: dict[str, float] = {}
    doc_service = SourceDocumentService(
        cache_dir=cache_dir / "documents",
        user_agent=sec_user_agent,
        timeout_seconds=20.0,
        min_request_interval_seconds=0.15,
    )

    results = [_target_result(target) for target in targets]
    result_by_id = {row["id"]: row for row in results}
    target_by_id = {target["id"]: target for target in targets}
    ids_by_ticker: dict[str, list[str]] = defaultdict(list)
    for target in targets:
        ids_by_ticker[str(target["ticker"]).upper()].append(target["id"])

    print(f"Validation basket: {basket['basket_id']}", flush=True)
    print(f"Targets: {len(targets)} across {len(ids_by_ticker)} tickers", flush=True)

    try:
        ticker_map = _ticker_map(client, cache_dir, throttle_state, force=args.force)
        cutoff = date.today() - timedelta(days=int(basket["lookback_days"]))
        ticker_items = list(ids_by_ticker.items())
        for ticker_index, (ticker, target_ids) in enumerate(ticker_items, start=1):
            wanted = ", ".join(target_by_id[target_id]["target_event_type"] for target_id in target_ids)
            print(f"[{ticker_index}/{len(ticker_items)}] {ticker}: searching {wanted}", flush=True)
            cik = ticker_map.get(ticker)
            if cik is None:
                for target_id in target_ids:
                    result_by_id[target_id]["error"] = "ticker_not_found_in_sec_map"
                print(f"  {ticker}: SEC ticker mapping unavailable", flush=True)
                continue
            try:
                submissions = _submissions_payload(
                    cik,
                    client=client,
                    cache_dir=cache_dir,
                    state=throttle_state,
                    force=args.force,
                )
                refs = index_submissions_payload(
                    ticker,
                    cik,
                    submissions,
                    allowed_forms=_ALLOWED_FORMS,
                    limit=max(int(basket["max_filings_per_ticker"]) * 3, 48),
                )
                refs = [ref for ref in refs if ref.filing_date is None or ref.filing_date >= cutoff]
                refs = refs[: int(basket["max_filings_per_ticker"])]

                unresolved = set(target_ids)
                for filing in refs:
                    if not unresolved:
                        break
                    try:
                        doc_refs = doc_service.filing_documents(
                            filing,
                            max_exhibits=int(basket["max_exhibits_per_filing"]),
                            force=args.force,
                        )
                    except Exception:
                        doc_refs = [filing]
                    for doc_ref in doc_refs:
                        if not unresolved:
                            break
                        try:
                            document = doc_service.fetch(doc_ref, rules_hash=candidate_rules_hash, force=args.force)
                        except Exception:
                            # A failed exhibit must not erase a usable primary filing or become evidence.
                            continue
                        is_biotech = any(bool(target_by_id[target_id].get("is_biotech", False)) for target_id in unresolved)
                        candidates = extract_sec_catalyst_candidates(document, is_biotech=is_biotech)
                        if not candidates:
                            continue
                        for extracted in candidates:
                            event_type = extracted.input.event_type
                            matching = [
                                target_id
                                for target_id in list(unresolved)
                                if target_by_id[target_id]["target_event_type"] == event_type
                            ]
                            for target_id in matching:
                                row = result_by_id[target_id]
                                assessment = assess_materiality(
                                    extracted.input,
                                    rules,
                                    rules_hash=candidate_rules_hash,
                                )
                                row["primary_evidence_found"] = True
                                row["assessment"] = _serialize_assessment(assessment)
                                row["sufficient_primary_evidence"] = bool(
                                    assessment.catalyst_candidate
                                    and assessment.event_class_base is not None
                                    and assessment.economic_exposure_score is not None
                                    and assessment.consequence_severity is not None
                                    and assessment.source
                                    and assessment.source_url
                                    and assessment.evidence_spans
                                )
                                row["materiality_scored"] = assessment.materiality is not None
                                row["provenance_complete"] = _provenance_complete(assessment) if assessment.materiality is not None else False
                                unresolved.discard(target_id)
                                score_text = assessment.materiality if assessment.materiality is not None else "null"
                                print(
                                    f"  found {target_id}: materiality={score_text}, sufficient={row['sufficient_primary_evidence']}",
                                    flush=True,
                                )
                if unresolved:
                    print(f"  unresolved targets: {', '.join(sorted(unresolved))}", flush=True)
            except Exception as exc:
                print(f"  {ticker}: {type(exc).__name__}: {exc}", flush=True)
                for target_id in target_ids:
                    if not result_by_id[target_id]["primary_evidence_found"]:
                        result_by_id[target_id]["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        doc_service.close()
        client.close()

    sufficient = [row for row in results if row["sufficient_primary_evidence"]]
    scored_sufficient = [row for row in sufficient if row["materiality_scored"]]
    coverage = (len(scored_sufficient) / len(sufficient)) if sufficient else 0.0
    scored_types = sorted({row["target_event_type"] for row in scored_sufficient})
    scored_rows = [row for row in results if row["materiality_scored"]]
    provenance_pct = (
        sum(1 for row in scored_rows if row["provenance_complete"]) / len(scored_rows) * 100.0
        if scored_rows
        else 0.0
    )
    invalid_scored = 0
    for row in scored_rows:
        assessment = row.get("assessment") or {}
        if row["target_event_type"] == "administrative_or_unverifiable" or not assessment.get("catalyst_candidate", False):
            invalid_scored += 1
    errors = [row for row in results if row["error"]]

    pass_gate = bool(
        coverage >= float(guardrails["minimum_materiality_coverage_with_sufficient_evidence"])
        and len(sufficient) >= int(guardrails["minimum_sufficient_primary_evidence_events"])
        and len(scored_types) >= int(guardrails["minimum_distinct_scored_event_types"])
        and invalid_scored <= int(guardrails["administrative_or_unverified_scored_max"])
        and (not guardrails.get("require_100pct_provenance", True) or provenance_pct == 100.0)
        and not errors
    )

    summary = {
        "targets_attempted": len(results),
        "primary_evidence_targets_found": sum(1 for row in results if row["primary_evidence_found"]),
        "sufficient_primary_evidence_events": len(sufficient),
        "materiality_scored_sufficient_events": len(scored_sufficient),
        "materiality_coverage_pct": coverage * 100.0,
        "distinct_scored_event_types": len(scored_types),
        "scored_event_types": scored_types,
        "provenance_complete_pct": provenance_pct,
        "administrative_or_unverified_scored": invalid_scored,
        "error_count": len(errors),
        "exit_gate": "PASS" if pass_gate else "FAIL",
    }
    payload = {
        "basket_id": basket["basket_id"],
        "model_version": "SOE-1.1.0",
        "phase": "1.1C",
        "generated_at": datetime.now(UTC).isoformat(),
        "default_runtime_model_unchanged": True,
        "rules_hash": candidate_rules_hash,
        "guardrails": guardrails,
        "summary": summary,
        "results": results,
    }
    _write_report(output_dir, payload)
    print(json.dumps(summary, indent=2, sort_keys=True), flush=True)
    print(f"Validation artifacts: {output_dir}", flush=True)
    return 0 if pass_gate else 2


if __name__ == "__main__":
    raise SystemExit(main())
