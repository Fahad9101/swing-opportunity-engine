from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Iterable
from uuid import UUID

from app.domain.guidance_canonical_v1 import (
    CanonicalGuidanceFact,
    CanonicalizationResult,
    EvidenceBinding,
    GuidanceFactRole,
    GuidanceInvariantCode,
    GuidanceInvariantViolation,
    GuidancePeriodKind,
    GuidanceProvenance,
    GuidanceScopeKind,
    GuidanceUnit,
    GuidanceValueKind,
    TypedGuidanceFact,
    ValidatedGuidanceFact,
)
from app.domain.soe_v1_1 import (
    ExtractionMethod,
    GuidanceAction,
    GuidanceMetric,
    GuidanceMetricRecord,
)


_MONEY_METRICS = {GuidanceMetric.REVENUE, GuidanceMetric.EBITDA, GuidanceMetric.FCF}
_MARGIN_METRICS = {GuidanceMetric.GROSS_MARGIN, GuidanceMetric.OPERATING_MARGIN}

_METRIC_LABELS: list[tuple[str, GuidanceMetric | None, re.Pattern[str]]] = [
    ("stock_based_compensation", None, re.compile(r"\bstock[- ]based compensation(?: expense)?\b", re.I)),
    ("gross_margin", GuidanceMetric.GROSS_MARGIN, re.compile(r"\b(?:adjusted\s+)?gross(?:\s+profit)?\s+margin\b", re.I)),
    ("operating_margin", GuidanceMetric.OPERATING_MARGIN, re.compile(r"\b(?:adjusted\s+)?operating\s+margin\b", re.I)),
    ("fcf", GuidanceMetric.FCF, re.compile(r"\b(?:adjusted\s+)?(?:free\s+cash\s+flow|FCF)\b", re.I)),
    ("ebitda", GuidanceMetric.EBITDA, re.compile(r"\b(?:adjusted\s+)?EBITDA\b", re.I)),
    ("eps", GuidanceMetric.EPS, re.compile(r"\b(?:adjusted\s+|GAAP\s+|non[- ]GAAP\s+)?(?:EPS|earnings per share)\b", re.I)),
    ("revenue", GuidanceMetric.REVENUE, re.compile(r"\b(?:total\s+revenue|net\s+(?:product\s+)?revenue|revenues?|net\s+sales)\b", re.I)),
    ("bookings", None, re.compile(r"\b(?:gross\s+)?bookings\b", re.I)),
]

_RANGE = re.compile(
    r"(?P<d1>\$)?\s*(?P<lo>\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<s1>(?:billion|million|thousand|bn|mm|m|b)\b)?\s*"
    r"(?P<p1>%|bps|basis points)?\s*"
    r"(?:to|through|-|–|—)\s*"
    r"(?P<d2>\$)?\s*(?P<hi>\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<s2>(?:billion|million|thousand|bn|mm|m|b)\b)?\s*"
    r"(?P<p2>%|bps|basis points)?",
    re.I,
)
_SINGLE = re.compile(
    r"(?P<d>\$)?\s*(?P<value>\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<scale>(?:billion|million|thousand|bn|mm|m|b)\b)?\s*"
    r"(?P<pct>%|bps|basis points)?",
    re.I,
)
_RUN94_AUTHORITY = re.compile(
    r"phase_1_1e_run94_explicit_period_authority(?:=|;\s*(?:from=[^;]+;\s*)?to=)(?P<period>Q[1-4]FY20\d{2}|FY20\d{2})",
    re.I,
)
_NORMALIZED_PERIOD = re.compile(
    r"normalized_explicit_guidance_scope;\s*(?P<period>Q[1-4]FY20\d{2}|FY\s*20\d{2})\s+guidance",
    re.I,
)
_FULL_YEAR = re.compile(
    r"\b(?:full[- ]year|fiscal\s+year|FY)\s*'?(?P<year>20\d{2})\b"
    r"|\b(?P<year2>20\d{2})\s+(?:full[- ]year|annual)\b",
    re.I,
)
_YEAR_GUIDANCE = re.compile(
    r"\b(?P<year>20\d{2})\s+(?:net\s+)?(?:product\s+)?"
    r"(?:revenue|sales|EPS|earnings|EBITDA|free\s+cash\s+flow|FCF|gross\s+margin|operating\s+margin)"
    r"\s+(?:guidance|outlook|forecast)\b",
    re.I,
)
_QUARTER = re.compile(
    r"\bQ(?P<q>[1-4])\s*(?:FY)?\s*'?(?P<year>20\d{2})\b"
    r"|\b(?P<word>first|second|third|fourth)\s+quarter(?:\s+of)?\s+"
    r"(?:fiscal(?:\s+year)?\s*)?(?P<year2>20\d{2})\b",
    re.I,
)
_QUARTER_WORD = {"first": 1, "second": 2, "third": 3, "fourth": 4}


