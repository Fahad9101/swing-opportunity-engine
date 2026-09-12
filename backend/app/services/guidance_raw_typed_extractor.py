from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, NamedTuple

from app.domain.guidance_canonical_v1 import (
    EvidenceBinding,
    GuidanceFactRole,
    GuidancePeriodKind,
    GuidanceProvenance,
    GuidanceScopeKind,
    GuidanceUnit,
    GuidanceValueKind,
    TypedGuidanceFact,
)
from app.domain.soe_v1_1 import ExtractionMethod, GuidanceAction, GuidanceMetric, SourceDocument
from app.services.fact_extraction_service import html_to_text


_GUIDANCE = re.compile(
    r"\b(?:guidance|outlook|forecast|expects?|anticipat(?:e|es|ed|ing)|"
    r"project(?:s|ed|ing)|reaffirm(?:s|ed|ing)?|reiterat(?:e|es|ed|ing)|"
    r"rais(?:e|es|ed|ing)|lower(?:s|ed|ing)?|reduc(?:e|es|ed|ing)|"
    r"withdraw(?:s|n|ing)?|suspend(?:s|ed|ing)?)\b",
    re.I,
)
_ACTUAL = re.compile(
    r"\b(?:reported|results?|actual|achieved|generated|delivered|grew|"
    r"year[- ]to[- ]date|for the quarter ended)\b",
    re.I,
)
_ACTION_PATTERNS: list[tuple[GuidanceAction, re.Pattern[str]]] = [
    (GuidanceAction.WITHDRAW, re.compile(r"\b(?:withdraw(?:s|n|ing)?|suspend(?:s|ed|ing)?)\b", re.I)),
    (GuidanceAction.LOWER, re.compile(r"\b(?:lower(?:s|ed|ing)?|reduc(?:e|es|ed|ing)|cut(?:s|ting)?)\b", re.I)),
    (GuidanceAction.RAISE, re.compile(r"\b(?:rais(?:e|es|ed|ing)|boost(?:s|ed|ing)?)\b", re.I)),
    (GuidanceAction.REAFFIRM, re.compile(r"\b(?:reaffirm(?:s|ed|ing)?|reiterat(?:e|es|ed|ing)|maintain(?:s|ed|ing)?)\b", re.I)),
]

_METRICS: list[tuple[GuidanceMetric, str, re.Pattern[str]]] = [
    (
        GuidanceMetric.GROSS_MARGIN,
        "gross_margin",
        re.compile(r"\b(?:(?:adjusted|non[- ]GAAP)\s+)?gross(?:\s+profit)?\s+margin\b", re.I),
    ),
    (
        GuidanceMetric.OPERATING_MARGIN,
        "operating_margin",
        re.compile(r"\b(?:(?:adjusted|non[- ]GAAP)\s+)?operating\s+margin\b", re.I),
    ),
    (
        GuidanceMetric.FCF,
        "fcf",
        re.compile(r"\b(?:(?:adjusted|non[- ]GAAP)\s+)?(?:free\s+cash\s+flow|FCF)\b", re.I),
    ),
    (
        GuidanceMetric.EPS,
        "eps",
        re.compile(
            r"\b(?:(?:adjusted|non[- ]GAAP|GAAP)\s+)?"
            r"(?:diluted\s+)?(?:EPS|earnings\s+per\s+(?:common\s+)?share)\b",
            re.I,
        ),
    ),
    (
        GuidanceMetric.EBITDA,
        "ebitda",
        re.compile(r"\b(?:(?:adjusted|non[- ]GAAP)\s+)?EBITDA\b(?!\s+margin)", re.I),
    ),
    (
        GuidanceMetric.REVENUE,
        "revenue",
        re.compile(
            r"\b(?:total\s+product\s+revenue|total\s+revenue|consolidated\s+revenue|"
            r"net\s+[A-Za-z0-9&.'/-]+\s+product\s+revenue|net\s+product\s+revenue|"
            r"[A-Za-z0-9&.'/-]+\s+product\s+revenue|segment\s+revenue|"
            r"net\s+sales|revenues?)\b",
            re.I,
        ),
    ),
]

