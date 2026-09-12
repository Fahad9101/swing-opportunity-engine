from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from app.domain.guidance_canonical_v1 import GuidanceScopeKind
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
