"""Source-boundary regressions identified in the complete run-84 ledger audit."""

import pytest
from test_phase_1_1e_run83_pipeline_regressions import pipeline
from test_guidance_explicit_scope_normalizer_v1_1 import values


def test_screening_product_revenue_cannot_replace_company_revenue():
    records = pipeline("Full year 2026 guidance: We expect revenue to be in the range of $1.34 to $1.36 billion. Screening revenue is now expected to be in the range of $218 to $230 million.")
    assert values(records) == {("revenue", "FY2026", "UNSPECIFIED", 1.34e9, 1.36e9)}


def test_different_explicit_endpoint_units_and_hyphenated_quarter():
    records = pipeline("Updated 2026 Full-Year Guidance: Revenue expected to be in the range of approximately $980 million to $1 billion. Adjusted EBITDA projected in the range of approximately $225 million to $250 million. Second-Quarter 2026 Guidance: Revenue expected to be in the range of approximately $190 million to $205 million.")
    assert values(records) == {
        ("revenue", "FY2026", "UNSPECIFIED", 980e6, 1e9),
        ("ebitda", "FY2026", "ADJUSTED", 225e6, 250e6),
        ("revenue", "Q2FY2026", "UNSPECIFIED", 190e6, 205e6),
    }


def test_operating_margins_do_not_shift_to_next_fiscal_scope():
    records = pipeline("Third Quarter 2026 Outlook: Non-GAAP operating margin is expected to be in the range of 19% to 19.5%. Full Year 2026 Outlook: Non-GAAP operating margin is expected to be in the range of 18.5% to 19.0%. Free cash flow margin is expected to be 19.5%. Full Year 2027 Outlook: Non-GAAP operating margin is expected to be 25%.")
    assert values(records) == {
        ("operating_margin", "Q3FY2026", "ADJUSTED", .19, .195),
        ("operating_margin", "FY2026", "ADJUSTED", .185, .19),
        ("operating_margin", "FY2027", "ADJUSTED", .25, .25),
    }


def test_prior_eps_range_is_not_another_current_forecast():
    records = pipeline("The company now expects full-year 2026 EPS of $4.29 to $4.39 on a GAAP basis and adjusted EPS of $5.00 to $5.10, versus prior guidance of $3.68 to $3.78 on a GAAP basis and adjusted EPS of $4.45 to $4.55.")
    assert values(records) == {("eps", "FY2026", "ADJUSTED", 5, 5.1), ("eps", "FY2026", "GAAP", 4.29, 4.39)}


def test_colon_guidance_keeps_current_values_and_accompanying_metrics():
    records = pipeline("Second Quarter Fiscal Year 2027 Guidance: Net Sales: $7.95 billion to $8.25 billion. Adjusted EPS: $1.00 to $1.07. Updated Fiscal Year 2027 Guidance: Net Sales: $33.7 billion to $35.2 billion. Adjusted Operating Margin: 7.0% to 7.2%. Adjusted EPS: $4.42 to $4.74. Fiscal Year 2027 Guidance Prior Updated Net Sales $32.3 - $33.8 billion $33.7 - $35.2 billion")
    actual = values(records)
    assert any(v[:3] == ("revenue", "FY2027", "UNSPECIFIED") and v[3] == pytest.approx(33.7e9) and v[4] == pytest.approx(35.2e9) for v in actual)
    assert ("eps", "FY2027", "ADJUSTED", 4.42, 4.74) in actual
    assert ("eps", "Q2FY2027", "ADJUSTED", 1, 1.07) in actual
    assert not any(r.metric.value == "revenue" and r.low < 8e9 and r.fiscal_period == "FY2027" for r in records)


def test_reported_eps_after_adjusted_only_table_survives():
    records = pipeline("2026 Guidance (In millions, except per share amounts) Previous Guidance (May 5, 2026) Revised Guidance (August 4, 2026) Adjusted EBITDA $365 to $385 $385 to $400 Operating Adjusted EPS $1.28 to $1.42 $1.40 to $1.50 Note: Per share amounts are presented on a diluted basis. Revised guidance is based on Net Income of $163 million to $176 million and Net Income per Share of $1.23 to $1.33 (up from previous guidance of $147 million to $164 million and $1.09 to $1.23, respectively).")
    assert ("eps", "FY2026", "ADJUSTED", 1.4, 1.5) in values(records)
    assert ("eps", "FY2026", "UNSPECIFIED", 1.23, 1.33) in values(records)


def test_cash_burn_keeps_sign_and_forecast_year():
    records = pipeline("2026 Guidance: We expect full year 2026 revenue of $1.3 billion to $1.32 billion. We continue to expect free cash flow burn to be in the range of $185 to $195 million, an improvement compared to $233 million for the full year 2025.")
    assert ("fcf", "FY2026", "UNSPECIFIED", -195e6, -185e6) in values(records)
    assert not any(r.metric.value == "fcf" and r.fiscal_period == "FY2025" for r in records)


def test_conflicting_cash_burn_year_is_not_silently_corrected():
    records = pipeline("2026 Guidance: We expect free cash flow burn to be in the range of $185 to $195 million in 2025, an improvement compared to $233 million for the full year 2025.")
    assert not any(r.metric.value == "fcf" for r in records)


