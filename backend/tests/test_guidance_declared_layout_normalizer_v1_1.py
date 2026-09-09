"""Run-82 source-layout regressions; assertions are transcribed source values."""

import pytest

from test_guidance_explicit_scope_normalizer_v1_1 import extract, values


def test_total_revenue_wins_over_named_product_guidance():
    result = extract(
        "The company reaffirms its full year 2026 total revenue guidance of $730 million to $760 million. "
        "The company reaffirms its full year 2026 Crysvita revenue guidance of $500 million to $520 million. "
        "The company reaffirms its full year 2026 Dojolvi revenue guidance of $100 million to $110 million."
    )
    assert values(result) == {("revenue", "FY2026", "UNSPECIFIED", 730e6, 760e6)}


def test_full_fiscal_and_quarter_outlooks_keep_all_primary_rows():
    result = extract(
        "Second Quarter Fiscal 2027 Outlook: Revenue of $395 million to $397 million. "
        "Non-GAAP subscription ARR contribution margin of approximately 11-12%. "
        "Non-GAAP net income per share of $0.03 to $0.05. "
        "Full Fiscal Year 2027 Outlook: Subscription ARR between $1,854 million and $1,862 million. "
        "Revenue of $1,638 million to $1,648 million. "
        "Non-GAAP net income per share of $0.25 to $0.35. "
        "Free cash flow of $293 million to $303 million."
    )
    assert values(result) == {
        ("revenue", "Q2FY2027", "UNSPECIFIED", 395e6, 397e6),
        ("eps", "Q2FY2027", "ADJUSTED", 0.03, 0.05),
        ("revenue", "FY2027", "UNSPECIFIED", 1638e6, 1648e6),
        ("eps", "FY2027", "ADJUSTED", 0.25, 0.35),
        ("fcf", "FY2027", "UNSPECIFIED", 293e6, 303e6),
    }


def test_expense_and_operating_cash_flow_cannot_supply_earnings_or_fcf():
    result = extract(
        "Guidance Item Current Guidance for Full-Year 2026 3 Prior Guidance for Full-Year 2026 "
        "Operating Expense $1,535 to $1,575 million $1,490 to $1,530 million "
        "Adjusted EBITDA Expense $1,340 to $1,370 million $1,305 to $1,335 million "
        "Net Cash Provided by Operating Activities $1,655 to $1,705 million $1,640 to $1,690 million "
        "Free Cash Flow $1,485 to $1,545 million $1,470 to $1,530 million"
    )
    assert values(result) == {("fcf", "FY2026", "UNSPECIFIED", 1485e6, 1545e6)}


def test_revised_column_and_table_units():
    result = extract(
        "Full-Year FY26 Guidance 2026 Guidance (In millions, except per share amounts) "
        "Previous Guidance (May 5, 2026) Revised Guidance (August 4, 2026) "
        "Adjusted EBITDA $365 to $385 $385 to $400 "
        "Operating Adjusted EPS $1.28 to $1.42 $1.40 to $1.50 "
        "Capital Expenditures $55 to $60 $55 to $60"
    )
    assert values(result) == {
        ("ebitda", "FY2026", "ADJUSTED", 385e6, 400e6),
        ("eps", "FY2026", "ADJUSTED", 1.4, 1.5),
    }


def test_actual_column_and_row_units():
    result = extract(
        "Fiscal Year 2027 Guidance 7 Key Metric FY 2026 FY 2027 Y - o- y Change "
        "Net Sales (in Millions) $3,050 $3,350 - $3,550 +10% to +16% "
        "Adj. EBITDA (in Millions) $963 $1,000 - $1,050 +4% to +9% "
        "Adj. EBITDA Margin 31.6% 29.6% - 29.9%"
    )
    assert values(result) == {
        ("revenue", "FY2027", "UNSPECIFIED", 3350e6, 3550e6),
        ("ebitda", "FY2027", "ADJUSTED", 1000e6, 1050e6),
    }


def test_growth_percentages_are_not_operating_margin():
    result = extract(
        "Financial Outlook (In millions, except per share data) "
        "Current Guidance Fiscal 2026 Prior Guidance Fiscal 2026* Guidance Change at Midpoint** "
        "ARR $2,010 - $2,025 $1,988 - $2,003 $22 "
        "Total revenue $1,985 - $1,995 $1,970 - $1,985 $13 "
        "Constant currency 15% - 15.5% 14% - 15% 75 bps "
        "Subscription revenue $1,898 - $1,908 $1,884 - $1,899 $12 "
        "Non-GAAP operating margin 29% 29% — "
        "Non-GAAP net income per diluted share $1.62 - $1.64 $1.58 - $1.61 $0.04 "
        "Free cash flow $505 - $515 $505 - $515 — Free cash flow margin 26% 26%"
    )
    assert values(result) == {
        ("revenue", "FY2026", "UNSPECIFIED", 1985e6, 1995e6),
        ("operating_margin", "FY2026", "ADJUSTED", 0.29, 0.29),
        ("eps", "FY2026", "ADJUSTED", 1.62, 1.64),
        ("fcf", "FY2026", "UNSPECIFIED", 505e6, 515e6),
    }


