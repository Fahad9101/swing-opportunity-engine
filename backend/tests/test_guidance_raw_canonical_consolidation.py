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
        document_id=f"consolidation-{ticker}-{digest[:12]}",
        rules_hash="canonical-consolidation-test",
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


def test_historical_quarter_does_not_rebind_later_annual_guidance():
    extraction = extract_canonical_typed_guidance_facts(
        _document(
            "PERIOD",
            "Fourth quarter of 2023 performance is shown for comparison while Fiscal 2025 Guidance Revenue is expected to be $500 million to $520 million.",
        )
    )
    revenue = [fact for fact in extraction.facts if fact.metric.value == "revenue"]
    assert any(fact.fiscal_period == "FY2025" and (fact.low, fact.high) == (500.0, 520.0) for fact in revenue)
    assert not any(fact.fiscal_period == "Q4FY2023" and (fact.low, fact.high) == (500.0, 520.0) for fact in revenue)


def test_plain_fiscal_year_phrase_is_authoritative():
    extraction = extract_canonical_typed_guidance_facts(
        _document("FISCAL", "Fiscal 2026 Outlook: Revenue is expected to be $640 million to $660 million.")
    )
    revenue = next(fact for fact in extraction.facts if fact.metric.value == "revenue")
    assert revenue.fiscal_period == "FY2026"
    assert (revenue.low, revenue.high) == (640.0, 660.0)


def test_directional_from_to_emits_current_and_quoted_prior():
    extraction = extract_canonical_typed_guidance_facts(
        _document("PAIR", "Fiscal 2026 guidance raises Revenue from $480 million to $500 million.")
    )
    revenue = [fact for fact in extraction.facts if fact.metric.value == "revenue"]
    assert any(fact.role is GuidanceFactRole.CURRENT and fact.low == 500.0 and fact.explicit_action is GuidanceAction.RAISE for fact in revenue)
    assert any(fact.role is GuidanceFactRole.QUOTED_PRIOR and fact.low == 480.0 for fact in revenue)


def test_directional_delta_to_target_does_not_treat_delta_as_absolute_guidance():
    extraction = extract_canonical_typed_guidance_facts(
        _document("DELTA", "Fiscal 2026 guidance raises Revenue by $20 million to $500 million.")
    )
    revenue = [fact for fact in extraction.facts if fact.metric.value == "revenue"]
    assert any(fact.role is GuidanceFactRole.CURRENT and fact.low == 500.0 and fact.high == 500.0 for fact in revenue)
    assert not any(fact.low == 20.0 and fact.high == 20.0 for fact in revenue)


def test_previous_now_language_emits_both_roles():
    extraction = extract_canonical_typed_guidance_facts(
        _document(
            "PREVIOUSLY",
            "Fiscal 2026 Revenue guidance was previously expected at $480 million and is now expected at $500 million.",
        )
    )
    revenue = [fact for fact in extraction.facts if fact.metric.value == "revenue"]
    assert any(fact.role is GuidanceFactRole.CURRENT and fact.low == 500.0 for fact in revenue)
    assert any(fact.role is GuidanceFactRole.QUOTED_PRIOR and fact.low == 480.0 for fact in revenue)


def test_acquisition_contribution_scope_applies_to_non_revenue_metric():
    extraction = extract_canonical_typed_guidance_facts(
        _document(
            "ACQ",
            "Fiscal 2026 guidance: acquisition contribution to Adjusted EBITDA is expected to be $25 million.",
        )
    )
    ebitda = next(fact for fact in extraction.facts if fact.metric.value == "ebitda")
    assert ebitda.scope_kind is GuidanceScopeKind.SEGMENT


def test_same_document_endpoint_fragment_is_suppressed_when_full_range_exists():
    extraction = extract_canonical_typed_guidance_facts(
        _document(
            "FRAGMENT",
            "Fiscal 2026 guidance: Revenue is expected to be $500 million to $520 million; Revenue is expected to be $520 million.",
        )
    )
    revenue = [fact for fact in extraction.facts if fact.metric.value == "revenue" and fact.role is GuidanceFactRole.CURRENT]
    assert any((fact.low, fact.high) == (500.0, 520.0) for fact in revenue)
    assert not any((fact.low, fact.high) == (520.0, 520.0) for fact in revenue)
    assert any(item["reason"] == "same_document_range_endpoint_fragment" for item in extraction.rejected_candidates)
