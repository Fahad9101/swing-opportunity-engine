from datetime import UTC, date, datetime

from app.domain.soe_v1_1 import SourceDocument
from app.services.catalyst_primary_evidence_service import extract_sec_catalyst_candidates


def _doc(text: str) -> SourceDocument:
    return SourceDocument(
        document_id="doc-guidance",
        rules_hash="rules",
        ticker="PANW",
        cik="0001327567",
        accession="0001327567-26-000019",
        form="8-K",
        filing_date=date(2026, 9, 1),
        source_url="https://www.sec.gov/Archives/edgar/data/1327567/000132756726000019/ex991q426earningsrelease.htm",
        source_timestamp=datetime(2026, 9, 1, tzinfo=UTC),
        fetched_at=datetime(2026, 9, 1, tzinfo=UTC),
        content_hash="abc",
        content=text,
    )


def test_explicit_for_fiscal_year_we_expect_is_full_year_guidance():
    doc = _doc(
        "Financial Outlook. Palo Alto Networks provides guidance based on current market conditions and expectations. "
        "For the fiscal first quarter 2027, we expect total revenue of $3.3 billion. "
        "For the fiscal year 2027, we expect total revenue in the range of $14.10 billion to $14.20 billion."
    )
    candidates = extract_sec_catalyst_candidates(doc)
    guidance = [item for item in candidates if item.input.event_type == "formal_full_year_guidance_update"]
    assert len(guidance) == 1
    assert "For the fiscal year 2027, we expect" in guidance[0].matched_text


def test_quarter_only_outlook_remains_not_full_year_guidance():
    doc = _doc(
        "We look forward to executing against our targets as we close fiscal year 2025. "
        "Financial Outlook. Palo Alto Networks provides guidance based on current market conditions and expectations. "
        "For the fiscal fourth quarter 2025, we expect total revenue of $2.5 billion."
    )
    candidates = extract_sec_catalyst_candidates(doc)
    assert not any(item.input.event_type == "formal_full_year_guidance_update" for item in candidates)
