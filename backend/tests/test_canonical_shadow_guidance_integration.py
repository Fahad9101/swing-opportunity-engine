from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime

from app.core.config import SOE_1_1_RULES_PATH, load_rules_for_version, rules_hash
from app.domain.soe_v1_1 import SecDocumentReference, SourceDocument
from app.services.canonical_shadow_guidance_service import assess_canonical_guidance_documents
from app.services.guidance_raw_replay_differential_service import build_raw_replay_manifest
from app.services.source_document_service import complete_submission_text_reference


def _rules():
    rules = load_rules_for_version(SOE_1_1_RULES_PATH, "SOE-1.1.0")
    return rules, rules_hash(rules)


def _document(ticker: str, text: str, timestamp: datetime, suffix: str) -> SourceDocument:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    accession = f"0000000001-26-{suffix}"
    return SourceDocument(
        document_id=f"canonical-shadow-{ticker}-{suffix}-{digest[:12]}",
        rules_hash="canonical-shadow-test",
        ticker=ticker,
        cik="0000000001",
        accession=accession,
        form="8-K",
        filing_date=timestamp.date(),
        source_url=f"https://www.sec.gov/Archives/edgar/data/1/{accession.replace('-', '')}/release{suffix}.htm",
        source_timestamp=timestamp,
        fetched_at=timestamp,
        content_hash=digest,
        content_type="text/plain",
        content=text,
    )


def test_full_market_guidance_path_does_not_bind_q1_eps_to_full_year_orcl_period():
    rules, rules_hash_value = _rules()
    june = _document(
        "ORCL",
        "Q1 FY 2027 Guidance. Non-GAAP earnings per share is expected to be between $1.71 and $1.75. "
        "Guidance for Full FY 2027. For fiscal year 2027, non-GAAP EPS guidance is $8.05 and total revenue guidance is $90 billion.",
        datetime(2026, 6, 10, tzinfo=UTC),
        "000010",
    )
    september = _document(
        "ORCL",
        "Full FY 2027 Guidance. For fiscal year 2027, non-GAAP EPS guidance is $8.10 and total revenue guidance is $90 billion.",
        datetime(2026, 9, 10, tzinfo=UTC),
        "000020",
    )

    assessment, meta, errors = assess_canonical_guidance_documents(
        "ORCL", [june, september], rules, rules_hash=rules_hash_value
    )

    assert errors == []
    assert assessment is not None
    assert assessment.guidance_deterioration is False
    fy_eps = [
        row for row in meta["ledger_records"]
        if row["metric"] == "eps" and row["fiscal_period"] == "FY2027"
    ]
    assert any(row["low"] == 8.05 and row["high"] == 8.05 for row in fy_eps)
    assert any(row["low"] == 8.10 and row["high"] == 8.10 for row in fy_eps)
    assert not any(row["low"] == 1.71 and row["high"] == 1.75 for row in fy_eps)


def test_guidance_under_review_becomes_latest_qualitative_state_and_blocks_stale_fallback():
    rules, rules_hash_value = _rules()
    july = _document(
        "IOVA",
        "Full Year 2026 Guidance. Total revenue guidance is expected to be $350 million to $370 million.",
        datetime(2026, 7, 2, tzinfo=UTC),
        "000030",
    )
    august = _document(
        "IOVA",
        "Management is reviewing our previously issued 2026 total revenue guidance of $350 million to $370 million "
        "and will provide an update during the third quarter.",
        datetime(2026, 8, 6, tzinfo=UTC),
        "000040",
    )

    assessment, meta, errors = assess_canonical_guidance_documents(
        "IOVA", [july, august], rules, rules_hash=rules_hash_value
    )

    assert errors == []
    assert assessment is not None
    assert assessment.guidance_deterioration is None
    assert meta["classification"] == "UNKNOWN"
    latest = max(meta["ledger_records"], key=lambda row: row["source_timestamp"])
    assert latest["source_timestamp"].startswith("2026-08-06")
    assert latest["low"] is None and latest["high"] is None
    assert latest["canonical_value_kind"] == "QUALITATIVE"


def test_raw_replay_manifest_prefers_canonical_source_documents_over_legacy_rows():
    current_url = "https://www.sec.gov/Archives/edgar/data/1/000000000126000050/current.htm"
    stale_url = "https://www.sec.gov/Archives/edgar/data/1/000000000125000001/stale.htm"
    validation = {
        "per_name_deltas": [
            {
                "ticker": "TEST",
                "structural_inputs": {
                    "guidance": {
                        "source_documents": [
                            {
                                "source_url": current_url,
                                "source_document_hash": "a" * 64,
                                "source_accession": "0000000001-26-000050",
                                "source_timestamp": "2026-08-01T00:00:00+00:00",
                            }
                        ],
                        "ledger_records": [
                            {
                                "source_url": stale_url,
                                "source_document_hash": "b" * 64,
                                "source_accession": "0000000001-25-000001",
                                "source_timestamp": "2025-08-01T00:00:00+00:00",
                            }
                        ],
                    }
                },
            }
        ]
    }

    manifest = build_raw_replay_manifest(validation)
    assert [item.source_url for item in manifest] == [current_url]
    assert manifest[0].source_document_hash == "a" * 64


def test_complete_submission_fallback_uses_official_sec_accession_text():
    filing = SecDocumentReference(
        ticker="SPXC",
        cik="0000088205",
        accession="0000088205-26-000052",
        form="8-K",
        filing_date=date(2026, 7, 30),
        primary_document="spxc-20260730.htm",
        source_url="https://www.sec.gov/Archives/edgar/data/88205/000008820526000052/spxc-20260730.htm",
    )
    fallback = complete_submission_text_reference(filing)
    assert fallback.primary_document == "0000088205-26-000052.txt"
    assert fallback.source_url == (
        "https://www.sec.gov/Archives/edgar/data/88205/000008820526000052/0000088205-26-000052.txt"
    )
