from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from app.domain.guidance_canonical_v1 import GuidanceFactRole, GuidanceScopeKind
from app.domain.soe_v1_1 import GuidanceAction, SourceDocument
from app.services.guidance_raw_canonical_extractor import extract_canonical_typed_guidance_facts


TS = datetime(2026, 8, 15, tzinfo=UTC)


def _document(ticker: str, text: str) -> SourceDocument:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return SourceDocument(
        document_id=f"canonical-{ticker}-{digest[:12]}",
        rules_hash="canonical-raw-test",
        ticker=ticker,
        cik="0000000001",
        accession="0000000001-26-000001",
        form="8-K",
        source_url=f"https://www.sec.gov/Archives/edgar/data/1/{ticker.lower()}.htm",
        source_timestamp=TS,
        fetched_at=TS,
        content_hash=digest,
        content_type="text/plain",
        content=text,
    )


def test_reversed_range_is_rejected_before_typed_model_construction():
    extraction = extract_canonical_typed_guidance_facts(
        _document("RANGE", "2026 Guidance. Adjusted EPS $2.50 to $2.10.")
    )

    assert not extraction.facts
    assert any(item["reason"] == "invalid_reversed_range" for item in extraction.rejected_candidates)


def test_directional_action_binds_only_to_owning_metric():
    extraction = extract_canonical_typed_guidance_facts(
        _document(
            "LOCAL",
            "2026 Guidance. The Company lowers revenue to $4.0 billion to $4.2 billion; "
            "adjusted EPS is expected to be $5.00 to $5.20.",
        )
    )

    revenue = next(fact for fact in extraction.facts if fact.metric.value == "revenue")
    eps = next(fact for fact in extraction.facts if fact.metric.value == "eps")

    assert revenue.explicit_action is GuidanceAction.LOWER
    assert eps.explicit_action is not GuidanceAction.LOWER


def test_directional_segment_action_is_never_inherited_past_another_metric():
    extraction = extract_canonical_typed_guidance_facts(
        _document(
            "MULTI",
            "Full-year 2026 guidance lowers total revenue to $8.0 billion to $8.4 billion and "
            "adjusted EBITDA is expected at $1.0 billion to $1.1 billion.",
        )
    )

    revenue = next(fact for fact in extraction.facts if fact.metric.value == "revenue")
    ebitda = next(fact for fact in extraction.facts if fact.metric.value == "ebitda")

    assert revenue.explicit_action is GuidanceAction.LOWER
    assert ebitda.explicit_action is not GuidanceAction.LOWER


def test_explicit_quarter_and_full_year_outlook_do_not_collapse_to_bare_year():
    extraction = extract_canonical_typed_guidance_facts(
        _document(
            "MIXED",
            "Third Quarter and Fiscal Year 2026 Outlook. "
            "Third Quarter 2026 Outlook: Revenue is expected to be between $164 million and $166 million. "
            "Fiscal Year 2026 Outlook: Revenue is expected to be between $648 million and $652 million.",
        )
    )

    revenue = [fact for fact in extraction.facts if fact.metric.value == "revenue"]
    observed = {(fact.fiscal_period, fact.low, fact.high) for fact in revenue}
    assert ("Q3FY2026", 164.0, 166.0) in observed
    assert ("FY2026", 648.0, 652.0) in observed
    assert ("FY2026", 164.0, 166.0) not in observed


def test_qualified_revenue_is_non_company_while_total_revenue_is_company():
    extraction = extract_canonical_typed_guidance_facts(
        _document(
            "SCOPE",
            "Third Quarter 2026 Outlook: Cloud subscriptions revenue is expected to be between $133 million and $135 million. "
            "Third Quarter 2026 Outlook: Total revenue is expected to be between $214 million and $218 million.",
        )
    )

    revenue = [fact for fact in extraction.facts if fact.metric.value == "revenue"]
    cloud = next(fact for fact in revenue if fact.low == 133.0)
    total = next(fact for fact in revenue if fact.low == 214.0)
    assert cloud.scope_kind is GuidanceScopeKind.SEGMENT
    assert total.scope_kind is GuidanceScopeKind.COMPANY


def test_directional_word_in_risk_factor_prose_cannot_create_guidance():
    extraction = extract_canonical_typed_guidance_facts(
        _document(
            "RISK",
            "Adverse economic conditions, including reduced information technology and network infrastructure spending, "
            "could contribute to volatility in our revenue and operating results.",
        )
    )

    assert not extraction.facts
    assert all(fact.explicit_action is not GuidanceAction.LOWER for fact in extraction.facts)


