from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from app.domain.guidance_canonical_v1 import GuidanceFactRole, GuidanceUnit
from app.domain.soe_v1_1 import GuidanceAction, GuidanceMetric, SourceDocument
from app.services.guidance_raw_canonical_extractor import extract_canonical_typed_guidance_facts


def _doc(text: str) -> SourceDocument:
    ts = datetime(2026, 9, 15, tzinfo=UTC)
    digest = hashlib.sha256(text.encode()).hexdigest()
    return SourceDocument(
        document_id=f"range-revision-{digest[:12]}",
        rules_hash="candidate-hash",
        ticker="TEST",
        cik="0000000001",
        accession="0000000001-26-999995",
        form="8-K",
        filing_date=ts.date(),
        source_url="https://www.sec.gov/Archives/edgar/data/1/range-revision.htm",
        source_timestamp=ts,
        fetched_at=ts,
        content_hash=digest,
        content_type="text/plain",
        content=text,
    )


def _revenue_facts(text: str):
    return [
        fact for fact in extract_canonical_typed_guidance_facts(_doc(text)).facts
        if fact.metric is GuidanceMetric.REVENUE
    ]


def test_increasing_range_to_range_emits_new_current_and_old_quoted_prior():
    facts = _revenue_facts(
        "For 2025, the company is increasing total revenue guidance "
        "from a range of $250 million to $260 million to a range of $260 million to $270 million."
    )
    current = [fact for fact in facts if fact.role is GuidanceFactRole.CURRENT]
    prior = [fact for fact in facts if fact.role is GuidanceFactRole.QUOTED_PRIOR]
    assert any(
        fact.low == 260 and fact.high == 270 and fact.unit is GuidanceUnit.USD_MILLION
        and fact.explicit_action is GuidanceAction.RAISE
        for fact in current
    )
    assert any(
        fact.low == 250 and fact.high == 260 and fact.unit is GuidanceUnit.USD_MILLION
        and fact.explicit_action is GuidanceAction.NONE
        for fact in prior
    )
    assert not any(fact.low == 250 and fact.high == 260 for fact in current)


def test_lowering_range_to_range_emits_new_current_and_old_quoted_prior():
    facts = _revenue_facts(
        "For 2026, the company is lowering total revenue guidance "
        "from a range of $300 million to $320 million to a range of $280 million to $290 million."
    )
    assert any(
        fact.role is GuidanceFactRole.CURRENT and fact.low == 280 and fact.high == 290
        and fact.explicit_action is GuidanceAction.LOWER
        for fact in facts
    )
    assert any(
        fact.role is GuidanceFactRole.QUOTED_PRIOR and fact.low == 300 and fact.high == 320
        and fact.explicit_action is GuidanceAction.NONE
        for fact in facts
    )


def test_plain_guidance_range_from_to_is_not_reclassified_as_revision():
    facts = _revenue_facts(
        "For 2026, the company expects total revenue guidance in a range from $315 million to $325 million."
    )
    assert any(
        fact.role is GuidanceFactRole.CURRENT and fact.low == 315 and fact.high == 325
        for fact in facts
    )
    assert not any(fact.role is GuidanceFactRole.QUOTED_PRIOR for fact in facts)
