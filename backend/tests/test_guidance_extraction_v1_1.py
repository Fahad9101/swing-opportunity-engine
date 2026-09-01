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


def test_historical_fiscal_year_increase_is_not_a_raise_action():
    result = extract_guidance_facts(
        document(
            "Fiscal year 2026 revenue increased 23.7% compared to fiscal year 2025, driven by strong customer demand."
        ),
        rules_hash=RULES_HASH,
    )
    assert result.records == []


def test_reported_fiscal_year_actuals_are_not_guidance():
    result = extract_guidance_facts(
        document(
            "KLA reported GAAP diluted EPS of $1.04 on total revenues of $3.66 billion for the fourth quarter of fiscal year 2026."
        ),
        rules_hash=RULES_HASH,
    )
    assert result.records == []


def test_extracts_multiple_metrics_from_same_guidance_sentence_locally():
    result = extract_guidance_facts(
        document(
            "For the full year 2026, the company is raising its guidance for consolidated revenue to approximately $91.2 billion, "
            "consolidated non-GAAP adjusted operating profit to approximately $8.65 billion, and non-GAAP adjusted diluted EPS to approximately $7.22."
        ),
        rules_hash=RULES_HASH,
    )
    revenue = next(record for record in result.records if record.metric is GuidanceMetric.REVENUE)
    eps = next(record for record in result.records if record.metric is GuidanceMetric.EPS)
    assert revenue.midpoint == 91_200_000_000
    assert eps.midpoint == 7.22
    assert eps.accounting_basis == "ADJUSTED"
    assert revenue.explicit_action is GuidanceAction.RAISE
    assert eps.explicit_action is GuidanceAction.RAISE


def test_extracts_at_least_eps_values_for_gaap_and_adjusted_mentions():
    result = extract_guidance_facts(
        document(
            "The Company intends to reaffirm its guidance of at least $8.36 in diluted earnings per common share (EPS) "
            "or at least $9.00 in adjusted earnings per share (Adjusted EPS), in each case for full-year 2026."
        ),
        rules_hash=RULES_HASH,
    )
    eps_records = [record for record in result.records if record.metric is GuidanceMetric.EPS]
    assert {record.midpoint for record in eps_records} == {8.36, 9.0}
    assert any(record.accounting_basis == "ADJUSTED" and record.midpoint == 9.0 for record in eps_records)


def test_quarter_header_takes_precedence_over_later_full_year_section():
    result = extract_guidance_facts(
        document(
            "Consolidated metric Q3 FY27 Net sales (cc) Increase 3.0% to 3.75% Operating income (cc) Increase 2.0% to 4.0% "
            "Adjusted EPS $0.62 to $0.64 Fiscal year 2027 The Company's fiscal year guidance is based on FY26 figures."
        ),
        rules_hash=RULES_HASH,
    )
    eps = next(record for record in result.records if record.metric is GuidanceMetric.EPS)
    assert eps.fiscal_period == "Q3FY2027"
    assert eps.low == 0.62
    assert eps.high == 0.64
    assert eps.explicit_action is GuidanceAction.NONE


def test_table_cells_are_reconstructed_into_guidance_records():
    content = """
    <table>
      <tr><th>Q2 FY2027 Guidance</th></tr>
      <tr><td>Revenue</td><td>$5.80 billion to $5.85 billion</td></tr>
      <tr><td>Adjusted EPS</td><td>$4.95 to $5.05</td></tr>
    </table>
    """
    result = extract_guidance_facts(document(content), rules_hash=RULES_HASH)
    revenue = next(record for record in result.records if record.metric is GuidanceMetric.REVENUE)
    eps = next(record for record in result.records if record.metric is GuidanceMetric.EPS)
    assert revenue.fiscal_period == "Q2FY2027"
    assert revenue.low == 5_800_000_000
    assert revenue.high == 5_850_000_000
    assert eps.fiscal_period == "Q2FY2027"
    assert eps.low == 4.95
    assert eps.high == 5.05
