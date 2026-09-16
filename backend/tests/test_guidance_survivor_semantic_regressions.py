from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from app.domain.guidance_canonical_v1 import GuidanceFactRole, GuidancePeriodKind, GuidanceUnit
from app.domain.soe_v1_1 import GuidanceAction, GuidanceMetric, SourceDocument
from app.services.guidance_raw_canonical_extractor import extract_canonical_typed_guidance_facts
from app.services.guidance_raw_typed_extractor import _action


def _doc(text: str) -> SourceDocument:
    ts = datetime(2026, 9, 15, tzinfo=UTC)
    digest = hashlib.sha256(text.encode()).hexdigest()
    return SourceDocument(
        document_id=f"survivor-{digest[:12]}", rules_hash="candidate-hash", ticker="TEST",
        cik="0000000001", accession="0000000001-26-999994", form="8-K",
        filing_date=ts.date(), source_url="https://www.sec.gov/Archives/edgar/data/1/survivor.htm",
        source_timestamp=ts, fetched_at=ts, content_hash=digest, content_type="text/plain", content=text,
    )


def _facts(text: str, metric: GuidanceMetric):
    return [f for f in extract_canonical_typed_guidance_facts(_doc(text)).facts if f.metric is metric]


def test_mixed_scale_money_range_is_normalized_economically():
    facts = _facts("2026 Guidance: Total revenue expected between $980 million and $1 billion.", GuidanceMetric.REVENUE)
    assert any(f.low == 0.98 and f.high == 1.0 and f.unit is GuidanceUnit.USD_BILLION for f in facts)
    assert not any(f.low == f.high == 980 for f in facts)


def test_mixed_scale_directional_range_preserves_full_range():
    facts = _facts("2026 Guidance: The company raised total revenue guidance from a range of $900 million to $950 million to a range of $940 million to $1 billion.", GuidanceMetric.REVENUE)
    assert any(f.role is GuidanceFactRole.CURRENT and f.low == 0.94 and f.high == 1.0 and f.unit is GuidanceUnit.USD_BILLION for f in facts)


def test_bare_year_guidance_heading_owns_following_ebitda():
    facts = _facts("2026 Guidance: Revenue expected at $955 million to $970 million; Adjusted EBITDA projected at $213 million to $220 million.", GuidanceMetric.EBITDA)
    assert any(f.fiscal_period == "FY2026" and f.low == 213 and f.high == 220 for f in facts)
    assert not any(f.fiscal_period == "FY2025" for f in facts)


def test_full_year_heading_beats_trailing_versus_reference_year():
    facts = _facts("2025 Full Year Guidance: Adjusted EBITDA of $90 million to $100 million versus 2024 adjusted EBITDA.", GuidanceMetric.EBITDA)
    assert any(f.fiscal_period == "FY2025" and f.low == 90 and f.high == 100 for f in facts)
    assert not any(f.fiscal_period == "FY2024" for f in facts)


def test_flattened_multiple_guidance_version_columns_fail_closed():
    extraction = extract_canonical_typed_guidance_facts(_doc("2025 Revenue Guidance Initial Guidance Most Recent Guidance Current Guidance Total revenue $250 million to $260 million $260 million to $270 million $275 million to $280 million."))
    assert not [f for f in extraction.facts if f.metric is GuidanceMetric.REVENUE]
    assert any(r.get("reason") == "ambiguous_guidance_version_table" for r in extraction.rejected_candidates)


def test_split_money_digit_corruption_fails_closed():
    extraction = extract_canonical_typed_guidance_facts(_doc("2026 Annual Guidance: Total revenue of $21 8 million to $222 million."))
    assert not [f for f in extraction.facts if f.metric is GuidanceMetric.REVENUE]
    assert any(r.get("reason") == "split_money_token_corruption" for r in extraction.rejected_candidates)


def test_prior_revenue_marker_does_not_relabel_current_ebitda():
    facts = _facts("For the full year 2026, revenue is expected at $3.29 billion to $3.33 billion, up from our prior guidance range of approximately 25% to 26% growth; Adjusted EBITDA is expected to be $199 million to $201 million.", GuidanceMetric.EBITDA)
    assert any(f.role is GuidanceFactRole.CURRENT and f.fiscal_period == "FY2026" and f.low == 199 and f.high == 201 for f in facts)
    assert not any(f.role is GuidanceFactRole.QUOTED_PRIOR and f.low == 199 for f in facts)


