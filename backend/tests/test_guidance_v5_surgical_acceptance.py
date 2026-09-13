from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from app.domain.guidance_canonical_v1 import GuidanceFactRole, GuidanceScopeKind
from app.domain.soe_v1_1 import SourceDocument
from app.services.guidance_raw_canonical_extractor import extract_canonical_typed_guidance_facts

TS = datetime(2026, 8, 15, tzinfo=UTC)


def _doc(ticker: str, text: str) -> SourceDocument:
    digest = hashlib.sha256(text.encode()).hexdigest()
    return SourceDocument(
        document_id=f"surgical-{ticker}-{digest[:10]}", rules_hash="surgical", ticker=ticker,
        cik="0000000001", accession="0000000001-26-000001", form="8-K",
        source_url=f"https://www.sec.gov/Archives/edgar/data/1/{ticker.lower()}.htm",
        source_timestamp=TS, fetched_at=TS, stale=False, content_hash=digest,
        content_type="text/plain", content=text,
    )


def test_reaffirmed_current_value_not_demoted_by_previous_update_date():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "ROLE",
        "2026 Outlook. The company is reaffirming its full year 2026 outlook, which was previously updated on May 7, 2026. "
        "The Company expects full year revenue between $130 million and $150 million.",
    ))
    revenue = [f for f in ex.facts if f.metric.value == "revenue" and f.low == 130.0]
    assert revenue and all(f.role is GuidanceFactRole.CURRENT for f in revenue)


def test_branded_net_sales_is_product_scope():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "BRAND",
        "We have raised our 2026 ARCALYST net sales guidance to between $980 million and $995 million.",
    ))
    revenue = [f for f in ex.facts if f.metric.value == "revenue"]
    assert revenue and all(f.scope_kind is GuidanceScopeKind.PRODUCT for f in revenue)


def test_unscaled_range_endpoint_shadow_is_suppressed():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "SCALE2",
        "For full year 2026, we are raising our revenue guidance to between $8.150 – $8.158 billion. "
        "Full year 2026 revenue guidance is $8.150 billion to $8.158 billion.",
    ))
    revenue = [f for f in ex.facts if f.metric.value == "revenue"]
    assert all(not (f.unit.value == "USD" and f.low == f.high == 8.15) for f in revenue)


def test_yoy_result_tail_is_historical_not_forward_guidance():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "ACTUALTAIL",
        "Adjusted EBITDA was $102.6 million, up 11.5% year-over-year. Raising 2025 Guidance. "
        "Full-year 2025 Adjusted EBITDA guidance is $470 million to $495 million.",
    ))
    ebitda = [f for f in ex.facts if f.metric.value == "ebitda"]
    assert all(not (f.low == f.high == 102.6) for f in ebitda)
    assert any((f.low, f.high) == (470.0, 495.0) for f in ebitda)


def test_compact_suffix_ranges_bind_to_their_own_metric():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "COMPACT",
        "Raised full-year 2025 guidance to: $452 - $458 million revenue; $138.5 - $141.5 million Adjusted EBITDA.",
    ))
    rev = [f for f in ex.facts if f.metric.value == "revenue"]
    ebitda = [f for f in ex.facts if f.metric.value == "ebitda"]
    assert any((f.low, f.high) == (452.0, 458.0) for f in rev)
    assert any((f.low, f.high) == (138.5, 141.5) for f in ebitda)
    assert all((f.low, f.high) != (138.5, 141.5) for f in rev)


def test_breakeven_range_preserves_zero_lower_bound():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "BREAKEVEN",
        "Full year 2025 guidance: Adjusted EBITDA is expected to be between breakeven and $10 million.",
    ))
    ebitda = [f for f in ex.facts if f.metric.value == "ebitda"]
    assert any((f.low, f.high) == (0.0, 10.0) for f in ebitda)


def test_adjusted_gaap_eps_contradiction_is_rejected():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "BASIS",
        "FY 2026 Guidance. Affirms Adjusted FY 2026 GAAP EPS guidance of at least $9.00; "
        "while revising GAAP EPS guidance to at least $8.36.",
    ))
    eps = [f for f in ex.facts if f.metric.value == "eps"]
    assert all(not (f.accounting_basis == "GAAP" and f.low == 9.0) for f in eps)
    assert any(item["reason"] == "ambiguous_accounting_basis" for item in ex.rejected_candidates)



