from datetime import UTC, date, datetime

from app.domain.soe_v1_1 import GuidanceAction, GuidanceMetric, SourceDocument
from app.services.fact_extraction_service import extract_guidance_facts, html_to_text


NOW = datetime(2026, 9, 1, tzinfo=UTC)
RULES_HASH = "1" * 64


def document(content: str) -> SourceDocument:
    return SourceDocument(
        document_id="doc-1",
        rules_hash=RULES_HASH,
        ticker="TEST",
        cik="0000000001",
        accession="0000000001-26-000001",
        form="8-K",
        filing_date=date(2026, 9, 1),
        source_url="https://www.sec.gov/Archives/edgar/data/1/000000000126000001/test.htm",
        source_timestamp=NOW,
        fetched_at=NOW,
        content_hash="a" * 64,
        content=content,
    )


def test_html_to_text_removes_tags_but_keeps_content():
    assert "FY2027 revenue" in html_to_text("<html><body><p>FY2027 revenue guidance</p></body></html>")


def test_extracts_full_year_revenue_range_and_scales_billions():
    result = extract_guidance_facts(
        document("For full-year 2027, we expect revenue guidance of $1.2 billion to $1.3 billion."),
        rules_hash=RULES_HASH,
    )
    assert len(result.records) == 1
    record = result.records[0]
    assert record.metric is GuidanceMetric.REVENUE
    assert record.fiscal_period == "FY2027"
    assert record.low == 1_200_000_000
    assert record.high == 1_300_000_000
    assert record.midpoint == 1_250_000_000
    assert record.explicit_action is GuidanceAction.INITIATE
    assert record.evidence_span


def test_extracts_lowered_adjusted_eps_guidance():
    result = extract_guidance_facts(
        document("We lowered full-year 2027 adjusted EPS guidance to $3.00 to $3.20."),
        rules_hash=RULES_HASH,
    )
    record = result.records[0]
    assert record.metric is GuidanceMetric.EPS
    assert record.accounting_basis == "ADJUSTED"
    assert record.explicit_action is GuidanceAction.LOWER
    assert record.low == 3.0
    assert record.high == 3.2
    assert record.unit == "USD/share"


def test_extracts_reaffirmed_fcf_guidance():
    result = extract_guidance_facts(
        document("The company reaffirmed FY2027 free cash flow guidance of $500 million to $550 million."),
        rules_hash=RULES_HASH,
    )
    record = result.records[0]
    assert record.metric is GuidanceMetric.FCF
    assert record.explicit_action is GuidanceAction.REAFFIRM
    assert record.low == 500_000_000
    assert record.high == 550_000_000


def test_extracts_margin_range_as_fraction():
    result = extract_guidance_facts(
        document("For fiscal year 2027, operating margin guidance is 28% to 30%."),
        rules_hash=RULES_HASH,
    )
    record = result.records[0]
    assert record.metric is GuidanceMetric.OPERATING_MARGIN
    assert record.low == 0.28
    assert record.high == 0.30
    assert record.unit == "fraction"


def test_missing_fiscal_period_is_rejected_not_guessed():
    result = extract_guidance_facts(
        document("We expect revenue guidance of $1.2 billion to $1.3 billion."),
        rules_hash=RULES_HASH,
    )
    assert result.records == []
    assert result.rejected_candidates[0]["reason"] == "missing_fiscal_period"


def test_standing_no_guidance_policy_is_extracted_as_fact_only():
    result = extract_guidance_facts(
        document("The company does not provide quantitative financial guidance as a standing policy."),
        rules_hash=RULES_HASH,
    )
    assert result.policy_evidence is not None
    assert result.policy_evidence.standing_no_guidance_policy is True
    assert result.policy_evidence.evidence_span


def test_ordinary_historical_metric_is_not_mislabeled_as_guidance():
    result = extract_guidance_facts(
        document("Revenue for the quarter was $1.2 billion and operating margin was 20%."),
        rules_hash=RULES_HASH,
    )
    assert result.records == []