def test_previous_updated_table_scales_both_metrics():
    records = pipeline("Previous Updated (In millions, except for student starts) FY 2025 Guidance FY 2025 Guidance Revenue $480 - $490 $485 - $495 Adjusted EBITDA $55 - $60 1 $58 - $63 1 Net income $8 - $13 $10 - $15")
    assert values(records) == {("revenue", "FY2025", "UNSPECIFIED", 485e6, 495e6), ("ebitda", "FY2025", "ADJUSTED", 58e6, 63e6)}


def test_terminal_m_unit_applies_to_entire_ebitda_range():
    records = pipeline("2026 Guidance 2025 Adj EBITDA 2026 Expectation Consolidated Adjusted EBITDA of $350 - $370M")
    assert ("ebitda", "FY2026", "ADJUSTED", 350e6, 370e6) in values(records)


def test_reported_results_cannot_become_guidance_from_nearby_outlook():
    records = pipeline("Our cost outlook is stable. Fourth Quarter 2025 Consolidated Results Net sales increased $0.5 million, or 0.4%, to $128 million. Full year 2026 guidance: Net sales expected to be between $680 million and $700 million.")
    assert values(records) == {("revenue", "FY2026", "UNSPECIFIED", 680e6, 700e6)}


def test_second_half_eps_is_not_a_full_year_forecast():
    records = pipeline("Bunge expects full-year 2025 adjusted EPS in the range of approximately $7.30 to $7.60, which reflects an expected second half adjusted EPS in the range of $4.00 to $4.25.")
    assert values(records) == {("eps", "FY2025", "ADJUSTED", 7.3, 7.6)}


def test_loss_per_share_and_breakeven_bounds_remain_signed():
    records = pipeline("Full Year 2026 Outlook: Non-GAAP net loss per share of $(0.18) to $(0.16). Adjusted EBITDA is expected to be between breakeven and $10 million.")
    assert ("eps", "FY2026", "ADJUSTED", -.18, -.16) in values(records)
    assert ("ebitda", "FY2026", "ADJUSTED", 0, 10e6) in values(records)


def test_of_between_forecasts_keep_annual_metrics():
    records = pipeline("For the full year 2026, we expect: Revenue of between $7.182 - $7.198 billion. Adjusted free cash flow of between $3.9 - $4.1 billion.")
    assert {r.metric.value for r in records} == {"revenue", "fcf"}


def test_estimated_quarter_eps_retains_gaap_and_adjusted_basis():
    records = pipeline("The company estimates third quarter 2026 EPS on a GAAP basis of $1.18 to $1.21 and adjusted EPS of $1.35 to $1.38.")
    assert values(records) == {("eps", "Q3FY2026", "GAAP", 1.18, 1.21), ("eps", "Q3FY2026", "ADJUSTED", 1.35, 1.38)}


def test_presentation_reported_period_is_not_a_forecast():
    records = pipeline("Second Quarter 2025 Results. Full Year 2025 Guidance. Second Quarter 2025 For the three and six months ended June 30, 2024, total GAAP revenue of $582,822 and $1,023,182, respectively, have been adjusted to exclude RHB revenue.")
    assert not any(r.fiscal_period == "Q2FY2025" for r in records)


def test_product_only_forecast_cannot_become_company_total():
    records = pipeline("2026 Financial Guidance For the full year 2026, PTC anticipates: Total product revenue of $700 to $800 million, excluding Evrysdi royalty revenue and collaboration revenue.")
    assert not any(r.metric.value == "revenue" for r in records)


def test_forward_points_and_plain_footnotes():
    assert ("ebitda", "FY2025", "ADJUSTED", 5e6, 5e6) in values(pipeline("Expect positive Adjusted EBITDA of $5 million for full year 2025, increasing approximately $110 million over 2024."))
    assert ("revenue", "FY2025", "UNSPECIFIED", 370e6, 370e6) in values(pipeline("2025 Revenue Guidance: CareDx anticipates revenue of $370 million during 2025."))
    assert ("ebitda", "FY2025", "ADJUSTED", 86e6, 92e6) in values(pipeline("Full year 2025 outlook: Adjusted EBITDA 1 expected to be in the range of $86 million to $92 million."))


def test_reported_positive_ebitda_is_not_point_guidance():
    assert not pipeline("We reported Adjusted EBITDA of $5 million for full year 2025, an improvement over 2024.")


def test_revised_reconciliation_keeps_reported_and_adjusted_ebitda():
    records = pipeline("2026 GUIDANCE - PREVIOUS 2026 GUIDANCE - REVISED (In millions, except per share amounts) (Unaudited) Low High Low High EBITDA $435 $455 $458 $473 Total addbacks (deductions), net (70) (70) (73) (73) Adjusted EBITDA $365 $385 $385 $400")
    assert values(records) == {("ebitda", "FY2026", "UNSPECIFIED", 458e6, 473e6), ("ebitda", "FY2026", "ADJUSTED", 385e6, 400e6)}


def test_accompanying_point_after_decimal_revenue_and_inline_footnote():
    records = pipeline("Tempus expects full year 2025 revenue of approximately $1.26 billion for the consolidated business, which represents approximately 82% annual growth, and Adjusted EBITDA of $5 million for full year 2025.")
    assert ("ebitda", "FY2025", "ADJUSTED", 5e6, 5e6) in values(records)
    records = pipeline("Full year 2025 outlook: Adjusted EBITDA1 expected to be in the range of $86 million to $92 million.")
    assert ("ebitda", "FY2025", "ADJUSTED", 86e6, 92e6) in values(records)