_BLOCKERS = re.compile(
    r"\b(?:stock[- ]based compensation(?: expense)?|bookings?|ARR|annual recurring revenue|"
    r"capital expenditures?|capex)\b",
    re.I,
)

_FULL_YEAR = [
    re.compile(r"\b(?:FY|fiscal\s+year|full[- ]year)\s*'?((?:20)?\d{2})\b", re.I),
    re.compile(r"\b(20\d{2})\s+(?:full[- ]year|annual)\b", re.I),
    re.compile(r"\byear\s+ending\s+[A-Za-z]+\s+\d{1,2},?\s*(20\d{2})\b", re.I),
]
_QUARTER = [
    re.compile(r"\bQ([1-4])\s*(?:FY)?\s*'?((?:20)?\d{2})\b", re.I),
    re.compile(r"\b(first|second|third|fourth)\s+quarter(?:\s+of)?\s+(?:fiscal(?:\s+year)?\s*)?(20\d{2})\b", re.I),
]
_QUARTER_MAP = {"first": "1", "second": "2", "third": "3", "fourth": "4"}
_YEAR_NEAR_FORWARD = re.compile(r"\b(20\d{2})\b")

_MONEY_RANGE = re.compile(
    r"(?:\bbetween\s+)?(?P<d1>\$)?\s*(?P<lo>\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<s1>billion|million|thousand|bn|mm|m|b)?\s*"
    r"(?:and|to|through|-|–|—)\s*"
    r"(?P<d2>\$)?\s*(?P<hi>\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<s2>billion|million|thousand|bn|mm|m|b)?\b",
    re.I,
)
_MONEY_SINGLE = re.compile(
    r"(?P<d>\$)\s*(?P<value>\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<scale>billion|million|thousand|bn|mm|m|b)?\b",
    re.I,
)
_PERCENT_RANGE = re.compile(
    r"(?P<lo>\d{1,3}(?:\.\d+)?)\s*%\s*(?:to|through|-|–|—)\s*(?P<hi>\d{1,3}(?:\.\d+)?)\s*%",
    re.I,
)
_PERCENT_SINGLE = re.compile(
    r"(?:approximately|about|around|at|of|expect(?:s|ed)?(?:\s+to\s+be)?)?\s*"
    r"(?P<value>\d{1,3}(?:\.\d+)?)\s*%",
    re.I,
)
_BPS_RANGE = re.compile(
    r"(?P<lo>\d+(?:\.\d+)?)\s*(?:to|through|-|–|—)\s*(?P<hi>\d+(?:\.\d+)?)\s*(?:bps|basis\s+points)",
    re.I,
)

_SCALE_UNITS = {
    "b": GuidanceUnit.USD_BILLION,
    "bn": GuidanceUnit.USD_BILLION,
    "billion": GuidanceUnit.USD_BILLION,
    "m": GuidanceUnit.USD_MILLION,
    "mm": GuidanceUnit.USD_MILLION,
    "million": GuidanceUnit.USD_MILLION,
    "thousand": GuidanceUnit.USD_THOUSAND,
}


class _MetricMention(NamedTuple):
    metric: GuidanceMetric
    raw_label: str
    text: str
    start: int
    end: int


class _ValueBinding(NamedTuple):
    low: float
    high: float
    unit: GuidanceUnit
    value_kind: GuidanceValueKind
    text: str
    start: int
    end: int


class _PeriodBinding(NamedTuple):
    period: str
    kind: GuidancePeriodKind
    text: str
    start: int
    end: int


@dataclass(frozen=True)
class RawTypedGuidanceExtraction:
    ticker: str
    document_id: str
    facts: tuple[TypedGuidanceFact, ...]
    rejected_candidates: tuple[dict, ...]


def _normalize_year(token: str) -> int:
    value = int(token)
    return value + 2000 if value < 100 else value


