from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Iterable

from app.domain.guidance_canonical_v1 import (
    CanonicalGuidanceFact,
    GuidanceFactRole,
    GuidanceProvenance,
    GuidanceScopeKind,
    GuidanceUnit,
)
from app.domain.soe_v1_1 import (
    ExtractionMethod,
    GuidanceAction,
    GuidanceAssessment,
    GuidanceClassification,
    GuidanceMetricRecord,
)
from app.services.guidance_canonical_service import canonicalize_legacy_records
from app.services.guidance_classifier import classify_guidance


_EXPLICIT_ACTIONS = {
    GuidanceAction.RAISE,
    GuidanceAction.LOWER,
    GuidanceAction.REAFFIRM,
    GuidanceAction.WITHDRAW,
}
_ACTION_PRIORITY = {
    GuidanceAction.NONE: 0,
    GuidanceAction.INITIATE: 1,
    GuidanceAction.REAFFIRM: 2,
    GuidanceAction.RAISE: 3,
    GuidanceAction.LOWER: 3,
    GuidanceAction.WITHDRAW: 4,
}


@dataclass(frozen=True)
class CanonicalGuidanceObservation:
    """One point-in-time observation of one canonical guidance fact.

    Canonical normalization is allowed to merge identical semantic facts from
    multiple documents. Chronology must not be lost when the same guidance is
    repeated on different dates, so the ledger expands merged provenance back
    into timestamp-specific observations without reparsing source prose.
    """

    fact: CanonicalGuidanceFact
    available_at: datetime
    provenance: tuple[GuidanceProvenance, ...]

    @property
    def comparison_key(self) -> tuple[str, str, str, str, str, str, str]:
        fact = self.fact
        scope_label = (
            ""
            if fact.scope_kind is GuidanceScopeKind.COMPANY
            else (fact.scope_label or "")
        )
        return (
            fact.metric.value,
            fact.fiscal_period,
            fact.accounting_basis,
            fact.scope_kind.value,
            scope_label,
            fact.value_kind.value,
            fact.unit.value,
        )


@dataclass(frozen=True)
class CanonicalGuidanceView:
    ticker: str
    as_of: datetime
    current: tuple[CanonicalGuidanceObservation, ...]
    prior: tuple[CanonicalGuidanceObservation, ...]
    conflicts: tuple[str, ...] = ()


def _observation_sort_key(item: CanonicalGuidanceObservation) -> tuple:
    fact = item.fact
    return (
        item.available_at,
        fact.metric.value,
        fact.fiscal_period,
        fact.accounting_basis,
        str(fact.canonical_id),
    )


def _point_in_time_observations(facts: Iterable[CanonicalGuidanceFact]) -> list[CanonicalGuidanceObservation]:
    observations: list[CanonicalGuidanceObservation] = []
    for fact in facts:
        by_timestamp: dict[datetime, list[GuidanceProvenance]] = defaultdict(list)
        for provenance in fact.provenance:
            by_timestamp[provenance.source_timestamp].append(provenance)
        for available_at, provenance in by_timestamp.items():
            observations.append(
                CanonicalGuidanceObservation(
                    fact=fact,
                    available_at=available_at,
                    provenance=tuple(
                        sorted(
                            provenance,
                            key=lambda item: (
                                item.source_url,
                                item.source_accession or "",
                                item.source_document_hash or "",
                            ),
                        )
                    ),
                )
            )
    return sorted(observations, key=_observation_sort_key)


def _observations_conflict(rows: Iterable[CanonicalGuidanceObservation]) -> bool:
    rows = list(rows)
    numeric_values = {(row.fact.low, row.fact.high) for row in rows}
    if len(numeric_values) > 1:
        return True

    explicit_actions = {
        row.fact.explicit_action
        for row in rows
        if row.fact.explicit_action in _EXPLICIT_ACTIONS
    }
    return len(explicit_actions) > 1


def _choose_consistent_observation(
    rows: Iterable[CanonicalGuidanceObservation],
) -> CanonicalGuidanceObservation | None:
    rows = list(rows)
    if not rows or _observations_conflict(rows):
        return None
    return sorted(
        rows,
        key=lambda item: (
            _ACTION_PRIORITY.get(item.fact.explicit_action, 0),
            _observation_sort_key(item),
        ),
    )[-1]


