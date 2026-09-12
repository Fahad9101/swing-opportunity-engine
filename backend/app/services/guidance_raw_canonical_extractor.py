from __future__ import annotations

import re
from collections import defaultdict
from typing import Iterable

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
from app.services.guidance_raw_typed_extractor import (
    RawTypedGuidanceExtraction,
    _ACTION_PATTERNS,
    _PeriodBinding,
    _ValueBinding,
    _action,
    _basis,
    _bind_value,
    _metric_clause,
    _metric_mentions,
    _normalize_year,
    _segments,
)


_EXPLICIT_FORWARD = re.compile(
    r"\b(?:guidance|outlook|forecast|expects?|expected|anticipat(?:e|es|ed|ing)|"
    r"project(?:s|ed|ing)|provid(?:e|es|ed|ing)\s+(?:guidance|outlook)|"
    r"issu(?:e|es|ed|ing)\s+(?:guidance|outlook)|"
    r"reaffirm(?:s|ed|ing)?|reiterat(?:e|es|ed|ing)|maintain(?:s|ed|ing)?)\b",
    re.I,
)
_FORWARD_SIGNAL = re.compile(
    r"\b(?:guidance|outlook|forecast|expects?|expected|anticipat(?:e|es|ed|ing)|"
    r"project(?:s|ed|ing)|rais(?:e|es|ed|ing)|lower(?:s|ed|ing)?|"
    r"reduc(?:e|es|ed|ing)|cut(?:s|ting)?|boost(?:s|ed|ing)?|"
    r"reaffirm(?:s|ed|ing)?|reiterat(?:e|es|ed|ing)|maintain(?:s|ed|ing)?)\b",
    re.I,
)
_ACTUAL_VALUE = re.compile(
    r"\b(?:was|were|totaled|reports?|reported|generated|delivered|achieved|realized|"
    r"(?:increased|decreased|grew|declined|rose|fell)(?:\s+\d+(?:\.\d+)?%)?\s+to|"
    r"for\s+the\s+quarter\s+ended|for\s+the\s+year\s+ended|year[- ]to[- ]date)\b",
    re.I,
)

_CANONICAL_FULL_YEAR = [
    re.compile(r"\b(?:FY|fiscal(?:\s+year)?|full[- ]year)\s*'?((?:20)?\d{2})\b", re.I),
    re.compile(r"\b(20\d{2})\s+(?:full[- ]year|fiscal\s+year|annual)\b", re.I),
    re.compile(r"\byear\s+ending\s+[A-Za-z]+\s+\d{1,2},?\s*(20\d{2})\b", re.I),
]
_CANONICAL_QUARTER = [
    re.compile(r"\bQ([1-4])\s*(?:FY)?\s*'?((?:20)?\d{2})\b", re.I),
    re.compile(r"\b([1-4])Q\s*(?:FY)?\s*'?((?:20)?\d{2})\b", re.I),
    re.compile(
        r"\b(first|second|third|fourth)\s+quarter(?:\s+of)?\s+"
        r"(?:fiscal(?:\s+year)?\s*)?(20\d{2})\b",
        re.I,
    ),
    re.compile(
        r"\b(first|second|third|fourth)\s+quarter\s+ending\s+"
        r"[A-Za-z]+\s+\d{1,2},?\s*(20\d{2})\b",
        re.I,
    ),
]
_QUARTER_WORD = {"first": "1", "second": "2", "third": "3", "fourth": "4"}
_BARE_YEAR = re.compile(r"\b(20\d{2})\b")

_SEGMENT_REVENUE_QUALIFIER = re.compile(
    r"\b(?:cloud\s+subscriptions?|subscriptions?|services?|licensing|commercial|"
    r"government|enterprise|consumer|advertising|international|domestic|platform|"
    r"software|hardware|maintenance|support|professional\s+services|annualized|"
    r"incremental|acquisition|u\.?s\.?\s+commercial|u\.?s\.?\s+government)\s*$",
    re.I,
)
_PRODUCT_REVENUE_QUALIFIER = re.compile(r"\bproduct\s*$", re.I)
_NON_COMPANY_CONTRIBUTION = re.compile(
    r"(?:\b(?:acquisitions?|segments?|products?|divisions?|business\s+units?)\b"
    r"[^.;]{0,120}\b(?:contribut(?:e|es|ed|ing)|contribution|portion|component)\b"
    r"|\b(?:contribut(?:e|es|ed|ing)|contribution|portion|component)\b"
    r"[^.;]{0,120}\b(?:from|of)\s+(?:the\s+)?(?:acquisitions?|segments?|products?|divisions?|business\s+units?)\b)",
    re.I,
)

