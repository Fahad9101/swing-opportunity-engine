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
        """Return latest and prior assessment-eligible facts per comparison key.

        Raw extracted records remain immutable in the ledger. Evidence-quality
        filtering occurs only when constructing the assessment view, so rejected
        facts remain auditable rather than silently deleted.
        """
        as_of = as_of or datetime.now(UTC)
        eligible = [
            item
            for item in self._records
            if item.ticker == ticker and item.source_timestamp <= as_of and _assessment_eligible(item)
        ]
        by_key: dict[tuple[str, str, str], list[GuidanceMetricRecord]] = defaultdict(list)
        for item in eligible:
            by_key[item.comparison_key].append(item)

        current: list[GuidanceMetricRecord] = []
        prior: list[GuidanceMetricRecord] = []
        for rows in by_key.values():
            rows = sorted(rows, key=lambda item: (item.source_timestamp, str(item.record_id)))
            timestamps = sorted({item.source_timestamp for item in rows})
            latest_ts = timestamps[-1]
            current.extend(item for item in rows if item.source_timestamp == latest_ts)
            if len(timestamps) >= 2:
                prior_ts = timestamps[-2]
                prior.extend(item for item in rows if item.source_timestamp == prior_ts)
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