def test_bullet_plain_revenue_remains_company_scope():
    extraction = extract_canonical_typed_guidance_facts(
        _document(
            "BULLET",
            "Fiscal Year 2026 Outlook: o Revenue is expected to be between $648 million and $652 million.",
        )
    )
    revenue = next(fact for fact in extraction.facts if fact.metric.value == "revenue")
    assert revenue.scope_kind is GuidanceScopeKind.COMPANY


def test_issuer_name_and_guidance_verbs_do_not_become_revenue_scope():
    extraction = extract_canonical_typed_guidance_facts(
        _document(
            "ISSUER",
            "ACM is maintaining its full-year 2026 revenue guidance range of $1.08 billion to $1.175 billion. "
            "We are raising our full-year 2026 revenue guidance to $1.10 billion to $1.20 billion.",
        )
    )
    revenue = [fact for fact in extraction.facts if fact.metric.value == "revenue"]
    assert revenue
    assert all(fact.scope_kind is GuidanceScopeKind.COMPANY for fact in revenue)


def test_explicit_category_revenue_qualifiers_are_non_company():
    extraction = extract_canonical_typed_guidance_facts(
        _document(
            "CATEGORIES",
            "Third Quarter 2026 Outlook: Service revenue is expected to be $500 million to $520 million. "
            "Third Quarter 2026 Outlook: U.S. commercial revenue is expected to be $300 million to $320 million. "
            "Third Quarter 2026 Outlook: Product revenue is expected to be $100 million to $110 million.",
        )
    )
    revenue = [fact for fact in extraction.facts if fact.metric.value == "revenue"]
    service = next(fact for fact in revenue if fact.low == 500.0)
    commercial = next(fact for fact in revenue if fact.low == 300.0)
    product = next(fact for fact in revenue if fact.low == 100.0)
    assert service.scope_kind is GuidanceScopeKind.SEGMENT
    assert commercial.scope_kind is GuidanceScopeKind.SEGMENT
    assert product.scope_kind is GuidanceScopeKind.PRODUCT


def test_quarter_ending_phrase_outranks_later_full_year_section():
    extraction = extract_canonical_typed_guidance_facts(
        _document(
            "PERIOD",
            "Alkami is providing guidance for its first quarter ending March 31, 2026 of: "
            "Total revenue in the range of $120 million to $125 million. "
            "Alkami is providing guidance for its fiscal year ending December 31, 2026 of: "
            "Total revenue in the range of $500 million to $520 million.",
        )
    )
    observed = {(fact.fiscal_period, fact.low, fact.high) for fact in extraction.facts if fact.metric.value == "revenue"}
    assert ("Q1FY2026", 120.0, 125.0) in observed
    assert ("FY2026", 500.0, 520.0) in observed
    assert ("FY2026", 120.0, 125.0) not in observed


def test_value_cannot_bind_across_a_closer_metric_owner():
    extraction = extract_canonical_typed_guidance_facts(
        _document(
            "OWNER",
            "Second quarter 2026 guidance: revenue guidance of $109 million to $111 million, "
            "and adjusted EBITDA guidance of $9 million to $10 million.",
        )
    )
    revenue = [fact for fact in extraction.facts if fact.metric.value == "revenue"]
    assert revenue
    assert all((fact.low, fact.high) != (9.0, 10.0) for fact in revenue)


def test_actual_result_before_guidance_heading_is_rejected():
    extraction = extract_canonical_typed_guidance_facts(
        _document(
            "ACTUAL",
            "Adjusted EBITDA was $58.4 million in the first quarter. Raising Full Year 2026 Guidance. "
            "Adjusted EBITDA is expected to be $220 million to $230 million for full-year 2026.",
        )
    )
    ebitda = [fact for fact in extraction.facts if fact.metric.value == "ebitda"]
    assert any((fact.low, fact.high) == (220.0, 230.0) for fact in ebitda)
    assert all((fact.low, fact.high) != (58.4, 58.4) for fact in ebitda)
    assert any(item["reason"] == "historical_actual" for item in extraction.rejected_candidates)