def test_same_sentence_value_wins_over_later_metric_value_v5():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "HPELIKE",
        "Fiscal 2026 Full Year Outlook. HPE is raising its free cash flow guidance and now expects free cash flow to be at least $3.5 billion. The company had expected to generate at least $3.00 in non-GAAP diluted net EPS and more than $3.5 billion in free cash flow by FY28.",
    ))
    fcf = [f for f in ex.facts if f.metric.value == "fcf"]
    assert any(f.fiscal_period == "FY2026" and f.low == 3.5 for f in fcf)
    assert not any(f.low == 3.0 and f.unit.value == "USD" for f in fcf)


def test_heading_only_full_year_period_inheritance_v5():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "ZETALIKE",
        "Increasing 2026 Guidance. Full Year 2026 • Increasing revenue guidance to a range of $1,811 million to $1,824 million. • Increasing free cash flow guidance to a range of $254.8 million to $255.8 million, up $20.3 million at the midpoint from the prior guidance of $235.0 million.",
    ))
    fcf = [f for f in ex.facts if f.metric.value == "fcf" and f.fiscal_period == "FY2026"]
    assert any((f.low, f.high) == (254.8, 255.8) for f in fcf)


def test_following_outlook_heading_does_not_steal_prior_sentence_v5():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "HPEPERIOD",
        "Fiscal 2026 Full Year Outlook. HPE is raising its free cash flow guidance and now expects free cash flow to be at least $3.75 billion. Fiscal 2027 Outlook Framework. The company expects revenue growth of 8% to 12%.",
    ))
    fcf = [f for f in ex.facts if f.metric.value == "fcf"]
    assert any(f.fiscal_period == "FY2026" and f.low == 3.75 for f in fcf)
    assert not any(f.fiscal_period == "FY2027" and f.low == 3.75 for f in fcf)


def test_historical_result_before_raising_guidance_heading_is_rejected_v5():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "SPXCLIKE",
        "Adjusted EBITDA of $102.6 million, up 11.5% Raising 2025 Guidance. We are raising our full-year 2025 guidance for Adjusted EBITDA to a range of $470 to $495 million.",
    ))
    ebitda = [f for f in ex.facts if f.metric.value == "ebitda" and f.fiscal_period == "FY2025"]
    assert any((f.low, f.high) == (470.0, 495.0) for f in ebitda)
    assert not any(f.low == 102.6 and f.high == 102.6 for f in ebitda)


def test_guidance_delta_is_not_misread_as_absolute_range_v5():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "ZETADELTA",
        "Increasing full year 2026 revenue guidance by $33 million to $1,818 million at the midpoint, up from prior guidance of $1,785 million reflecting Y/Y growth of 39%.",
    ))
    revenue = [f for f in ex.facts if f.metric.value == "revenue"]
    assert not any(f.low == 33.0 and f.high == 1818.0 for f in revenue)



def test_cross_sentence_eps_value_cannot_bind_to_fcf_v6():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "HPECROSS",
        "Fiscal 2026 Full Year Outlook. HPE is raising its free cash flow guidance and now expects free cash flow to be at least $3.5 billion. The updated FY26 outlook ranges for non-GAAP diluted net EPS and free cash flow are higher than projected. The company had expected to generate at least $3.00 in non-GAAP diluted net EPS.",
    ))
    fcf = [f for f in ex.facts if f.metric.value == "fcf"]
    assert any(f.fiscal_period == "FY2026" and f.low == 3.5 for f in fcf), [(f.fiscal_period, f.low, f.high, f.unit.value, f.explicit_action.value) for f in fcf]
    assert not any(f.low == 3.0 for f in fcf)


def test_following_fy27_heading_cannot_capture_fy26_fcf_v6():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "HPEFOLLOW",
        "Fiscal 2026 Full Year Outlook. HPE is raising its free cash flow guidance and now expects free cash flow to be at least $3.75 billion. Fiscal 2027 Outlook Framework. The company is raising its growth framework for FY27 and expects free cash flow to be at least $5.0 billion.",
    ))
    fcf = [f for f in ex.facts if f.metric.value == "fcf"]
    assert any(f.fiscal_period == "FY2026" and f.low == 3.75 for f in fcf), [(f.fiscal_period, f.low, f.high, f.unit.value, f.explicit_action.value) for f in fcf]
    assert not any(f.fiscal_period == "FY2027" and f.low == 3.75 for f in fcf)


def test_money_metric_margin_percent_is_not_metric_growth_v6():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "ZETAMARGIN",
        "Full Year 2026. Increasing free cash flow guidance to a range of $254.8 million to $255.8 million, up $20.3 million at the midpoint from prior guidance of $235.0 million. The revised guidance represents year-over-year growth of 55% and a free cash flow margin of 14.0% to 14.1%.",
    ))
    fcf = [f for f in ex.facts if f.metric.value == "fcf"]
    assert any((f.low, f.high) == (254.8, 255.8) for f in fcf)
    assert not any(f.unit.value == "PERCENT" and f.low == 14.0 for f in fcf)