def _period_kind(period: str) -> GuidancePeriodKind:
    if re.fullmatch(r"FY20\d{2}", period):
        return GuidancePeriodKind.FULL_YEAR
    if re.fullmatch(r"Q[1-4]FY20\d{2}", period):
        return GuidancePeriodKind.QUARTER
    return GuidancePeriodKind.UNKNOWN


def _nearly_equal(left: float, right: float) -> bool:
    return abs(left - right) <= max(1e-7, abs(right) * 1e-7)


def _unit_from_text(match: re.Match[str], record: GuidanceMetricRecord, text: str | None = None) -> GuidanceUnit:
    groups = match.groupdict()
    pct = (groups.get("p2") or groups.get("p1") or groups.get("pct") or "").lower()
    if pct:
        if "bp" in pct or "basis" in pct:
            return GuidanceUnit.BASIS_POINTS
        return GuidanceUnit.PERCENT
    scale = (groups.get("s2") or groups.get("s1") or groups.get("scale") or "").lower()
    if scale in {"b", "bn", "billion"}:
        return GuidanceUnit.USD_BILLION
    if scale in {"m", "mm", "million"}:
        return GuidanceUnit.USD_MILLION
    if scale == "thousand":
        return GuidanceUnit.USD_THOUSAND
    if text is not None:
        header = text[max(0, match.start() - 180):match.start()]
        if re.search(r"\b(?:in|\$\s*in)\s+billions?\b", header, re.I):
            return GuidanceUnit.USD_BILLION
        if re.search(r"\b(?:in|\$\s*in)\s+millions?\b", header, re.I):
            return GuidanceUnit.USD_MILLION
        if re.search(r"\b(?:in|\$\s*in)\s+thousands?\b", header, re.I):
            return GuidanceUnit.USD_THOUSAND
    if groups.get("d1") or groups.get("d2") or groups.get("d"):
        return GuidanceUnit.USD_PER_SHARE if record.metric is GuidanceMetric.EPS else GuidanceUnit.USD
    if record.unit == "USD/share":
        return GuidanceUnit.USD_PER_SHARE
    if record.unit == "fraction":
        return GuidanceUnit.FRACTION
    if record.unit == "USD":
        return GuidanceUnit.USD
    return GuidanceUnit.UNKNOWN


def _scaled_values(match: re.Match[str], unit: GuidanceUnit) -> tuple[float, float]:
    groups = match.groupdict()
    if "lo" in groups:
        low = float(groups["lo"].replace(",", ""))
        high = float(groups["hi"].replace(",", ""))
    else:
        low = high = float(groups["value"].replace(",", ""))
    scale = {
        GuidanceUnit.USD_THOUSAND: 1_000.0,
        GuidanceUnit.USD_MILLION: 1_000_000.0,
        GuidanceUnit.USD_BILLION: 1_000_000_000.0,
    }.get(unit, 1.0)
    return low * scale, high * scale