_VALUE_OWNER_PATTERNS: list[tuple[GuidanceMetric | str, re.Pattern[str]]] = [
    (
        GuidanceMetric.GROSS_MARGIN,
        re.compile(r"\b(?:(?:adj(?:usted)?|non[- ]GAAP)\s+)?gross(?:\s+profit)?\s+margin\b", re.I),
    ),
    (
        GuidanceMetric.OPERATING_MARGIN,
        re.compile(r"\b(?:(?:adj(?:usted)?|non[- ]GAAP)\s+)?operating\s+margin\b", re.I),
    ),
    (GuidanceMetric.FCF, re.compile(r"\b(?:free\s+cash\s+flow|FCF)\b", re.I)),
    (
        GuidanceMetric.EPS,
        re.compile(
            r"\b(?:(?:adj(?:usted)?|non[- ]GAAP|GAAP)\s+)?(?:diluted\s+)?"
            r"(?:EPS|earnings\s+per\s+(?:common\s+)?share|per\s+diluted\s+share)\b",
            re.I,
        ),
    ),
    (
        GuidanceMetric.EBITDA,
        re.compile(r"\b(?:(?:adj(?:usted)?|non[- ]GAAP)\s+)?EBITDA\b(?!\s+margin)", re.I),
    ),
    (
        GuidanceMetric.REVENUE,
        re.compile(r"\b(?:total\s+(?:product\s+)?revenue|consolidated\s+revenue|net\s+sales|revenues?)\b", re.I),
    ),
    ("net_income", re.compile(r"\b(?:(?:adjusted|GAAP)\s+)?net\s+(?:income|loss)\b", re.I)),
    (
        "operating_cash",
        re.compile(r"\b(?:net\s+cash\s+provided\s+by\s+operating\s+activities|operating\s+cash\s+flow)\b", re.I),
    ),
    ("cash_balance", re.compile(r"\b(?:cash(?:\s+and\s+cash\s+equivalents?)?|liquidity)\b", re.I)),
    ("capex", re.compile(r"\b(?:capital\s+expenditures?|capex)\b", re.I)),
    ("stock_comp", re.compile(r"\bstock[- ]based\s+compensation(?:\s+expense)?\b", re.I)),
    ("operating_expense", re.compile(r"\b(?:operating|interest)\s+expense\b", re.I)),
    ("repurchase", re.compile(r"\b(?:(?:share|stock)\s+repurchase|repurchas(?:e|es|ed|ing))\b", re.I)),
    ("shares", re.compile(r"\b(?:weighted[- ]average\s+)?shares?\s+outstanding\b", re.I)),
    (
        "contract_value",
        re.compile(
            r"\b(?:contract\s+wins?|contracts?\s+valued|transaction\s+consideration|"
            r"contracts?\b[^.;]{0,100}\b(?:valued|combined\s+annual\s+revenues?))\b",
            re.I,
        ),
    ),

]

_MONEY_SCALE_UNITS = {
    "b": GuidanceUnit.USD_BILLION,
    "bn": GuidanceUnit.USD_BILLION,
    "billion": GuidanceUnit.USD_BILLION,
    "m": GuidanceUnit.USD_MILLION,
    "mm": GuidanceUnit.USD_MILLION,
    "million": GuidanceUnit.USD_MILLION,
    "thousand": GuidanceUnit.USD_THOUSAND,
}
_MONEY_UNIT_SCALE = {
    GuidanceUnit.USD: 1.0,
    GuidanceUnit.USD_THOUSAND: 1_000.0,
    GuidanceUnit.USD_MILLION: 1_000_000.0,
    GuidanceUnit.USD_BILLION: 1_000_000_000.0,
}

_FROM_TO_MONEY = re.compile(
    r"\bfrom\s+(?P<d1>\$)?\s*(?P<old>-?\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<s1>billion|million|thousand|bn|mm|m|b)?\s+"
    r"(?:to|through)\s+(?P<d2>\$)?\s*(?P<new>-?\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<s2>billion|million|thousand|bn|mm|m|b)?\b",
    re.I,
)
_BY_TO_MONEY = re.compile(
    r"\bby\s+(?P<d1>\$)?\s*(?P<delta>\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<s1>billion|million|thousand|bn|mm|m|b)?\s*,?\s*"
    r"(?:to|bringing\s+(?:the\s+)?(?:guidance|outlook)\s+to)\s+"
    r"(?P<d2>\$)?\s*(?P<target>-?\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<s2>billion|million|thousand|bn|mm|m|b)?\b",
    re.I,
)
_FROM_TO_PERCENT = re.compile(
    r"\bfrom\s+(?P<old>\d{1,3}(?:\.\d+)?)\s*%\s+(?:to|through)\s+"
    r"(?P<new>\d{1,3}(?:\.\d+)?)\s*%",
    re.I,
)
_BY_TO_PERCENT = re.compile(
    r"\bby\s+(?P<delta>\d{1,3}(?:\.\d+)?)\s*(?:percentage\s+points?|%)\s*,?\s*"
    r"(?:to|bringing\s+(?:the\s+)?(?:guidance|outlook)\s+to)\s+"
    r"(?P<target>\d{1,3}(?:\.\d+)?)\s*%",
    re.I,
)
_PREVIOUS_NOW_MONEY = re.compile(
    r"\bpreviously\b[^$%]{0,100}(?P<d1>\$)?\s*(?P<old>-?\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<s1>billion|million|thousand|bn|mm|m|b)?"
    r"[^$%]{0,100}\b(?:now|currently|today)\b[^$%]{0,100}"
    r"(?P<d2>\$)?\s*(?P<new>-?\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<s2>billion|million|thousand|bn|mm|m|b)?\b",
    re.I,
)
_PREVIOUS_NOW_PERCENT = re.compile(
    r"\bpreviously\b[^%]{0,100}(?P<old>\d{1,3}(?:\.\d+)?)\s*%"
    r"[^%]{0,100}\b(?:now|currently|today)\b[^%]{0,100}"
    r"(?P<new>\d{1,3}(?:\.\d+)?)\s*%",
    re.I,
)