def _same_snapshot_conflicts(
    observations: Iterable[CanonicalGuidanceObservation],
) -> list[str]:
    grouped: dict[tuple, list[CanonicalGuidanceObservation]] = defaultdict(list)
    for item in observations:
        grouped[(item.available_at, item.comparison_key, item.fact.role.value)].append(item)

    conflicts: list[str] = []
    for (available_at, key, role), rows in grouped.items():
        if _observations_conflict(rows):
            conflicts.append(
                f"conflicting canonical facts at {available_at.isoformat()} "
                f"for key={key} role={role}"
            )
    return sorted(conflicts)


def _legacy_unit(fact: CanonicalGuidanceFact) -> str:
    if fact.unit is GuidanceUnit.USD:
        return "USD"
    if fact.unit is GuidanceUnit.USD_PER_SHARE:
        return "USD/share"
    if fact.unit is GuidanceUnit.FRACTION:
        return "fraction"
    if fact.unit is GuidanceUnit.UNKNOWN and fact.low is None and fact.high is None:
        return "UNKNOWN"
    raise ValueError(f"Canonical unit {fact.unit.value} is not comparator-compatible")


def _observation_to_legacy_record(
    observation: CanonicalGuidanceObservation,
    *,
    rules_hash: str,
) -> GuidanceMetricRecord:
    """Temporary typed compatibility adapter to the frozen pure classifier.

    No metric, period, basis, scope, role, unit, or numeric value is inferred
    from evidence text here. The evidence span is retained only for provenance.
    """
    fact = observation.fact
    if not observation.provenance:
        raise ValueError("Canonical guidance observation must retain provenance")
    primary = min(
        observation.provenance,
        key=lambda item: (item.source_timestamp, item.source_url),
    )
    return GuidanceMetricRecord(
        rules_hash=rules_hash,
        ticker=fact.ticker,
        fiscal_period=fact.fiscal_period,
        metric=fact.metric,
        accounting_basis=fact.accounting_basis,
        low=fact.low,
        high=fact.high,
        unit=_legacy_unit(fact),
        source=primary.source,
        source_url=primary.source_url,
        source_accession=primary.source_accession,
        source_timestamp=observation.available_at,
        explicit_action=fact.explicit_action,
        verified=True,
        extraction_method=ExtractionMethod.STRUCTURED,
        evidence_span=primary.evidence.full_text,
        source_document_hash=primary.source_document_hash,
        as_of=observation.available_at,
        fetched_at=observation.available_at,
        stale=False,
    )