def _record_value_match(record: GuidanceMetricRecord, text: str) -> re.Match[str] | None:
    if record.low is None or record.high is None:
        return None
    for pattern in (_RANGE, _SINGLE):
        for match in pattern.finditer(text):
            unit = _unit_from_text(match, record, text)
            low, high = _scaled_values(match, unit)
            candidates = [(low, high)]
            # Existing repair layers can contain a contaminated inherited scale.
            # Locate the raw source value anyway so invariants can quarantine it.
            candidates.extend((low * scale, high * scale) for scale in (1_000.0, 1_000_000.0, 1_000_000_000.0))
            if unit is GuidanceUnit.PERCENT and record.unit == "fraction":
                candidates.append((low / 100.0, high / 100.0))
            if unit is GuidanceUnit.BASIS_POINTS and record.unit == "fraction":
                candidates.append((low / 10_000.0, high / 10_000.0))
            if any(
                _nearly_equal(record.low, candidate_low) and _nearly_equal(record.high, candidate_high)
                for candidate_low, candidate_high in candidates
            ):
                return match
    return None


def _nearest_metric_label(text: str, position: int, *, window: int = 220) -> tuple[str, GuidanceMetric | None, int, int] | None:
    left = max(0, position - window)
    segment = text[left:position]
    best: tuple[int, str, GuidanceMetric | None, int, int] | None = None
    for raw_label, metric, pattern in _METRIC_LABELS:
        for match in pattern.finditer(segment):
            absolute_start = left + match.start()
            absolute_end = left + match.end()
            distance = position - absolute_end
            if best is None or distance < best[0]:
                best = (distance, raw_label, metric, absolute_start, absolute_end)
    if best is None:
        return None
    _, raw_label, metric, start, end = best
    return raw_label, metric, start, end


def _authoritative_period(text: str, value_position: int | None) -> tuple[str | None, str | None, int | None, int | None]:
    markers = list(_RUN94_AUTHORITY.finditer(text))
    if markers:
        periods = {match.group("period").upper().replace(" ", "") for match in markers}
        if len(periods) == 1:
            match = markers[-1]
            return next(iter(periods)), match.group(0), match.start(), match.end()
        return None, None, None, None

    normalized = list(_NORMALIZED_PERIOD.finditer(text))
    if normalized:
        periods = {match.group("period").upper().replace(" ", "") for match in normalized}
        if len(periods) == 1:
            match = normalized[-1]
            return next(iter(periods)), match.group(0), match.start(), match.end()

    if value_position is None:
        return None, None, None, None

    left = max(0, value_position - 260)
    right = min(len(text), value_position + 180)
    local = text[left:right]
    candidates: list[tuple[int, int, str, re.Match[str]]] = []
    for match in _QUARTER.finditer(local):
        if match.group("q"):
            period = f"Q{match.group('q')}FY{match.group('year')}"
        else:
            period = f"Q{_QUARTER_WORD[match.group('word').lower()]}FY{match.group('year2')}"
        distance = abs((left + match.end()) - value_position)
        candidates.append((1, distance, period, match))
    for match in _FULL_YEAR.finditer(local):
        year = match.group("year") or match.group("year2")
        period = f"FY{year}"
        distance = abs((left + match.end()) - value_position)
        candidates.append((1, distance, period, match))
    for match in _YEAR_GUIDANCE.finditer(local):
        period = f"FY{match.group('year')}"
        distance = abs((left + match.end()) - value_position)
        candidates.append((0, distance, period, match))
    if not candidates:
        return None, None, None, None
    candidates.sort(key=lambda value: (value[0], value[1]))
    best_priority, best_distance = candidates[0][0], candidates[0][1]
    tied = [candidate for candidate in candidates if candidate[0] == best_priority and candidate[1] == best_distance]
    periods = {candidate[2] for candidate in tied}
    if len(periods) != 1:
        return None, None, None, None
    _, _, period, match = tied[0]
    return period, match.group(0), left + match.start(), left + match.end()


def _value_kind(text: str, value_match: re.Match[str] | None, unit: GuidanceUnit) -> GuidanceValueKind:
    if value_match is None:
        return GuidanceValueKind.QUALITATIVE
    local = text[max(0, value_match.start() - 100): min(len(text), value_match.end() + 100)]
    if unit is GuidanceUnit.BASIS_POINTS:
        return GuidanceValueKind.DELTA
    if unit is GuidanceUnit.PERCENT and re.search(r"\b(?:growth|increase|decrease|decline|expansion|contraction)\b", local, re.I):
        return GuidanceValueKind.GROWTH_RATE
    return GuidanceValueKind.ABSOLUTE_LEVEL