def _segments(text: str) -> Iterable[str]:
    normalized = re.sub(r"[ \t]+", " ", text.replace("\xa0", " "))
    lines = [line.strip() for line in re.split(r"[\r\n]+", normalized) if line.strip()]
    seen: set[str] = set()

    for line in lines:
        for part in re.split(r"(?<=[.;])\s+(?=[A-Z0-9])", line):
            part = part.strip()
            if 20 <= len(part) <= 1800 and _GUIDANCE.search(part) and part not in seen:
                seen.add(part)
                yield part

    for index in range(len(lines)):
        buf: list[str] = []
        for offset in range(8):
            if index + offset >= len(lines):
                break
            buf.append(lines[index + offset])
            joined = " ".join(buf)
            if len(joined) > 1800:
                break
            if len(joined) >= 20 and _GUIDANCE.search(joined) and joined not in seen:
                seen.add(joined)
                yield joined


def _metric_mentions(segment: str) -> list[_MetricMention]:
    mentions: list[_MetricMention] = []
    for metric, raw_label, pattern in _METRICS:
        for match in pattern.finditer(segment):
            mentions.append(_MetricMention(metric, raw_label, match.group(0), match.start(), match.end()))
    mentions.sort(key=lambda item: (item.start, -(item.end - item.start)))
    result: list[_MetricMention] = []
    for item in mentions:
        if any(not (item.end <= other.start or item.start >= other.end) for other in result):
            continue
        result.append(item)
    return sorted(result, key=lambda item: item.start)


def _action(text: str) -> GuidanceAction:
    for action, pattern in _ACTION_PATTERNS:
        if pattern.search(text):
            return action
    if re.search(r"\b(?:provid(?:e|es|ed|ing)|issu(?:e|es|ed|ing)|initiat(?:e|es|ed|ing))\b.{0,100}\b(?:guidance|outlook)\b", text, re.I):
        return GuidanceAction.INITIATE
    if re.search(r"\b(?:we|company|management|[A-Z][A-Za-z]+)\s+expects?\b", text) or re.search(
        r"\bexpects?\s+(?:FY|fiscal|full[- ]year|20\d{2}|revenue|net\s+sales|EPS|EBITDA|free\s+cash\s+flow)",
        text,
        re.I,
    ):
        return GuidanceAction.INITIATE
    return GuidanceAction.NONE


def _period_binding(segment: str, mention: _MetricMention) -> _PeriodBinding | None:
    candidates: list[tuple[int, int, _PeriodBinding]] = []

    for pattern in _FULL_YEAR:
        for match in pattern.finditer(segment):
            year = _normalize_year(match.group(1))
            binding = _PeriodBinding(f"FY{year}", GuidancePeriodKind.FULL_YEAR, match.group(0), match.start(), match.end())
            distance = min(abs(match.end() - mention.start), abs(match.start() - mention.end))
            candidates.append((0, distance, binding))

    for pattern in _QUARTER:
        for match in pattern.finditer(segment):
            if match.group(1).isdigit():
                q = match.group(1)
                year = _normalize_year(match.group(2))
            else:
                q = _QUARTER_MAP[match.group(1).lower()]
                year = int(match.group(2))
            binding = _PeriodBinding(f"Q{q}FY{year}", GuidancePeriodKind.QUARTER, match.group(0), match.start(), match.end())
            distance = min(abs(match.end() - mention.start), abs(match.start() - mention.end))
            candidates.append((1, distance, binding))

    local_left = max(0, mention.start - 120)
    local_right = min(len(segment), mention.end + 80)
    local = segment[local_left:local_right]
    for match in _YEAR_NEAR_FORWARD.finditer(local):
        absolute_start = local_left + match.start()
        absolute_end = local_left + match.end()
        direct_prefix = segment[max(0, absolute_start - 8):absolute_start]
        if re.search(r"Q[1-4]\s*(?:FY)?\s*'?\s*$", direct_prefix, re.I):
            continue
        around = segment[max(0, absolute_start - 100): min(len(segment), mention.end + 100)]
        if not _GUIDANCE.search(around):
            continue
        year = int(match.group(1))
        binding = _PeriodBinding(f"FY{year}", GuidancePeriodKind.FULL_YEAR, match.group(0), absolute_start, absolute_end)
        distance = min(abs(absolute_end - mention.start), abs(absolute_start - mention.end))
        candidates.append((0, distance, binding))

    if not candidates:
        return None

    candidates.sort(key=lambda item: (item[0], item[1], item[2].start))
    best_priority, best_distance = candidates[0][0], candidates[0][1]
    tied = [item for item in candidates if item[0] == best_priority and item[1] == best_distance]
    periods = {item[2].period for item in tied}
    if len(periods) != 1:
        return None
    return tied[0][2]