class CanonicalGuidanceLedger:
    """Canonical-only point-in-time ledger.

    This is the architectural boundary after invariant validation and canonical
    normalization. It never reparses raw SEC prose to alter metric, period,
    accounting basis, scope, unit, role, or value.
    """

    def __init__(self, facts: Iterable[CanonicalGuidanceFact] | None = None):
        self._facts = tuple(facts or ())
        self._observations = tuple(_point_in_time_observations(self._facts))

    @property
    def facts(self) -> tuple[CanonicalGuidanceFact, ...]:
        return self._facts

    @property
    def observations(self) -> tuple[CanonicalGuidanceObservation, ...]:
        return self._observations

    def current_and_prior(
        self,
        ticker: str,
        *,
        as_of: datetime | None = None,
    ) -> CanonicalGuidanceView:
        as_of = as_of or datetime.now(UTC)
        eligible = [
            item
            for item in self._observations
            if item.fact.ticker == ticker
            and item.available_at <= as_of
            and item.fact.role in {GuidanceFactRole.CURRENT, GuidanceFactRole.QUOTED_PRIOR}
        ]
        if not eligible:
            return CanonicalGuidanceView(ticker=ticker, as_of=as_of, current=(), prior=())

        conflicts = _same_snapshot_conflicts(eligible)
        current_candidates = [item for item in eligible if item.fact.role is GuidanceFactRole.CURRENT]
        if not current_candidates:
            return CanonicalGuidanceView(
                ticker=ticker,
                as_of=as_of,
                current=(),
                prior=(),
                conflicts=tuple(conflicts),
            )

        latest_ts = max(item.available_at for item in current_candidates)
        latest_current = [item for item in current_candidates if item.available_at == latest_ts]
        current_by_key: dict[tuple, list[CanonicalGuidanceObservation]] = defaultdict(list)
        for item in latest_current:
            current_by_key[item.comparison_key].append(item)

        current: list[CanonicalGuidanceObservation] = []
        prior: list[CanonicalGuidanceObservation] = []
        for key, rows in current_by_key.items():
            chosen_current = _choose_consistent_observation(rows)
            if chosen_current is None:
                conflicts.append(f"conflicting current canonical values for key={key}")
                continue
            current.append(chosen_current)

            older = [
                item
                for item in current_candidates
                if item.comparison_key == key and item.available_at < latest_ts
            ]
            if older:
                prior_ts = max(item.available_at for item in older)
                prior_rows = [item for item in older if item.available_at == prior_ts]
                chosen_prior = _choose_consistent_observation(prior_rows)
                if chosen_prior is None:
                    conflicts.append(f"conflicting prior canonical values for key={key}")
                else:
                    prior.append(chosen_prior)
                continue

            quoted = [
                item
                for item in eligible
                if item.fact.role is GuidanceFactRole.QUOTED_PRIOR
                and item.available_at == latest_ts
                and item.comparison_key == key
            ]
            if quoted:
                chosen_quoted = _choose_consistent_observation(quoted)
                if chosen_quoted is None:
                    conflicts.append(f"conflicting quoted-prior canonical values for key={key}")
                else:
                    prior.append(chosen_quoted)

        return CanonicalGuidanceView(
            ticker=ticker,
            as_of=as_of,
            current=tuple(sorted(current, key=_observation_sort_key)),
            prior=tuple(sorted(prior, key=_observation_sort_key)),
            conflicts=tuple(sorted(set(conflicts))),
        )

    def assess(
        self,
        ticker: str,
        rules: dict,
        *,
        rules_hash: str,
        as_of: datetime | None = None,
    ) -> GuidanceAssessment:
        view = self.current_and_prior(ticker, as_of=as_of)
        if view.conflicts:
            return GuidanceAssessment(
                rules_hash=rules_hash,
                ticker=ticker,
                as_of=view.as_of,
                classification=GuidanceClassification.UNKNOWN,
                guidance_deterioration=None,
                rule_path="guidance_v1_1.canonical_conflict",
                reasons=list(view.conflicts),
                sources=sorted(
                    {
                        provenance.source_url
                        for observation in (*view.current, *view.prior)
                        for provenance in observation.provenance
                    }
                ),
            )

        current_records: list[GuidanceMetricRecord] = []
        prior_keys = {item.comparison_key for item in view.prior}
        for observation in view.current:
            record = _observation_to_legacy_record(observation, rules_hash=rules_hash)
            if (
                observation.comparison_key not in prior_keys
                and record.midpoint is not None
                and record.explicit_action is GuidanceAction.NONE
            ):
                record = record.model_copy(update={"explicit_action": GuidanceAction.INITIATE})
            current_records.append(record)

        prior_records = [
            _observation_to_legacy_record(observation, rules_hash=rules_hash)
            for observation in view.prior
        ]

        if not current_records and not prior_records:
            return GuidanceAssessment(
                rules_hash=rules_hash,
                ticker=ticker,
                as_of=view.as_of,
                classification=GuidanceClassification.UNKNOWN,
                guidance_deterioration=None,
                rule_path="guidance_v1_1.no_canonical_guidance",
                reasons=["No accepted canonical guidance facts are available."],
                sources=[],
            )

        return classify_guidance(
            current_records,
            prior_records,
            rules,
            rules_hash=rules_hash,
            as_of=view.as_of,
        )


def canonicalize_legacy_records_with_roles(
    records: Iterable[GuidanceMetricRecord],
):
    """Migration-only helper preserving same-snapshot quoted-prior roles.

    The permanent extractor should emit roles directly. This bridge exists only
    for differential validation of the historical Phase 1.1E ledger.
    """
    records = list(records)
    result = canonicalize_legacy_records(records)
    quoted_prior_ids = {
        str(record.supersedes_record_id)
        for record in records
        if record.supersedes_record_id is not None
        and any(
            candidate.record_id == record.supersedes_record_id
            and candidate.source_timestamp == record.source_timestamp
            for candidate in records
        )
    }

    accepted: list[CanonicalGuidanceFact] = []
    for fact in result.accepted:
        legacy_id = str(fact.metadata.get("legacy_record_id") or "")
        if legacy_id in quoted_prior_ids:
            fact = fact.model_copy(update={"role": GuidanceFactRole.QUOTED_PRIOR})
        accepted.append(fact)
    return result.model_copy(update={"accepted": accepted})