def typed_fact_from_legacy_record(record: GuidanceMetricRecord) -> TypedGuidanceFact:
    """Migration bridge only: convert old ledger rows into typed evidence candidates."""
    text = re.sub(r"\s+", " ", record.evidence_span or "").strip()
    value_match = _record_value_match(record, text)
    raw_metric_label = None
    metric_text = None
    metric_start = metric_end = None
    if value_match is not None:
        label = _nearest_metric_label(text, value_match.start())
        if label is not None:
            raw_metric_label, _, metric_start, metric_end = label
            metric_text = text[metric_start:metric_end]
    unit = _unit_from_text(value_match, record, text) if value_match is not None else (
        GuidanceUnit.USD_PER_SHARE if record.unit == "USD/share" else
        GuidanceUnit.FRACTION if record.unit == "fraction" else
        GuidanceUnit.USD if record.unit == "USD" else
        GuidanceUnit.UNKNOWN
    )
    authoritative_period, period_text, period_start, period_end = _authoritative_period(
        text,
        value_match.start() if value_match is not None else None,
    )
    provenance = GuidanceProvenance(
        document_id=record.source_document_hash,
        source=record.source,
        source_url=record.source_url,
        source_accession=record.source_accession,
        source_timestamp=record.source_timestamp,
        source_document_hash=record.source_document_hash,
        evidence=EvidenceBinding(
            full_text=text,
            metric_text=metric_text,
            value_text=value_match.group(0) if value_match is not None else None,
            period_text=period_text,
            metric_start=metric_start,
            metric_end=metric_end,
            value_start=value_match.start() if value_match is not None else None,
            value_end=value_match.end() if value_match is not None else None,
            period_start=period_start,
            period_end=period_end,
        ),
    )
    return TypedGuidanceFact(
        ticker=record.ticker,
        metric=record.metric,
        raw_metric_label=raw_metric_label,
        fiscal_period=record.fiscal_period,
        authoritative_period=authoritative_period,
        period_kind=_period_kind(record.fiscal_period),
        accounting_basis=record.accounting_basis,
        scope_kind=GuidanceScopeKind.COMPANY,
        value_kind=_value_kind(text, value_match, unit),
        role=GuidanceFactRole.CURRENT,
        low=record.low,
        high=record.high,
        unit=unit,
        explicit_action=record.explicit_action,
        extraction_method=record.extraction_method,
        provenance=[provenance],
        metadata={"legacy_record_id": str(record.record_id)},
    )


def _metric_from_raw_label(raw_label: str | None) -> GuidanceMetric | None:
    if raw_label is None:
        return None
    for label, metric, _ in _METRIC_LABELS:
        if label == raw_label:
            return metric
    return None