def _explicit_forward_context(text: str) -> bool:
    return bool(_EXPLICIT_FORWARD.search(text))


def _owned_directional_action(clause: str, anchor: int, metric_text: str, metric) -> GuidanceAction:
    mentions = _metric_mentions(clause)
    candidates = [
        item for item in mentions
        if item.metric is metric and item.text.lower() == metric_text.lower()
    ]
    if not candidates:
        return GuidanceAction.NONE
    current = min(candidates, key=lambda item: abs(item.start - anchor))
    owned: list[tuple[int, GuidanceAction]] = []
    for action, pattern in _ACTION_PATTERNS:
        for match in pattern.finditer(clause):
            if match.end() <= current.start:
                gap = current.start - match.end()
                if gap > 120:
                    continue
                if any(match.end() <= item.start < current.start for item in mentions):
                    continue
                owned.append((gap, action))
            elif match.start() >= current.end:
                gap = match.start() - current.end
                if gap > 120:
                    continue
                if any(current.end < item.start <= match.start() for item in mentions):
                    continue
                owned.append((gap, action))
            else:
                owned.append((0, action))
    if not owned:
        return GuidanceAction.NONE
    owned.sort(key=lambda item: item[0])
    nearest = owned[0][0]
    actions = {action for distance, action in owned if distance == nearest}
    return next(iter(actions)) if len(actions) == 1 else GuidanceAction.NONE


def _metric_action(segment: str, clause: str, anchor: int, mention) -> GuidanceAction:
    local = clause[max(0, anchor - 140): min(len(clause), anchor + len(mention.text) + 160)]
    has_forward_context = _explicit_forward_context(local)
    directional = _owned_directional_action(clause, anchor, mention.text, mention.metric)
    if directional is not GuidanceAction.NONE:
        return directional if has_forward_context else GuidanceAction.NONE
    local_action = _action(local)
    if local_action is GuidanceAction.INITIATE and has_forward_context:
        return local_action
    segment_action = _action(segment)
    if segment_action is GuidanceAction.INITIATE and _explicit_forward_context(clause):
        return segment_action
    return GuidanceAction.NONE


def _admissible_period_candidate(clause: str, anchor: int, binding: _PeriodBinding) -> bool:
    markers = list(_FORWARD_SIGNAL.finditer(clause[: max(anchor + 1, binding.end + 1)]))
    if not markers:
        return True
    latest = markers[-1]
    if binding.end >= latest.start() - 48:
        return True
    return min(abs(binding.end - anchor), abs(binding.start - anchor)) <= 70


