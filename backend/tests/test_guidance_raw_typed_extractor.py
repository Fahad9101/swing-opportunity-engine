from __future__ import annotations

import hashlib
import inspect
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.domain.guidance_canonical_v1 import GuidanceUnit
from app.domain.soe_v1_1 import SourceDocument
from app.services.guidance_canonical_service import CanonicalGuidanceNormalizer, GuidanceInvariantValidator
from app.services.guidance_raw_typed_extractor import extract_typed_guidance_facts


FIXTURE = Path(__file__).parent / "fixtures" / "guidance_raw_extraction_corpus_v1.json"
TS = datetime(2026, 8, 15, tzinfo=UTC)


def _document(ticker: str, text: str) -> SourceDocument:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return SourceDocument(
        document_id=f"raw-{ticker}-{digest[:12]}",
        rules_hash="raw-typed-test",
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


def _semantic(fact):
    return (
        fact.metric.value,
        fact.fiscal_period,
        fact.accounting_basis,
        fact.scope_kind.value,
        fact.low,
        fact.high,
        fact.unit.value,
        fact.value_kind.value,
        fact.explicit_action.value,
    )


def _matches(fact, expected: dict) -> bool:
    if fact.metric.value != expected["metric"]:
        return False
    if fact.fiscal_period != expected["period"]:
        return False
    if fact.accounting_basis != expected["basis"]:
        return False
    if fact.scope_kind.value != expected["scope"]:
        return False
    if fact.unit.value != expected["unit"]:
        return False
    if "value_kind" in expected and fact.value_kind.value != expected["value_kind"]:
        return False
    if "action" in expected and fact.explicit_action.value != expected["action"]:
        return False
    if expected.get("low") is None:
        if fact.low is not None:
            return False
    elif fact.low != pytest.approx(expected["low"]):
        return False
    if expected.get("high") is None:
        if fact.high is not None:
            return False
    elif fact.high != pytest.approx(expected["high"]):
        return False
    return True


@pytest.mark.parametrize("case", json.loads(FIXTURE.read_text(encoding="utf-8")), ids=lambda case: case["name"])
def test_raw_sec_corpus_emits_typed_facts_and_fails_closed(case):
    extraction = extract_typed_guidance_facts(_document(case["ticker"], case["text"]))
    validator = GuidanceInvariantValidator()
    validated = [validator.validate(fact) for fact in extraction.facts]

    forbidden = set(case.get("forbidden_metrics") or [])
    assert not forbidden.intersection({fact.metric.value for fact in extraction.facts})

    for expected in case["expected"]:
        matches = [result for result in validated if _matches(result.fact, expected)]
        assert matches, (
            f"{case['name']}: missing expected fact {expected}; "
            f"got {[result.fact.model_dump(mode='json') for result in validated]}"
        )
        assert any(result.accepted is expected["accepted"] for result in matches)

    unexpected_accepted = [
        result.fact
        for result in validated
        if result.accepted
        and not any(_matches(result.fact, expected) and expected["accepted"] for expected in case["expected"])
    ]
    assert not unexpected_accepted, (
        f"{case['name']}: unexpected accepted facts "
        f"{[fact.model_dump(mode='json') for fact in unexpected_accepted]}"
    )


def test_raw_extractor_replay_is_semantically_deterministic():
    case = next(
        item
        for item in json.loads(FIXTURE.read_text(encoding="utf-8"))
        if item["ticker"] == "CLS"
    )
    document = _document(case["ticker"], case["text"])
    first = extract_typed_guidance_facts(document)
    second = extract_typed_guidance_facts(document)

    assert sorted(_semantic(fact) for fact in first.facts) == sorted(_semantic(fact) for fact in second.facts)
    assert [item["reason"] for item in first.rejected_candidates] == [
        item["reason"] for item in second.rejected_candidates
    ]
    assert {
        provenance.source_document_hash
        for fact in first.facts
        for provenance in fact.provenance
    } == {document.content_hash}


def test_raw_source_units_are_normalized_exactly_once():
    case = next(
        item
        for item in json.loads(FIXTURE.read_text(encoding="utf-8"))
        if item["ticker"] == "CLS"
    )
    extraction = extract_typed_guidance_facts(_document(case["ticker"], case["text"]))
    validator = GuidanceInvariantValidator()
    normalized = CanonicalGuidanceNormalizer().normalize(
        validator.validate(fact) for fact in extraction.facts
    )

    revenue = next(fact for fact in normalized.accepted if fact.metric.value == "revenue")
    assert revenue.low == pytest.approx(3_325_000_000.0)
    assert revenue.high == pytest.approx(3_575_000_000.0)
    assert revenue.unit is GuidanceUnit.USD


def test_raw_extractor_does_not_depend_on_legacy_repair_stack():
    import app.services.guidance_raw_typed_extractor as module

    source = inspect.getsource(module)
    assert "phase_1_1e_" not in source
    assert "GuidanceMetricRecord" not in source
    assert "guidance_canonical_migration_service" not in source
