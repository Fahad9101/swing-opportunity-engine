from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.config import SOE_1_1_RULES_PATH, load_rules, load_rules_for_version, rules_hash
from app.services.shadow_enrichment_service import StructuralEnrichmentResult
from app.services.shadow_validation_service import assert_frozen_rule_equivalence, snapshot_fingerprint
from app.services.universe_service import passes_universal_gate


@dataclass(frozen=True)
class ShadowChunkContext:
    capture: dict[str, Any]
    baseline_rules: dict[str, Any]
    candidate_rules: dict[str, Any]
    baseline_hash: str
    candidate_hash: str
    universal_tickers: list[str]
    growth_targets: list[str]
    fingerprint: str


def build_shadow_chunk_context(scan_run_id: str) -> ShadowChunkContext:
    """Reconstruct the exact persisted 1.1E snapshot without another market pull."""
    # Imported lazily so the normal validation CLI remains independent of the
    # chunked orchestration helper and no frozen evaluation function is copied.
    from app.cli_shadow_validation import _evaluate_all, _growth_needs_structural, _load_capture

    baseline_rules = load_rules()
    candidate_rules = load_rules_for_version(SOE_1_1_RULES_PATH, "SOE-1.1.0")
    assert_frozen_rule_equivalence(baseline_rules, candidate_rules)
    baseline_hash = rules_hash(baseline_rules)
    candidate_hash = rules_hash(candidate_rules)
    capture = _load_capture(scan_run_id)

    universal_tickers: list[str] = []
    for ticker, market in capture["markets"].items():
        instrument = capture["instruments"][ticker]
        before = passes_universal_gate(instrument, market, baseline_rules).passed
        after = passes_universal_gate(instrument, market, candidate_rules).passed
        if before != after:
            raise RuntimeError(f"Frozen universal gate mismatch during chunk reconstruction: {ticker}")
        if before:
            universal_tickers.append(ticker)
    universal_tickers.sort()

    snapshot_rows = []
    for ticker in universal_tickers:
        snapshot_rows.append(
            {
                "ticker": ticker,
                "instrument": capture["instruments"][ticker].model_dump(mode="json"),
                "market": capture["markets"][ticker].model_dump(mode="json"),
                "fundamental": capture["fundamentals"].get(ticker).model_dump(mode="json")
                if capture["fundamentals"].get(ticker)
                else None,
                "estimates": capture["estimates"].get(ticker).model_dump(mode="json")
                if capture["estimates"].get(ticker)
                else None,
                "catalysts": [item.model_dump(mode="json") for item in capture["catalysts"].get(ticker, [])],
                "corporate_events": [item.model_dump(mode="json") for item in capture["events"].get(ticker, [])],
            }
        )
    fingerprint = snapshot_fingerprint(snapshot_rows)

    baseline_results = _evaluate_all(universal_tickers, capture, baseline_rules)
    growth_targets = [item.ticker for item in baseline_results if _growth_needs_structural(item)]

    return ShadowChunkContext(
        capture=capture,
        baseline_rules=baseline_rules,
        candidate_rules=candidate_rules,
        baseline_hash=baseline_hash,
        candidate_hash=candidate_hash,
        universal_tickers=universal_tickers,
        growth_targets=growth_targets,
        fingerprint=fingerprint,
    )


def partition_targets(targets: list[str], *, chunk_index: int, chunk_count: int) -> list[str]:
    if chunk_count < 1:
        raise ValueError("chunk_count must be >= 1")
    if chunk_index < 0 or chunk_index >= chunk_count:
        raise ValueError("chunk_index must satisfy 0 <= chunk_index < chunk_count")
    return [ticker for index, ticker in enumerate(targets) if index % chunk_count == chunk_index]


def serialize_growth_result(item: StructuralEnrichmentResult) -> dict[str, Any]:
    if item.catalyst_overrides or item.catalysts:
        raise ValueError("Growth chunk serialization must not contain catalyst enrichment")
    return {
        "ticker": item.ticker,
        "guidance_deterioration": item.guidance_deterioration,
        "balance_sheet_distressed": item.balance_sheet_distressed,
        "guidance": item.guidance,
        "distress": item.distress,
        "errors": list(item.errors),
    }


def deserialize_growth_result(payload: dict[str, Any]) -> StructuralEnrichmentResult:
    return StructuralEnrichmentResult(
        ticker=str(payload["ticker"]),
        guidance_deterioration=payload.get("guidance_deterioration"),
        balance_sheet_distressed=payload.get("balance_sheet_distressed"),
        guidance=dict(payload.get("guidance") or {}),
        distress=dict(payload.get("distress") or {}),
        errors=list(payload.get("errors") or []),
    )


def merge_growth_chunks(
    payloads: list[dict[str, Any]],
    *,
    expected_tickers: list[str],
    fingerprint: str,
    baseline_hash: str,
    candidate_hash: str,
) -> dict[str, StructuralEnrichmentResult]:
    expected = set(expected_tickers)
    merged: dict[str, StructuralEnrichmentResult] = {}
    declared_chunk_count: int | None = None
    seen_chunks: set[int] = set()

    for payload in payloads:
        if payload.get("fingerprint") != fingerprint:
            raise RuntimeError("Growth chunk snapshot fingerprint mismatch")
        if payload.get("baseline_rules_hash") != baseline_hash:
            raise RuntimeError("Growth chunk baseline rules hash mismatch")
        if payload.get("candidate_rules_hash") != candidate_hash:
            raise RuntimeError("Growth chunk candidate rules hash mismatch")
        chunk_count = int(payload["chunk_count"])
        chunk_index = int(payload["chunk_index"])
        if declared_chunk_count is None:
            declared_chunk_count = chunk_count
        elif declared_chunk_count != chunk_count:
            raise RuntimeError("Growth chunks disagree on chunk_count")
        if chunk_index in seen_chunks:
            raise RuntimeError(f"Duplicate growth chunk index: {chunk_index}")
        seen_chunks.add(chunk_index)

        for row in payload.get("items") or []:
            item = deserialize_growth_result(row)
            if item.ticker in merged:
                raise RuntimeError(f"Duplicate growth enrichment ticker: {item.ticker}")
            merged[item.ticker] = item

    if declared_chunk_count is None or seen_chunks != set(range(declared_chunk_count)):
        raise RuntimeError("Growth chunk set is incomplete")
    actual = set(merged)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise RuntimeError(f"Growth enrichment coverage mismatch missing={missing[:10]} extra={extra[:10]}")
    return merged
