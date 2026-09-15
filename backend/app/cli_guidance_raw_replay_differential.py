from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from pathlib import Path

import httpx
import yaml

from app.services.guidance_raw_replay_differential_service import (
    VerifiedDocumentContent,
    build_raw_replay_manifest,
    raw_sec_replay_differential_report,
)


def _fetch_verified_documents(
    manifest,
    *,
    user_agent: str,
    min_interval_seconds: float,
    retries: int,
):
    verified: dict[str, VerifiedDocumentContent] = {}
    failures: list[dict] = []
    mismatches: list[dict] = []
    last_request_at = 0.0

    with httpx.Client(
        timeout=30.0,
        follow_redirects=True,
        headers={
            "User-Agent": user_agent,
            "Accept-Encoding": "gzip, deflate",
            "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.5",
        },
    ) as client:
        for index, source in enumerate(manifest, start=1):
            response = None
            error = None
            for attempt in range(retries + 1):
                elapsed = time.monotonic() - last_request_at
                if elapsed < min_interval_seconds:
                    time.sleep(min_interval_seconds - elapsed)
                try:
                    response = client.get(source.source_url)
                    last_request_at = time.monotonic()
                    if response.status_code in {429, 500, 502, 503, 504} and attempt < retries:
                        time.sleep(min(4.0, 0.5 * (2**attempt)))
                        continue
                    response.raise_for_status()
                    error = None
                    break
                except Exception as exc:  # network boundary: report, never guess
                    last_request_at = time.monotonic()
                    error = f"{type(exc).__name__}: {exc}"
                    if attempt < retries:
                        time.sleep(min(4.0, 0.5 * (2**attempt)))
                        continue
            if response is None or error is not None:
                failures.append(
                    {
                        "ticker": source.ticker,
                        "source_url": source.source_url,
                        "error": error or "unknown_fetch_failure",
                    }
                )
                continue

            digest = hashlib.sha256(response.content).hexdigest()
            if digest.lower() != source.source_document_hash.lower():
                mismatches.append(
                    {
                        "ticker": source.ticker,
                        "source_url": source.source_url,
                        "expected_hash": source.source_document_hash,
                        "actual_hash": digest,
                        "status_code": response.status_code,
                    }
                )
                continue

            verified[source.source_url] = VerifiedDocumentContent(
                content=response.text,
                content_hash=digest,
                content_type=response.headers.get("content-type"),
            )
            if index % 25 == 0 or index == len(manifest):
                print(
                    f"verified SEC documents: {len(verified)}/{index} "
                    f"(failures={len(failures)}, hash_mismatches={len(mismatches)})",
                    flush=True,
                )

    return verified, failures, mismatches


def main() -> None:
    parser = argparse.ArgumentParser(description="Hash-verified raw SEC canonical guidance replay")
    parser.add_argument("validation_json", type=Path)
    parser.add_argument("--rules", type=Path, default=Path("config/soe_v1_1_rules.yaml"))
    parser.add_argument("--output", type=Path, default=Path("canonical-guidance-raw-replay.json"))
    parser.add_argument("--user-agent", default=os.environ.get("SEC_USER_AGENT"))
    parser.add_argument("--min-interval", type=float, default=0.15)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    if not args.user_agent or "@" not in args.user_agent:
        raise SystemExit("SEC_USER_AGENT with a contact email is required")
    if args.min_interval < 0.10:
        raise SystemExit("SEC request interval must remain >= 0.10 seconds")

    validation = json.loads(args.validation_json.read_text(encoding="utf-8"))
    rules = yaml.safe_load(args.rules.read_text(encoding="utf-8"))
    manifest = build_raw_replay_manifest(validation)
    print(f"immutable SEC replay manifest: {len(manifest)} unique documents", flush=True)

    verified, fetch_failures, hash_mismatches = _fetch_verified_documents(
        manifest,
        user_agent=args.user_agent,
        min_interval_seconds=args.min_interval,
        retries=args.retries,
    )
    report = raw_sec_replay_differential_report(
        validation,
        rules,
        verified,
        rules_hash=str(validation.get("candidate_rules_hash") or ""),
    )
    report["fetch_failure_count"] = len(fetch_failures)
    report["fetch_failures"] = fetch_failures
    report["hash_mismatch_count"] = len(hash_mismatches)
    report["hash_mismatches"] = hash_mismatches
    report["all_manifest_hashes_verified"] = (
        not fetch_failures
        and not hash_mismatches
        and report["verified_source_count"] == report["source_manifest_count"]
    )

    args.output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(
        "raw SEC replay: "
        f"documents={report['verified_source_count']}/{report['source_manifest_count']} "
        f"complete_tickers={report['complete_ticker_count']}/{report['tickers_with_guidance_payload']} "
        f"raw_facts={report['raw_typed_fact_count']} "
        f"canonical_facts={report['canonical_fact_count']} "
        f"quarantined={report['quarantined_fact_count']} "
        f"divergences={report['classification_divergence_count']}",
        flush=True,
    )

    if args.strict and (
        fetch_failures
        or hash_mismatches
        or report["incomplete_ticker_count"]
        or report["classification_divergence_count"]
    ):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
