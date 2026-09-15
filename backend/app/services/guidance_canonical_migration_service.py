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
_BETWEEN_RANGE = re.compile(
    r"\bbetween\s+"
    r"(?P<d1>\$)?\s*(?P<lo>\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<s1>billion|million|thousand|bn|mm|m|b)?\s*"
    r"(?P<p1>%|bps|basis points)?\s+and\s+"
    r"(?P<d2>\$)?\s*(?P<hi>\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<s2>billion|million|thousand|bn|mm|m|b)?\s*"
    r"(?P<p2>%|bps|basis points)?",
    re.I,
)
_NON_COMPANY_REVENUE = re.compile(
    r"\b(?P<label>(?:annual\s+recurring|subscription|segment|product|service|services)\s+revenue)\b",
    re.I,
)
_COMPANY_REVENUE = re.compile(
    r"\b(?P<label>(?:total\s+(?:net\s+)?product\s+revenue|"
    r"(?:total|consolidated|company[- ]wide)\s+(?:net\s+)?revenues?|net\s+sales))\b",
    re.I,
)


def _nearly_equal(left: float, right: float) -> bool:
    return abs(left - right) <= max(1e-7, abs(right) * 1e-7)


def _raw_bound_values(value_text: str | None) -> tuple[float | None, float | None]:
    if not value_text:
        return None, None
    values = [float(token.replace(",", "")) for token in _NUMBER.findall(value_text)]
    if not values:
        return None, None
    if len(values) == 1:
        return values[0], values[0]
    return values[0], values[1]


def _unit_from_range_tokens(record: GuidanceMetricRecord, match: re.Match[str]) -> GuidanceUnit:
    groups = match.groupdict()
    pct = (groups.get("p2") or groups.get("p1") or "").lower()
    if pct:
        if "bp" in pct or "basis" in pct:
            return GuidanceUnit.BASIS_POINTS
        return GuidanceUnit.PERCENT
    scale = (groups.get("s2") or groups.get("s1") or "").lower()
    if scale in {"b", "bn", "billion"}:
        return GuidanceUnit.USD_BILLION
    if scale in {"m", "mm", "million"}:
        return GuidanceUnit.USD_MILLION
    if scale == "thousand":
        return GuidanceUnit.USD_THOUSAND
    if record.metric is GuidanceMetric.EPS:
        return GuidanceUnit.USD_PER_SHARE
    return GuidanceUnit.USD


def _canonical_pair(low: float, high: float, unit: GuidanceUnit) -> tuple[float, float]:
    scale = {
        GuidanceUnit.USD_THOUSAND: 1_000.0,
        GuidanceUnit.USD_MILLION: 1_000_000.0,
        GuidanceUnit.USD_BILLION: 1_000_000_000.0,
    }.get(unit, 1.0)
    if unit is GuidanceUnit.PERCENT:
        return low / 100.0, high / 100.0
    if unit is GuidanceUnit.BASIS_POINTS:
        return low / 10_000.0, high / 10_000.0
    return low * scale, high * scale


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


def _migration_value_binding(
    record: GuidanceMetricRecord,
    fact,
) -> tuple[float | None, float | None, GuidanceUnit, int | None]:
    """Recover source-level value/unit/anchor exactly once for legacy migration.

    The permanent raw extractor will emit this binding directly. This bridge
    exists because the repaired Phase-1.1E ledger already contains normalized
    values while some original issuer phrasings (notably "between X and Y") were
    never represented in EvidenceBinding.value_text.
    """
    evidence = fact.provenance[0].evidence
    raw_low, raw_high = _raw_bound_values(evidence.value_text)
    if raw_low is not None and raw_high is not None:
        return raw_low, raw_high, _source_unit(fact), evidence.value_start

    if record.low is None or record.high is None:
        return None, None, fact.unit, None

    for match in _BETWEEN_RANGE.finditer(evidence.full_text):
        low = float(match.group("lo").replace(",", ""))
        high = float(match.group("hi").replace(",", ""))
        if low > high:
            continue
        unit = _unit_from_range_tokens(record, match)
        canonical_low, canonical_high = _canonical_pair(low, high, unit)
        if _nearly_equal(canonical_low, record.low) and _nearly_equal(canonical_high, record.high):
            return low, high, unit, match.start()

    return None, None, fact.unit, None


def _nearest_revenue_scope(
    fact,
    *,
    value_anchor: int | None = None,
) -> tuple[GuidanceScopeKind, str | None]:
    """Bind revenue scope to the phrase that owns the selected numeric value.

    Metric normalization deliberately collapses phrases such as "net product
    revenue" to the REVENUE metric. Scope is recovered independently from the
    nearest source phrase before the bound value. A longer/more-specific phrase
    wins ties, so "total product revenue" is company-wide while named-product
    "product revenue" remains non-company scope.
    """
    if fact.metric is not GuidanceMetric.REVENUE:
        return GuidanceScopeKind.COMPANY, None

    evidence = fact.provenance[0].evidence
    anchor = value_anchor if value_anchor is not None else evidence.value_start
    if anchor is None:
        local = evidence.metric_text or ""
        company = list(_COMPANY_REVENUE.finditer(local))
        non_company = list(_NON_COMPANY_REVENUE.finditer(local))
        candidates: list[tuple[int, GuidanceScopeKind, str]] = []
        for match in company:
            label = match.group("label")
            candidates.append((-len(label), GuidanceScopeKind.COMPANY, label))
        for match in non_company:
            label = match.group("label")
            kind = GuidanceScopeKind.SEGMENT if "segment" in label.lower() else GuidanceScopeKind.PRODUCT
            candidates.append((-len(label), kind, label))
        if not candidates:
            return GuidanceScopeKind.COMPANY, None
        _, kind, label = min(candidates, key=lambda item: item[0])
        return kind, label

    left = max(0, anchor - 260)
    prefix = evidence.full_text[left:anchor]
    candidates: list[tuple[int, int, GuidanceScopeKind, str]] = []

    for match in _NON_COMPANY_REVENUE.finditer(prefix):
        label = match.group("label")
        kind = GuidanceScopeKind.SEGMENT if "segment" in label.lower() else GuidanceScopeKind.PRODUCT
        distance = len(prefix) - match.end()
        candidates.append((distance, -len(label), kind, label))

    for match in _COMPANY_REVENUE.finditer(prefix):
        label = match.group("label")
        distance = len(prefix) - match.end()
        candidates.append((distance, -len(label), GuidanceScopeKind.COMPANY, label))

    if not candidates:
        return GuidanceScopeKind.COMPANY, None

    distance, _, kind, label = min(candidates, key=lambda item: (item[0], item[1]))
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
    raw_low, raw_high, unit, value_anchor = _migration_value_binding(record, fact)
    scope_kind, scope_label = _nearest_revenue_scope(fact, value_anchor=value_anchor)

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