def _scope(mention: _MetricMention) -> tuple[GuidanceScopeKind, str | None]:
    if mention.metric is not GuidanceMetric.REVENUE:
        return GuidanceScopeKind.COMPANY, None
    text = mention.text.strip()
    lower = text.lower()
    if "total product revenue" in lower:
        return GuidanceScopeKind.COMPANY, text
    if "segment revenue" in lower:
        return GuidanceScopeKind.SEGMENT, text
    if "product revenue" in lower:
        return GuidanceScopeKind.PRODUCT, text
    return GuidanceScopeKind.COMPANY, text if re.search(r"\b(?:total|consolidated)\b", lower) else None


def _basis(segment: str, mention: _MetricMention) -> str:
    if mention.metric is GuidanceMetric.REVENUE:
        return "UNSPECIFIED"
    label = mention.text
    if re.search(r"\b(?:adjusted|non[- ]GAAP)\b", label, re.I):
        return "ADJUSTED"
    if re.search(r"(?<!non[- ])\bGAAP\b", label, re.I):
        return "GAAP"
    local = segment[max(0, mention.start - 35): min(len(segment), mention.end + 35)]
    if re.search(r"\b(?:adjusted|non[- ]GAAP)\b", local, re.I):
        return "ADJUSTED"
    if re.search(r"(?<!non[- ])\bGAAP\b", local, re.I):
        return "GAAP"
    return "UNSPECIFIED"


def _metric_clause(segment: str, mentions: list[_MetricMention], index: int) -> tuple[str, int]:
    mention = mentions[index]
    left = max(0, mention.start - 180)
    right = min(len(segment), mention.end + 320)

    if index + 1 < len(mentions):
        right = min(right, mentions[index + 1].start)
    blocker = _BLOCKERS.search(segment, mention.end, right)
    if blocker:
        right = min(right, blocker.start())

    tail = segment[mention.end:right]
    boundary = re.search(r"[;•]", tail)
    if boundary:
        right = min(right, mention.end + boundary.start())

    return segment[left:right], mention.start - left


def _header_money_unit(text: str, position: int) -> GuidanceUnit | None:
    prefix = text[max(0, position - 160):position]
    if re.search(r"\b(?:in|\$\s*in)\s+billions?\b|\(\s*in\s+billions?\s*\)", prefix, re.I):
        return GuidanceUnit.USD_BILLION
    if re.search(r"\b(?:in|\$\s*in)\s+millions?\b|\(\s*in\s+millions?\s*\)", prefix, re.I):
        return GuidanceUnit.USD_MILLION
    if re.search(r"\b(?:in|\$\s*in)\s+thousands?\b|\(\s*in\s+thousands?\s*\)", prefix, re.I):
        return GuidanceUnit.USD_THOUSAND
    return None


def _source_money_unit(
    scale1: str | None,
    scale2: str | None,
    *,
    has_dollar: bool,
    text: str,
    position: int,
) -> GuidanceUnit:
    scale = (scale2 or scale1 or "").lower()
    if scale:
        return _SCALE_UNITS.get(scale, GuidanceUnit.UNKNOWN)
    inherited = _header_money_unit(text, position)
    if inherited is not None:
        return inherited
    return GuidanceUnit.USD if has_dollar else GuidanceUnit.UNKNOWN