def test_prior_guidance_value_gets_quoted_prior_role_only_locally():
    extraction = extract_canonical_typed_guidance_facts(
        _document(
            "PRIOR",
            "Full-year 2026 outlook: Adjusted EBITDA is expected to be $225 million to $230 million. "
            "This outlook reflects an increase from our prior Adjusted EBITDA outlook of $195 million to $210 million.",
        )
    )
    ebitda = [fact for fact in extraction.facts if fact.metric.value == "ebitda"]
    assert any(fact.role is GuidanceFactRole.CURRENT and (fact.low, fact.high) == (225.0, 230.0) for fact in ebitda)
    assert any(fact.role is GuidanceFactRole.QUOTED_PRIOR and (fact.low, fact.high) == (195.0, 210.0) for fact in ebitda)


def test_parallel_quarter_and_full_year_table_fails_closed():
    extraction = extract_canonical_typed_guidance_facts(
        _document(
            "TABLE",
            "TABLE II RECONCILIATION OF NON-GAAP GUIDANCE Three months ending March 31, 2026 "
            "Year ending December 31, 2026 GAAP operating margin 2.7% 3.2%.",
        )
    )
    assert not extraction.facts
    assert any(item["reason"] == "ambiguous_parallel_period_table" for item in extraction.rejected_candidates)



def test_semantic_acceptance_cross_metric_owner_regressions():
    extraction = extract_canonical_typed_guidance_facts(
        _document(
            "OWNER2",
            "Fiscal year 2027 guidance: Revenue of between $630 million and $650 million; "
            "Non-GAAP adjusted EBITDA of between $135 million and $145 million. "
            "Full year 2026 guidance: net cash provided by operating activities to range between "
            "$2.90 billion and $3.40 billion and free cash flow to range between $2.00 billion and $2.50 billion.",
        )
    )
    ebitda = [fact for fact in extraction.facts if fact.metric.value == "ebitda"]
    fcf = [fact for fact in extraction.facts if fact.metric.value == "fcf"]
    assert all((fact.low, fact.high) != (630.0, 650.0) for fact in ebitda)
    assert all((fact.low, fact.high) != (2.90, 3.40) for fact in fcf)
    assert any((fact.low, fact.high) == (135.0, 145.0) for fact in ebitda)
    assert any((fact.low, fact.high) == (2.00, 2.50) for fact in fcf)


def test_semantic_acceptance_period_heading_blocks_prior_value_binding():
    extraction = extract_canonical_typed_guidance_facts(
        _document(
            "HEADING",
            "Adjusted restaurant-level profit is expected to be approximately $208 million to $212 million in FY25. "
            "Initial Fiscal 2026 Financial Guidance: Total revenue of $1.6 billion to $1.7 billion.",
        )
    )
    revenue = [fact for fact in extraction.facts if fact.metric.value == "revenue"]
    assert any(fact.fiscal_period == "FY2026" and (fact.low, fact.high) == (1.6, 1.7) for fact in revenue)
    assert all((fact.low, fact.high) != (208.0, 212.0) for fact in revenue)


def test_semantic_acceptance_scale_shadow_is_suppressed():
    extraction = extract_canonical_typed_guidance_facts(
        _document(
            "SCALE",
            "For full year 2026, we are raising our revenue guidance to between $8.150 - $8.158 billion.",
        )
    )
    revenue = [fact for fact in extraction.facts if fact.metric.value == "revenue"]
    observed = {(fact.low, fact.high, fact.unit.value) for fact in revenue}
    assert (8.15, 8.158, "USD_BILLION") in observed
    assert (8.15, 8.158, "USD") not in observed


def test_semantic_acceptance_result_headline_is_not_forward_guidance():
    extraction = extract_canonical_typed_guidance_facts(
        _document(
            "ACTUAL2",
            "Humana Reports Second Quarter 2026 Financial Results; Affirms Full Year 2026 Adjusted Financial Guidance. "
            "Reports 2Q26 earnings per share (EPS) of $5.73 on a GAAP basis, Adjusted EPS of $7.61. "
            "FY 2026 Adjusted EPS guidance is at least $9.00.",
        )
    )
    eps = [fact for fact in extraction.facts if fact.metric.value == "eps"]
    assert all(fact.low not in {5.73, 7.61} for fact in eps)
    assert any(fact.low == 9.0 for fact in eps)


def test_semantic_acceptance_eps_does_not_truncate_comma_dollar_amount():
    extraction = extract_canonical_typed_guidance_facts(
        _document(
            "COMMA",
            "FY 2026 Adjusted EPS guidance is at least $9.00. Adjusted net income $2,263 million.",
        )
    )
    eps = [fact for fact in extraction.facts if fact.metric.value == "eps"]
    assert all(fact.low != 2.0 for fact in eps)