def test_long_lookback_midpoint_delta_is_not_revenue_level_v6():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "ZETADELTA2",
        "After raising the midpoint of our 2026 revenue guidance last quarter by $25 million, we are again raising it by $30 million, representing growth of 37%.",
    ))
    revenue = [f for f in ex.facts if f.metric.value == "revenue"]
    assert not any(f.low in {25.0, 30.0} for f in revenue)



def test_nested_fiscal_year_does_not_steal_quarter_heading_v9():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "JBLQ",
        "Second Quarter of Fiscal Year 2026 Outlook: Net revenue $7.5 billion to $8.0 billion.",
    ))
    revenue = [f for f in ex.facts if f.metric.value == "revenue"]
    assert any(f.fiscal_period == "Q2FY2026" and f.low == 7.5 for f in revenue)
    assert not any(f.fiscal_period == "FY2026" and f.low == 7.5 for f in revenue)


def test_direct_year_metric_guidance_beats_later_results_period_v9():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "CORTY",
        "First quarter financial results were strong. We are reiterating our 2025 revenue guidance of $900 to $950 million. First quarter 2025 revenue was $157.2 million.",
    ))
    revenue = [f for f in ex.facts if f.metric.value == "revenue" and f.low == 900.0]
    assert any(f.fiscal_period == "FY2025" for f in revenue)
    assert not any(f.fiscal_period.startswith("Q1") for f in revenue)


def test_strict_heading_recovery_applies_to_initiated_guidance_v9():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "PWRY",
        "Full Year 2026 Guidance. Quanta expects EBITDA to range between $3.09 billion and $3.25 billion and adjusted EBITDA to range between $3.34 billion and $3.50 billion.",
    ))
    ebitda = [f for f in ex.facts if f.metric.value == "ebitda"]
    assert any(f.fiscal_period == "FY2026" and f.low == 3.34 and f.high == 3.50 for f in ebitda)


def test_quarter_ending_with_comma_is_authoritative_v9():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "SHAKQ",
        "For the Fourth Quarter, ending December 31, 2025, the Company continues to expect total revenue of $406 million to $412 million.",
    ))
    revenue = [f for f in ex.facts if f.metric.value == "revenue"]
    assert any(f.fiscal_period == "Q4FY2025" and f.low == 406.0 for f in revenue)


def test_direct_margin_percentage_is_absolute_level_v9():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "DXCMM",
        "Full Year 2025 Guidance. Non-GAAP Gross Profit Margin of approximately 62%. The reduction relative to prior guidance reflects supply dynamics.",
    ))
    margins = [f for f in ex.facts if f.metric.value == "gross_margin"]
    assert any(f.fiscal_period == "FY2025" and f.value_kind.value == "ABSOLUTE_LEVEL" for f in margins)



def test_direct_guidance_year_overrides_preceding_results_year_v12():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "ATROV12",
        "Full year 2024 preliminary unaudited revenue was approximately $796 million. Initial 2025 revenue guidance established at $820 million to $860 million.",
    ))
    rev = [f for f in ex.facts if f.metric.value == "revenue" and f.low == 820.0]
    assert rev
    assert all(f.fiscal_period == "FY2025" for f in rev), [(f.fiscal_period, f.low, f.high) for f in rev]


def test_results_quarter_cannot_steal_direct_guidance_year_v12():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "CORTV12",
        "Revenue of $157.2 million, compared to $146.8 million in first quarter 2024. Reiterated 2025 revenue guidance of $900 to $950 million.",
    ))
    rev = [f for f in ex.facts if f.metric.value == "revenue" and f.low == 900.0]
    assert rev
    assert all(f.fiscal_period == "FY2025" for f in rev), [(f.fiscal_period, f.low, f.high) for f in rev]


def test_compact_revenue_range_cannot_bind_to_ebitda_v12():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "KRMNV12",
        "Raised full-year 2025 guidance to: $452 - $458 million revenue: 32% YoY increase to midpoint $138.5 - $141.5 million adjusted EBITDA.",
    ))
    ebitda = [f for f in ex.facts if f.metric.value == "ebitda"]
    assert any((f.low, f.high) == (138.5, 141.5) for f in ebitda)
    assert not any((f.low, f.high) == (452.0, 458.0) for f in ebitda)


