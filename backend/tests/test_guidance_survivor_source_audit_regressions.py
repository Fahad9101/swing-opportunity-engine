"""Source-transcribed semantic defects from strict-v4 replay at 24d77f2."""
from test_guidance_survivor_semantic_regressions import _doc
from app.domain.guidance_canonical_v1 import GuidanceFactRole, GuidanceScopeKind
from app.domain.soe_v1_1 import GuidanceAction, GuidanceMetric
from app.services.guidance_evidence_binder_v4 import GuidanceEvidenceBinder
from app.services.guidance_raw_canonical_extractor import extract_canonical_typed_guidance_facts
from app.services.guidance_semantic_ownership_service import normalize_typed_guidance_fact


def admitted(text):
    document = _doc(text)
    facts = [normalize_typed_guidance_fact(f, document)
             for f in extract_canonical_typed_guidance_facts(document).facts]
    return [f for f in facts if GuidanceEvidenceBinder().bind(f, document).accepted]


def test_raising_lower_endpoint_is_raise_not_cut():
    facts = admitted('Raised lower end of revenue guidance to range of $840 million to $860 million for 2025.')
    assert facts
    assert all(f.explicit_action is GuidanceAction.RAISE for f in facts)


def test_gaap_total_revenue_is_company_scope():
    facts = admitted('Full year 2026 guidance: GAAP total revenue in the range of $440 million to $445 million.')
    assert any(f.metric is GuidanceMetric.REVENUE and f.scope_kind is GuidanceScopeKind.COMPANY for f in facts)


def test_acquisition_arr_is_not_consolidated_revenue():
    assert not admitted("The company expects MANTL's annual recurring revenue under contract at December 31, 2025 to be approximately $60 million, which represents a year-over-year growth rate of over 30%.")


def test_prior_year_comparison_does_not_change_current_eps_role():
    facts = admitted('Full year 2026 guidance: adjusted operating margin of 20.0% to 20.9%, an increase of 60 to 150 bps versus prior year. EPS is expected to be $4.47 to $4.67, with adjusted EPS of $8.12 to $8.32.')
    eps = [f for f in facts if f.metric is GuidanceMetric.EPS]
    assert eps
    assert all(f.role is GuidanceFactRole.CURRENT for f in eps)


def test_actual_eps_before_outlook_is_not_forward_guidance():
    facts = admitted('Adjusted EPS, Diluted $0.25 $0.75 Outlook For Q1 2026, we expect: Revenue of between $1.532 billion and $1.536 billion.')
    assert not [f for f in facts if f.metric is GuidanceMetric.EPS]
    assert any(f.metric is GuidanceMetric.REVENUE for f in facts)


def test_actual_fcf_before_reconciliation_heading_is_not_guidance():
    facts = admitted('Free Cash Flow (Non-GAAP) $160,547 $(12,325) Exhibit 99.1 Reconciliation of GAAP Operating Income Guidance to Non-GAAP Operating Income Guidance for Full Year 2026')
    assert not [f for f in facts if f.metric is GuidanceMetric.FCF]


def test_percentage_ranges_preserve_both_endpoints():
    for value in ("63-64%", "63% and 64%", "63% to 64%"):
        facts = admitted(f"Full year 2026 guidance: gross margin is expected to be {value}.")
        margins = [f for f in facts if f.metric is GuidanceMetric.GROSS_MARGIN]
        assert margins
        assert all((f.low, f.high) == (63, 64) for f in margins)


def test_eps_decimal_before_punctuation_is_not_truncated():
    facts = admitted("For fiscal year 2027, we confirm our prior revenue guidance of $90 billion total revenue and raise our non-GAAP EPS guidance to $8.05, which is growth of 18%")
    eps = [f for f in facts if f.metric is GuidanceMetric.EPS]
    assert eps and all(f.low == f.high == 8.05 for f in eps)


