from __future__ import annotations

import hashlib

import yaml

from app.services.guidance_raw_replay_differential_service import (
    VerifiedDocumentContent,
    raw_sec_replay_differential_report,
)


def _rules() -> dict:
    with open("config/soe_v1_1_rules.yaml", "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def test_reversed_range_is_rejected_without_aborting_or_marking_extraction_failure():
    content = b"Full-year 2026 guidance. Adjusted EPS $5.00 to $4.00."
    url = "https://www.sec.gov/Archives/edgar/data/1/bad.htm"
    digest = hashlib.sha256(content).hexdigest()
    ts = "2026-04-01T00:00:00Z"
    validation = {
        "candidate_rules_hash": "candidate-hash",
        "per_name_deltas": [
            {
                "ticker": "BAD",
                "structural_inputs": {
                    "guidance": {
                        "classification": "UNKNOWN",
                        "rule_path": "guidance_v1_1.insufficient_evidence",
                        "ledger_records": [
                            {
                                "ticker": "BAD",
                                "fiscal_period": "FY2026",
                                "metric": "eps",
                                "accounting_basis": "ADJUSTED",
                                "low": 4.0,
                                "high": 5.0,
                                "unit": "USD/share",
                                "source": "SEC EDGAR",
                                "source_url": url,
                                "source_accession": "0000000001-26-000001",
                                "source_timestamp": ts,
                                "source_document_hash": digest,
                                "explicit_action": "INITIATE",
                                "verified": True,
                                "extraction_method": "deterministic_text",
                                "as_of": ts,
                                "fetched_at": ts,
                                "stale": False,
                                "rules_hash": "candidate-hash"
                            }
                        ]
                    }
                }
            }
        ]
    }
    report = raw_sec_replay_differential_report(
        validation,
        _rules(),
        {url: VerifiedDocumentContent(content=content.decode(), content_hash=digest)},
        rules_hash="candidate-hash",
    )
    assert report["extraction_error_count"] == 0
    assert report["complete_ticker_count"] == 1
    assert report["incomplete_ticker_count"] == 0
    assert report["classification_divergence_count"] == 0
    assert report["rejected_candidate_count"] >= 1
    ticker = report["ticker_reports"][0]
    assert ticker["status"] == "COMPLETE"
    assert ticker["rejected_candidate_count"] >= 1