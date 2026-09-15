from __future__ import annotations

from datetime import UTC, datetime

from app.domain.guidance_canonical_v1 import (
    CanonicalizationResult,
    GuidanceFactRole,
    GuidanceInvariantCode,
    GuidanceScopeKind,
)
from app.domain.soe_v1_1 import GuidanceAssessment, GuidanceClassification
from app.services.guidance_canonical_ledger_service import CanonicalGuidanceLedger


_NON_BLOCKING_QUARANTINE = {
    GuidanceInvariantCode.NON_COMPANY_SCOPE,
    GuidanceInvariantCode.HISTORICAL_ACTUAL,
    GuidanceInvariantCode.LONG_TERM_TARGET,
}

_SUPPLEMENTARY_VALUE_QUARANTINE = {
    GuidanceInvariantCode.NON_ABSOLUTE_VALUE,
    GuidanceInvariantCode.UNIT_METRIC_MISMATCH,
}


def _latest_accepted_timestamp(result: CanonicalizationResult, ticker: str) -> datetime | None:
    timestamps = [
        provenance.source_timestamp
        for fact in result.accepted
        if fact.ticker == ticker and fact.role is GuidanceFactRole.CURRENT
        for provenance in fact.provenance
    ]
    return max(timestamps) if timestamps else None


def _fact_identity(fact) -> tuple:
    scope_label = "" if fact.scope_kind is GuidanceScopeKind.COMPANY else (fact.scope_label or "")
    return (
        fact.metric.value,
        fact.fiscal_period,
        fact.accounting_basis,
        fact.scope_kind.value,
        scope_label,
    )


def _has_same_snapshot_absolute_replacement(
    result: CanonicalizationResult,
    ticker: str,
    quarantined_fact,
    timestamp: datetime,
) -> bool:
    """Return true only when the same economic guidance identity is accepted.

    Raw filings can state both an absolute level and a supplementary growth/bps
    expression for the same metric/period in the same release. The supplementary
    expression remains quarantined, but it must not force UNKNOWN when a valid
    absolute fact for that exact economic identity is authoritative at the same
    timestamp. Newer unsupported guidance with no same-snapshot absolute fact
    remains blocking, preventing stale fallback.
    """
    identity = _fact_identity(quarantined_fact)
    for fact in result.accepted:
        if fact.ticker != ticker or fact.role is not GuidanceFactRole.CURRENT:
            continue
        if _fact_identity(fact) != identity:
            continue
        if any(provenance.source_timestamp == timestamp for provenance in fact.provenance):
            return True
    return False


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

    A newer unresolved candidate blocks stale fallback. Supplementary growth/bps
    representations are the sole exception when a valid absolute fact for the
    same metric/period/scope/basis is accepted at that exact source timestamp.
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
        codes = {violation.code for violation in violations}
        if (
            codes
            and codes.issubset(_SUPPLEMENTARY_VALUE_QUARANTINE)
            and _has_same_snapshot_absolute_replacement(result, ticker, item.fact, latest)
        ):
            continue
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
