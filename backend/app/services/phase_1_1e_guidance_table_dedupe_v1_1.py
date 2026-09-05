from __future__ import annotations

from app.domain.soe_v1_1 import ExtractionMethod, GuidanceMetricRecord
from app.services.phase_1_1e_evidence_hygiene_round4_v1_1 import _action_consistent_history
from app.services.phase_1_1e_guidance_scope_guard_round8_v1_1 import dedupe_guidance_records_round8


_PREFIX = "normalized_comparative_guidance_table;"


def _is_normalized_table_record(record: GuidanceMetricRecord) -> bool:
    return (
        record.extraction_method is ExtractionMethod.STRUCTURED
        and (record.evidence_span or "").startswith(_PREFIX)
    )


def dedupe_guidance_records_table_normalized(
    records: list[GuidanceMetricRecord],
) -> list[GuidanceMetricRecord]:
    """Global guidance dedupe with structured table records as authoritative.

    Generic Round-8 evidence remains fully hardened. When a normalized
    comparative-table record exists, conflicting generic records from the same
    ticker/source timestamp/metric/fiscal scope are removed before ledger use.
    This prevents a later global dedupe pass from re-running prose binders over
    the structured table record and undoing its row/unit normalization.
    """
    table_records = [item for item in records if _is_normalized_table_record(item)]
    generic_records = [item for item in records if not _is_normalized_table_record(item)]
    generic_records = dedupe_guidance_records_round8(generic_records)

    authoritative = {
        (item.ticker, item.source_timestamp, item.metric, item.fiscal_period)
        for item in table_records
    }
    generic_records = [
        item
        for item in generic_records
        if (item.ticker, item.source_timestamp, item.metric, item.fiscal_period) not in authoritative
    ]

    # Table normalizer already emits one current row per metric/scope/source.
    # Retain deterministic de-duplication in case the same exhibit is encountered
    # through more than one filing-document reference.
    table_unique: dict[tuple, GuidanceMetricRecord] = {}
    for item in table_records:
        key = (
            item.ticker,
            item.source_timestamp,
            item.metric,
            item.fiscal_period,
            item.accounting_basis,
            item.low,
            item.high,
            item.source_url,
        )
        table_unique[key] = item

    combined = [*generic_records, *table_unique.values()]
    combined = _action_consistent_history(combined)
    return sorted(
        combined,
        key=lambda item: (
            item.source_timestamp,
            item.metric.value,
            item.fiscal_period,
            item.accounting_basis,
            item.source_url,
        ),
    )
