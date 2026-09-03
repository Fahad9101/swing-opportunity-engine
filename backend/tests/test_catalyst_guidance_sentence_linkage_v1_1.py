from datetime import UTC, date, datetime

from app.domain.soe_v1_1 import SourceDocument
from app.services.catalyst_primary_evidence_service import extract_sec_catalyst_candidates


def _doc(text: str) -> SourceDocument:
    return SourceDocument(
        document_id="doc-guidance-linkage",
        rules_hash="rules",
        ticker="TEST",
        cik="0000000001",
        accession="0000000001-26-000002",
        form="8-K",
        filing_date=date(2026, 8, 1),
        source_url="https://www.sec.gov/Archives/edgar/data/1/000000000126000002/ex991.htm",
        source_timestamp=datetime(2026, 8, 1, tzinfo=UTC),
        fetched_at=datetime(2026, 8, 1, tzinfo=UTC),
        content_hash="guidance-linkage",
        content=text,
    )


def _event_types(text: str) -> list[str]:
    return [item.input.event_type for item in extract_sec_catalyst_candidates(_doc(text))]


def test_panw_close_fiscal_year_then_quarter_only_outlook_is_not_full_year_guidance():
    text = (
        'We look forward to executing against our targets as we close fiscal year 2025. '
        'Financial Outlook. Palo Alto Networks provides guidance based on current market conditions and expectations. '
        'For the fiscal fourth quarter 2025, we expect Next-Generation Security ARR of $5.52 billion to $5.57 billion.'
    )
    assert "formal_full_year_guidance_update" not in _event_types(text)


def test_same_sentence_fy_guidance_action_still_extracts():
    text = "FY2027 guidance updated for revenue and adjusted EPS based on current market conditions."
    assert "formal_full_year_guidance_update" in _event_types(text)


def test_explicit_raises_outlook_for_fy_still_extracts():
    text = "The company raises its revenue outlook for FY2027 and now expects revenue of $10 billion."
    assert "formal_full_year_guidance_update" in _event_types(text)
