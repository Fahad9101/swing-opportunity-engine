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
_DIRECTIONAL_ACTIONS = {GuidanceAction.RAISE, GuidanceAction.LOWER}
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
    """One point-in-time observation of one canonical guidance fact."""

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


def _midpoint(item: CanonicalGuidanceObservation) -> float | None:
    if item.fact.low is None or item.fact.high is None:
        return None
    return (item.fact.low + item.fact.high) / 2.0


def _resolve_latest_current_rows(
    rows: Iterable[CanonicalGuidanceObservation],
) -> tuple[CanonicalGuidanceObservation | None, CanonicalGuidanceObservation | None]:
    """Resolve one latest current value and, when explicit, one quoted prior.

    Same-value NONE/INITIATE duplicates are already non-conflicting. When two
    different numeric values coexist at one timestamp, resolve them only if one
    unique RAISE/LOWER value is explicit and the other unique value is
    directionally consistent as the pre-change guidance. Any additional value,
    contradictory action, or ambiguity remains a hard conflict.
    """
    rows = list(rows)
    chosen = _choose_consistent_observation(rows)
    if chosen is not None:
        return chosen, None

    directional = [row for row in rows if row.fact.explicit_action in _DIRECTIONAL_ACTIONS]
    directions = {row.fact.explicit_action for row in directional}
    directional_values = {(row.fact.low, row.fact.high) for row in directional}
    if len(directions) != 1 or len(directional_values) != 1:
        return None, None

    direction = next(iter(directions))
    current = sorted(directional, key=_observation_sort_key)[-1]
    current_value = (current.fact.low, current.fact.high)

    prior_rows = [row for row in rows if (row.fact.low, row.fact.high) != current_value]
    if not prior_rows:
        return current, None
    if any(row.fact.explicit_action not in {GuidanceAction.NONE, GuidanceAction.INITIATE} for row in prior_rows):
        return None, None
    prior_values = {(row.fact.low, row.fact.high) for row in prior_rows}
    if len(prior_values) != 1:
        return None, None

    prior = _choose_consistent_observation(prior_rows)
    if prior is None:
        return None, None
    current_midpoint = _midpoint(current)
    prior_midpoint = _midpoint(prior)
    if current_midpoint is None or prior_midpoint is None:
        return None, None
    if direction is GuidanceAction.RAISE and current_midpoint <= prior_midpoint:
        return None, None
    if direction is GuidanceAction.LOWER and current_midpoint >= prior_midpoint:
        return None, None
    return current, prior


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
    """Canonical-only point-in-time ledger."""

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

        current_candidates = [item for item in eligible if item.fact.role is GuidanceFactRole.CURRENT]
        if not current_candidates:
            return CanonicalGuidanceView(ticker=ticker, as_of=as_of, current=(), prior=())

        latest_ts = max(item.available_at for item in current_candidates)
        latest_current = [item for item in current_candidates if item.available_at == latest_ts]
        current_by_key: dict[tuple, list[CanonicalGuidanceObservation]] = defaultdict(list)
        for item in latest_current:
            current_by_key[item.comparison_key].append(item)

        current: list[CanonicalGuidanceObservation] = []
        prior: list[CanonicalGuidanceObservation] = []
        conflicts: list[str] = []
        for key, rows in current_by_key.items():
            chosen_current, same_snapshot_prior = _resolve_latest_current_rows(rows)
            if chosen_current is None:
                conflicts.append(f"conflicting current canonical values for key={key}")
                continue
            current.append(chosen_current)

            if same_snapshot_prior is not None:
                prior.append(same_snapshot_prior)
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
                continue

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
    """Migration-only helper preserving same-snapshot quoted-prior roles."""
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