def _canonical_period_binding(clause: str, anchor: int, mention) -> _PeriodBinding | None:
    mention_end = anchor + len(mention.text)
    explicit: list[tuple[int, int, _PeriodBinding]] = []
    def add(binding: _PeriodBinding) -> None:
        if not _admissible_period_candidate(clause, anchor, binding):
            return
        if binding.end <= anchor:
            direction = 0
            distance = anchor - binding.end
        elif binding.start >= mention_end:
            direction = 1
            distance = binding.start - mention_end
        else:
            direction = 0
            distance = 0
        explicit.append((direction, distance, binding))
    for pattern in _CANONICAL_FULL_YEAR:
        for match in pattern.finditer(clause):
            year = _normalize_year(match.group(1))
            add(_PeriodBinding(f"FY{year}", GuidancePeriodKind.FULL_YEAR, match.group(0), match.start(), match.end()))
    for pattern in _CANONICAL_QUARTER:
        for match in pattern.finditer(clause):
            token = match.group(1)
            q = token if token.isdigit() else _QUARTER_WORD[token.lower()]
            year = _normalize_year(match.group(2))
            add(_PeriodBinding(f"Q{q}FY{year}", GuidancePeriodKind.QUARTER, match.group(0), match.start(), match.end()))
    if explicit:
        preceding = [item for item in explicit if item[0] == 0 and item[2].end <= anchor]
        pool = preceding or [item for item in explicit if item[0] == 1 and item[1] <= 240]
        if pool:
            pool.sort(key=lambda item: (item[0], item[1], -item[2].end))
            best_distance = pool[0][1]
            tied = [item for item in pool if item[0] == pool[0][0] and item[1] == best_distance]
            periods = {item[2].period for item in tied}
            return tied[0][2] if len(periods) == 1 else None
    left = max(0, anchor - 150)
    right = min(len(clause), mention_end + 120)
    local = clause[left:right]
    bare: list[tuple[int, int, _PeriodBinding]] = []
    for match in _BARE_YEAR.finditer(local):
        start, end = left + match.start(), left + match.end()
        prefix = clause[max(0, start - 14):start]
        if re.search(r"(?:Q[1-4]|[1-4]Q)\s*(?:FY)?\s*'?\s*$", prefix, re.I):
            continue
        around = clause[max(0, start - 90): min(len(clause), end + 110)]
        if not _FORWARD_SIGNAL.search(around):
            continue
        binding = _PeriodBinding(f"FY{int(match.group(1))}", GuidancePeriodKind.FULL_YEAR, match.group(0), start, end)
        if not _admissible_period_candidate(clause, anchor, binding):
            continue
        if end <= anchor:
            bare.append((0, anchor - end, binding))
        else:
            bare.append((1, max(0, start - mention_end), binding))
    if not bare:
        return None
    preceding = [item for item in bare if item[0] == 0]
    pool = preceding or [item for item in bare if item[1] <= 100]
    if not pool:
        return None
    pool.sort(key=lambda item: (item[0], item[1], -item[2].end))
    best = pool[0]
    tied = [item for item in pool if item[:2] == best[:2]]
    periods = {item[2].period for item in tied}
    return best[2] if len(periods) == 1 else None


def _unique_explicit_period_from_segment(segment: str) -> _PeriodBinding | None:
    candidates: list[_PeriodBinding] = []
    for pattern in _CANONICAL_FULL_YEAR:
        for match in pattern.finditer(segment):
            year = _normalize_year(match.group(1))
            candidates.append(_PeriodBinding(f"FY{year}", GuidancePeriodKind.FULL_YEAR, match.group(0), match.start(), match.end()))
    for pattern in _CANONICAL_QUARTER:
        for match in pattern.finditer(segment):
            token = match.group(1)
            q = token if token.isdigit() else _QUARTER_WORD[token.lower()]
            year = _normalize_year(match.group(2))
            candidates.append(_PeriodBinding(f"Q{q}FY{year}", GuidancePeriodKind.QUARTER, match.group(0), match.start(), match.end()))
    periods = {candidate.period for candidate in candidates}
    if len(periods) != 1:
        return None
    return min(candidates, key=lambda candidate: candidate.start)


def _span_gap(a_start: int, a_end: int, b_start: int, b_end: int) -> int:
    if a_end <= b_start:
        return b_start - a_end
    if b_end <= a_start:
        return a_start - b_end
    return 0


def _value_has_local_metric_owner(clause: str, anchor: int, mention, value) -> bool:
    current_start = anchor
    current_end = anchor + len(mention.text)
    current_gap = _span_gap(current_start, current_end, value.start, value.end)
    nearest_other: tuple[int, GuidanceMetric | str] | None = None
    current_basis = (
        "ADJUSTED" if re.search(r"\b(?:adjusted|non[- ]GAAP)\b", mention.text, re.I)
        else "GAAP" if re.search(r"(?<!non[- ])\bGAAP\b", mention.text, re.I)
        else None
    )
    for owner, pattern in _VALUE_OWNER_PATTERNS:
        for match in pattern.finditer(clause):
            overlaps_current = not (match.end() <= current_start or match.start() >= current_end)
            if owner is mention.metric and overlaps_current:
                continue
            owner_is_effectively_other = owner is not mention.metric
            if owner is mention.metric and value.end <= current_start:
                owner_text = match.group(0)
                owner_basis = (
                    "ADJUSTED" if re.search(r"\b(?:adjusted|non[- ]GAAP)\b", owner_text, re.I)
                    else "GAAP" if re.search(r"(?<!non[- ])\bGAAP\b", owner_text, re.I)
                    else None
                )
                owner_is_effectively_other = bool(
                    current_basis and owner_basis and current_basis != owner_basis
                )
            if not owner_is_effectively_other:
                continue
            gap = _span_gap(match.start(), match.end(), value.start, value.end)
            if value.end <= current_start and match.end() <= value.start:
                prior_gap = value.start - match.end()
                if prior_gap <= 120 and prior_gap <= current_gap + 80:
                    return False
            if nearest_other is None or gap < nearest_other[0]:
                nearest_other = (gap, owner)
    if nearest_other is None:
        return True
    other_gap, _ = nearest_other
    return current_gap < other_gap


def _value_is_historical_actual(clause: str, anchor: int, value) -> bool:
    if value is None:
        return False
    before = clause[max(0, min(anchor, value.start) - 120):value.start]
    actuals = list(_ACTUAL_VALUE.finditer(before))
    if not actuals:
        return False
    latest_actual = actuals[-1]
    after_actual = before[latest_actual.end():]
    if _FORWARD_SIGNAL.search(after_actual):
        return False
    return len(before) - latest_actual.end() <= 120