def test_actual_eps_before_new_quarter_outlook_heading_does_not_inherit_quarter_v12():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "JBLV12",
        "Fiscal Year 2025 Outlook: Core diluted earnings per share (Non-GAAP): $9.75 First Quarter of Fiscal Year 2026 Outlook: Net revenue $7.7 billion to $8.3 billion.",
    ))
    eps = [f for f in ex.facts if f.metric.value == "eps" and f.low == 9.75]
    assert not any(f.fiscal_period == "Q1FY2026" for f in eps)


def test_presentation_footer_is_not_guidance_period_v12():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "FRPTV12",
        "2027 Targets: Adjusted Gross Margin Target 48% Q3 2025 Earnings Presentation 26.",
    ))
    margins = [f for f in ex.facts if f.metric.value == "gross_margin" and f.low == 0.48]
    assert not any(f.fiscal_period == "Q3FY2025" for f in margins)



def test_direct_full_year_phrase_does_not_steal_later_quarter_period_v13():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "ALKTV13",
        "2025 revenue guidance remains $443 million to $447 million. Second Quarter 2025 Outlook: revenue $109 million to $110.5 million.",
    ))
    quarter = [f for f in ex.facts if f.metric.value == "revenue" and f.low == 109.0]
    assert quarter
    assert all(f.fiscal_period == "Q2FY2025" for f in quarter), [(f.fiscal_period, f.low, f.high) for f in quarter]


def test_direct_fy26_phrase_does_not_steal_later_fy27_period_v13():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "HPEV13",
        "Fiscal 2026 revenue guidance is $11.5 billion to $12.1 billion. Fiscal 2027 Outlook: revenue is expected to be $12.2 billion.",
    ))
    forward = [f for f in ex.facts if f.metric.value == "revenue" and f.low == 12.2]
    assert forward
    assert all(f.fiscal_period == "FY2027" for f in forward), [(f.fiscal_period, f.low, f.high) for f in forward]


def test_direct_full_year_phrase_does_not_steal_q2fy26_period_v13():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "ZETAV13",
        "2026 revenue guidance is $1.779 billion to $1.792 billion. Q2 FY2026 Outlook: revenue $419 million to $422 million.",
    ))
    quarter = [f for f in ex.facts if f.metric.value == "revenue" and f.low == 419.0]
    assert quarter
    assert all(f.fiscal_period == "Q2FY2026" for f in quarter), [(f.fiscal_period, f.low, f.high) for f in quarter]



def test_compact_ebitda_value_before_full_year_guidance_heading_is_retained_v15():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "STRLV15",
        "Net Income of $222 million to $239 million • Diluted EPS of $7.15 to $7.65 • EBITDA (1) of $381 million to $403 million Full Year 2025 Adjusted Guidance",
    ))
    ebitda = [f for f in ex.facts if f.metric.value == "ebitda" and f.low == 381.0 and f.high == 403.0]
    assert ebitda, ex.rejected_candidates
    assert all(f.fiscal_period == "FY2025" for f in ebitda), [(f.fiscal_period, f.low, f.high) for f in ebitda]


def test_compact_forward_binding_does_not_steal_prior_investment_value_v15():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "WABV15",
        "Committed $3.5 billion to investments expected to create immediate value, with higher adjusted EBITDA margins and increased adjusted EPS in the first year.",
    ))
    eps = [f for f in ex.facts if f.metric.value == "eps"]
    assert not any(f.low == 3.5 for f in eps), [(f.fiscal_period, f.low, f.high) for f in eps]


def test_compact_forward_binding_rejects_mismatched_scales_v15():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "BADSCV15",
        "EBITDA of $381 million to $403 billion Full Year 2025 Adjusted Guidance",
    ))
    ebitda = [f for f in ex.facts if f.metric.value == "ebitda"]
    assert not any(f.low == 381.0 and f.high == 403.0 for f in ebitda)



def test_sentence_separated_full_year_heading_is_not_compact_owned_v16():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "STRLNEG16",
        "EBITDA of $381 million to $403 million. Full Year 2025 Adjusted Guidance: Revenue $1.0 billion to $1.1 billion.",
    ))
    ebitda = [f for f in ex.facts if f.metric.value == "ebitda" and f.low == 381.0 and f.high == 403.0]
    assert not any(f.fiscal_period == "FY2025" for f in ebitda), [(f.fiscal_period, f.low, f.high) for f in ebitda]



