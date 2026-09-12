from __future__ import annotations

import re
from typing import Iterable

from app.domain.guidance_canonical_v1 import (
    CanonicalizationResult,
    GuidanceFactRole,
    GuidanceScopeKind,
    GuidanceUnit,
    GuidanceValueKind,
)
from app.domain.soe_v1_1 import GuidanceMetric, GuidanceMetricRecord
from app.services.guidance_canonical_service import (
    CanonicalGuidanceNormalizer,
    GuidanceInvariantValidator,
    typed_fact_from_legacy_record,
)


_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
_MILLION_HEADER = re.compile(r"\b(?:USD|\$)\s*(?:in\s+)?millions?\b|\bin\s+millions?\b", re.I)
_BILLION_HEADER = re.compile(r"\b(?:USD|\$)\s*(?:in\s+)?billions?\b|\bin\s+billions?\b", re.I)
_THOUSAND_HEADER = re.compile(r"\b(?:USD|\$)\s*(?:in\s+)?thousands?\b|\bin\s+thousands?\b", re.I)
_NON_COMPANY_REVENUE = re.compile(
    r"\b(?P<label>(?:annual\s+recurring|subscription|segment|product|service|services)\s+revenue)\b",
    re.I,
)
_COMPANY_REVENUE = re.compile(
    r"\b(?P<label>(?:total|consolidated|company[- ]wide)\s+(?:net\s+)?revenues?|net\s+sales)\b",
    re.I,
)


def _raw_bound_values(value_text: str | None) -> tuple[float | None, float | None]:
    if not value_text:
        return None, None
    values = [float(token.replace(",", "")) for token in _NUMBER.findall(value_text)]
    if not values:
        return None, None
    if len(values) == 1:
        return values[0], values[0]
    return values[0], values[1]


def _source_unit(fact) -> GuidanceUnit:
    """Recover the source presentation unit before canonical normalization.

    The Phase-1.1E legacy ledger already stores normalized values. Migration must
    use the raw bound source numbers plus their source unit so normalization is
    applied exactly once.
    """
    provenance = fact.provenance[0]
    evidence = provenance.evidence
    unit = fact.unit
    if unit is not GuidanceUnit.USD or evidence.value_start is None:
        return unit
    prefix = evidence.full_text[max(0, evidence.value_start - 200): evidence.value_start]
    if _BILLION_HEADER.search(prefix):
        return GuidanceUnit.USD_BILLION
    if _MILLION_HEADER.search(prefix):
        return GuidanceUnit.USD_MILLION
    if _THOUSAND_HEADER.search(prefix):
        return GuidanceUnit.USD_THOUSAND
    return unit


def _nearest_revenue_scope(fact) -> tuple[GuidanceScopeKind, str | None]:
    """Bind revenue scope to the phrase that owns the selected numeric value.

    Metric normalization deliberately collapses phrases such as "net product
    revenue" to the REVENUE metric. Scope is therefore recovered independently
    from the nearest source phrase before the bound value. Specific non-company
    phrases win over generic revenue; an explicit total/consolidated/net-sales
    phrase can win only when it is closer to the value.
    """
    if fact.metric is not GuidanceMetric.REVENUE:
        return GuidanceScopeKind.COMPANY, None

    evidence = fact.provenance[0].evidence
    anchor = evidence.value_start
    if anchor is None:
        # Qualitative revenue guidance has no value anchor. Use the local metric
        # phrase only; ambiguity remains company scope until the raw extractor
        # emits explicit scope directly.
        local = evidence.metric_text or ""
        match = _NON_COMPANY_REVENUE.search(local)
        if not match:
            return GuidanceScopeKind.COMPANY, None
        label = match.group("label")
        kind = GuidanceScopeKind.SEGMENT if "segment" in label.lower() else GuidanceScopeKind.PRODUCT
        return kind, label

    left = max(0, anchor - 260)
    prefix = evidence.full_text[left:anchor]
    candidates: list[tuple[int, int, GuidanceScopeKind, str]] = []

    for match in _NON_COMPANY_REVENUE.finditer(prefix):
        label = match.group("label")
        kind = GuidanceScopeKind.SEGMENT if "segment" in label.lower() else GuidanceScopeKind.PRODUCT
        distance = len(prefix) - match.end()
        # Priority 0 means a specific scope phrase wins a tie with a company
        # phrase ending at the same "revenue" token.
        candidates.append((distance, 0, kind, label))

    for match in _COMPANY_REVENUE.finditer(prefix):
        label = match.group("label")
        distance = len(prefix) - match.end()
        candidates.append((distance, 1, GuidanceScopeKind.COMPANY, label))

    if not candidates:
        return GuidanceScopeKind.COMPANY, None

    distance, _, kind, label = min(candidates, key=lambda item: (item[0], item[1]))
    # Do not let a remote phrase elsewhere in a flattened filing assign scope to
    # an unrelated value. 180 characters covers ordinary guidance table/copy
    # constructions while failing safely on distant context.
    if distance > 180:
        return GuidanceScopeKind.COMPANY, None
    return kind, label


def typed_fact_from_legacy_record_for_migration(record: GuidanceMetricRecord):
    """Point-in-time migration bridge from repaired legacy rows to typed facts.

    This function is intentionally isolated from the permanent raw-document
    extractor. It reconstructs source presentation values/units once, then the
    canonical invariant/normalization pipeline owns the fact permanently.
    """
    fact = typed_fact_from_legacy_record(record)
    evidence = fact.provenance[0].evidence
    raw_low, raw_high = _raw_bound_values(evidence.value_text)
    unit = _source_unit(fact)
    scope_kind, scope_label = _nearest_revenue_scope(fact)

    updates = {
        "unit": unit,
        "scope_kind": scope_kind,
        "scope_label": scope_label,
    }
    if raw_low is not None and raw_high is not None:
        updates["low"] = raw_low
        updates["high"] = raw_high

    # A gross/operating margin expressed as a percentage/fraction is an absolute
    # margin level even when adjacent rows contain words such as "growth".
    if fact.metric in {GuidanceMetric.GROSS_MARGIN, GuidanceMetric.OPERATING_MARGIN}:
        if unit in {GuidanceUnit.PERCENT, GuidanceUnit.FRACTION}:
            updates["value_kind"] = GuidanceValueKind.ABSOLUTE_LEVEL
        elif unit is GuidanceUnit.BASIS_POINTS:
            updates["value_kind"] = GuidanceValueKind.DELTA

    return fact.model_copy(update=updates)


def canonicalize_legacy_records_for_migration(
    records: Iterable[GuidanceMetricRecord],
) -> CanonicalizationResult:
    """Canonicalize historical Phase-1.1E rows without losing quoted-prior role."""
    records = list(records)
    by_id = {record.record_id: record for record in records}
    quoted_prior_ids = {
        record.supersedes_record_id
        for record in records
        if record.supersedes_record_id is not None
        and record.supersedes_record_id in by_id
        and by_id[record.supersedes_record_id].source_timestamp == record.source_timestamp
    }

    validator = GuidanceInvariantValidator()
    validated = []
    for record in records:
        fact = typed_fact_from_legacy_record_for_migration(record)
        if record.record_id in quoted_prior_ids:
            fact = fact.model_copy(update={"role": GuidanceFactRole.QUOTED_PRIOR})
        validated.append(validator.validate(fact))
    return CanonicalGuidanceNormalizer().normalize(validated)
