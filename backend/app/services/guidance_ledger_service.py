from __future__ import annotations

import re
from collections import defaultdict
from datetime import UTC, datetime
from typing import Iterable

from app.domain.soe_v1_1 import (
    GuidanceAction,
    GuidanceAssessment,
    GuidanceMetric,
    GuidanceMetricRecord,
    GuidancePolicyEvidence,
)
from app.services.guidance_classifier import classify_guidance


_GUIDANCE_CONTEXT = re.compile(
    r"\b(?:guidance|outlook|forecast|financial\s+targets?|targets?|expects?|anticipates?|projects?)\b",
    re.I,
)
_ACTUAL_MARKER = re.compile(
    r"\b(?:reported|achieved|was|were|grew|increased|decreased|compared\s+(?:with|to)|results?)\b",
    re.I,
)
_UNSUPPORTED_REVENUE = re.compile(
    r"\b(?:annual\s+recurring|subscription|segment|product|service|services)\s+revenue\b",
    re.I,
)
_FORWARD_VERB = re.compile(r"\b(?:expects?|anticipates?|projects?|forecast(?:s|ed|ing)?)\b", re.I)


def _assessment_eligible(record: GuidanceMetricRecord) -> bool:
    """Return whether an extracted fact may participate in guidance assessment.

    Structured/manual records without an evidence span are accepted unchanged.
    Deterministic text records are screened for primary-metric scope and obvious
    reported-actual contamination before they can create current/prior pairs.
    """
    if not record.verified:
        return False
    text = (record.evidence_span or "").strip()
    if not text:
        return True

    if record.metric is GuidanceMetric.REVENUE and _UNSUPPORTED_REVENUE.search(text):
        # SOE-1.1 primary revenue means company-level revenue/net sales, not ARR,
        # subscription, product, service, or segment revenue.
        if not re.search(r"\b(?:total|consolidated)\s+revenue\b|\bnet\s+sales\b", text, re.I):
            return False

    if record.midpoint is None:
        # Qualitative guidance facts are useful only when an explicit management
        # action is present in genuine forward-guidance context.
        return (
            record.explicit_action
            in {GuidanceAction.RAISE, GuidanceAction.REAFFIRM, GuidanceAction.LOWER, GuidanceAction.WITHDRAW}
            and bool(_GUIDANCE_CONTEXT.search(text))
        )

    if not _GUIDANCE_CONTEXT.search(text):
        return False

    # A single reported/achieved historical value embedded near a guidance
    # headline must not become a guidance midpoint. Explicit forward verbs are
    # the narrow exception for true point guidance such as "expects revenue of".
    if record.low == record.high and _ACTUAL_MARKER.search(text) and not _FORWARD_VERB.search(text):
        return False

    return True


def _snapshot_timestamp(records: list[GuidanceMetricRecord]) -> datetime | None:
    """Return the latest timestamp that contains assessment-eligible guidance.

    Guidance classification is about the latest management guidance update, not
    the latest surviving record for every historical fiscal period. Old quarters
    therefore cannot remain in the current set indefinitely and block a new
    comparable annual guidance assessment.
    """
    if not records:
        return None
    return max(item.source_timestamp for item in records)


class GuidanceLedger:
    """Append-only in-memory guidance ledger used by extraction and validation paths.

    Persistence is delegated to GuidanceRepository. The ledger never mutates an
    existing record; supersession is represented by a copied record carrying
    supersedes_record_id before persistence.
    """

    def __init__(self, records: Iterable[GuidanceMetricRecord] | None = None):
        self._records: list[GuidanceMetricRecord] = sorted(
            list(records or []),
            key=lambda item: (item.ticker, item.source_timestamp, str(item.record_id)),
        )

    @property
    def records(self) -> list[GuidanceMetricRecord]:
        return list(self._records)

    def add(self, record: GuidanceMetricRecord) -> GuidanceMetricRecord:
        same_key = [
            item
            for item in self._records
            if item.ticker == record.ticker
            and item.comparison_key == record.comparison_key
            and item.source_timestamp <= record.source_timestamp
        ]
        supersedes = max(
            same_key,
            key=lambda item: (item.source_timestamp, str(item.record_id)),
            default=None,
        )
        if record.supersedes_record_id is None and supersedes is not None:
            record = record.model_copy(update={"supersedes_record_id": supersedes.record_id})
        self._records.append(record)
        self._records.sort(key=lambda item: (item.ticker, item.source_timestamp, str(item.record_id)))
        return record

    def add_many(self, records: Iterable[GuidanceMetricRecord]) -> list[GuidanceMetricRecord]:
        return [self.add(record) for record in sorted(records, key=lambda item: item.source_timestamp)]

    def current_and_prior(
        self,
        ticker: str,
        *,
        as_of: datetime | None = None,
    ) -> tuple[list[GuidanceMetricRecord], list[GuidanceMetricRecord]]:
        """Return the latest guidance snapshot and its latest comparable priors.

        The current set is restricted to the newest assessment-eligible source
        timestamp. For each current comparison key, the prior set contains the
        latest older assessment-eligible version of that same key. Historical
        fiscal periods not repeated in the latest guidance update are excluded
        from the current set rather than lingering forever.

        A current numeric NONE-action key with no historical version is treated
        as an implicitly initiated metric/period *only in the assessment view*.
        The immutable ledger record is not changed. This mirrors the existing
        SOE-1.1 rule that an explicitly initiated new metric must not block other
        genuinely comparable metrics. If no comparable prior exists for any key,
        the classifier still returns UNKNOWN.
        """
        as_of = as_of or datetime.now(UTC)
        eligible = [
            item
            for item in self._records
            if item.ticker == ticker and item.source_timestamp <= as_of and _assessment_eligible(item)
        ]
        latest_ts = _snapshot_timestamp(eligible)
        if latest_ts is None:
            return [], []

        current_raw = [item for item in eligible if item.source_timestamp == latest_ts]
        current_by_key: dict[tuple[str, str, str], list[GuidanceMetricRecord]] = defaultdict(list)
        for item in current_raw:
            current_by_key[item.comparison_key].append(item)

        current: list[GuidanceMetricRecord] = []
        prior: list[GuidanceMetricRecord] = []
        for key, rows in current_by_key.items():
            older = [
                item
                for item in eligible
                if item.comparison_key == key and item.source_timestamp < latest_ts
            ]
            if older:
                prior_ts = max(item.source_timestamp for item in older)
                prior.extend(item for item in older if item.source_timestamp == prior_ts)
                current.extend(rows)
                continue

            # New metric/period introduced in the latest snapshot. Do not mutate
            # the ledger; mark NONE-action numeric facts as initiated in the
            # assessment view so they cannot make a separate comparable set null.
            for item in rows:
                if item.midpoint is not None and item.explicit_action is GuidanceAction.NONE:
                    current.append(item.model_copy(update={"explicit_action": GuidanceAction.INITIATE}))
                else:
                    current.append(item)

        current.sort(key=lambda item: (item.metric.value, item.fiscal_period, item.accounting_basis, str(item.record_id)))
        prior.sort(key=lambda item: (item.metric.value, item.fiscal_period, item.accounting_basis, str(item.record_id)))
        return current, prior

    def assess(
        self,
        ticker: str,
        rules: dict,
        *,
        rules_hash: str,
        policy: GuidancePolicyEvidence | None = None,
        as_of: datetime | None = None,
    ) -> GuidanceAssessment:
        current, prior = self.current_and_prior(ticker, as_of=as_of)
        return classify_guidance(
            current,
            prior,
            rules,
            rules_hash=rules_hash,
            policy=policy,
            as_of=as_of,
        )