def test_eps_value_explicitly_owned_after_value_cannot_be_fcf_v19():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "HPE19",
        "Fiscal 2026 Full Year Outlook. Free cash flow guidance is higher than prior expectations. The company had expected to generate at least $3.00 in non-GAAP diluted net EPS.",
    ))
    fcf = [f for f in ex.facts if f.metric.value == "fcf"]
    assert not any(f.low == 3.0 for f in fcf), [(f.low, f.high, f.fiscal_period) for f in fcf]


def test_compact_revenue_then_eps_keeps_each_own_value_v19():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "STRL19",
        "Full Year 2025 Guidance Revenue of $2.00 to $2.15 billion EPS of $6.75 to $7.25.",
    ))
    revenue = [f for f in ex.facts if f.metric.value == "revenue"]
    eps = [f for f in ex.facts if f.metric.value == "eps"]
    assert any((f.low, f.high) == (2.0, 2.15) for f in revenue), [(f.low, f.high) for f in revenue]
    # The ownership invariant is negative: the revenue range must never become EPS.
    # Standalone dollar EPS ranges may fail later per-share/unit normalization, which
    # is orthogonal to this regression and already covered by existing EPS tests.
    assert not any((f.low, f.high) == (2.0, 2.15) for f in eps), [(f.low, f.high) for f in eps]


def test_quarter_token_digits_cannot_start_money_range_v19():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "IOVA19",
        "2025 guidance follows prior results. Total Product Revenue of $73.7M in 4Q24 and $164.1M in FY24.",
    ))
    revenue = [f for f in ex.facts if f.metric.value == "revenue"]
    assert not any(f.low == 24.0 and f.high == 164.1 for f in revenue), [(f.low, f.high, f.fiscal_period) for f in revenue]


def test_following_conference_call_quarter_cannot_steal_annual_eps_v19():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "WAB19",
        "Adjusted EPS guidance is $8.35 to $8.95. First Quarter 2025 Conference Call.",
    ))
    eps = [f for f in ex.facts if f.metric.value == "eps" and f.low == 8.35]
    assert not any(f.fiscal_period == "Q1FY2025" for f in eps), [(f.low, f.high, f.fiscal_period) for f in eps]


def test_reference_quarter_cannot_own_unchanged_guidance_value_v19():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "ZETA19",
        "Revenue guidance remains $1,289 million to $1,292 million, unchanged from the third quarter 2025 earnings release.",
    ))
    revenue = [f for f in ex.facts if f.metric.value == "revenue" and f.low == 1289.0]
    assert not any(f.fiscal_period == "Q3FY2025" for f in revenue), [(f.low, f.high, f.fiscal_period) for f in revenue]


def test_flattened_current_q1_and_fy_columns_fail_closed_v19():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "ATI19",
        "Current Guidance Q1 2026 Fiscal Year 2026 Adjusted EBITDA (b) $216M - $226M.",
    ))
    ebitda = [f for f in ex.facts if f.metric.value == "ebitda"]
    assert not any((f.low, f.high) == (216.0, 226.0) for f in ebitda), [(f.low, f.high, f.fiscal_period) for f in ebitda]


def test_quarter_guidance_with_growth_tail_remains_forward_v19():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "U19",
        "Q2 2026 Guidance • Strategic Revenue of $455 million to $465 million, up 29% - 32% year-over-year.",
    ))
    revenue = [f for f in ex.facts if f.metric.value == "revenue"]
    assert any((f.low, f.high) == (455.0, 465.0) for f in revenue), [(f.low, f.high, f.fiscal_period) for f in revenue]



def test_annual_outlook_section_owns_fcf_before_trailing_q3_reference_v22():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "CLSV22",
        "2025 Annual Outlook Update • Non-GAAP free cash flow of $400 million (previous outlook $350 million). Our Q3 2025 Guidance and 2025 Annual Outlook Update assume current conditions.",
    ))
    fcf = [f for f in ex.facts if f.metric.value == "fcf"]
    current = [f for f in fcf if f.role.value == "CURRENT" and f.low == 400.0]
    assert current, [(f.role.value, f.fiscal_period, f.low, f.high) for f in fcf]
    assert all(f.fiscal_period == "FY2025" for f in current), [(f.fiscal_period, f.low, f.high) for f in current]
    # The population dossier already contains the quoted-prior $350M fact; this
    # focused regression tests the lost current fact and period ownership only.
    assert not any(f.fiscal_period == "Q3FY2025" and f.low in {350.0, 400.0} for f in fcf)



def test_explicit_annual_heading_can_own_late_fcf_bullet_v24():
    filler = " assumptions" * 42
    ex = extract_canonical_typed_guidance_facts(_doc(
        "CLSV24",
        "2025 Annual Outlook Update" + filler + " non-GAAP free cash flow outlook of $400 million.",
    ))
    fcf = [f for f in ex.facts if f.metric.value == "fcf" and f.low == 400.0]
    assert fcf, ex.rejected_candidates
    assert all(f.fiscal_period == "FY2025" for f in fcf), [(f.fiscal_period, f.low, f.high) for f in fcf]