def _ambiguous_parallel_period_table(clause: str) -> bool:
    return bool(
        re.search(r"\bthree\s+months\s+ending\b", clause, re.I)
        and re.search(r"\byear\s+ending\b", clause, re.I)
        and re.search(r"\b(?:table|reconciliation|guidance)\b", clause, re.I)
    )


def _ambiguous_current_prior_table(clause: str) -> bool:
    return bool(
        re.search(r"\b(?:updated|current)\b.{0,40}\bguidance\b", clause, re.I)
        and re.search(r"\bprior\b.{0,40}\bguidance\b", clause, re.I)
    )


def _fact_role(clause: str, value) -> GuidanceFactRole:
    if value is None:
        return GuidanceFactRole.CURRENT
    before = clause[max(0, value.start - 180):value.start]
    if re.search(r"\b(?:from\s+(?:our\s+)?)?prior(?:\s+[A-Za-z0-9*.-]+){0,5}\s+(?:guidance|outlook|forecast)\b", before, re.I) or re.search(r"\bprevious(?:\s+[A-Za-z0-9*.-]+){0,5}\s+(?:guidance|outlook|forecast)\b", before, re.I) or re.search(r"\bpreviously(?:\s+(?:expected|forecast|guided|provided|stated))?\b", before, re.I):
        return GuidanceFactRole.QUOTED_PRIOR
    return GuidanceFactRole.CURRENT


def _canonical_scope(clause: str, anchor: int, mention, value) -> tuple[GuidanceScopeKind, str | None]:
    value_end = value.end if value is not None else anchor + len(mention.text)
    local_context = clause[max(0, anchor - 100): min(len(clause), value_end)]
    contribution = _NON_COMPANY_CONTRIBUTION.search(local_context)
    if contribution:
        kind = GuidanceScopeKind.PRODUCT if re.search(r"\bproducts?\b", contribution.group(0), re.I) else GuidanceScopeKind.SEGMENT
        return kind, contribution.group(0).strip()
    if mention.metric is not GuidanceMetric.REVENUE:
        return GuidanceScopeKind.COMPANY, None
    label = mention.text.strip()
    lower = label.lower()
    if "total product revenue" in lower or "total revenue" in lower or "consolidated revenue" in lower or "net sales" in lower:
        return GuidanceScopeKind.COMPANY, label
    if "segment revenue" in lower:
        return GuidanceScopeKind.SEGMENT, label
    if "product revenue" in lower and "total product revenue" not in lower:
        return GuidanceScopeKind.PRODUCT, label
    prefix = clause[max(0, anchor - 70):anchor]
    prefix = re.split(r"[.;:•|\n\r]", prefix)[-1].strip()
    if _PRODUCT_REVENUE_QUALIFIER.search(prefix):
        return GuidanceScopeKind.PRODUCT, prefix
    segment_match = _SEGMENT_REVENUE_QUALIFIER.search(prefix)
    if segment_match:
        return GuidanceScopeKind.SEGMENT, segment_match.group(0).strip()
    return GuidanceScopeKind.COMPANY, None


def _unit_from_scale(scale: str | None, metric: GuidanceMetric, *, dollar: bool) -> GuidanceUnit:
    if metric is GuidanceMetric.EPS:
        return GuidanceUnit.USD_PER_SHARE
    if scale:
        return _MONEY_SCALE_UNITS.get(scale.lower(), GuidanceUnit.UNKNOWN)
    return GuidanceUnit.USD if dollar else GuidanceUnit.UNKNOWN


def _previous_now_value_pair(clause: str, mention) -> tuple[_ValueBinding | None, _ValueBinding | None]:
    if mention.metric in {GuidanceMetric.GROSS_MARGIN, GuidanceMetric.OPERATING_MARGIN}:
        match = _PREVIOUS_NOW_PERCENT.search(clause)
        if match:
            old, new = float(match.group("old")), float(match.group("new"))
            return (
                _ValueBinding(new, new, GuidanceUnit.PERCENT, GuidanceValueKind.ABSOLUTE_LEVEL, match.group("new") + "%", match.start("new"), match.end("new") + 1),
                _ValueBinding(old, old, GuidanceUnit.PERCENT, GuidanceValueKind.ABSOLUTE_LEVEL, match.group("old") + "%", match.start("old"), match.end("old") + 1),
            )
        return None, None
    if mention.metric not in {GuidanceMetric.REVENUE, GuidanceMetric.EBITDA, GuidanceMetric.FCF, GuidanceMetric.EPS}:
        return None, None
    match = _PREVIOUS_NOW_MONEY.search(clause)
    if not match:
        return None, None
    common_scale = match.group("s2") or match.group("s1")
    dollar = bool(match.group("d1") or match.group("d2"))
    old_unit = _unit_from_scale(match.group("s1") or common_scale, mention.metric, dollar=dollar)
    new_unit = _unit_from_scale(match.group("s2") or common_scale, mention.metric, dollar=dollar)
    if old_unit is GuidanceUnit.UNKNOWN or new_unit is GuidanceUnit.UNKNOWN:
        return None, None
    old = float(match.group("old").replace(",", ""))
    new = float(match.group("new").replace(",", ""))
    return (
        _ValueBinding(new, new, new_unit, GuidanceValueKind.ABSOLUTE_LEVEL, match.group("new"), match.start("new"), match.end("new")),
        _ValueBinding(old, old, old_unit, GuidanceValueKind.ABSOLUTE_LEVEL, match.group("old"), match.start("old"), match.end("old")),
    )


