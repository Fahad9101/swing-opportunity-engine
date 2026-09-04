import pytest

from app.services.shadow_chunk_service import (
    deserialize_growth_result,
    merge_growth_chunks,
    partition_targets,
    serialize_growth_result,
)
from app.services.shadow_enrichment_service import StructuralEnrichmentResult


def test_partition_targets_is_complete_and_disjoint() -> None:
    targets = [f"T{i}" for i in range(10)]
    chunks = [partition_targets(targets, chunk_index=i, chunk_count=3) for i in range(3)]

    flattened = [ticker for chunk in chunks for ticker in chunk]

    assert sorted(flattened) == sorted(targets)
    assert len(flattened) == len(set(flattened))


def test_growth_result_round_trip_preserves_structural_fields() -> None:
    item = StructuralEnrichmentResult(
        ticker="ABC",
        guidance_deterioration=False,
        balance_sheet_distressed=True,
        guidance={"classification": "SAFE"},
        distress={"classification": "DISTRESSED"},
        errors=["SOURCE_ROW_SKIPPED"],
    )

    restored = deserialize_growth_result(serialize_growth_result(item))

    assert restored.ticker == "ABC"
    assert restored.guidance_deterioration is False
    assert restored.balance_sheet_distressed is True
    assert restored.guidance == {"classification": "SAFE"}
    assert restored.distress == {"classification": "DISTRESSED"}
    assert restored.errors == ["SOURCE_ROW_SKIPPED"]


def test_merge_growth_chunks_requires_exact_snapshot_and_coverage() -> None:
    payloads = [
        {
            "fingerprint": "fp",
            "baseline_rules_hash": "b",
            "candidate_rules_hash": "c",
            "chunk_index": 0,
            "chunk_count": 2,
            "items": [serialize_growth_result(StructuralEnrichmentResult(ticker="A"))],
        },
        {
            "fingerprint": "fp",
            "baseline_rules_hash": "b",
            "candidate_rules_hash": "c",
            "chunk_index": 1,
            "chunk_count": 2,
            "items": [serialize_growth_result(StructuralEnrichmentResult(ticker="B"))],
        },
    ]

    merged = merge_growth_chunks(
        payloads,
        expected_tickers=["A", "B"],
        fingerprint="fp",
        baseline_hash="b",
        candidate_hash="c",
    )

    assert set(merged) == {"A", "B"}

    with pytest.raises(RuntimeError, match="coverage mismatch"):
        merge_growth_chunks(
            payloads[:1],
            expected_tickers=["A", "B"],
            fingerprint="fp",
            baseline_hash="b",
            candidate_hash="c",
        )


def test_merge_growth_chunks_rejects_cross_snapshot_payload() -> None:
    payload = {
        "fingerprint": "wrong",
        "baseline_rules_hash": "b",
        "candidate_rules_hash": "c",
        "chunk_index": 0,
        "chunk_count": 1,
        "items": [serialize_growth_result(StructuralEnrichmentResult(ticker="A"))],
    }

    with pytest.raises(RuntimeError, match="fingerprint mismatch"):
        merge_growth_chunks(
            [payload],
            expected_tickers=["A"],
            fingerprint="fp",
            baseline_hash="b",
            candidate_hash="c",
        )