class GuidanceInvariantValidator:
    """Hard evidence gate. Ambiguity quarantines; it never guesses."""

    def validate(self, fact: TypedGuidanceFact) -> ValidatedGuidanceFact:
        violations: list[GuidanceInvariantViolation] = []

        if fact.low is not None and fact.high is not None and fact.low > fact.high:
            violations.append(GuidanceInvariantViolation(code=GuidanceInvariantCode.INVALID_RANGE, message="low exceeds high"))

        if fact.value_kind not in {GuidanceValueKind.ABSOLUTE_LEVEL, GuidanceValueKind.QUALITATIVE}:
            violations.append(GuidanceInvariantViolation(
                code=GuidanceInvariantCode.NON_ABSOLUTE_VALUE,
                message=f"{fact.value_kind.value} cannot enter absolute guidance comparison",
            ))

        allowed_units = {
            GuidanceMetric.REVENUE: {GuidanceUnit.USD, GuidanceUnit.USD_THOUSAND, GuidanceUnit.USD_MILLION, GuidanceUnit.USD_BILLION},
            GuidanceMetric.EBITDA: {GuidanceUnit.USD, GuidanceUnit.USD_THOUSAND, GuidanceUnit.USD_MILLION, GuidanceUnit.USD_BILLION},
            GuidanceMetric.FCF: {GuidanceUnit.USD, GuidanceUnit.USD_THOUSAND, GuidanceUnit.USD_MILLION, GuidanceUnit.USD_BILLION},
            GuidanceMetric.EPS: {GuidanceUnit.USD_PER_SHARE},
            GuidanceMetric.GROSS_MARGIN: {GuidanceUnit.PERCENT, GuidanceUnit.FRACTION},
            GuidanceMetric.OPERATING_MARGIN: {GuidanceUnit.PERCENT, GuidanceUnit.FRACTION},
        }[fact.metric]
        if fact.low is not None and fact.unit not in allowed_units:
            violations.append(GuidanceInvariantViolation(
                code=GuidanceInvariantCode.UNIT_METRIC_MISMATCH,
                message=f"{fact.unit.value} is incompatible with {fact.metric.value}",
            ))

        bound_metric = _metric_from_raw_label(fact.raw_metric_label)
        if fact.raw_metric_label is not None and bound_metric is not fact.metric:
            violations.append(GuidanceInvariantViolation(
                code=GuidanceInvariantCode.METRIC_VALUE_LOCALITY_MISMATCH,
                message=f"value is locally bound to {fact.raw_metric_label}, not {fact.metric.value}",
            ))

        if fact.authoritative_period and fact.authoritative_period != fact.fiscal_period:
            violations.append(GuidanceInvariantViolation(
                code=GuidanceInvariantCode.PERIOD_AUTHORITY_MISMATCH,
                message=f"authoritative period {fact.authoritative_period} conflicts with {fact.fiscal_period}",
            ))

        expected_kind = _period_kind(fact.fiscal_period)
        if expected_kind is not GuidancePeriodKind.UNKNOWN and fact.period_kind is not expected_kind:
            violations.append(GuidanceInvariantViolation(
                code=GuidanceInvariantCode.PERIOD_KIND_MISMATCH,
                message=f"{fact.period_kind.value} conflicts with fiscal period {fact.fiscal_period}",
            ))

        if fact.scope_kind in {GuidanceScopeKind.SEGMENT, GuidanceScopeKind.PRODUCT}:
            violations.append(GuidanceInvariantViolation(
                code=GuidanceInvariantCode.NON_COMPANY_SCOPE,
                message=f"{fact.scope_kind.value} guidance is not company-wide guidance",
            ))
        if fact.role is GuidanceFactRole.ACTUAL:
            violations.append(GuidanceInvariantViolation(
                code=GuidanceInvariantCode.HISTORICAL_ACTUAL,
                message="historical actual cannot enter forward guidance ledger",
            ))
        if fact.role is GuidanceFactRole.LONG_TERM_TARGET:
            violations.append(GuidanceInvariantViolation(
                code=GuidanceInvariantCode.LONG_TERM_TARGET,
                message="long-term target cannot enter current-period guidance ledger",
            ))

        return ValidatedGuidanceFact(
            fact=fact,
            violations=violations,
            accepted=not any(violation.quarantine for violation in violations),
        )


def _canonical_values(fact: TypedGuidanceFact) -> tuple[float | None, float | None, GuidanceUnit]:
    if fact.low is None or fact.high is None:
        return fact.low, fact.high, fact.unit
    if fact.unit is GuidanceUnit.USD_THOUSAND:
        return fact.low * 1_000.0, fact.high * 1_000.0, GuidanceUnit.USD
    if fact.unit is GuidanceUnit.USD_MILLION:
        return fact.low * 1_000_000.0, fact.high * 1_000_000.0, GuidanceUnit.USD
    if fact.unit is GuidanceUnit.USD_BILLION:
        return fact.low * 1_000_000_000.0, fact.high * 1_000_000_000.0, GuidanceUnit.USD
    if fact.unit is GuidanceUnit.PERCENT and fact.metric in _MARGIN_METRICS:
        return fact.low / 100.0, fact.high / 100.0, GuidanceUnit.FRACTION
    return fact.low, fact.high, fact.unit