def test_historical_comparison_does_not_relabel_current_quarter():
    result = extract(
        "BUSINESS OUTLOOK Third quarter 2026 - The company expects revenue growth of approximately 8% "
        "compared to the third quarter of 2025 and non-GAAP EPS between $4.39 and $4.44 per share. "
        "Full-year 2026 - The company now expects non-GAAP EPS between $17.62 and $17.72 per share."
    )
    assert values(result) == {
        ("eps", "Q3FY2026", "ADJUSTED", 4.39, 4.44),
        ("eps", "FY2026", "ADJUSTED", 17.62, 17.72),
    }


def test_republication_disclaimer_does_not_create_new_update():
    result = extract(
        "Affirming 2025 Guidance Revenue $3.0B – $3.1B EBITDA $210M – $225M. "
        "Guidance provided as of May 13, 2025 and is neither being reaffirmed nor updated today."
    )
    assert result == []


def test_point_ebitda_keeps_explicit_forward_year():
    assert ("ebitda", "FY2026", "ADJUSTED", 65e6, 65e6) in values(
        extract("We continue to expect 2026 Adjusted EBITDA to be ~$65 million.")
    )


def test_stated_operating_margin_is_distinct_from_gross_margin():
    assert ("operating_margin", "FY2026", "UNSPECIFIED", 0.27, 0.27) in values(
        extract(
            "Fiscal Year 2026 Guidance: We now anticipate revenue of approximately $8.05 billion "
            "and pro forma EPS of $10.00 based on gross margin of 59.7%, operating margin of 27.0%."
        )
    )


def test_forecast_header_binds_both_revenue_and_ebitda():
    assert values(
        extract(
            "Forecast for 2025 Everus is affirming its estimated full-year guidance for 2025. "
            "Revenue is expected to be in the range of $3.0 billion to $3.1 billion. "
            "EBITDA is expected to be in the range of $210 million to $225 million."
        )
    ) == {
        ("revenue", "FY2025", "UNSPECIFIED", 3e9, 3.1e9),
        ("ebitda", "FY2025", "UNSPECIFIED", 210e6, 225e6),
    }


@pytest.mark.parametrize("defined", [True, False])
def test_pro_forma_eps_requires_the_issuers_explicit_non_gaap_definition(defined):
    from app.services.guidance_declared_layout_normalizer_v1_1 import (
        normalize_declared_layouts,
    )
    from test_guidance_explicit_scope_normalizer_v1_1 import doc, HASH

    text = (
        "Fiscal Year 2026 Guidance: We now anticipate revenue of approximately $8.05 billion "
        "and pro forma EPS of $10.00 based on gross margin of 59.7%, operating margin of 27.0%."
    )
    if defined:
        text += " Non-GAAP financial measures: pro forma effective tax rate, pro forma net income (earnings) per share and free cash flow."
    records, _ = normalize_declared_layouts(doc(text), rules_hash=HASH)
    eps = {v for v in values(records) if v[0] == "eps"}
    assert eps == ({("eps", "FY2026", "ADJUSTED", 10, 10)} if defined else set())


def test_gaap_and_adjusted_eps_do_not_share_the_gaap_floor():
    assert values(
        extract(
            "Introduces FY 2026 GAAP EPS guidance of 'at least $8.89'; 'at least $9.00' on an Adjusted basis."
        )
    ) == {
        ("eps", "FY2026", "GAAP", 8.89, 8.89),
        ("eps", "FY2026", "ADJUSTED", 9.0, 9.0),
    }


def test_in_the_range_of_preserves_consolidated_ebitda_and_fcf():
    result = extract(
        "Full Year 2026 Guidance: Consolidated net sales in the range of $5,575 to $5,925 million. "
        "Consolidated Adjusted EBITDA in the range of $1,365 to $1,515 million. "
        "Consolidated Adjusted free cash flow in the range of $655 to $805 million."
    )
    assert values(result) == {
        ("revenue", "FY2026", "UNSPECIFIED", 5575e6, 5925e6),
        ("ebitda", "FY2026", "ADJUSTED", 1365e6, 1515e6),
        ("fcf", "FY2026", "ADJUSTED", 655e6, 805e6),
    }


@pytest.mark.parametrize(
    "text",
    [
        "Reported 2026 Adjusted EBITDA of $65 million.",
        "2026 Guidance Total Revenue and Other Income Expected to be between $1.4 billion and $1.575 billion.",
        "Fiscal Year 2026 Guidance: Reported gross margin of 58.5%, operating margin of 25.5%.",
    ],
)
def test_declared_layout_adapter_does_not_invent_forecasts_or_metric_mapping(text):
    from app.services.guidance_declared_layout_normalizer_v1_1 import (
        normalize_declared_layouts,
    )
    from test_guidance_explicit_scope_normalizer_v1_1 import doc, HASH

    assert normalize_declared_layouts(doc(text), rules_hash=HASH) == ([], set())