def test_current_metric_after_previous_metric_comparison():
    for separator in (". ", " • ", " · "):
        text = "Full year 2026 guidance: Revenue of $447 million to $465 million, compared to the $420 million to $444 million range that was previously disclosed" + separator + "Adjusted EBITDA in the range of $43 million to $57 million."
        facts = [f for f in admitted(text) if f.metric is GuidanceMetric.EBITDA]
        assert facts
        assert all(f.role is GuidanceFactRole.CURRENT for f in facts)


def test_reaffirmed_prior_guidance_is_current():
    facts = admitted("For fiscal year 2027, we confirm our prior revenue guidance of $90 billion.")
    assert facts and all(f.role is GuidanceFactRole.CURRENT for f in facts)


def test_lowercase_product_name_in_parentheses_is_not_company_sales():
    for text in ("2026 Guidance: (valbenazine) Net Sales Guidance of $2.7 - $2.8 Billion", "(valbenazine) 2026 Net Sales Guidance Raised to $2.825 to $2.875 Billion"):
        facts = admitted(text)
        assert not [f for f in facts if f.scope_kind is GuidanceScopeKind.COMPANY]


def test_previous_year_preliminary_expectation_is_not_current_guidance():
    assert not admitted("Expects Full Year 2025 Revenue of Approximately $380 Million")


def test_historical_withdrawal_is_not_current_action():
    facts = admitted("our prior decision to withdraw our revenue guidance for fiscal 2023")
    assert not [f for f in facts if f.role is GuidanceFactRole.CURRENT]


def test_comparator_quarter_is_not_guidance_period():
    facts = admitted("Quarterly Outlook: Sales expected to be $465 - $485 million; foreign exchange anticipated to be a tailwind of 2 percent compared to the first quarter of fiscal 2025 • Adjusted EPS is expected to be $0.20 - $0.30")
    assert not [f for f in facts if f.fiscal_period == "Q1FY2025"]


def test_revenue_basis_does_not_leak_from_adjusted_ebitda():
    facts = admitted("Full year 2026 revenue and adjusted EBITDA guidance reaffirmed.")
    assert all(f.accounting_basis == "UNSPECIFIED" for f in facts if f.metric is GuidanceMetric.REVENUE)


def test_annual_guidance_not_duplicated_as_result_quarter():
    facts = admitted("Second quarter 2025 results. Financial Outlook For the year ending December 31, 2025, Example expects: • Revenue in the range of $235 million to $241 million • Adjusted EBITDA loss in the range of $9 million to $5 million. We have not provided an outlook for net loss (GAAP).")
    assert any(f.fiscal_period == "FY2025" for f in facts)
    assert not [f for f in facts if f.fiscal_period == "Q2FY2025"]


def test_annual_outlook_not_assigned_to_quarter_from_comparator():
    facts = admitted("Outlook The Company's expectations for the second quarter of fiscal 2026 and the full year are as follows: Quarterly Outlook: • Sales expected to be $500 - $520 million; foreign exchange anticipated to be a tailwind of 2 percent compared to the second quarter of fiscal 2025 • Adjusted EPS is expected to be $0.30 - $0.40 Annual Outlook: • Sales expected to be $2.100 - $2.170 billion • Adjusted EPS is expected to be $1.35 - $1.65")
    assert not [f for f in facts if f.low == 1.35 and f.fiscal_period != "FY2026"]
    assert not [f for f in facts if f.fiscal_period == "Q2FY2025"]


def test_split_source_numeric_fragment_is_not_admitted():
    facts = admitted("2026 Annual Guidance: Total revenue of $21\n8 million to $222 million. Non-GAAP gross margin of 80% to 81%.")
    assert not [f for f in facts if f.metric is GuidanceMetric.REVENUE and f.low == 21]


def test_raise_action_does_not_borrow_following_reaffirmation():
    facts = admitted("The company is raising fiscal year 2026 guidance for Revenue, and reiterating guidance for adjusted EBITDA.")
    revenue = [f for f in facts if f.metric is GuidanceMetric.REVENUE]
    assert revenue and all(f.explicit_action is GuidanceAction.RAISE for f in revenue)


