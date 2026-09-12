from __future__ import annotations

import hashlib
from datetime import UTC, datetime

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
