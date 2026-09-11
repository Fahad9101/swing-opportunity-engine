from __future__ import annotations

from datetime import UTC, datetime

from app.domain.soe_v1_1 import GuidanceMetric, SourceDocument
from app.services.phase_1_1e_run89_guidance_repairs_v1_1 import extract_guidance_facts_run89


NOW = datetime(2026, 9, 11, tzinfo=UTC)


def document(text: str, ticker: str = "TEST") -> SourceDocument:
    return SourceDocument(
        document_id=f"{ticker}:run89:test",
        rules_hash="run89-test",
        ticker=ticker,
        cik="0000000001",
        accession="0000000001-26-000001",
        form="8-K",
        filing_date=NOW.date(),
        source="SEC EDGAR",
        source_url="https://www.sec.gov/example.htm",
        source_timestamp=NOW,
        fetched_at=NOW,
        content_hash="run89",
        content_type="text/plain",
        content=text,
    )


def run89_records(text: str, ticker: str = "TEST"):
    result = extract_guidance_facts_run89(document(text, ticker), rules_hash="run89-test")
    return [
        item
        for item in result.records
        if (item.evidence_span or "").startswith("phase_1_1e_run89_authoritative_forward_scope;")
    ]


def test_two_column_company_revenue_overrides_segment_rows_and_binds_q1_and_fy():
    text = (
        "Financial Outlook. The company is providing guidance for the first fiscal quarter "
        "and the full fiscal year 2027. Q1 FY27 Full fiscal year FY27 "
        "Total BlackBerry revenue: $132 - $140 million $584 - $611 million "
        "QNX revenue: $60 - $64 million $290 - $307 million "
        "Secure Communications revenue: $66 - $70 million $270 - $280 million."
    )
    records = run89_records(text, "BB")
    revenue = [r for r in records if r.metric is GuidanceMetric.REVENUE]
    assert {(r.fiscal_period, r.low, r.high) for r in revenue} == {
        ("Q1FY2027", 132_000_000.0, 140_000_000.0),
        ("FY2027", 584_000_000.0, 611_000_000.0),
    }


def test_two_column_company_revenue_binds_q2_and_fy_not_prior_q1():
    text = (
        "Financial Outlook. BlackBerry is providing guidance for the second fiscal quarter "
        "and fiscal year ending February 28, 2027. Q2 FY27 FY27 "
        "Total BlackBerry revenue: $137 - $148 million $594 - $621 million "
        "QNX revenue: $70 - $75 million $295 - $312 million "
        "Secure Communications revenue: $57 - $63 million $275 - $285 million."
    )
    records = run89_records(text, "BB")
    revenue = [r for r in records if r.metric is GuidanceMetric.REVENUE]
    assert {(r.fiscal_period, r.low, r.high) for r in revenue} == {
        ("Q2FY2027", 137_000_000.0, 148_000_000.0),
        ("FY2027", 594_000_000.0, 621_000_000.0),
    }


def test_coherent_quarter_outlook_is_quarter_not_full_year():
    text = (
        "Third quarter fiscal 2026 Outlook. "
        "REVENUE $1.70 billion to $1.84 billion "
        "NON-GAAP GROSS MARGIN 38.5% to 40.5% "
        "NON-GAAP EARNINGS PER SHARE $1.28 to $1.48."
    )
    records = run89_records(text, "COHR")
    assert any(
        r.metric is GuidanceMetric.GROSS_MARGIN
        and r.fiscal_period == "Q3FY2026"
        and r.low == 0.385
        and r.high == 0.405
        for r in records
    )
    assert not any(r.fiscal_period == "FY2026" for r in records)


def test_repligen_full_year_table_recovers_revenue_and_diluted_eps():
    text = (
        "FINANCIAL GUIDANCE FOR FULL YEAR 2026. All adjusted figures are non-GAAP. "
        "CURRENT GUIDANCE (at May 5, 2026) FY 2026 Adjusted (non-GAAP) "
        "Total Reported Revenue $803M - $833M "
        "Gross Margin 53.7% - 54.2% "
        "Operating Margin 15.4% - 15.8% "
        "Earnings Per Share - Diluted $1.97 - $2.05."
    )
    records = run89_records(text, "RGEN")
    assert any(
        r.metric is GuidanceMetric.REVENUE
        and r.fiscal_period == "FY2026"
        and r.low == 803_000_000.0
        and r.high == 833_000_000.0
        for r in records
    )
    assert any(
        r.metric is GuidanceMetric.EPS
        and r.fiscal_period == "FY2026"
        and r.low == 1.97
        and r.high == 2.05
        for r in records
    )


def test_pagaya_total_revenue_and_other_income_is_company_revenue():
    text = (
        "Full-Year 2026 Outlook FY26 "
        "Network Volume Expected to be between $11.45 billion and $13 billion "
        "Total Revenue and Other Income Expected to be between $1.4 billion and $1.575 billion "
        "Adjusted EBITDA Expected to be between $420 million and $460 million "
        "GAAP Net Income Expected to be between $110 million and $160 million."
    )
    records = run89_records(text, "PGY")
    assert any(
        r.metric is GuidanceMetric.REVENUE
        and r.fiscal_period == "FY2026"
        and r.low == 1_400_000_000.0
        and r.high == 1_575_000_000.0
        for r in records
    )
    assert any(
        r.metric is GuidanceMetric.EBITDA
        and r.low == 420_000_000.0
        and r.high == 460_000_000.0
        for r in records
    )


def test_footnoted_adjusted_ebitda_guidance_is_not_dropped():
    text = (
        "Full Year 2026 Outlook. "
        "Revenue in the range of $600 million to $640 million. "
        "Adjusted EBITDA1 in the range of $118 million to $132 million. "
        "Cash flow from operations in the range of $65 million to $85 million."
    )
    records = run89_records(text, "SHLS")
    assert any(
        r.metric is GuidanceMetric.REVENUE
        and r.fiscal_period == "FY2026"
        and r.low == 600_000_000.0
        and r.high == 640_000_000.0
        for r in records
    )
    assert any(
        r.metric is GuidanceMetric.EBITDA
        and r.accounting_basis == "ADJUSTED"
        and r.low == 118_000_000.0
        and r.high == 132_000_000.0
        for r in records
    )


def test_segment_only_revenue_is_not_promoted_to_company_revenue():
    text = (
        "Full Year 2027 Outlook. "
        "QNX segment revenue $295 million to $312 million. "
        "Secure Communications segment revenue $275 million to $285 million."
    )
    records = run89_records(text, "TEST")
    assert not any(r.metric is GuidanceMetric.REVENUE for r in records)
