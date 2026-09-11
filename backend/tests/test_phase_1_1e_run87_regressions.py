from __future__ import annotations

from datetime import UTC, datetime

from app.domain.soe_v1_1 import GuidanceMetric, SourceDocument
from app.services.phase_1_1e_run87_repairs_v1_1 import extract_guidance_facts_run87


FETCHED = datetime(2026, 9, 11, tzinfo=UTC)


def document(text: str) -> SourceDocument:
    return SourceDocument(
        document_id="KN:run87:ex99-2",
        rules_hash="run87-test",
        ticker="KN",
        cik="0001587523",
        accession="0001587523-25-000077",
        form="8-K",
        filing_date=FETCHED.date(),
        source="SEC EDGAR",
        source_url="https://www.sec.gov/example.htm",
        source_timestamp=FETCHED,
        fetched_at=FETCHED,
        content_hash="run87",
        content_type="text/plain",
        content=text,
    )


def test_historical_reconciliation_gross_margin_is_not_forward_guidance():
    text = (
        "2025 Outlook. Full year adjusted EBITDA margins are expected to be in the low 40% range for 2025. "
        "Q4 2025 Guidance Revenues from continuing operations $151 to $161 million; "
        "Diluted earnings per share from continuing operations $0.21 to $0.25. "
        "RECONCILIATION OF GAAP FINANCIAL MEASURES TO NON-GAAP FINANCIAL MEASURES "
        "Quarter Ended September 30, 2025 2024 Revenues $152.9 $142.5 Gross profit $69.9 $62.9 "
        "Gross profit margin 45.7% 44.1% Non-GAAP gross profit $70.7 $64.8 "
        "Non-GAAP gross profit margin 46.2% 45.5%."
    )
    result = extract_guidance_facts_run87(document(text), rules_hash="run87-test")
    margins = [
        record
        for record in result.records
        if record.metric in {GuidanceMetric.GROSS_MARGIN, GuidanceMetric.OPERATING_MARGIN}
    ]
    assert margins == []
    assert any(
        item.get("reason") == "phase_1_1e_run87_historical_margin_actual_rejected"
        for item in result.rejected_candidates
    )


def test_true_guidance_margin_table_remains_allowed():
    text = (
        "Fiscal Year 2026 Guidance: revenue approximately $8.05 billion and pro forma EPS $10.00 "
        "based on gross margin of 59.7%, operating margin of 27.0%."
    )
    result = extract_guidance_facts_run87(document(text), rules_hash="run87-test")
    assert any(
        record.metric is GuidanceMetric.GROSS_MARGIN
        and record.low == 0.597
        for record in result.records
    )
    assert any(
        record.metric is GuidanceMetric.OPERATING_MARGIN
        and record.low == 0.27
        for record in result.records
    )
