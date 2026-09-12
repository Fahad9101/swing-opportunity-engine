from __future__ import annotations

from datetime import UTC, datetime

from app.domain.guidance_canonical_v1 import (
    CanonicalizationResult,
    GuidanceFactRole,
    GuidanceInvariantCode,
)
from app.domain.soe_v1_1 import GuidanceAssessment, GuidanceClassification
from app.services.guidance_canonical_ledger_service import CanonicalGuidanceLedger


_NON_BLOCKING_QUARANTINE = {
    GuidanceInvariantCode.NON_COMPANY_SCOPE,
    GuidanceInvariantCode.HISTORICAL_ACTUAL,
    GuidanceInvariantCode.LONG_TERM_TARGET,
}


def _latest_accepted_timestamp(result: CanonicalizationResult, ticker: str) -> datetime | None:
    timestamps = [
        provenance.source_timestamp
        for fact in result.accepted
        if fact.ticker == ticker and fact.role is GuidanceFactRole.CURRENT
        for provenance in fact.provenance
    ]
    return max(timestamps) if timestamps else None


def _blocking_quarantines(result: CanonicalizationResult, ticker: str):
    blocked = []
    for item in result.quarantined:
        if item.fact.ticker != ticker:
            continue
        blocking = [
            violation
            for violation in item.violations
            if violation.quarantine and violation.code not in _NON_BLOCKING_QUARANTINE
        ]
        if blocking:
            blocked.append((item, blocking))
    return blocked


def assess_canonicalization_result(
    result: CanonicalizationResult,
    ticker: str,
    rules: dict,
    *,
    rules_hash: str,
    as_of: datetime | None = None,
) -> GuidanceAssessment:
    """Assess accepted canonical facts without falling back past unresolved evidence.

    If a newer (or same-snapshot) guidance candidate is quarantined for a
    blocking invariant failure, classification is UNKNOWN rather than silently
    reverting to an older clean guidance snapshot. Non-company, historical, and
    long-term evidence is intentionally irrelevant and does not block.
    """
    as_of = as_of or datetime.now(UTC)
    accepted_latest = _latest_accepted_timestamp(result, ticker)
    blocked = _blocking_quarantines(result, ticker)

    active_blocked = []
    for item, violations in blocked:
        timestamps = [
            provenance.source_timestamp
            for provenance in item.fact.provenance
            if provenance.source_timestamp <= as_of
        ]
        if not timestamps:
            continue
        latest = max(timestamps)
        if accepted_latest is None or latest >= accepted_latest:
            active_blocked.append((latest, item, violations))

    if active_blocked:
        latest_blocked = max(entry[0] for entry in active_blocked)
        reasons = []
        sources = set()
        for timestamp, item, violations in active_blocked:
            if timestamp != latest_blocked:
                continue
            codes = ",".join(sorted({violation.code.value for violation in violations}))
            reasons.append(
                f"Latest guidance evidence is quarantined at {timestamp.isoformat()} "
                f"for {item.fact.metric.value}/{item.fact.fiscal_period}: {codes}."
            )
            for provenance in item.fact.provenance:
                if provenance.source_timestamp == timestamp:
                    sources.add(provenance.source_url)
        return GuidanceAssessment(
            rules_hash=rules_hash,
            ticker=ticker,
            as_of=as_of,
            classification=GuidanceClassification.UNKNOWN,
            guidance_deterioration=None,
            rule_path="guidance_v1_1.canonical_unresolved_latest_evidence",
            reasons=sorted(reasons),
            sources=sorted(sources),
        )

    return CanonicalGuidanceLedger(result.accepted).assess(
        ticker,
        rules,
        rules_hash=rules_hash,
        as_of=as_of,
    )