def test_prior_revenue_marker_does_not_relabel_current_margin():
    facts = _facts("2026 Guidance: Total revenue is now $220 million versus prior guidance of $215 million; non-GAAP gross margin is expected to be 82%.", GuidanceMetric.GROSS_MARGIN)
    assert any(f.role is GuidanceFactRole.CURRENT and f.low == 82 for f in facts)
    assert not any(f.role is GuidanceFactRole.QUOTED_PRIOR and f.low == 82 for f in facts)


def test_local_full_year_phrase_overrides_stale_quarter_context():
    facts = _facts("Q1 2026 results. For the full year 2026, the company expects Adjusted EBITDA of $199 million to $201 million.", GuidanceMetric.EBITDA)
    assert any(f.period_kind is GuidancePeriodKind.FULL_YEAR and f.fiscal_period == "FY2026" for f in facts)
    assert not any(f.period_kind is GuidancePeriodKind.QUARTER for f in facts)


def test_increase_is_directional_only_when_guidance_owned():
    assert _action("growing demand is increasing our revenue growth") is GuidanceAction.NONE
    assert _action("the company is increasing full-year 2026 revenue guidance") is GuidanceAction.RAISE


def test_directional_action_deduplicates_generic_initiate_same_value():
    facts = _facts("The company raised FY 2026 total revenue guidance to $1.6 billion. The company expects FY 2026 total revenue of $1.6 billion.", GuidanceMetric.REVENUE)
    assert any(f.explicit_action is GuidanceAction.RAISE and f.low == 1.6 for f in facts)
    assert not any(f.explicit_action is GuidanceAction.INITIATE and f.low == 1.6 for f in facts)



def _normalize_all(text: str):
    from app.services.guidance_semantic_ownership_service import normalize_typed_guidance_fact
    document = _doc(text)
    extraction = extract_canonical_typed_guidance_facts(document)
    return [normalize_typed_guidance_fact(fact, document) for fact in extraction.facts]


def test_post_period_preliminary_expectation_is_actual_not_guidance():
    facts = _normalize_all("The Company expects 2024 revenue of approximately $8.35 billion, an increase of 17% compared with $7.12 billion in 2023.")
    revenue = [f for f in facts if f.metric is GuidanceMetric.REVENUE and f.fiscal_period == "FY2024"]
    assert revenue
    assert all(f.role is GuidanceFactRole.ACTUAL for f in revenue)


def test_parenthesized_adjusted_ebitda_loss_preserves_negative_sign():
    facts = _normalize_all("2026 Guidance: Adjusted EBITDA*: $(15) million - $0 million.")
    ebitda = [f for f in facts if f.metric is GuidanceMetric.EBITDA]
    assert ebitda
    assert any(f.low == -15 and f.high == 0 for f in ebitda)


def test_actual_table_cells_before_guidance_heading_fail_as_actual():
    facts = _normalize_all("Free cash flow (Non-GAAP) $4,791 $975 F 2026 GUIDANCE: Revenue $44 billion to $45 billion.")
    fcf = [f for f in facts if f.metric is GuidanceMetric.FCF and f.low is not None]
    assert fcf
    assert all(f.role is GuidanceFactRole.ACTUAL for f in fcf)


def test_actual_growth_bullet_point_is_not_forward_guidance():
    from app.services.guidance_semantic_ownership_service import normalize_typed_guidance_fact
    from test_guidance_semantic_ownership_audit_regressions import _fact

    text = "FY2026 results: Revenue of $9.3 billion, +12% year over year."
    document = _doc(text)
    # Standalone results need not be emitted by a guidance extractor.
    assert not extract_canonical_typed_guidance_facts(document).facts
    # If a candidate reaches normalization, its realized-growth evidence must
    # still exclude it from forward guidance.
    candidate = _fact(document, metric=GuidanceMetric.REVENUE, period="FY2026",
                      metric_text="Revenue", value_text="$9.3 billion",
                      low=9.3, high=9.3, unit=GuidanceUnit.USD_BILLION)
    assert normalize_typed_guidance_fact(candidate, document).role is GuidanceFactRole.ACTUAL


def test_annual_loss_guidance_before_quarter_heading_stays_current():
    facts = _normalize_all("Full year 2026 guidance: Revenue of $119 million to $123 million. "
                           "Adjusted EBITDA loss of $19 million to $23 million. "
                           "Third Quarter 2026 Guidance: Revenue of $26 million to $30 million.")
    ebitda = [f for f in facts if f.metric is GuidanceMetric.EBITDA]
    assert len(ebitda) == 1
    assert (ebitda[0].fiscal_period, ebitda[0].low, ebitda[0].high, ebitda[0].role) == (
        "FY2026", -23, -19, GuidanceFactRole.CURRENT)