def test_document_annual_heading_recovers_late_current_prior_fcf_pair_v26():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "CLSV26",
        "2025 Annual Outlook Update\n"
        "Revenue outlook of $11.55 billion (previous outlook $10.85 billion)\n"
        "Adjusted operating margin outlook of 7.4% (previous outlook 7.2%)\n"
        "Adjusted EPS outlook of $5.50 (previous outlook $5.00)\n"
        "Tariff assumptions remain unchanged\n"
        "Demand assumptions remain unchanged\n"
        "Supply assumptions remain unchanged\n"
        "Tax assumptions remain unchanged\n"
        "Macro assumptions remain unchanged\n"
        "Non-GAAP free cash flow outlook of $400 million (previous outlook $350 million)\n",
    ))
    fcf = [f for f in ex.facts if f.metric.value == "fcf" and f.low == 400.0]
    assert fcf, ex.rejected_candidates
    assert all(f.fiscal_period == "FY2025" for f in fcf), [(f.fiscal_period, f.low, f.high) for f in fcf]


def test_intervening_quarter_heading_blocks_annual_prior_pair_recovery_v26():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "CLSV26NEG",
        "2025 Annual Outlook Update\n"
        "Revenue outlook of $11.55 billion (previous outlook $10.85 billion)\n"
        "Q3 2025 Guidance\n"
        "Non-GAAP free cash flow outlook of $400 million (previous outlook $350 million)\n",
    ))
    fcf = [f for f in ex.facts if f.metric.value == "fcf" and f.low == 400.0]
    assert not any(f.fiscal_period == "FY2025" for f in fcf), [(f.fiscal_period, f.low, f.high) for f in fcf]



def test_flattened_prior_marker_from_earlier_metric_does_not_demote_fcf_current_v28():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "CLSV28",
        "2025 Annual Outlook Update\n"
        "Revenue outlook of $11.55 billion (previous outlook $10.85 billion)\n"
        "Adjusted operating margin outlook of 7.4% (previous outlook 7.2%)\n"
        "Adjusted EPS outlook of $5.50 (previous outlook $5.00)\n"
        "Tariff assumptions remain unchanged\n"
        "Demand assumptions remain unchanged\n"
        "Supply assumptions remain unchanged\n"
        "Tax assumptions remain unchanged\n"
        "Macro assumptions remain unchanged\n"
        "Non-GAAP free cash flow outlook of $400 million (previous outlook $350 million)\n",
    ))
    fcf400 = [f for f in ex.facts if f.metric.value == "fcf" and f.low == 400.0]
    assert fcf400, ex.rejected_candidates
    assert any(f.role.value == "CURRENT" and f.fiscal_period == "FY2025" for f in fcf400), [
        (f.role.value, f.fiscal_period, f.low, f.high) for f in fcf400
    ]
    assert not any(f.role.value == "QUOTED_PRIOR" for f in fcf400), [
        (f.role.value, f.fiscal_period, f.low, f.high) for f in fcf400
    ]



def test_result_metric_cannot_cross_into_fresh_guidance_row_v29():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "KRMN29",
        "August 7, 2025 $115.1 million Revenue, up 35% YoY $35.3 million Adjusted EBITDA, up 29% YoY "
        "30.7% Adjusted EBITDA Margin $719 million Funded Backlog, up 36% YoY "
        "Raised full-year 2025 guidance to: $452 - $458 million revenue; "
        "$138.5 - $141.5 million Adjusted EBITDA.",
    ))
    ebitda = [f for f in ex.facts if f.metric.value == "ebitda"]
    assert any((f.low, f.high) == (138.5, 141.5) for f in ebitda), [(f.low, f.high, f.fiscal_period) for f in ebitda]
    assert not any((f.low, f.high) == (452.0, 458.0) for f in ebitda), [(f.low, f.high, f.fiscal_period) for f in ebitda]


def test_historical_eps_value_cannot_become_current_fcf_v29():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "HPEFCF29",
        "FY26 free cash flow guidance is higher than what HPE projected by FY28. "
        "The company had expected to generate at least $3.00 in non-GAAP diluted net EPS.",
    ))
    fcf = [f for f in ex.facts if f.metric.value == "fcf"]
    assert not any(f.low == 3.0 for f in fcf), [(f.low, f.high, f.fiscal_period) for f in fcf]