def _directional_value_pair(clause: str, anchor: int, mention, action: GuidanceAction) -> tuple[_ValueBinding | None, _ValueBinding | None]:
    if action not in {GuidanceAction.RAISE, GuidanceAction.LOWER}:
        return None, None
    if mention.metric in {GuidanceMetric.GROSS_MARGIN, GuidanceMetric.OPERATING_MARGIN}:
        by_match = _BY_TO_PERCENT.search(clause)
        if by_match:
            target = float(by_match.group("target"))
            return _ValueBinding(target, target, GuidanceUnit.PERCENT, GuidanceValueKind.ABSOLUTE_LEVEL, by_match.group("target") + "%", by_match.start("target"), by_match.end("target") + 1), None
        ft = _FROM_TO_PERCENT.search(clause)
        if ft:
            old, new = float(ft.group("old")), float(ft.group("new"))
            return _ValueBinding(new, new, GuidanceUnit.PERCENT, GuidanceValueKind.ABSOLUTE_LEVEL, ft.group("new") + "%", ft.start("new"), ft.end("new") + 1), _ValueBinding(old, old, GuidanceUnit.PERCENT, GuidanceValueKind.ABSOLUTE_LEVEL, ft.group("old") + "%", ft.start("old"), ft.end("old") + 1)
        return None, None
    if mention.metric not in {GuidanceMetric.REVENUE, GuidanceMetric.EBITDA, GuidanceMetric.FCF, GuidanceMetric.EPS}:
        return None, None
    by_match = _BY_TO_MONEY.search(clause)
    if by_match:
        scale = by_match.group("s2") or by_match.group("s1")
        dollar = bool(by_match.group("d2") or by_match.group("d1"))
        unit = _unit_from_scale(scale, mention.metric, dollar=dollar)
        if unit is not GuidanceUnit.UNKNOWN:
            target = float(by_match.group("target").replace(",", ""))
            return _ValueBinding(target, target, unit, GuidanceValueKind.ABSOLUTE_LEVEL, by_match.group("target"), by_match.start("target"), by_match.end("target")), None
    ft = _FROM_TO_MONEY.search(clause)
    if ft and not re.search(r"\brange\s*$", clause[max(0, ft.start() - 24):ft.start()], re.I):
        common_scale = ft.group("s2") or ft.group("s1")
        dollar = bool(ft.group("d1") or ft.group("d2"))
        old_unit = _unit_from_scale(ft.group("s1") or common_scale, mention.metric, dollar=dollar)
        new_unit = _unit_from_scale(ft.group("s2") or common_scale, mention.metric, dollar=dollar)
        if old_unit is not GuidanceUnit.UNKNOWN and new_unit is not GuidanceUnit.UNKNOWN:
            old = float(ft.group("old").replace(",", ""))
            new = float(ft.group("new").replace(",", ""))
            return _ValueBinding(new, new, new_unit, GuidanceValueKind.ABSOLUTE_LEVEL, ft.group("new"), ft.start("new"), ft.end("new")), _ValueBinding(old, old, old_unit, GuidanceValueKind.ABSOLUTE_LEVEL, ft.group("old"), ft.start("old"), ft.end("old"))
    return None, None


def _money_base(value: float | None, unit: GuidanceUnit) -> float | None:
    if value is None:
        return None
    scale = _MONEY_UNIT_SCALE.get(unit)
    return value * scale if scale is not None else None


def _same_economic_identity(left: TypedGuidanceFact, right: TypedGuidanceFact) -> bool:
    company_label_left = "" if left.scope_kind is GuidanceScopeKind.COMPANY else (left.scope_label or "")
    company_label_right = "" if right.scope_kind is GuidanceScopeKind.COMPANY else (right.scope_label or "")
    return (left.ticker, left.metric, left.fiscal_period, left.accounting_basis, left.scope_kind, company_label_left, left.role, left.value_kind) == (right.ticker, right.metric, right.fiscal_period, right.accounting_basis, right.scope_kind, company_label_right, right.role, right.value_kind)


