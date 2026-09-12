from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import yaml

from app.services.guidance_raw_replay_differential_service import (
    VerifiedDocumentContent,
    build_raw_replay_manifest,
    raw_sec_replay_differential_report,
)


def _rules() -> dict:
    with open("config/soe_v1_1_rules.yaml", "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _record(*, ticker: str, url: str, content: bytes, ts: str, low: float, high: float) -> dict:
    return {
        "ticker": ticker,
        "fiscal_period": "FY2026",
        "metric": "revenue",
        "accounting_basis": "UNSPECIFIED",
        "low": low,
        "high": high,
        "unit": "USD",
        "source": "SEC EDGAR",
        "source_url": url,
        "source_accession": "0000000001-26-000001",
        "source_timestamp": ts,
        "source_document_hash": hashlib.sha256(content).hexdigest(),
        "explicit_action": "INITIATE",
        "verified": True,
        "extraction_method": "deterministic_text",
        "as_of": ts,
        "fetched_at": ts,
        "stale": False,
        "rules_hash": "candidate-hash",
    }


def _validation() -> tuple[dict, dict[str, bytes]]:
    old = b"Full-year 2026 guidance. The company expects total revenue of $100 million."
    new = b"Full-year 2026 guidance. The company expects total revenue of $105 million."
    old_url = "https://www.sec.gov/Archives/edgar/data/1/old.htm"
    new_url = "https://www.sec.gov/Archives/edgar/data/1/new.htm"
    old_record = _record(
        ticker="TEST",
        url=old_url,
        content=old,
        ts="2026-01-01T00:00:00Z",
        low=100_000_000.0,
        high=100_000_000.0,
    )
    new_record = _record(
        ticker="TEST",
        url=new_url,
        content=new,
        ts="2026-04-01T00:00:00Z",
        low=105_000_000.0,
        high=105_000_000.0,
    )
    validation = {
        "candidate_rules_hash": "candidate-hash",
        "per_name_deltas": [
            {
                "ticker": "TEST",
                "structural_inputs": {
                    "guidance": {
                        "classification": "NOT_DETERIORATED",
                        "rule_path": "guidance_v1_1.no_material_cut",
                        "ledger_records": [old_record, new_record, dict(new_record)],
                    }
                },
            }
        ],
    }
    return validation, {old_url: old, new_url: new}


def test_manifest_deduplicates_exact_immutable_sec_documents():
    validation, contents = _validation()
    manifest = build_raw_replay_manifest(validation)
    assert len(manifest) == 2
    assert {item.source_url for item in manifest} == set(contents)
    assert all(item.cik == "0000000001" for item in manifest)


def test_raw_replay_matches_validated_classification_without_legacy_rows():
    validation, contents = _validation()
    verified = {
        url: VerifiedDocumentContent(
            content=payload.decode("utf-8"),
            content_hash=hashlib.sha256(payload).hexdigest(),
            content_type="text/plain",
        )
        for url, payload in contents.items()
    }
    report = raw_sec_replay_differential_report(
        validation,
        _rules(),
        verified,
        rules_hash="candidate-hash",
    )
    assert report["source_manifest_count"] == 2
    assert report["verified_source_count"] == 2
    assert report["complete_ticker_count"] == 1
    assert report["incomplete_ticker_count"] == 0
    assert report["classification_divergence_count"] == 0
    assert report["raw_typed_fact_count"] >= 2


def test_missing_source_fails_closed_without_partial_ticker_classification():
    validation, contents = _validation()
    first_url, first_payload = next(iter(contents.items()))
    report = raw_sec_replay_differential_report(
        validation,
        _rules(),
        {
            first_url: VerifiedDocumentContent(
                content=first_payload.decode("utf-8"),
                content_hash=hashlib.sha256(first_payload).hexdigest(),
            )
        },
        rules_hash="candidate-hash",
    )
    assert report["missing_source_count"] == 1
    assert report["complete_ticker_count"] == 0
    assert report["incomplete_ticker_count"] == 1
    assert report["classification_divergence_count"] == 0
    assert report["ticker_reports"][0]["status"] == "INCOMPLETE_SOURCE_REPLAY"