def test_eps_cannot_absorb_following_billion_scale_v29():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "HPEEPS29",
        "Fiscal 2025 guidance expected at least $3.00 in non-GAAP diluted net EPS and more than $3.5 billion in free cash flow.",
    ))
    eps = [f for f in ex.facts if f.metric.value == "eps"]
    assert not any(f.low == 3.5 for f in eps), [(f.low, f.high, f.fiscal_period) for f in eps]


def test_fiscal_year_first_quarter_outlook_binds_q1_v29():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "HPEQ129",
        "Fiscal 2026 First Quarter Outlook HPE estimates revenue to be in the range of $9.0 billion to $9.4 billion. "
        "HPE estimates GAAP diluted net EPS to be in the range of $0.09 to $0.13.",
    ))
    revenue = [f for f in ex.facts if f.metric.value == "revenue" and f.low == 9.0]
    eps = [f for f in ex.facts if f.metric.value == "eps" and f.low == 0.09]
    assert revenue and all(f.fiscal_period == "Q1FY2026" for f in revenue), [(f.fiscal_period, f.low) for f in revenue]
    assert eps and all(f.fiscal_period == "Q1FY2026" for f in eps), [(f.fiscal_period, f.low) for f in eps]


def test_compound_q2_and_fy_heading_keeps_q2_value_quarter_bound_v29():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "IOVA29",
        "Second Quarter 2026 and Full Year 2026 Guidance. "
        "Total product revenue guidance for 2Q26 is $86 million to $88 million and for FY26 is $350 million to $370 million.",
    ))
    q2 = [f for f in ex.facts if f.metric.value == "revenue" and f.low == 86.0]
    assert q2 and all(f.fiscal_period == "Q2FY2026" for f in q2), [(f.fiscal_period, f.low, f.high) for f in q2]


def test_record_financial_result_revenue_is_not_guidance_v29():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "HPEACT29",
        "HPE reports fiscal 2026 third quarter results. Record results and demand drive higher outlook for fiscal 2026 and fiscal 2027 - "
        "Record revenue of $12.2 billion, up 34% year-over-year. "
        "Third Quarter Fiscal 2026 Financial Results • Revenue: $12.2 billion, up 34% from the prior-year period.",
    ))
    revenue = [f for f in ex.facts if f.metric.value == "revenue"]
    assert not any(f.low == 12.2 for f in revenue), [(f.low, f.high, f.fiscal_period) for f in revenue]


def test_prior_quarter_reference_cannot_cross_fresh_annual_outlook_v29():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "ATRO29",
        "Reimbursements are expected to be received in the third quarter of 2026. "
        "2026 Outlook Astronics expects revenue to be $1.02 billion to $1.04 billion for the year.",
    ))
    annual = [f for f in ex.facts if f.metric.value == "revenue" and f.low == 1.02]
    assert not any(f.fiscal_period == "Q3FY2026" for f in annual), [(f.fiscal_period, f.low, f.high) for f in annual]


def test_growth_comparison_year_is_not_guidance_period_v29():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "FRPT29",
        "Full Year 2025 guidance: Net sales in the range of $1.12 billion to $1.15 billion, "
        "an increase of 15% to 18% from 2024, compared to previous guidance.",
    ))
    revenue = [f for f in ex.facts if f.metric.value == "revenue" and f.low == 1.12]
    assert not any(f.fiscal_period == "FY2024" for f in revenue), [(f.fiscal_period, f.low, f.high) for f in revenue]


def test_growth_yoy_row_cannot_absorb_neighbor_money_value_v29():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "FRPTTAB29",
        "2025 guidance Updated Previous ~13% 13 - 16% Net Sales Growth YoY $190 - $195M $190M - $210M Adjusted EBITDA.",
    ))
    revenue = [f for f in ex.facts if f.metric.value == "revenue"]
    assert not any((f.low, f.high) == (190.0, 195.0) for f in revenue), [(f.low, f.high, f.fiscal_period) for f in revenue]


def test_following_full_year_section_cannot_relabel_quarter_ebitda_v29():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "ZETA29",
        "Q2 2025 guidance: Increasing Adjusted EBITDA guidance to a range of $54.6 million to $55.2 million, "
        "up $500 thousand from prior guidance. The revised guidance represents an Adjusted EBITDA margin of 18.3% to 18.7%. "
        "Full Year 2025",
    ))
    ebitda = [f for f in ex.facts if f.metric.value == "ebitda" and f.low == 54.6]
    assert not any(f.fiscal_period == "FY2025" for f in ebitda), [(f.fiscal_period, f.low, f.high) for f in ebitda]



