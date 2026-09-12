from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import yaml

from app.domain.soe_v1_1 import ExtractionMethod, GuidanceAction, GuidanceMetric, GuidanceMetricRecord
from app.services.guidance_canonical_differential_service import (
    canonical_guidance_differential_report,
)


T1 = datetime(2026, 1, 1, tzinfo=UTC)
T2 = datetime(2026, 4, 1, tzinfo=UTC)


def rules() -> dict:
    with open("config/soe_v1_1_rules.yaml", "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def record(*, ts: datetime, low: float, high: float, evidence: str) -> dict:
    row = GuidanceMetricRecord(
        rules_hash="diff-test",
        ticker="TEST",
        fiscal_period="FY2026",
        metric=GuidanceMetric.REVENUE,
        accounting_basis="UNSPECIFIED",
        low=low,
        high=high,
        unit="USD",
        source="SEC EDGAR",
        source_url=f"https://www.sec.gov/{ts.date().isoformat()}.htm",
        source_accession=f"acc-{ts.date().isoformat()}",
        source_timestamp=ts,
        explicit_action=GuidanceAction.NONE,
        verified=True,
        extraction_method=ExtractionMethod.STRUCTURED,
        evidence_span=evidence,
        source_document_hash=str(uuid4()),
        as_of=ts,
        fetched_at=ts,
        stale=False,
    )
    return row.model_dump(mode="json")


def validation_payload(records: list[dict], *, classification: str) -> dict:
    return {
        "candidate_rules_hash": "diff-test",
        "per_name_deltas": [
            {
                "ticker": "TEST",
                "structural_inputs": {
                    "guidance": {
                        "classification": classification,
                        "rule_path": "legacy.test",
                        "ledger_records": records,
                    }
                },
            }
        ],
    }


def test_differential_preserves_clean_flat_classification():
    records = [
        record(ts=T1, low=100.0, high=100.0, evidence="FY2026 revenue guidance is $100 to $100"),
        record(ts=T2, low=100.0, high=100.0, evidence="FY2026 revenue guidance is $100 to $100"),
    ]
    report = canonical_guidance_differential_report(
        validation_payload(records, classification="NOT_DETERIORATED"),
        rules(),
        rules_hash="diff-test",
    )
    assert report["classification_divergence_count"] == 0
    assert report["quarantined_fact_count"] == 0


def test_differential_surfaces_quarantine_and_classification_drift():
    contaminated = record(
        ts=T2,
        low=75_000_000_000.0,
        high=100_000_000_000.0,
        evidence=(
            "phase_1_1e_run94_explicit_period_authority=FY2026; "
            "FY2026 Business Outlook Revenue $10 billion to $11 billion; "
            "EBITDA margin expansion 75 to 100 basis points"
        ),
    )
    report = canonical_guidance_differential_report(
        validation_payload([contaminated], classification="NOT_DETERIORATED"),
        rules(),
        rules_hash="diff-test",
    )
    assert report["quarantined_fact_count"] == 1
    assert report["classification_divergence_count"] == 1
    assert report["canonical_classification_distribution"]["UNKNOWN"] == 1
    assert report["quarantine_codes"]
