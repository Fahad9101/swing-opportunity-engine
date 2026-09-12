from datetime import UTC, datetime

from app.domain.soe_v1_1 import SourceDocument
from app.services.phase_1_1e_catalyst_evidence_round5_v1_1 import (
    extract_sec_catalyst_candidates_round5,
)

NOW = datetime(2026, 9, 5, tzinfo=UTC)
RULES_HASH = "a" * 64


def _doc(ticker: str, text: str) -> SourceDocument:
    return SourceDocument(
        document_id=f"{ticker}-round5",
        rules_hash=RULES_HASH,
        ticker=ticker,
        cik="0000000001",
        accession="0000000001-26-000001",
        form="8-K",
        source_url=f"https://www.sec.gov/Archives/edgar/data/1/{ticker.lower()}-ex991.htm",
        source_timestamp=NOW,
        fetched_at=NOW,
        content_hash="b" * 64,
        content=text,
    )


def test_brze_real_announced_today_will_release_wording_is_not_completed_earnings():
    doc = _doc(
        "BRZE",
        "Braze to Report Fiscal First Quarter 2027 Results; Reaffirms First Quarter and FY27 Guidance. "
        "Braze announced today that it will release its financial results for the first quarter of the "
        "2027 fiscal year after U.S. financial markets close on Wednesday, May 27, 2026. Braze will host "
        "a webcast conference call to discuss its financial results on the same day. In addition, Braze "
        "is reaffirming the financial guidance provided on March 24, 2026 for both the first quarter and "
        "the full year of its current fiscal year.",
    )
    candidates = extract_sec_catalyst_candidates_round5(doc)
    assert not any(candidate.input.event_type == "quarterly_earnings" for candidate in candidates)


def test_to_report_results_title_is_not_completed_earnings():
    doc = _doc(
        "TEST",
        "Company to Report Second Quarter 2026 Results. The company will release its financial results "
        "for the second quarter after market close next Tuesday and will host a webcast afterward.",
    )
    candidates = extract_sec_catalyst_candidates_round5(doc)
    assert not any(candidate.input.event_type == "quarterly_earnings" for candidate in candidates)


def test_announces_date_of_results_is_not_completed_earnings():
    doc = _doc(
        "TEST",
        "Company Announces Date of Second Quarter 2026 Financial Results. The company plans to release "
        "the results on September 10, 2026 after market close.",
    )
    candidates = extract_sec_catalyst_candidates_round5(doc)
    assert not any(candidate.input.event_type == "quarterly_earnings" for candidate in candidates)


def test_genuine_reported_quarterly_results_remain_valid_primary_evidence():
    doc = _doc(
        "TEST",
        "Company reported second quarter 2026 financial results today. Revenue for the quarter was "
        "$425 million and diluted earnings per share were $1.25.",
    )
    candidates = extract_sec_catalyst_candidates_round5(doc)
    assert any(candidate.input.event_type == "quarterly_earnings" for candidate in candidates)
