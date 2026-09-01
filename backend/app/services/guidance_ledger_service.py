from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import Iterable

from app.domain.soe_v1_1 import GuidanceAssessment, GuidanceMetricRecord, GuidancePolicyEvidence
from app.services.guidance_classifier import classify_guidance


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
        as_of = as_of or datetime.now(UTC)
        eligible = [
            item
            for item in self._records
            if item.ticker == ticker and item.verified and item.source_timestamp <= as_of
        ]
        by_key: dict[tuple[str, str, str], list[GuidanceMetricRecord]] = defaultdict(list)
        for item in eligible:
            by_key[item.comparison_key].append(item)

        current: list[GuidanceMetricRecord] = []
        prior: list[GuidanceMetricRecord] = []
        for rows in by_key.values():
            rows = sorted(rows, key=lambda item: (item.source_timestamp, str(item.record_id)))
            current.append(rows[-1])
            if len(rows) >= 2:
                prior.append(rows[-2])
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
