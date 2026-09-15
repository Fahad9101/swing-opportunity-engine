from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.domain.guidance_canonical_v1 import GuidanceInvariantCode
from app.domain.soe_v1_1 import ExtractionMethod, GuidanceAction, GuidanceMetric, GuidanceMetricRecord
from app.services.guidance_canonical_service import (
    CanonicalGuidanceNormalizer,
    GuidanceInvariantValidator,
    canonicalize_legacy_records,
    typed_fact_from_legacy_record,
)


NOW = datetime(2026, 9, 12, tzinfo=UTC)
FIXTURE = Path(__file__).parent / "fixtures" / "guidance_golden_corpus_v1.json"


def legacy_record(case: dict, *, source_url: str = "https://www.sec.gov/golden.htm") -> GuidanceMetricRecord:
    return GuidanceMetricRecord(
        rules_hash="golden-corpus",
        ticker=case["ticker"],
        fiscal_period=case["fiscal_period"],
        metric=GuidanceMetric(case["metric"]),
        accounting_basis=case.get("accounting_basis", "UNSPECIFIED"),
        low=case.get("low"),
        high=case.get("high"),
        unit=case.get("unit", "USD"),
        source="SEC EDGAR",
        source_url=source_url,
        source_accession="0000000001-26-000001",
        source_timestamp=NOW,
        explicit_action=GuidanceAction(case.get("explicit_action", "NONE")),
        verified=True,
        extraction_method=ExtractionMethod.STRUCTURED,
        evidence_span=case["evidence"],
        source_document_hash="golden-document",
        as_of=NOW,
        fetched_at=NOW,
        stale=False,
    )


@pytest.mark.parametrize("case", json.loads(FIXTURE.read_text()))
def test_golden_guidance_invariants(case: dict):
    typed = typed_fact_from_legacy_record(legacy_record(case))
    result = GuidanceInvariantValidator().validate(typed)
    codes = {violation.code.value for violation in result.violations}

    if case["expected"] == "accept":
        assert result.accepted, (case["name"], codes)
    else:
        assert not result.accepted, case["name"]
        assert case["code"] in codes, (case["name"], codes)


def test_duplicate_semantic_facts_merge_provenance():
    case = {
        "ticker": "HUM",
        "metric": "eps",
        "fiscal_period": "FY2026",
        "accounting_basis": "GAAP",
        "low": 8.36,
        "high": 8.36,
        "unit": "USD/share",
        "explicit_action": "LOWER",
        "evidence": "FY 2026 GAAP EPS guidance revised to at least $8.36 from at least $8.89",
    }
    first = legacy_record(case, source_url="https://www.sec.gov/exhibit-a.htm")
    second = legacy_record(case, source_url="https://www.sec.gov/exhibit-b.htm")

    canonical = canonicalize_legacy_records([first, second])
    assert not canonical.quarantined
    assert len(canonical.accepted) == 1
    fact = canonical.accepted[0]
    assert len(fact.source_fact_ids) == 2
    assert len(fact.provenance) == 2


def test_validator_is_idempotent_on_same_typed_fact():
    case = {
        "ticker": "ESI",
        "metric": "fcf",
        "fiscal_period": "FY2025",
        "accounting_basis": "ADJUSTED",
        "low": 280_000_000.0,
        "high": 280_000_000.0,
        "unit": "USD",
        "evidence": "2025 Guidance The Company expects full year 2025 adjusted free cash flow of approximately $280 million.",
    }
    typed = typed_fact_from_legacy_record(legacy_record(case))
    validator = GuidanceInvariantValidator()
    first = validator.validate(typed)
    second = validator.validate(typed)
    assert first == second
    assert first.accepted


def test_quarantined_fact_never_reaches_canonical_ledger():
    case = {
        "ticker": "AXON",
        "metric": "ebitda",
        "fiscal_period": "FY2026",
        "accounting_basis": "ADJUSTED",
        "low": 590_000_000.0,
        "high": 620_000_000.0,
        "unit": "USD",
        "evidence": "Full Year 2026 Guidance; Adjusted EBITDA margin of 25.5% • Stock-based compensation expense of $590 million to $620 million",
    }
    typed = typed_fact_from_legacy_record(legacy_record(case))
    validated = GuidanceInvariantValidator().validate(typed)
    normalized = CanonicalGuidanceNormalizer().normalize([validated])
    assert not normalized.accepted
    assert len(normalized.quarantined) == 1
    assert any(
        violation.code is GuidanceInvariantCode.METRIC_VALUE_LOCALITY_MISMATCH
        for violation in normalized.quarantined[0].violations
    )