def _suppress_document_fragments(facts: Iterable[TypedGuidanceFact], rejected: list[dict]) -> list[TypedGuidanceFact]:
    items = list(facts)
    remove: set[int] = set()
    for i, fact in enumerate(items):
        if i in remove or fact.low is None or fact.high is None or fact.low == fact.high:
            continue
        for j, other in enumerate(items):
            if i == j or j in remove or not _same_economic_identity(fact, other):
                continue
            if other.low is None or other.high is None or other.low != other.high:
                continue
            if fact.unit in _MONEY_UNIT_SCALE and other.unit in _MONEY_UNIT_SCALE:
                lo = _money_base(fact.low, fact.unit); hi = _money_base(fact.high, fact.unit); point = _money_base(other.low, other.unit)
            elif fact.unit == other.unit:
                lo, hi, point = fact.low, fact.high, other.low
            else:
                continue
            if lo is None or hi is None or point is None:
                continue
            tolerance = max(1e-8, abs(point) * 1e-8)
            if abs(point - lo) <= tolerance or abs(point - hi) <= tolerance:
                remove.add(j)
                rejected.append({"reason": "same_document_range_endpoint_fragment", "metric": other.metric.value, "period": other.fiscal_period, "value": point})
    # Suppress an unscaled shadow fragment when exactly the same raw endpoints
    # also exist in a scaled money observation for the same economic identity.
    scaled_units = {
        GuidanceUnit.USD_THOUSAND,
        GuidanceUnit.USD_MILLION,
        GuidanceUnit.USD_BILLION,
    }
    for i, fact in enumerate(items):
        if i in remove or fact.low is None or fact.high is None or fact.unit is not GuidanceUnit.USD:
            continue
        for j, other in enumerate(items):
            if i == j or j in remove or other.unit not in scaled_units:
                continue
            if not _same_economic_identity(fact, other):
                continue
            if fact.low == other.low and fact.high == other.high:
                remove.add(i)
                rejected.append(
                    {
                        "reason": "unscaled_shadow_fragment",
                        "metric": fact.metric.value,
                        "period": fact.fiscal_period,
                        "value": [fact.low, fact.high],
                    }
                )
                break

    best_by_key: dict[tuple, int] = {}
    for i, fact in enumerate(items):
        if i in remove:
            continue
        low = _money_base(fact.low, fact.unit) if fact.unit in _MONEY_UNIT_SCALE else fact.low
        high = _money_base(fact.high, fact.unit) if fact.unit in _MONEY_UNIT_SCALE else fact.high
        key = (fact.ticker, fact.metric.value, fact.fiscal_period, fact.accounting_basis, fact.scope_kind.value, "" if fact.scope_kind is GuidanceScopeKind.COMPANY else (fact.scope_label or ""), fact.role.value, fact.value_kind.value, low, high, fact.explicit_action.value)
        prior = best_by_key.get(key)
        if prior is None:
            best_by_key[key] = i
            continue
        prior_fact = items[prior]
        score = (fact.low != fact.high, fact.unit in {GuidanceUnit.USD_MILLION, GuidanceUnit.USD_BILLION, GuidanceUnit.USD_THOUSAND})
        prior_score = (prior_fact.low != prior_fact.high, prior_fact.unit in {GuidanceUnit.USD_MILLION, GuidanceUnit.USD_BILLION, GuidanceUnit.USD_THOUSAND})
        if score > prior_score:
            remove.add(prior); best_by_key[key] = i
        else:
            remove.add(i)
    return [fact for idx, fact in enumerate(items) if idx not in remove]


def _build_fact(*, document: SourceDocument, mention, period: _PeriodBinding, basis: str, scope_kind: GuidanceScopeKind, scope_label: str | None, role: GuidanceFactRole, action: GuidanceAction, value: _ValueBinding | None, clause: str, anchor: int) -> TypedGuidanceFact:
    low = high = None; unit = GuidanceUnit.UNKNOWN; value_kind = GuidanceValueKind.QUALITATIVE; value_text = None; value_start = value_end = None
    if value is not None:
        low, high, unit, value_kind, value_text, value_start, value_end = value.low, value.high, value.unit, value.value_kind, value.text, value.start, value.end
    evidence = EvidenceBinding(full_text=clause, metric_text=mention.text, value_text=value_text, period_text=period.text, action_text=action.value if action is not GuidanceAction.NONE else None, metric_start=anchor, metric_end=anchor + len(mention.text), value_start=value_start, value_end=value_end, period_start=period.start, period_end=period.end)
    provenance = GuidanceProvenance(document_id=document.document_id, source=document.source, source_url=document.source_url, source_accession=document.accession, source_timestamp=document.source_timestamp, source_document_hash=document.content_hash, evidence=evidence)
    return TypedGuidanceFact(ticker=document.ticker, metric=mention.metric, raw_metric_label=mention.raw_label, fiscal_period=period.period, authoritative_period=period.period, period_kind=period.kind, accounting_basis=basis, scope_kind=scope_kind, scope_label=scope_label, value_kind=value_kind, role=role, low=low, high=high, unit=unit, explicit_action=action, extraction_method=ExtractionMethod.DETERMINISTIC_TEXT, provenance=[provenance], metadata={"raw_document_extractor": "guidance-canonical-raw-v5", "source_form": document.form})


