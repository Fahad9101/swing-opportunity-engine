from __future__ import annotations

from collections import Counter
from typing import Any, Iterable

from app.domain.soe_v1_1 import GuidanceMetricRecord
from app.services.guidance_canonical_ledger_service import (
    CanonicalGuidanceLedger,
    canonicalize_legacy_records_with_roles,
)


def _guidance_payloads(validation: dict[str, Any]) -> Iterable[tuple[str, dict[str, Any]]]:
    for row in validation.get("per_name_deltas") or []:
        ticker = str(row.get("ticker") or "").upper()
        guidance = ((row.get("structural_inputs") or {}).get("guidance") or {})
        if ticker and guidance:
            yield ticker, guidance


def _record_from_payload(payload: dict[str, Any]) -> GuidanceMetricRecord:
    return GuidanceMetricRecord.model_validate(payload)


def canonical_guidance_differential_report(
    validation: dict[str, Any],
    rules: dict[str, Any],
    *,
    rules_hash: str,
) -> dict[str, Any]:
    """Compare the legacy Phase-1.1E assessment to the canonical evidence path.

    This is deliberately shadow-only. It consumes the immutable validation
    artifact and performs no network calls. Canonical invariant failures are
    quarantined before the frozen classifier sees the evidence.
    """

    tickers = 0
    legacy_records = 0
    canonical_facts = 0
    quarantined_facts = 0
    quarantine_codes: Counter[str] = Counter()
    classifications_old: Counter[str] = Counter()
    classifications_canonical: Counter[str] = Counter()
    divergences: list[dict[str, Any]] = []
    quarantine_by_ticker: list[dict[str, Any]] = []

    for ticker, payload in _guidance_payloads(validation):
        tickers += 1
        old_classification = str(payload.get("classification") or "UNKNOWN")
        classifications_old[old_classification] += 1

        raw_records = payload.get("ledger_records") or []
        records = [_record_from_payload(item) for item in raw_records]
        legacy_records += len(records)

        canonical = canonicalize_legacy_records_with_roles(records)
        canonical_facts += len(canonical.accepted)
        quarantined_facts += len(canonical.quarantined)

        ticker_codes: Counter[str] = Counter()
        for rejected in canonical.quarantined:
            for violation in rejected.violations:
                if violation.quarantine:
                    code = violation.code.value
                    quarantine_codes[code] += 1
                    ticker_codes[code] += 1
        if ticker_codes:
            quarantine_by_ticker.append(
                {
                    "ticker": ticker,
                    "legacy_classification": old_classification,
                    "legacy_record_count": len(records),
                    "canonical_fact_count": len(canonical.accepted),
                    "quarantined_fact_count": len(canonical.quarantined),
                    "quarantine_codes": dict(sorted(ticker_codes.items())),
                }
            )

        assessment = CanonicalGuidanceLedger(canonical.accepted).assess(
            ticker,
            rules,
            rules_hash=rules_hash,
        )
        canonical_classification = assessment.classification.value
        classifications_canonical[canonical_classification] += 1

        if canonical_classification != old_classification:
            divergences.append(
                {
                    "ticker": ticker,
                    "legacy_classification": old_classification,
                    "canonical_classification": canonical_classification,
                    "legacy_rule_path": payload.get("rule_path"),
                    "canonical_rule_path": assessment.rule_path,
                    "canonical_reasons": list(assessment.reasons),
                    "legacy_record_count": len(records),
                    "canonical_fact_count": len(canonical.accepted),
                    "quarantined_fact_count": len(canonical.quarantined),
                    "quarantine_codes": dict(sorted(ticker_codes.items())),
                }
            )

    # Divergences are not automatically labelled good or bad. Any classification
    # drift is an adjudication item. This prevents the differential validator
    # from hiding a regression simply because the canonical pipeline is newer.
    return {
        "tickers_with_guidance_payload": tickers,
        "legacy_record_count": legacy_records,
        "canonical_fact_count": canonical_facts,
        "quarantined_fact_count": quarantined_facts,
        "quarantine_rate": (quarantined_facts / legacy_records) if legacy_records else 0.0,
        "quarantine_codes": dict(sorted(quarantine_codes.items())),
        "legacy_classification_distribution": dict(sorted(classifications_old.items())),
        "canonical_classification_distribution": dict(sorted(classifications_canonical.items())),
        "classification_divergence_count": len(divergences),
        "classification_divergences": sorted(divergences, key=lambda item: item["ticker"]),
        "quarantine_by_ticker": sorted(quarantine_by_ticker, key=lambda item: item["ticker"]),
    }
