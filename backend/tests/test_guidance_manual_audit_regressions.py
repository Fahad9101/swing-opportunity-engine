from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from app.domain.soe_v1_1 import GuidanceAction, SourceDocument
from app.services.guidance_raw_canonical_extractor import extract_canonical_typed_guidance_facts


def _doc(ticker: str, text: str) -> SourceDocument:
    ts = datetime(2026, 9, 14, tzinfo=UTC)
    digest = hashlib.sha256(text.encode()).hexdigest()
    return SourceDocument(
        document_id=f"audit-{ticker}-{digest[:12]}", rules_hash="audit", ticker=ticker,
        cik="0000000001", accession="0000000001-26-999999", form="8-K", filing_date=ts.date(),
        source_url=f"https://www.sec.gov/Archives/edgar/data/1/{ticker.lower()}.htm",
        source_timestamp=ts, fetched_at=ts, content_hash=digest, content_type="text/plain", content=text,
    )


def _facts(ticker: str, text: str):
    return list(extract_canonical_typed_guidance_facts(_doc(ticker, text)).facts)


def test_ordinary_lower_revenue_expectation_is_not_a_guidance_cut():
    facts = _facts("IESC", "This is expected to result in lower multi-family revenues in fiscal 2026 as compared with the prior year.")
    assert not any(f.explicit_action is GuidanceAction.LOWER for f in facts)


def test_lower_operating_costs_do_not_lower_free_cash_flow_guidance():
    facts = _facts("CRGY", "The combination of higher expected production and lower operating costs is expected to support incremental free cash flow generation in 2026.")
    assert not any(f.explicit_action is GuidanceAction.LOWER for f in facts)


def test_rate_cut_commentary_is_not_revenue_guidance_withdrawal_or_cut():
    facts = _facts("HOOD", "The Federal Reserve lowered interest rates by 100 basis points, which negatively impacted our net interest revenues. We anticipate future rate cuts may have a similar impact.")
    assert not any(f.explicit_action in {GuidanceAction.LOWER, GuidanceAction.WITHDRAW} for f in facts)


def test_three_month_outlook_does_not_become_full_year_margin_guidance():
    facts = _facts("ALAB", "Outlook for Three Months Ending September 30, 2026 Low High GAAP gross margin 72 % Non-GAAP gross margin 75 %.")
    assert not any(f.fiscal_period == "FY2026" and f.metric.value == "gross_margin" for f in facts)


def test_parallel_quarter_and_full_year_columns_fail_closed():
    rblx = _facts("RBLX", "Guidance Q3 2026 Full Year 2026 ($ in millions) Low High Low High Revenue $1,413 $1,490 $5,865 $6,135.")
    assert not rblx
    brze = _facts("BRZE", "Metric FY 2027 Q3 Guidance FY 2027 Guidance Revenue $229.0 - $230.0 $900.0 - $910.0.")
    assert not brze


def test_contract_revenue_cost_change_is_not_revenue_guidance():
    facts = _facts("WLDN", "Fiscal Year 2026 Financial Targets Net Revenue between $410 million and $425 million. Direct costs of contract revenue in our Energy segment decreased $3.5 million, or 4.3%, for the three months ended April 3, 2026.")
    assert not any(f.metric.value == "revenue" and f.low == 3.5 for f in facts)


def test_financial_highlights_actual_is_not_forward_guidance():
    facts = _facts("BTSG", "Increased 2025 Revenue guidance: $12,200 - $12,600 million. Fourth Quarter 2025 Financial Highlights. Net revenue of $3,551 million, up 29.3% compared to $2,747 million in the fourth quarter of 2024.")
    assert not any(f.metric.value == "revenue" and f.low == 3551 for f in facts)


def test_yoy_change_amount_is_not_adjusted_ebitda_guidance_level():
    facts = _facts("CVNA", "Record Full Year Adjusted EBITDA of $2.2 billion, up more than $850 million YoY. Expects Significant Growth in Adjusted EBITDA in FY 2026.")
    assert not any(f.metric.value == "ebitda" and f.low == 850 for f in facts)


def test_net_income_ranges_do_not_become_prior_ebitda_value():
    facts = _facts("OPLN", "Revised Guidance (August 4, 2026) Net income (in millions) $147 - $164 $163 - $176 Adjusted EBITDA (in millions) $360 - $380 $385 - $400.")
    assert not any(f.metric.value == "ebitda" and f.low in {163, 147} and f.high in {176, 164} for f in facts)