def extract_canonical_typed_guidance_facts(document: SourceDocument) -> RawTypedGuidanceExtraction:
    text = html_to_text(document.content or "")
    facts: list[TypedGuidanceFact] = []
    rejected: list[dict] = []
    seen: set[tuple] = set()
    for segment in _segments(text):
        mentions = _metric_mentions(segment)
        if not mentions:
            continue
        for index, mention in enumerate(mentions):
            clause, anchor = _metric_clause(segment, mentions, index)
            local = clause[max(0, anchor - 140): min(len(clause), anchor + len(mention.text) + 160)]
            explicit_forward = _explicit_forward_context(local)
            local_action = _metric_action(segment, clause, anchor, mention)
            if not explicit_forward and local_action is GuidanceAction.NONE:
                continue
            if _ambiguous_parallel_period_table(clause):
                rejected.append({"reason": "ambiguous_parallel_period_table", "metric": mention.metric.value, "evidence": clause[:500]}); continue
            if _ambiguous_current_prior_table(clause):
                rejected.append({"reason": "ambiguous_current_prior_table", "metric": mention.metric.value, "evidence": clause[:500]}); continue
            previous_now_value, previous_now_prior = _previous_now_value_pair(clause, mention)
            directional_value, directional_prior = _directional_value_pair(clause, anchor, mention, local_action)
            value = previous_now_value or directional_value or _bind_value(clause, mention, anchor)
            explicit_prior = previous_now_prior or directional_prior
            if value is not None and value.low > value.high:
                rejected.append({"reason": "invalid_reversed_range", "metric": mention.metric.value, "value_text": value.text, "evidence": clause[:500]}); continue
            if value is not None and not _value_has_local_metric_owner(clause, anchor, mention, value):
                rejected.append({"reason": "metric_value_locality", "metric": mention.metric.value, "value_text": value.text, "evidence": clause[:500]}); continue
            if value is not None and _value_is_historical_actual(clause, anchor, value):
                rejected.append({"reason": "historical_actual", "metric": mention.metric.value, "value_text": value.text, "evidence": clause[:500]}); continue
            role = GuidanceFactRole.CURRENT if previous_now_value is not None else _fact_role(clause, value)
            period = _canonical_period_binding(clause, anchor, mention)
            if period is None and role is GuidanceFactRole.QUOTED_PRIOR:
                period = _unique_explicit_period_from_segment(segment)
            if period is None:
                rejected.append({"reason": "ambiguous_or_missing_period", "metric": mention.metric.value, "evidence": clause[:500]}); continue
            if value is not None and value.end <= period.start <= anchor:
                rejected.append(
                    {
                        "reason": "value_crosses_period_boundary",
                        "metric": mention.metric.value,
                        "value_text": value.text,
                        "period": period.period,
                        "evidence": clause[:500],
                    }
                ); continue
            if value is None and local_action not in {GuidanceAction.RAISE, GuidanceAction.LOWER, GuidanceAction.REAFFIRM, GuidanceAction.WITHDRAW}:
                rejected.append({"reason": "missing_bound_value", "metric": mention.metric.value, "evidence": clause[:500]}); continue
            scope_kind, scope_label = _canonical_scope(clause, anchor, mention, value)
            basis = _basis(segment, mention)
            fact = _build_fact(document=document, mention=mention, period=period, basis=basis, scope_kind=scope_kind, scope_label=scope_label, role=role, action=local_action, value=value, clause=clause, anchor=anchor)
            key = (fact.ticker, fact.metric.value, fact.fiscal_period, fact.accounting_basis, fact.scope_kind.value, fact.scope_label or "", fact.role.value, fact.low, fact.high, fact.unit.value, fact.value_kind.value, fact.explicit_action.value)
            if key not in seen:
                seen.add(key); facts.append(fact)
            if explicit_prior is not None:
                prior_fact = _build_fact(document=document, mention=mention, period=period, basis=basis, scope_kind=scope_kind, scope_label=scope_label, role=GuidanceFactRole.QUOTED_PRIOR, action=GuidanceAction.NONE, value=explicit_prior, clause=clause, anchor=anchor)
                prior_key = (prior_fact.ticker, prior_fact.metric.value, prior_fact.fiscal_period, prior_fact.accounting_basis, prior_fact.scope_kind.value, prior_fact.scope_label or "", prior_fact.role.value, prior_fact.low, prior_fact.high, prior_fact.unit.value, prior_fact.value_kind.value, prior_fact.explicit_action.value)
                if prior_key not in seen:
                    seen.add(prior_key); facts.append(prior_fact)
    facts = _suppress_document_fragments(facts, rejected)
    return RawTypedGuidanceExtraction(ticker=document.ticker, document_id=document.document_id, facts=tuple(facts), rejected_candidates=tuple(rejected))