def _bind_value(clause: str, mention: _MetricMention, anchor: int) -> _ValueBinding | None:
    metric = mention.metric
    candidates: list[_ValueBinding] = []

    if metric in {GuidanceMetric.GROSS_MARGIN, GuidanceMetric.OPERATING_MARGIN}:
        for match in _BPS_RANGE.finditer(clause):
            candidates.append(
                _ValueBinding(
                    float(match.group("lo")),
                    float(match.group("hi")),
                    GuidanceUnit.BASIS_POINTS,
                    GuidanceValueKind.DELTA,
                    match.group(0),
                    match.start(),
                    match.end(),
                )
            )
        for match in _PERCENT_RANGE.finditer(clause):
            candidates.append(
                _ValueBinding(
                    float(match.group("lo")),
                    float(match.group("hi")),
                    GuidanceUnit.PERCENT,
                    GuidanceValueKind.ABSOLUTE_LEVEL,
                    match.group(0),
                    match.start(),
                    match.end(),
                )
            )
        for match in _PERCENT_SINGLE.finditer(clause):
            local = clause[max(0, match.start() - 60): match.end() + 40]
            kind = GuidanceValueKind.DELTA if re.search(r"\b(?:growth|decline|increase|decrease|expansion|contraction)\b", local, re.I) else GuidanceValueKind.ABSOLUTE_LEVEL
            value = float(match.group("value"))
            candidates.append(_ValueBinding(value, value, GuidanceUnit.PERCENT, kind, match.group(0), match.start(), match.end()))
    elif metric is GuidanceMetric.EPS:
        eps_range = re.compile(
            r"\$?\s*(?P<lo>-?\d+(?:\.\d+)?)\s*(?:to|through|-|–|—)\s*\$?\s*(?P<hi>-?\d+(?:\.\d+)?)(?!\s*%)",
            re.I,
        )
        eps_single = re.compile(r"\$\s*(?P<value>-?\d+(?:\.\d+)?)(?!\s*%)")
        for match in eps_range.finditer(clause):
            candidates.append(_ValueBinding(float(match.group("lo")), float(match.group("hi")), GuidanceUnit.USD_PER_SHARE, GuidanceValueKind.ABSOLUTE_LEVEL, match.group(0), match.start(), match.end()))
        for match in eps_single.finditer(clause):
            value = float(match.group("value"))
            candidates.append(_ValueBinding(value, value, GuidanceUnit.USD_PER_SHARE, GuidanceValueKind.ABSOLUTE_LEVEL, match.group(0), match.start(), match.end()))
    else:
        for match in _MONEY_RANGE.finditer(clause):
            has_dollar = bool(match.group("d1") or match.group("d2"))
            unit = _source_money_unit(match.group("s1"), match.group("s2"), has_dollar=has_dollar, text=clause, position=match.start())
            if unit is GuidanceUnit.UNKNOWN:
                continue
            low = float(match.group("lo").replace(",", ""))
            high = float(match.group("hi").replace(",", ""))
            if low > high:
                continue
            candidates.append(_ValueBinding(low, high, unit, GuidanceValueKind.ABSOLUTE_LEVEL, match.group(0), match.start(), match.end()))
        for match in _MONEY_SINGLE.finditer(clause):
            unit = _source_money_unit(None, match.group("scale"), has_dollar=True, text=clause, position=match.start())
            value = float(match.group("value").replace(",", ""))
            candidates.append(_ValueBinding(value, value, unit, GuidanceValueKind.ABSOLUTE_LEVEL, match.group(0), match.start(), match.end()))

        for match in _PERCENT_SINGLE.finditer(clause):
            local = clause[max(0, match.start() - 60): match.end() + 40]
            if re.search(r"\b(?:growth|increase|decrease|decline|expansion|contraction)\b", local, re.I):
                value = float(match.group("value"))
                candidates.append(_ValueBinding(value, value, GuidanceUnit.PERCENT, GuidanceValueKind.GROWTH_RATE, match.group(0), match.start(), match.end()))
        for match in _BPS_RANGE.finditer(clause):
            candidates.append(_ValueBinding(float(match.group("lo")), float(match.group("hi")), GuidanceUnit.BASIS_POINTS, GuidanceValueKind.DELTA, match.group(0), match.start(), match.end()))

    if not candidates:
        return None

    forward = [item for item in candidates if item.end >= anchor]
    pool = forward or candidates
    ranges = [item for item in pool if item.low != item.high]
    pool = ranges or pool
    pool.sort(key=lambda item: (abs(item.start - anchor), item.start))
    return pool[0]


def _local_forward_context(clause: str, anchor: int, mention: _MetricMention) -> bool:
    local = clause[max(0, anchor - 90): min(len(clause), anchor + len(mention.text) + 110)]
    return bool(_GUIDANCE.search(local))