def test_recently_increased_forecast_is_reaffirmed_today():
    facts = admitted("The company re-affirms its recently increased 2026 Adjusted EBITDA guidance of $170 million to $190 million.")
    assert facts and all(f.explicit_action is GuidanceAction.REAFFIRM for f in facts)


def test_actual_exceeding_prior_guidance_is_not_new_guidance():
    assert not admitted("Exceeded 2025 guidance with full-year revenue of $344 million")
    assert not admitted("Full-year 2025 revenue of $332 million, an increase of 51% compared to 2024 and above previously reported guidance")


def test_historical_quarter_bullet_does_not_borrow_adjacent_guidance():
    facts = admitted("2026 revenue guidance increased to $120 million ● Q1 2026 fully diluted GAAP EPS of $0.05, non-GAAP fully diluted EPS of $0.14, and Adjusted EBITDA of $5.7 million")
    assert not [f for f in facts if f.metric is GuidanceMetric.EBITDA]


def test_explicit_year_metric_footnote_does_not_inherit_prior_quarter():
    facts = admitted("During the first quarter of 2026 • Obtained authorization to repurchase shares • Announced 2026 Adjusted EBITDA (2) guidance range of $205 million to 225 million, representing projected growth of over 20%.")
    assert not [f for f in facts if f.fiscal_period == "Q1FY2026"]


def test_relative_quarter_prior_range_does_not_inherit_following_year():
    facts = admitted("The Company expects adjusted EBITDA of approximately $135 million this quarter relative to its prior adjusted EBITDA guidance range of $120 million to $125 million. The Company has also increased its full year 2025 guidance.")
    assert not [f for f in facts if f.low == 120 and f.fiscal_period == "FY2025"]


def test_unsupported_currency_not_downgraded_to_qualitative_guidance():
    assert not admitted("We continue to maintain our full-year 2026 revenue guidance in the range of RMB 8.20 billion to RMB 8.80 billion.")


def test_compound_run_and_maintain_is_not_a_reaffirmation():
    assert not admitted("Fiscal year 2026 guidance. Revenue mix shifted toward run-and-maintain and callout activity relative to the prior-year period.")


def test_enumerated_risk_subject_does_not_own_other_metric():
    assert not admitted("2026 guidance risks include (iv) our ability to maintain strong profitability levels, (v) our net leverage ratio and free cash flow, (vi) our strategic plans.")


def test_result_growth_headline_is_not_qualitative_guidance():
    assert not admitted("Reports third quarter 2025 results. Continued Strong Orders and Revenue Growth Headline Multiple Performance Records Reaffirms 2025 Full Year Outlook and Introduces 2026 Outlook")


def test_expectation_does_not_assert_initiation():
    facts = admitted("The Company continues to expect full year 2026 adjusted EBITDA of $29 million to $33 million.")
    assert facts and all(f.explicit_action is not GuidanceAction.INITIATE for f in facts)


def test_previous_completed_year_preliminary_outlook_is_not_current():
    facts = admitted("Updated 2025 Revenue Outlook to $885 to $900 Million. The 2025 revenue outlook included in this press release is preliminary. Actual results are subject to audit. We expect 2026 revenue of $1,080 to $1,175 million.")
    assert not [f for f in facts if f.fiscal_period == "FY2025" and f.role is GuidanceFactRole.CURRENT]
    assert any(f.fiscal_period == "FY2026" for f in facts)


def test_page_fragment_preserves_source_prior_guidance_ownership():
    text = "2026 Full Year Guidance Update. This compares to the previous guidance range of revenue between $925 and $975\nmillion, and adjusted EBITDA between $115 and $135 million. The Company reiterates its full year free cash flow guidance."
    facts = admitted(text)
    assert not [f for f in facts if f.metric is GuidanceMetric.EBITDA and f.role is GuidanceFactRole.CURRENT]


def test_quoted_range_high_endpoint_does_not_become_prior_point():
    facts = admitted("Anticipate full year 2026 revenue slightly above high end of previously stated guidance range of $587.5 million provided in October 2025.")
    assert not [f for f in facts if f.low == f.high == 587.5]