def test_previous_then_now_pair_survives_historical_crossing_guard_v30():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "PREVNOW30",
        "Fiscal 2026 Revenue guidance was previously expected at $480 million and is now expected at $500 million.",
    ))
    revenue = [f for f in ex.facts if f.metric.value == "revenue"]
    assert any(f.role.value == "CURRENT" and f.low == 500.0 for f in revenue), [(f.role.value, f.low) for f in revenue]
    assert any(f.role.value == "QUOTED_PRIOR" and f.low == 480.0 for f in revenue), [(f.role.value, f.low) for f in revenue]



def test_annual_guidance_survives_unrelated_earlier_quarter_results_v31():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "GEO31",
        "2Q26 Adjusted EBITDA increased 20% to $142.0 million. "
        "Guidance for FY26 Revenues of $2.95 billion to $3.05 billion.",
    ))
    revenue = [f for f in ex.facts if f.metric.value == "revenue" and f.low == 2.95]
    assert revenue and all(f.fiscal_period == "FY2026" for f in revenue), [(f.fiscal_period, f.low) for f in revenue]


def test_annual_eps_guidance_survives_prior_quarter_backlog_reference_v31():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "TPC31",
        "Backlog of $21.1 billion at the end of Q2 2025, up 102% Y/Y. "
        "Company increases 2025 EPS guidance: 2025 GAAP EPS guidance now $1.70 to $2.00.",
    ))
    eps = [f for f in ex.facts if f.metric.value == "eps" and f.low == 1.70]
    assert eps and all(f.fiscal_period == "FY2025" for f in eps), [(f.fiscal_period, f.low) for f in eps]


def test_prior_q3_reference_does_not_steal_fourth_quarter_guidance_v31():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "SHAK31",
        "Targets provided in its Q3 2025 shareholder letter. "
        "For the Fourth Quarter, ending December 31, 2025, the Company continues to expect total revenue of $406 million to $412 million.",
    ))
    revenue = [f for f in ex.facts if f.metric.value == "revenue" and f.low == 406.0]
    assert revenue and all(f.fiscal_period == "Q4FY2025" for f in revenue), [(f.fiscal_period, f.low) for f in revenue]


def test_plain_annual_guidance_is_not_rejected_by_later_section_period_v31():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "PLTR31",
        "We are raising our adjusted free cash flow guidance to between $1.6 billion and $1.8 billion. Full Year 2025",
    ))
    fcf = [f for f in ex.facts if f.metric.value == "fcf" and f.low == 1.6]
    assert fcf, ex.rejected_candidates



def test_strict_quarter_outlook_heading_carries_to_second_metric_v32():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "HPEQ132",
        "Fiscal 2026 First Quarter Outlook HPE estimates revenue to be in the range of $9.0 billion to $9.4 billion. "
        "HPE estimates GAAP diluted net EPS to be in the range of $0.09 to $0.13.",
    ))
    eps = [f for f in ex.facts if f.metric.value == "eps" and f.low == 0.09]
    assert eps and all(f.fiscal_period == "Q1FY2026" for f in eps), [(f.fiscal_period, f.low) for f in eps]


def test_competing_annual_heading_blocks_quarter_heading_carry_v32():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "HPEQ132NEG",
        "Fiscal 2026 First Quarter Outlook HPE estimates revenue to be $9.0 billion to $9.4 billion. "
        "Full Year 2026 Outlook. HPE estimates GAAP diluted net EPS to be $1.90 to $2.10.",
    ))
    eps = [f for f in ex.facts if f.metric.value == "eps" and f.low == 1.90]
    assert not any(f.fiscal_period == "Q1FY2026" for f in eps), [(f.fiscal_period, f.low) for f in eps]


def test_terminal_full_year_heading_recovers_directional_guidance_v32():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "PLTR32",
        "We are raising our adjusted free cash flow guidance to between $1.6 billion and $1.8 billion. Full Year 2025",
    ))
    fcf = [f for f in ex.facts if f.metric.value == "fcf" and f.low == 1.6]
    assert fcf and all(f.fiscal_period == "FY2025" for f in fcf), [(f.fiscal_period, f.low) for f in fcf]


def test_terminal_full_year_heading_does_not_recover_non_directional_actual_v32():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "PLTR32NEG",
        "Adjusted free cash flow was $1.6 billion. Full Year 2025",
    ))
    fcf = [f for f in ex.facts if f.metric.value == "fcf" and f.low == 1.6]
    assert not fcf, [(f.fiscal_period, f.low) for f in fcf]