def extract_typed_guidance_facts(document: SourceDocument) -> RawTypedGuidanceExtraction:
    """Extract typed guidance facts directly from immutable SEC source content.

    This shadow-only extractor never creates a legacy guidance ledger row and
    never invokes the historical Phase-1.1E repair stack. Ambiguous raw evidence
    is rejected here or quarantined later by GuidanceInvariantValidator.
    """
    text = html_to_text(document.content or "")
    facts: list[TypedGuidanceFact] = []
    rejected: list[dict] = []
    seen: set[tuple] = set()

    for segment in _segments(text):
        mentions = _metric_mentions(segment)
        if not mentions:
            continue
        segment_action = _action(segment)

        for index, mention in enumerate(mentions):
            clause, anchor = _metric_clause(segment, mentions, index)
            local_action = _action(clause)
            if local_action is GuidanceAction.NONE:
                local_action = segment_action

            if not _local_forward_context(clause, anchor, mention) and local_action is GuidanceAction.NONE:
                continue

            local = clause[max(0, anchor - 100): min(len(clause), anchor + len(mention.text) + 120)]
            if _ACTUAL.search(local) and not _GUIDANCE.search(local):
                rejected.append({"reason": "historical_actual", "metric": mention.metric.value, "evidence": clause[:500]})
                continue

            period = _period_binding(segment, mention)
            if period is None:
                rejected.append({"reason": "ambiguous_or_missing_period", "metric": mention.metric.value, "evidence": clause[:500]})
                continue

            value = _bind_value(clause, mention, anchor)
            if value is None and local_action not in {
                GuidanceAction.RAISE,
                GuidanceAction.LOWER,
                GuidanceAction.REAFFIRM,
                GuidanceAction.WITHDRAW,
            }:
                rejected.append({"reason": "missing_bound_value", "metric": mention.metric.value, "evidence": clause[:500]})
                continue

            scope_kind, scope_label = _scope(mention)
            basis = _basis(segment, mention)
            role = GuidanceFactRole.CURRENT
            if re.search(r"\b(?:previous|prior|former)\s+guidance\b", clause, re.I):
                role = GuidanceFactRole.QUOTED_PRIOR

            low = high = None
            unit = GuidanceUnit.UNKNOWN
            value_kind = GuidanceValueKind.QUALITATIVE
            value_text = None
            value_start = value_end = None
            if value is not None:
                low, high, unit, value_kind = value.low, value.high, value.unit, value.value_kind
                value_text = value.text
                value_start, value_end = value.start, value.end

            evidence = EvidenceBinding(
                full_text=clause,
                metric_text=mention.text,
                value_text=value_text,
                period_text=period.text,
                action_text=local_action.value if local_action is not GuidanceAction.NONE else None,
                metric_start=anchor,
                metric_end=anchor + len(mention.text),
                value_start=value_start,
                value_end=value_end,
            )
            provenance = GuidanceProvenance(
                document_id=document.document_id,
                source=document.source,
                source_url=document.source_url,
                source_accession=document.accession,
                source_timestamp=document.source_timestamp,
                source_document_hash=document.content_hash,
                evidence=evidence,
            )

            key = (
                document.ticker,
                mention.metric.value,
                period.period,
                basis,
                scope_kind.value,
                scope_label or "",
                role.value,
                low,
                high,
                unit.value,
                value_kind.value,
                local_action.value,
            )
            if key in seen:
                continue
            seen.add(key)
            facts.append(
                TypedGuidanceFact(
                    ticker=document.ticker,
                    metric=mention.metric,
                    raw_metric_label=mention.raw_label,
                    fiscal_period=period.period,
                    authoritative_period=period.period,
                    period_kind=period.kind,
                    accounting_basis=basis,
                    scope_kind=scope_kind,
                    scope_label=scope_label,
                    value_kind=value_kind,
                    role=role,
                    low=low,
                    high=high,
                    unit=unit,
                    explicit_action=local_action,
                    extraction_method=ExtractionMethod.DETERMINISTIC_TEXT,
                    provenance=[provenance],
                    metadata={
                        "raw_document_extractor": "guidance-raw-typed-v1",
                        "source_form": document.form,
                    },
                )
            )

    return RawTypedGuidanceExtraction(
        ticker=document.ticker,
        document_id=document.document_id,
        facts=tuple(facts),
        rejected_candidates=tuple(rejected),
    )