def test_formal_numeric_outlook_cut_remains_extractable():
    facts = _facts("TFX", "The Company reduced its full year 2026 GAAP diluted earnings per share outlook range to $2.54 to $2.84.")
    assert any(f.metric.value == "eps" and f.explicit_action is GuidanceAction.LOWER for f in facts)

# Fresh post-v33 full-market manual-audit regressions (v34).
def test_remaining_performance_obligation_revenue_is_not_guidance():
    toast = _facts("TOST", "As of June 30, 2026, approximately $1,110 million of revenue is expected to be recognized from remaining performance obligations over the next twelve months.")
    assert not any(f.metric.value == "revenue" and f.low == 1110 for f in toast)
    okta = _facts("OKTA", "Remaining performance obligations were $4,858 million. Of this amount, the Company expects to recognize revenue of approximately $2,585 million over the next 12 months.")
    assert not any(f.metric.value == "revenue" and f.low == 2585 for f in okta)


def test_recognized_revenue_result_is_not_full_year_guidance():
    facts = _facts("PWR", "For the full year ending December 31, 2026, Quanta expects revenues to range between $34.7 billion and $35.2 billion. During the six months ended June 30, 2026 and 2025, Quanta recognized revenue of approximately $2.53 billion and $1.96 billion, respectively.")
    assert not any(f.metric.value == "revenue" and f.low == 2.53 for f in facts)


def test_outlook_historical_column_is_not_current_guidance():
    facts = _facts("EVTC", "2026 Outlook. Outlook 2026 2025 (Dollar amounts in millions, except per share data) Low High Revenues (GAAP) $1,085 $1,095 $1,073.")
    assert not any(f.metric.value == "revenue" and f.fiscal_period == "FY2025" and f.low == 1073 for f in facts)


def test_quarter_results_do_not_inherit_full_year_raise_action():
    facts = _facts("GE", "GE Aerospace announces Second Quarter 2026 Results, raising full-year guidance across the board. Second Quarter 2026 Results: Total revenue (GAAP) of $13.3 billion, +21%; adjusted revenue of $12.6 billion, +24%.")
    assert not any(f.metric.value == "revenue" and f.fiscal_period == "Q2FY2026" for f in facts)


def test_realized_fcf_before_financial_guidance_section_is_not_guidance():
    facts = _facts("PYPL", "Adjusted free cash flow $1,832 $656 179%. Financial Guidance 2026 Guidance: Following another strong quarter, PayPal is raising full year non-GAAP EPS guidance.")
    assert not any(f.metric.value == "fcf" and f.low == 1832 for f in facts)


def test_cost_of_revenues_plural_is_not_revenue_guidance():
    facts = _facts("ENTG", "We expect total depreciation expense in 2026 to be reduced by approximately $73.0 million recognized primarily in cost of revenues and R&D expenses.")
    assert not any(f.metric.value == "revenue" and f.low == 73 for f in facts)


def test_full_year_revenue_guidance_is_not_rebound_to_quarter():
    facts = _facts("CIEN", "Providing revenue guidance for fiscal fourth quarter 2026 of $1.75 billion plus or minus $50 million. Raising revenue guidance for fiscal year 2026 to $6.42 billion plus or minus $50 million.")
    assert any(f.metric.value == "revenue" and f.fiscal_period == "FY2026" and f.low == 6.42 for f in facts)
    assert not any(f.metric.value == "revenue" and f.fiscal_period == "Q4FY2026" and f.low == 6.42 for f in facts)


def test_stock_split_eps_restatement_is_not_economic_guidance_cut():
    facts = _facts("APH", "Following the two-for-one stock split, the Company's Adjusted Diluted EPS guidance for the third quarter of 2026 would be $0.70 to $0.71, versus pre-split guidance of $1.40 to $1.42.")
    assert not any(f.metric.value == "eps" and f.low == 0.70 and f.high == 0.71 for f in facts)


def test_named_entity_standalone_revenue_forecast_fails_closed_on_scope():
    facts = _facts("ECG", "For the full calendar year 2026, Epsilon expects to generate revenue of approximately $250 million with earnings before interest, taxes, depreciation and amortization.")
    assert not any(f.metric.value == "revenue" and f.low == 250 for f in facts)


def test_valid_annual_ebitda_raise_survives_v34_guards():
    facts = _facts("ESI", "The Company now expects full year 2026 adjusted EBITDA to be in the range of $690 million to $710 million.")
    assert any(f.metric.value == "ebitda" and f.fiscal_period == "FY2026" for f in facts)

