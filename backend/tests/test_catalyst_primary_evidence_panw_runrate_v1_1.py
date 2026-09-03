from datetime import UTC, date, datetime

from app.domain.soe_v1_1 import SourceDocument
from app.services.catalyst_primary_evidence_service import extract_sec_catalyst_candidates


def _doc(text: str) -> SourceDocument:
    return SourceDocument(
        document_id="doc-panw-runrate",
        rules_hash="rules",
        ticker="PANW",
        cik="0001327567",
        accession="0001193125-25-168821",
        form="8-K",
        filing_date=date(2025, 7, 30),
        source_url="https://www.sec.gov/Archives/edgar/data/1327567/000119312525168821/d67702dex991.htm",
        source_timestamp=datetime(2025, 7, 30, tzinfo=UTC),
        fetched_at=datetime(2025, 7, 30, tzinfo=UTC),
        content_hash="abc",
        content=text,
    )


def test_annual_revenue_run_rate_based_on_quarterly_guidance_is_not_full_year_guidance():
    doc = _doc(
        "Q4 FY'18 Revenue run rate. Annual Revenue run rate based on Q4 FY'18 Revenue multiplied by four. "
        "Based on Q4 FY'25 Revenue guidance mid-point run rate. Q4 FY'25 revenue guidance provided on 5/20/2025. "
        "Annual Revenue run rate based on Q4 FY'25 Revenue guidance mid-point multiplied by four."
    )
    candidates = extract_sec_catalyst_candidates(doc)
    assert not any(item.input.event_type == "formal_full_year_guidance_update" for item in candidates)