class CanonicalGuidanceNormalizer:
    """Create immutable canonical facts; merge duplicates by semantic identity."""

    def normalize(self, validated: Iterable[ValidatedGuidanceFact]) -> CanonicalizationResult:
        accepted_by_key: dict[tuple, CanonicalGuidanceFact] = {}
        quarantined: list[ValidatedGuidanceFact] = []

        for result in validated:
            if not result.accepted:
                quarantined.append(result)
                continue
            fact = result.fact
            low, high, unit = _canonical_values(fact)
            candidate = CanonicalGuidanceFact(
                ticker=fact.ticker,
                metric=fact.metric,
                fiscal_period=fact.fiscal_period,
                period_kind=fact.period_kind,
                accounting_basis=fact.accounting_basis,
                scope_kind=fact.scope_kind,
                scope_label=fact.scope_label,
                value_kind=fact.value_kind,
                role=fact.role,
                low=low,
                high=high,
                unit=unit,
                explicit_action=fact.explicit_action,
                source_fact_ids=[fact.fact_id],
                provenance=list(fact.provenance),
                metadata=dict(fact.metadata),
            )
            key = candidate.semantic_key
            existing = accepted_by_key.get(key)
            if existing is None:
                accepted_by_key[key] = candidate
                continue
            existing.source_fact_ids.append(fact.fact_id)
            known = {
                (p.source_url, p.source_accession, p.source_timestamp, p.source_document_hash, p.evidence.full_text)
                for p in existing.provenance
            }
            for provenance in fact.provenance:
                pkey = (
                    provenance.source_url,
                    provenance.source_accession,
                    provenance.source_timestamp,
                    provenance.source_document_hash,
                    provenance.evidence.full_text,
                )
                if pkey not in known:
                    existing.provenance.append(provenance)
                    known.add(pkey)

        return CanonicalizationResult(
            accepted=sorted(
                accepted_by_key.values(),
                key=lambda item: (
                    item.ticker,
                    min((p.source_timestamp for p in item.provenance), default=datetime.min.replace(tzinfo=UTC)),
                    item.metric.value,
                    item.fiscal_period,
                    item.accounting_basis,
                ),
            ),
            quarantined=quarantined,
        )


def canonical_fact_to_legacy_record(
    fact: CanonicalGuidanceFact,
    *,
    rules_hash: str,
    scan_run_id: UUID | None = None,
) -> GuidanceMetricRecord:
    """Temporary compatibility adapter: frozen comparator sees canonical facts only."""
    if not fact.provenance:
        raise ValueError("Canonical guidance fact must retain provenance")
    primary = min(fact.provenance, key=lambda item: (item.source_timestamp, item.source_url))
    if fact.unit is GuidanceUnit.USD:
        unit = "USD"
    elif fact.unit is GuidanceUnit.USD_PER_SHARE:
        unit = "USD/share"
    elif fact.unit is GuidanceUnit.FRACTION:
        unit = "fraction"
    else:
        raise ValueError(f"Canonical unit {fact.unit.value} is not comparator-compatible")
    return GuidanceMetricRecord(
        rules_hash=rules_hash,
        scan_run_id=scan_run_id,
        ticker=fact.ticker,
        fiscal_period=fact.fiscal_period,
        metric=fact.metric,
        accounting_basis=fact.accounting_basis,
        low=fact.low,
        high=fact.high,
        unit=unit,
        source=primary.source,
        source_url=primary.source_url,
        source_accession=primary.source_accession,
        source_timestamp=primary.source_timestamp,
        explicit_action=fact.explicit_action,
        verified=True,
        extraction_method=ExtractionMethod.STRUCTURED,
        evidence_span=primary.evidence.full_text,
        source_document_hash=primary.source_document_hash,
        as_of=max(item.source_timestamp for item in fact.provenance),
        fetched_at=max(item.source_timestamp for item in fact.provenance),
        stale=False,
    )


def canonicalize_legacy_records(records: Iterable[GuidanceMetricRecord]) -> CanonicalizationResult:
    validator = GuidanceInvariantValidator()
    typed = [typed_fact_from_legacy_record(record) for record in records]
    validated = [validator.validate(fact) for fact in typed]
    return CanonicalGuidanceNormalizer().normalize(validated)
