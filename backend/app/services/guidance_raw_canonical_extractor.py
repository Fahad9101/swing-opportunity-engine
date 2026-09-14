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
        r"\b(first|second|third|fourth)\s+quarter\s*,?\s*ending\s+"
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
_BRANDED_NET_SALES = re.compile(r"(?:^|[\s(])(?P<brand>[A-Z][A-Z0-9-]{2,})(?:®|™)?\s*$")
_BRAND_SCOPE_RESERVED = {
    "TOTAL", "FULL", "GAAP", "NON", "ADJUSTED", "ANNUAL", "FISCAL", "COMPANY",
    "FY", "QTR", "QUARTER", "YEAR",
}
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
_SUFFIX_MONEY_RANGE = re.compile(
    r"(?P<d1>\$)?\s*(?P<lo>-?\d[\d,]*(?:\.\d+)?)\s*"
    r"(?:-|–|—|to|through)\s*(?P<d2>\$)?\s*(?P<hi>-?\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<scale>billion|million|thousand|bn|mm|m|b)?\s*$",
    re.I,
)
_BREAKEVEN_TO_MONEY = re.compile(
    r"\b(?:between\s+)?breakeven\s+(?:and|to|through|-|–|—)\s*"
    r"(?P<d>\$)?\s*(?P<high>\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<scale>billion|million|thousand|bn|mm|m|b)?\b",
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
        quarter_bindings = [item[2] for item in explicit if item[2].kind is GuidancePeriodKind.QUARTER]
        if quarter_bindings:
            explicit = [
                item for item in explicit
                if not (
                    item[2].kind is GuidancePeriodKind.FULL_YEAR
                    and any(q.start <= item[2].start and item[2].end <= q.end for q in quarter_bindings)
                )
            ]
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


_COMPACT_FORWARD_MONEY_RANGE = re.compile(
    r"^\s*(?:\(\s*\d+[A-Za-z]?\s*\)\s*)?(?:(?:of|at)\s+)?"
    r"(?P<d1>\$)?\s*(?P<lo>-?\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<s1>billion|million|thousand|bn|mm|m|b)?\s*"
    r"(?:-|–|—|to|through|and)\s*"
    r"(?P<d2>\$)?\s*(?P<hi>-?\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<s2>billion|million|thousand|bn|mm|m|b)?"
    r"(?P<after>\s+(?:Full[- ]Year|FY|Fiscal(?:\s+Year)?)\s*'?20\d{2}\b.{0,28}\b(?:Adjusted\s+)?Guidance\b)",
    re.I,
)


def _compact_metric_forward_guidance_value(clause: str, anchor: int, mention) -> _ValueBinding | None:
    """Bind only deterministic metric-before-value compact guidance rows.

    Example: ``EBITDA (1) of $381 million to $403 million Full Year 2025 Adjusted Guidance``.
    The range must immediately follow the metric (apart from a footnote and
    ``of``/``at``), and an explicit full-year guidance label must immediately
    follow the range. This intentionally does not cover free prose.
    """
    mention_end = anchor + len(mention.text)
    tail = clause[mention_end:min(len(clause), mention_end + 180)]
    match = _COMPACT_FORWARD_MONEY_RANGE.match(tail)
    if not match:
        return None

    s1 = (match.group("s1") or "").lower()
    s2 = (match.group("s2") or "").lower()
    if s1 and s2 and s1 != s2:
        aliases = {"m": "million", "mm": "million", "b": "billion", "bn": "billion"}
        if aliases.get(s1, s1) != aliases.get(s2, s2):
            return None
    scale = match.group("s2") or match.group("s1")
    if not scale:
        return None

    unit = _unit_from_scale(
        scale,
        mention.metric,
        dollar=bool(match.group("d1") or match.group("d2")),
    )
    if unit is GuidanceUnit.UNKNOWN:
        return None

    low = float(match.group("lo").replace(",", ""))
    high = float(match.group("hi").replace(",", ""))
    if low > high:
        return None

    value_start = mention_end + match.start("lo")
    if match.group("d1"):
        value_start = mention_end + match.start("d1")
    value_end = mention_end + match.end("s2") if match.group("s2") else mention_end + match.end("s1")
    return _ValueBinding(
        low,
        high,
        unit,
        GuidanceValueKind.ABSOLUTE_LEVEL,
        clause[value_start:value_end].strip(),
        value_start,
        value_end,
    )


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
    before = clause[max(0, min(anchor, value.start) - 140):value.start]
    after = clause[value.end:min(len(clause), value.end + 100)]
    forward_before = bool(_FORWARD_SIGNAL.search(before))
    if not forward_before and re.search(
        r"^\s*(?:,|;)?\s*(?:up|down)\s+\d+(?:\.\d+)?%\b"
        r"(?:\s+(?:YoY|Y/Y|year[- ]over[- ]year))?",
        after,
        re.I,
    ):
        return True
    actuals = list(_ACTUAL_VALUE.finditer(before))
    if not actuals:
        return False
    latest_actual = actuals[-1]
    after_actual = before[latest_actual.end():]
    if _FORWARD_SIGNAL.search(after_actual):
        return False
    return len(before) - latest_actual.end() <= 120


_SECTION_FULL_YEAR_HEADINGS = (
    re.compile(r"(?:^|[.;:•])\s*(?:initial\s+|updated\s+|revised\s+|increasing\s+|raising\s+)?full[- ]year\s+(20\d{2})(?:\s+(?:guidance|outlook))?\b", re.I),
    re.compile(r"(?:^|[.;:•])\s*fiscal\s+(20\d{2})\s+full[- ]year\s+(?:guidance|outlook)\b", re.I),
    re.compile(r"(?:^|[.;:•])\s*(?:FY|fiscal\s+year)\s*(20\d{2})\s+(?:guidance|outlook)\b", re.I),
    re.compile(r"(?:^|[.;:•])\s*(20\d{2})\s+(?:annual|financial)\s+(?:guidance|outlook)(?:\s+update)?\b", re.I),
)


def _nearest_section_heading_period(segment: str, clause: str, anchor: int, mention) -> _PeriodBinding | None:
    clause_start = segment.find(clause)
    if clause_start < 0:
        return None
    absolute_anchor = clause_start + anchor
    candidates: list[_PeriodBinding] = []
    for pattern in _SECTION_FULL_YEAR_HEADINGS:
        for match in pattern.finditer(segment):
            if match.end() > absolute_anchor:
                continue
            heading_distance = absolute_anchor - match.end()
            # Flattened annual-outlook bullet lists can place the final metric
            # slightly beyond the ordinary 420-character locality window.
            # Extend locality only for the explicit ``YYYY Annual/Financial
            # Guidance/Outlook`` section form; generic FY headings remain at
            # the original 420-character boundary.
            annual_table_heading = bool(re.search(
                r"\b20\d{2}\s+(?:annual|financial)\s+(?:guidance|outlook)(?:\s+update)?\b",
                match.group(0),
                re.I,
            ))
            max_heading_distance = 650 if annual_table_heading else 420
            if heading_distance > max_heading_distance:
                continue
            year = _normalize_year(match.group(1))
            candidates.append(
                _PeriodBinding(
                    f"FY{year}", GuidancePeriodKind.FULL_YEAR,
                    match.group(0).strip(" .;:•"), match.start(), match.end(),
                )
            )
    if not candidates:
        return None
    best = max(candidates, key=lambda item: item.end)
    between = segment[best.end:absolute_anchor]
    # Do not inherit a full-year heading across another explicit quarter/year heading.
    if re.search(
        r"\b(?:Q[1-4]\s*(?:FY)?\s*'?20\d{2}|(?:first|second|third|fourth)\s+quarter(?:\s+of)?\s+(?:fiscal(?:\s+year)?\s*)?20\d{2}|"
        r"(?:FY|fiscal(?:\s+year)?|full[- ]year)\s*'?20\d{2})\b",
        between,
        re.I,
    ):
        return None
    return best


def _selected_following_period_crosses_sentence(clause: str, anchor: int, mention, value, period: _PeriodBinding | None) -> bool:
    if period is None or period.start <= anchor:
        return False
    start = anchor + len(mention.text)
    if value is not None:
        start = max(start, value.end)
    if period.start <= start:
        return False
    return bool(re.search(r"(?<!\d)\.(?!\d)|[!?•]", clause[start:period.start]))


def _prefer_same_sentence_value(clause: str, anchor: int, mention, value):
    if value is None:
        return None
    mention_end = anchor + len(mention.text)
    tail = clause[mention_end:]
    boundary = re.search(r"(?<!\d)\.(?!\d)(?=\s|$)|[!?•]", tail)
    if boundary is None:
        return value
    sentence_end = mention_end + boundary.start()
    if value.start <= sentence_end:
        return value
    local_clause = clause[:sentence_end]
    rebound = _bind_value(local_clause, mention, anchor)
    if rebound is None:
        return value
    return rebound


def _value_precedes_forward_heading(clause: str, anchor: int, value) -> bool:
    if value is None:
        return False
    heading = re.compile(
        r"\b(?:raising|increasing|updating|updated|lowering|reducing|maintaining|reaffirming)\s+"
        r"(?:(?:full[- ]year|fiscal(?:\s+year)?|FY)\s*)?(?:20\d{2}|\d{2})?\s*"
        r"(?:guidance|outlook)\b",
        re.I,
    )
    for match in heading.finditer(clause):
        if anchor < match.start() and value.end <= match.start() and match.start() - value.end <= 140:
            return True
    return False


def _value_is_guidance_delta_not_level(clause: str, value) -> bool:
    if value is None or value.value_kind is not GuidanceValueKind.ABSOLUTE_LEVEL:
        return False
    before = clause[max(0, value.start - 140):value.start]
    # "raising the midpoint ... by $25m" and "guidance by $33m to $1.818b"
    # describe a delta, not an absolute guidance range/level.
    return bool(
        re.search(
            r"\b(?:rais(?:e|es|ed|ing)|increas(?:e|es|ed|ing)|boost(?:s|ed|ing)?)\b"
            r"[^.;]{0,120}\bby\s*$",
            before,
            re.I,
        )
        or re.search(r"\b(?:up|down)\s*$", before, re.I)
    )


_DOCUMENT_SECTION_HEADINGS = (
    (re.compile(r"\bfiscal\s+(20\d{2})\s+full[- ]year\s+(?:guidance|outlook)\b", re.I), "FY"),
    (re.compile(r"\bfull[- ]year\s+(20\d{2})(?:\s+(?:guidance|outlook))?\b", re.I), "FY"),
    (re.compile(r"\b(?:FY|fiscal\s+year)\s*(20\d{2})\s+(?:guidance|outlook)\b", re.I), "FY"),
    (re.compile(r"\b(20\d{2})\s+(?:annual|financial)\s+(?:guidance|outlook)(?:\s+update)?\b", re.I), "FY"),
    (re.compile(r"\bfiscal\s+(20\d{2})\s+(first|second|third|fourth)\s+quarter\s+(?:guidance|outlook)\b", re.I), "QY"),
    (re.compile(r"\b(first|second|third|fourth)\s+quarter(?:\s+of)?\s+fiscal(?:\s+year)?\s+(20\d{2})(?:\s+(?:guidance|outlook))?\b", re.I), "QW"),
    (re.compile(r"\b(first|second|third|fourth)\s+quarter\s+(20\d{2})(?:\s+(?:guidance|outlook))?\b", re.I), "QW"),
    (re.compile(r"\bQ([1-4])\s*(?:FY|fiscal(?:\s+year)?)?\s*'?\s*(20\d{2})(?:\s+(?:guidance|outlook))?\b", re.I), "QN"),
)


def _document_heading_period(text: str, segment: str, clause: str, anchor: int, mention) -> _PeriodBinding | None:
    flat = re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()
    needle = re.sub(r"\s+", " ", segment).strip()
    clause_start = segment.find(clause)
    if not needle or clause_start < 0:
        return None
    starts: list[int] = []
    pos = 0
    while len(starts) < 8:
        found = flat.find(needle, pos)
        if found < 0:
            break
        starts.append(found)
        pos = found + 1
    if not starts:
        return None

    resolved: list[_PeriodBinding] = []
    quarter_map = {"first": "1", "second": "2", "third": "3", "fourth": "4"}
    for segment_start in starts:
        metric_abs = segment_start + clause_start + anchor
        window_start = max(0, metric_abs - 750)
        prefix = flat[window_start:metric_abs]
        headings: list[tuple[int, _PeriodBinding]] = []
        for pattern, kind in _DOCUMENT_SECTION_HEADINGS:
            for match in pattern.finditer(prefix):
                absolute_start = window_start + match.start()
                absolute_end = window_start + match.end()
                if kind == "FY":
                    year = _normalize_year(match.group(1))
                    binding = _PeriodBinding(f"FY{year}", GuidancePeriodKind.FULL_YEAR, match.group(0), absolute_start, absolute_end)
                elif kind == "QY":
                    year = _normalize_year(match.group(1))
                    q = quarter_map[match.group(2).lower()]
                    binding = _PeriodBinding(f"Q{q}FY{year}", GuidancePeriodKind.QUARTER, match.group(0), absolute_start, absolute_end)
                else:
                    token = match.group(1)
                    q = token if token.isdigit() else quarter_map[token.lower()]
                    year = _normalize_year(match.group(2))
                    binding = _PeriodBinding(f"Q{q}FY{year}", GuidancePeriodKind.QUARTER, match.group(0), absolute_start, absolute_end)
                headings.append((absolute_end, binding))
        if not headings:
            continue
        headings.sort(key=lambda item: item[0], reverse=True)
        nearest = headings[0][1]
        if metric_abs - nearest.end > 750:
            continue
        resolved.append(nearest)
    periods = {item.period for item in resolved}
    if len(periods) != 1:
        return None
    return resolved[0]


def _metric_value_crosses_sentence(clause: str, anchor: int, mention, value) -> bool:
    if value is None:
        return False
    metric_start = anchor
    metric_end = anchor + len(mention.text)
    if value.start >= metric_end:
        between = clause[metric_end:value.start]
    elif value.end <= metric_start:
        between = clause[value.end:metric_start]
    else:
        return False
    return bool(re.search(r"(?<!\d)\.(?!\d)(?=\s|$)|[!?•]", between))


def _money_metric_margin_percent(clause: str, mention, value) -> bool:
    if value is None or value.unit is not GuidanceUnit.PERCENT:
        return False
    if mention.metric not in {GuidanceMetric.REVENUE, GuidanceMetric.EBITDA, GuidanceMetric.FCF}:
        return False
    before = clause[max(0, value.start - 65):value.start]
    return bool(re.search(r"\bmargin(?:\s+(?:of|at))?\s*$", before, re.I))


_DIRECT_GUIDANCE_METRIC = {
    GuidanceMetric.REVENUE: r"(?:total\s+|consolidated\s+)?(?:revenue|net\s+sales)",
    GuidanceMetric.EBITDA: r"(?:(?:adjusted|non[- ]GAAP)\s+)?EBITDA",
    GuidanceMetric.FCF: r"(?:free\s+cash\s+flow|FCF)",
    GuidanceMetric.EPS: r"(?:(?:adjusted|non[- ]GAAP|GAAP)\s+)?(?:diluted\s+)?(?:EPS|earnings\s+per\s+(?:common\s+)?share)",
    GuidanceMetric.GROSS_MARGIN: r"(?:(?:adjusted|non[- ]GAAP)\s+)?gross(?:\s+profit)?\s+margin",
    GuidanceMetric.OPERATING_MARGIN: r"(?:(?:adjusted|non[- ]GAAP)\s+)?operating\s+margin",
}


def _direct_guidance_period(clause: str, anchor: int, mention) -> _PeriodBinding | None:
    metric_pattern = _DIRECT_GUIDANCE_METRIC.get(mention.metric)
    if not metric_pattern:
        return None
    left = max(0, anchor - 190)
    right = min(len(clause), anchor + len(mention.text) + 190)
    local = clause[left:right]
    candidates: list[tuple[int, _PeriodBinding]] = []
    patterns = [
        re.compile(rf"\b(20\d{{2}})\s+{metric_pattern}\s+(?:guidance|outlook)\b", re.I),
        re.compile(rf"\b(?:guidance|outlook)\s+(?:for\s+)?(?:full[- ]year\s+|fiscal(?:\s+year)?\s+)?(20\d{{2}})\b[^.;]{{0,90}}\b{metric_pattern}\b", re.I),
    ]
    for pattern in patterns:
        for match in pattern.finditer(local):
            year = _normalize_year(match.group(1))
            start, end = left + match.start(), left + match.end()
            distance = _span_gap(start, end, anchor, anchor + len(mention.text))
            candidates.append((distance, _PeriodBinding(f"FY{year}", GuidancePeriodKind.FULL_YEAR, match.group(0), start, end)))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], -item[1].end))
    best_distance = candidates[0][0]
    tied = [item[1] for item in candidates if item[0] == best_distance]
    periods = {item.period for item in tied}
    return tied[0] if len(periods) == 1 else None


def _normalize_margin_level(clause: str, anchor: int, mention, value):
    if value is None or mention.metric not in {GuidanceMetric.GROSS_MARGIN, GuidanceMetric.OPERATING_MARGIN}:
        return value
    if value.unit is not GuidanceUnit.PERCENT or value.value_kind is not GuidanceValueKind.DELTA:
        return value
    metric_end = anchor + len(mention.text)
    if value.start < anchor:
        local = clause[value.start:metric_end]
    else:
        local = clause[anchor:value.end]
    # A directly stated margin percentage is a level. Keep true change language
    # ("margin expansion/increase of X%") as a delta.
    if re.search(r"\bmargin\b[^.;]{0,55}(?:approximately|about|around|of|at|between|range)?[^.;]{0,24}\d+(?:\.\d+)?\s*%", local, re.I) and not re.search(
        r"\bmargin\s+(?:increase|decrease|expansion|contraction|improvement|decline)\s+(?:of|by)\b",
        local,
        re.I,
    ):
        return _ValueBinding(value.low, value.high, value.unit, GuidanceValueKind.ABSOLUTE_LEVEL, value.text, value.start, value.end)
    return value


_OTHER_METRIC_OWNER_PATTERNS = {
    GuidanceMetric.REVENUE: re.compile(r"\b(?:revenue|net\s+sales|sales)\b", re.I),
    GuidanceMetric.EBITDA: re.compile(r"\b(?:adjusted\s+)?EBITDA\b", re.I),
    GuidanceMetric.FCF: re.compile(r"\b(?:free\s+cash\s+flow|FCF)\b", re.I),
    GuidanceMetric.EPS: re.compile(r"\b(?:diluted\s+)?(?:EPS|earnings\s+per\s+(?:common\s+)?share)\b", re.I),
    GuidanceMetric.GROSS_MARGIN: re.compile(r"\bgross(?:\s+profit)?\s+margin\b", re.I),
    GuidanceMetric.OPERATING_MARGIN: re.compile(r"\boperating\s+margin\b", re.I),
}


def _value_crosses_other_metric_owner(clause: str, anchor: int, mention, value) -> bool:
    if value is None or value.start >= anchor:
        return False
    between = clause[value.end:anchor]
    for metric, pattern in _OTHER_METRIC_OWNER_PATTERNS.items():
        if metric is mention.metric:
            continue
        if pattern.search(between):
            return True
    return False


def _local_preliminary_actual(clause: str, anchor: int, mention, value) -> bool:
    if value is None:
        return False
    left = max(clause.rfind("•", 0, anchor), clause.rfind(".", 0, anchor), clause.rfind(";", 0, anchor))
    left = 0 if left < 0 else left + 1
    right_candidates = [x for x in (clause.find("•", value.end), clause.find(".", value.end), clause.find(";", value.end)) if x >= 0]
    right = min(right_candidates) if right_candidates else len(clause)
    local = clause[left:right]
    return bool(
        re.search(r"\bpreliminary\s+unaudited\b", local, re.I)
        and re.search(r"\b(?:first|second|third|fourth)\s+quarter\b", local, re.I)
        and re.search(r"\b(?:revenue|net\s+sales|sales|EPS|earnings)\b", local, re.I)
    )



def _compact_forward_period_is_owned(clause: str, value, period: _PeriodBinding | None) -> bool:
    """Treat a trailing FY period as part of the same deterministic compact row.

    This is deliberately narrower than general following-period recovery. The
    value must already be the strict compact-forward owned value, the selected
    period must be FULL_YEAR, start immediately after that value, and the
    period must itself be followed by an explicit Guidance label.
    """
    if value is None or period is None or period.kind is not GuidancePeriodKind.FULL_YEAR:
        return False
    if period.start < value.end or period.start - value.end > 4:
        return False
    if clause[value.end:period.start].strip():
        return False
    suffix = clause[period.end:min(len(clause), period.end + 36)]
    return bool(re.match(r"\s*(?:Adjusted\s+)?Guidance\b", suffix, re.I))


def _following_period_is_new_outlook_heading(clause: str, anchor: int, mention, value, period: _PeriodBinding | None) -> bool:
    if period is None or value is None or period.start <= value.end:
        return False
    between = clause[value.end:period.start]
    if between.strip(" \t\r\n:;-–—•"):
        return False
    tail = clause[period.start:min(len(clause), period.end + 45)]
    return bool(re.search(r"\b(?:outlook|guidance)\b\s*:?", tail, re.I))


def _period_is_presentation_footer(clause: str, period: _PeriodBinding | None) -> bool:
    if period is None:
        return False
    local = clause[max(0, period.start - 12):min(len(clause), period.end + 40)]
    return bool(re.search(r"\bearnings\s+presentation\b", local, re.I))


def _value_starts_inside_period_token_v19(clause: str, value) -> bool:
    """Reject a money range whose first numeric token is actually Q/FY syntax."""
    if value is None:
        return False
    prefix = clause[max(0, value.start - 10):value.start]
    return bool(re.search(r"(?:\b[1-4]Q|\bQ[1-4]|\bFY)\s*$", prefix, re.I))


def _syntactic_cross_metric_owner_v19(clause: str, anchor: int, mention, value) -> bool:
    """Reject only explicit cross-metric ownership of the selected value.

    This deliberately avoids the broad proximity/locality rule that over-pruned
    compact guidance tables in v18. Another metric must be syntactically tied
    to the value, e.g. ``EPS of $3.00`` or ``$3.00 in non-GAAP diluted net EPS``.
    """
    if value is None:
        return False
    for owner, pattern in _VALUE_OWNER_PATTERNS:
        if owner is mention.metric:
            continue
        for match in pattern.finditer(clause):
            # Other metric immediately owns a following value.
            if match.end() <= value.start:
                bridge = clause[match.end():value.start]
                if len(bridge) <= 36 and re.fullmatch(
                    r"\s*(?:(?:of|is|at|to|range\s+of)\s*)?[:=,-]?\s*",
                    bridge,
                    re.I,
                ):
                    return True
            # Value explicitly described as belonging to another metric.
            elif match.start() >= value.end:
                bridge = clause[value.end:match.start()]
                if len(bridge) <= 48 and re.fullmatch(
                    r"\s*(?:in|for|per|of)\s+(?:(?:non[- ]?gaap|adjusted)\s+)?(?:(?:diluted|net)\s+){0,2}",
                    bridge,
                    re.I,
                ):
                    return True
    return False


def _following_period_is_reference_v19(clause: str, value, period: _PeriodBinding | None) -> bool:
    """A period after the value can be a comparison/reference, not its target."""
    if value is None or period is None or period.start <= value.end:
        return False
    bridge = clause[value.end:period.start]
    tail = clause[period.end:min(len(clause), period.end + 100)]
    if re.search(
        r"\b(?:unchanged\s+from|compared\s+(?:with|to)|from\s+(?:the\s+)?prior|"
        r"previous(?:ly)?|as\s+reported|reported|results?|reference(?:d)?)\b",
        bridge[-160:],
        re.I,
    ):
        return True
    if re.match(
        r"\s*(?:earnings\s+(?:release|materials?|presentation)|conference\s+call|"
        r"results?|release|materials?|presentation)\b",
        tail,
        re.I,
    ):
        return True
    return False


def _ambiguous_current_guidance_columns_v19(clause: str, anchor: int, mention, value) -> bool:
    """Fail closed only for flattened Current Guidance Q/FY column headers."""
    if value is None:
        return False
    left = max(0, anchor - 220)
    local = clause[left:min(len(clause), value.end + 40)]
    if not re.search(r"\bcurrent\s+guidance\b", local, re.I):
        return False

    quarters: list[tuple[int, int]] = []
    full_years: list[tuple[int, int]] = []
    for pattern in _CANONICAL_QUARTER:
        for match in pattern.finditer(local):
            if left + match.end() <= value.start:
                quarters.append((left + match.start(), left + match.end()))
    for pattern in _CANONICAL_FULL_YEAR:
        for match in pattern.finditer(local):
            if left + match.end() > value.start:
                continue
            span = (left + match.start(), left + match.end())
            if any(qs <= span[0] and span[1] <= qe for qs, qe in quarters):
                continue
            full_years.append(span)
    if not quarters or not full_years:
        return False
    nearest_q = min(value.start - end for _, end in quarters)
    nearest_fy = min(value.start - end for _, end in full_years)
    return nearest_q <= 140 and nearest_fy <= 140


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


_PRIOR_ROLE_OWNERSHIP_MARKER = re.compile(
    r"(?:\b(?:from\s+(?:our\s+)?)?prior(?:\s+[A-Za-z0-9*.-]+){0,5}\s+(?:guidance|outlook|forecast)\b"
    r"|\bprevious(?:\s+[A-Za-z0-9*.-]+){0,5}\s+(?:guidance|outlook|forecast)\b"
    r"|\bpreviously\s+(?:expected|forecast|guided|provided|stated)\b)",
    re.I,
)


def _quoted_prior_marker_owned_by_other_metric(clause: str, anchor: int, mention, value) -> bool:
    """Detect only cross-metric contamination of an already-QUOTED_PRIOR role.

    The original role parser remains authoritative. This helper is used only
    after it returned QUOTED_PRIOR. In flattened multi-metric outlook lists,
    an earlier row's ``previous outlook`` marker can otherwise leak into the
    next row's current value. We flip the role only when the latest qualifying
    prior marker is demonstrably owned by a different metric.
    """
    if value is None:
        return False
    left = max(0, value.start - 220)
    markers = list(_PRIOR_ROLE_OWNERSHIP_MARKER.finditer(clause, left, value.start))
    if not markers:
        return False
    mentions = _metric_mentions(clause)
    for marker in reversed(markers):
        # A marker at/after this metric mention belongs to the current row.
        if marker.start() >= anchor:
            return False
        # A marker phrase that itself names the current metric is also owned.
        if any(
            item.metric is mention.metric
            and not (item.end <= marker.start() or item.start >= marker.end())
            for item in mentions
        ):
            return False
        # Otherwise use the nearest metric immediately preceding the marker as
        # its owner. Only explicit ownership by a *different* metric is enough
        # to override the original QUOTED_PRIOR classification.
        preceding = [item for item in mentions if item.end <= marker.start()]
        if preceding:
            owner = max(preceding, key=lambda item: item.end)
            return owner.metric is not mention.metric
    return False


def _fact_role(clause: str, value) -> GuidanceFactRole:
    if value is None:
        return GuidanceFactRole.CURRENT
    before = clause[max(0, value.start - 180):value.start]
    prior_patterns = [
        re.compile(r"\b(?:from\s+(?:our\s+)?)?prior(?:\s+[A-Za-z0-9*.-]+){0,5}\s+(?:guidance|outlook|forecast)\b", re.I),
        re.compile(r"\bprevious(?:\s+[A-Za-z0-9*.-]+){0,5}\s+(?:guidance|outlook|forecast|estimate)\b", re.I),
        re.compile(r"\bpreviously(?:\s+(?:expected|forecast|guided|provided|stated|updated))?\b", re.I),
    ]
    matches = [match for pattern in prior_patterns for match in pattern.finditer(before)]
    if not matches:
        return GuidanceFactRole.CURRENT
    latest = max(matches, key=lambda item: item.end())
    tail = before[latest.end():]
    # A fresh forward/current cue after the historical marker owns the value.
    # Example: "reaffirming ... previously updated ... The Company expects ... $X".
    if re.search(
        r"\b(?:now|currently|reaffirm(?:s|ed|ing)?|maintain(?:s|ed|ing)?|"
        r"expects?|expected|anticipat(?:e|es|ed|ing)|project(?:s|ed|ing))\b",
        tail,
        re.I,
    ):
        return GuidanceFactRole.CURRENT
    return GuidanceFactRole.QUOTED_PRIOR

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
    if "net sales" in lower:
        prefix = clause[max(0, anchor - 70):anchor]
        prefix = re.split(r"[.;:•|\n\r]", prefix)[-1].strip()
        branded = _BRANDED_NET_SALES.search(prefix)
        if branded and branded.group("brand").upper() not in _BRAND_SCOPE_RESERVED:
            return GuidanceScopeKind.PRODUCT, branded.group("brand") + " net sales"
        return GuidanceScopeKind.COMPANY, label
    if "total product revenue" in lower or "total revenue" in lower or "consolidated revenue" in lower:
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


def _suffix_owned_money_range(clause: str, anchor: int, mention) -> _ValueBinding | None:
    prefix_start = max(0, anchor - 90)
    prefix = clause[prefix_start:anchor]
    boundaries = [
        match.start()
        for match in re.finditer(r";|•|(?<!\d)\.(?!\d)", prefix)
    ]
    boundary = max(boundaries) if boundaries else -1
    local = prefix[boundary + 1:]

    basis_tail = re.search(r"\s+(?:adjusted|non[- ]GAAP|GAAP)\s*$", local, re.I)
    value_local = local[:basis_tail.start()] if basis_tail else local
    match = _SUFFIX_MONEY_RANGE.search(value_local)
    if not match:
        return None

    absolute_start = prefix_start + boundary + 1 + match.start()
    absolute_end = prefix_start + boundary + 1 + match.end()
    bridge = clause[absolute_end:anchor]
    if len(bridge) > 32 or not re.fullmatch(
        r"[\s,:()]*(?:(?:adjusted|non[- ]GAAP|GAAP)\s*)?",
        bridge,
        re.I,
    ):
        return None

    unit = _unit_from_scale(
        match.group("scale"),
        mention.metric,
        dollar=bool(match.group("d1") or match.group("d2")),
    )
    if unit is GuidanceUnit.UNKNOWN:
        return None
    low = float(match.group("lo").replace(",", ""))
    high = float(match.group("hi").replace(",", ""))
    if low > high:
        return None
    return _ValueBinding(
        low, high, unit, GuidanceValueKind.ABSOLUTE_LEVEL,
        match.group(0).strip(), absolute_start, absolute_end,
    )

def _breakeven_value(clause: str, anchor: int, mention) -> _ValueBinding | None:
    if mention.metric not in {GuidanceMetric.EBITDA, GuidanceMetric.FCF}:
        return None
    match = _BREAKEVEN_TO_MONEY.search(clause)
    if not match:
        return None
    if _span_gap(anchor, anchor + len(mention.text), match.start(), match.end()) > 150:
        return None
    unit = _unit_from_scale(match.group("scale"), mention.metric, dollar=bool(match.group("d")))
    if unit is GuidanceUnit.UNKNOWN:
        return None
    high = float(match.group("high").replace(",", ""))
    return _ValueBinding(
        0.0, high, unit, GuidanceValueKind.ABSOLUTE_LEVEL,
        match.group(0), match.start(), match.end(),
    )


def _ambiguous_eps_basis_window(clause: str, anchor: int, mention) -> bool:
    if mention.metric is not GuidanceMetric.EPS:
        return False
    window = clause[max(0, anchor - 45):anchor + len(mention.text)]
    adjusted = bool(re.search(r"\b(?:adjusted|non[- ]GAAP)\b", window, re.I))
    gaap = bool(re.search(r"(?<!non[- ])\bGAAP\b", window, re.I))
    return adjusted and gaap


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



_LOCAL_FISCAL_YEAR_QUARTER_V29 = re.compile(
    r"\bFiscal(?:\s+Year)?\s+(?P<year>20\d{2})\s+"
    r"(?P<word>First|Second|Third|Fourth)\s+Quarter\b",
    re.I,
)
_LOCAL_QFY_V29 = re.compile(
    r"\bQ(?P<q>[1-4])\s*(?:FY)?\s*'?(?P<year>(?:20)?\d{2})\b",
    re.I,
)
_LOCAL_NQ_V29 = re.compile(
    r"\b(?P<q>[1-4])Q\s*'?(?P<year>(?:20)?\d{2})\b",
    re.I,
)


def _local_explicit_quarter_before_value_v29(clause: str, anchor: int, mention, value) -> _PeriodBinding | None:
    """Recover a quarter only when the quarter directly owns this metric/value."""
    if value is None:
        return None
    candidates: list[_PeriodBinding] = []

    def directly_owned(match: re.Match[str]) -> bool:
        if match.end() > value.start:
            return False
        # Explicit quarter embedded in this metric's guidance phrase, e.g.
        # "revenue guidance for 2Q26 is $86-$88m".
        if match.start() >= anchor:
            if value.start - match.end() > 90:
                return False
            bridge = clause[max(0, anchor - 32):value.start]
            if not re.search(r"\b(?:guidance|outlook|forecast|estimat(?:e|es|ed)|expects?)\b", bridge, re.I):
                return False
            # A later explicit annual token before the value owns the value instead.
            tail = clause[match.end():value.start]
            if re.search(r"\b(?:FY\s*'?\d{2,4}|full[- ]year\s+20\d{2}|Fiscal(?:\s+Year)?\s+20\d{2})\b", tail, re.I):
                return False
            return True

        # Heading-owned form, e.g. "Fiscal 2026 First Quarter Outlook HPE estimates revenue ...".
        if anchor - match.end() > 70:
            return False
        bridge = clause[match.end():anchor]
        if re.search(r"[.;•]", bridge):
            return False
        return bool(re.match(r"\s*(?:outlook|guidance)\b", bridge, re.I))

    for match in _LOCAL_FISCAL_YEAR_QUARTER_V29.finditer(clause):
        if not directly_owned(match):
            continue
        q = _QUARTER_WORD[match.group("word").lower()]
        year = _normalize_year(match.group("year"))
        candidates.append(_PeriodBinding(f"Q{q}FY{year}", GuidancePeriodKind.QUARTER, match.group(0), match.start(), match.end()))

    for pattern in (_LOCAL_QFY_V29, _LOCAL_NQ_V29):
        for match in pattern.finditer(clause):
            if not directly_owned(match):
                continue
            q = match.group("q")
            year = _normalize_year(match.group("year"))
            candidates.append(_PeriodBinding(f"Q{q}FY{year}", GuidancePeriodKind.QUARTER, match.group(0), match.start(), match.end()))

    if not candidates:
        return None
    return max(candidates, key=lambda item: item.end)



def _strict_segment_quarter_heading_v32(segment: str, clause: str, anchor: int, mention) -> _PeriodBinding | None:
    heading = re.match(
        r"\s*Fiscal(?:\s+Year)?\s+(?P<year>20\d{2})\s+"
        r"(?P<word>First|Second|Third|Fourth)\s+Quarter\s+"
        r"(?:Outlook|Guidance)\b",
        segment,
        re.I,
    )
    if heading is None:
        return None
    # Do not carry the heading through a later explicit quarter/year heading.
    metric_pos = segment.find(mention.text)
    if metric_pos < 0:
        return None
    between = segment[heading.end():metric_pos]
    if re.search(
        r"\b(?:Q[1-4]\s*(?:FY)?\s*'?20\d{2}|[1-4]Q\s*'?20\d{2}|"
        r"Fiscal(?:\s+Year)?\s+20\d{2}\s+(?:First|Second|Third|Fourth)\s+Quarter|"
        r"FY\s*'?20\d{2}|Full[- ]Year\s+20\d{2})\b",
        between,
        re.I,
    ):
        return None
    q = _QUARTER_WORD[heading.group("word").lower()]
    year = _normalize_year(heading.group("year"))
    return _PeriodBinding(
        f"Q{q}FY{year}",
        GuidancePeriodKind.QUARTER,
        heading.group(0),
        heading.start(),
        heading.end(),
    )


def _trailing_full_year_heading_v32(clause: str, anchor: int, mention, value) -> _PeriodBinding | None:
    """Recover only a terminal `. Full Year YYYY` layout heading.

    The value must belong to explicit directional guidance/outlook in the same
    sentence. This targets flattened SEC/table layout such as PLTR without
    reintroducing the rejected generic following-section fallback.
    """
    if value is None:
        return None
    tail = clause[value.end:]
    match = re.match(
        r"\s*[.!?]\s*Full[- ]Year\s+(?P<year>20\d{2})\s*$",
        tail,
        re.I,
    )
    if match is None:
        return None
    local = clause[max(0, anchor - 120):value.start]
    if not re.search(r"\b(?:guidance|outlook|forecast)\b", local, re.I):
        return None
    if not re.search(r"\b(?:rais(?:e|es|ed|ing)|lower(?:s|ed|ing)?|revis(?:e|es|ed|ing)|updat(?:e|es|ed|ing)|reaffirm(?:s|ed|ing)?)\b", local, re.I):
        return None
    start = value.end + match.start("year")
    end = value.end + match.end("year")
    year = _normalize_year(match.group("year"))
    return _PeriodBinding(f"FY{year}", GuidancePeriodKind.FULL_YEAR, match.group(0).strip(), start, end)

def _semantic_alias_reason_v29(fact: TypedGuidanceFact) -> str | None:
    if not fact.provenance:
        return None
    evidence = fact.provenance[0].evidence
    clause = evidence.full_text or ""
    if not clause:
        return None

    ms, me = evidence.metric_start, evidence.metric_end
    vs, ve = evidence.value_start, evidence.value_end
    ps, pe = evidence.period_start, evidence.period_end

    if fact.metric is GuidanceMetric.EPS and ve is not None:
        if re.match(r"\s*(?:million|billion|thousand|mm|bn)\b", clause[ve:ve + 24], re.I):
            return "eps_money_scale_cross_metric"

    if fact.role is GuidanceFactRole.CURRENT and me is not None and vs is not None and vs > me:
        bridge = clause[me:vs]
        historical = re.search(
            r"\b(?:had|previously)\s+(?:expected|projected|forecast|guided|anticipated)\b",
            bridge,
            re.I,
        )
        if historical is not None:
            after_historical = bridge[historical.end():]
            if not re.search(r"\b(?:now|currently|today)\b", after_historical, re.I):
                return "current_value_crosses_historical_expectation"

        fresh = list(re.finditer(
            r"\b(?:rais(?:e|es|ed|ing)|revis(?:e|es|ed|ing)|updat(?:e|es|ed|ing)|"
            r"lower(?:s|ed|ing)?|reaffirm(?:s|ed|ing)?)\b[^.;•]{0,80}"
            r"\b(?:guidance|outlook)\b",
            bridge,
            re.I,
        ))
        if fresh:
            marker = fresh[-1]
            result_side = bridge[:marker.start()]
            if len(bridge) >= 96 and re.search(r"\b(?:up|down)\s+\d+(?:\.\d+)?%\s+YoY\b", result_side, re.I):
                return "result_metric_crosses_new_guidance_row"

    if fact.metric is GuidanceMetric.REVENUE and vs is not None and ve is not None:
        before = clause[max(0, ms - 180 if ms is not None else vs - 180):vs]
        after = clause[ve:min(len(clause), ve + 100)]
        if (
            re.search(r"\brecord\s+(?:total\s+)?revenue\b", before, re.I)
            and re.match(r"\s*,?\s*(?:up|down)\s+\d+(?:\.\d+)?%", after, re.I)
        ):
            return "realized_record_revenue"
        if (
            re.search(r"\bfinancial\s+results\b", before, re.I)
            and re.match(r"\s*,?\s*(?:up|down|compared\s+(?:to|with)|versus|vs\.?)\b", after, re.I)
        ):
            return "financial_results_actual"

        if me is not None:
            bridge = clause[me:vs]
            if re.search(r"\b(?:net\s+sales|revenue)?\s*growth\s+YoY\b", bridge, re.I):
                if fact.unit in {
                    GuidanceUnit.USD,
                    GuidanceUnit.USD_THOUSAND,
                    GuidanceUnit.USD_MILLION,
                    GuidanceUnit.USD_BILLION,
                }:
                    return "growth_row_money_neighbor"

    if ve is not None and ps is not None and ps > ve:
        bridge = clause[ve:ps]
        if re.search(r"\b(?:increase|growth|decrease|decline)\b[^.;•]{0,90}\bfrom\s*$", bridge, re.I):
            return "comparison_year_as_period"
        if fact.fiscal_period.startswith("FY"):
            before_value = clause[max(0, vs - 260 if vs is not None else 0):ve]
            quarter_before = bool(
                re.search(
                    r"\b(?:Q[1-4]\s*(?:FY)?\s*'?20\d{2}|[1-4]Q\s*'?20\d{2}|"
                    r"(?:first|second|third|fourth)\s+quarter(?:\s+(?:of\s+)?20\d{2})?)"
                    r"[^.;•]{0,55}\b(?:guidance|outlook)\b",
                    before_value,
                    re.I,
                )
                or re.search(
                    r"\b(?:guidance|outlook)\b[^.;•]{0,55}"
                    r"(?:Q[1-4]\s*(?:FY)?\s*'?20\d{2}|[1-4]Q\s*'?20\d{2}|"
                    r"(?:first|second|third|fourth)\s+quarter(?:\s+(?:of\s+)?20\d{2})?)",
                    before_value,
                    re.I,
                )
            )
            if quarter_before:
                return "following_full_year_overrides_local_quarter"

    if pe is not None and vs is not None and pe < vs:
        bridge = clause[pe:vs]
        if re.search(
            r"(?:^|[.!?•])\s*(?:FY\s*'?\d{2,4}|Fiscal(?:\s+Year)?\s+20\d{2}|20\d{2})"
            r"[^.;•]{0,35}\b(?:guidance|outlook)\b",
            bridge,
            re.I,
        ):
            return "stale_period_before_new_outlook"

    return None


def _suppress_semantic_aliases_v29(
    facts: Iterable[TypedGuidanceFact],
    rejected: list[dict],
) -> list[TypedGuidanceFact]:
    kept: list[TypedGuidanceFact] = []
    for fact in facts:
        reason = _semantic_alias_reason_v29(fact)
        if reason is None:
            kept.append(fact)
            continue
        rejected.append({
            "reason": reason,
            "metric": fact.metric.value,
            "period": fact.fiscal_period,
            "value": [fact.low, fact.high],
        })
    return kept


# Phase 1.1E manual-audit hardening. These guards are deliberately conservative:
# they reject ambiguous/non-guidance evidence rather than inventing a comparator.
# Frozen SOE thresholds and classifier rules are unchanged.
_FORMAL_GUIDANCE_NOUN_V33 = re.compile(r"\b(?:guidance|outlook|forecast)\b", re.I)
_THREE_MONTH_OUTLOOK_V33 = re.compile(
    r"\b(?:outlook|guidance)\s+for\s+(?:the\s+)?three\s+months?\s+ending\b"
    r"|\bthree\s+months?\s+ending\b.{0,90}\b(?:outlook|guidance)\b",
    re.I | re.S,
)
_PARALLEL_QUARTER_V33 = re.compile(
    r"\b(?:Q[1-4]\s*(?:FY)?\s*'?20\d{2}|FY\s*20\d{2}\s+Q[1-4]|"
    r"(?:first|second|third|fourth)\s+quarter(?:\s+(?:of|fiscal(?:\s+year)?))?\s+20\d{2})\b",
    re.I,
)
_PARALLEL_FULL_YEAR_V33 = re.compile(
    r"\b(?:full[- ]year\s+20\d{2}|FY\s*20\d{2}\s+(?:guidance|outlook))\b",
    re.I,
)
_PARALLEL_COLUMNS_V33 = re.compile(
    r"\blow\s+high\b.{0,140}\blow\s+high\b"
    r"|\bFY\s*20\d{2}\s+Q[1-4]\s+guidance\b.{0,100}\bFY\s*20\d{2}\s+guidance\b",
    re.I | re.S,
)
_OUTLOOK_ACTUAL_COLUMNS_V33 = re.compile(
    r"\bFY\s*(20\d{2})\s+outlook\b.{0,120}\bFY\s*(20\d{2})\s+actual\b",
    re.I | re.S,
)


def _manual_audit_semantic_reason_v33(fact: TypedGuidanceFact) -> str | None:
    if not fact.provenance:
        return None
    evidence = fact.provenance[0].evidence
    clause = evidence.full_text or ""
    if not clause:
        return None
    ms, me = evidence.metric_start, evidence.metric_end
    vs, ve = evidence.value_start, evidence.value_end

    # LOWER/WITHDRAW must be guidance-local. Ordinary lower costs, lower demand,
    # lower year-over-year revenue, or rate cuts are not formal guidance actions.
    if (
        fact.value_kind is GuidanceValueKind.QUALITATIVE
        and fact.explicit_action in {GuidanceAction.LOWER, GuidanceAction.WITHDRAW}
        and ms is not None
    ):
        local = clause[max(0, ms - 180):min(len(clause), (me or ms) + 180)]
        if not _FORMAL_GUIDANCE_NOUN_V33.search(local) and not re.search(
            r"\b(?:range|target|projection)s?\b", local, re.I
        ):
            return "directional_action_not_guidance_local"

    # A three-month outlook is not full-year guidance merely because the calendar
    # year appears in the ending date.
    if fact.period_kind is GuidancePeriodKind.FULL_YEAR and _THREE_MONTH_OUTLOOK_V33.search(clause):
        return "three_month_outlook_misbound_full_year"

    # Flattened tables with simultaneous quarter and full-year columns are not
    # safe for a one-dimensional nearest-value binder. Fail closed instead of
    # comparing the first quarter column as annual guidance.
    if (
        _PARALLEL_QUARTER_V33.search(clause)
        and _PARALLEL_FULL_YEAR_V33.search(clause)
        and _PARALLEL_COLUMNS_V33.search(clause)
    ):
        return "ambiguous_parallel_quarter_full_year_columns"

    # Likewise, do not bind a value under the Actual column to the preceding
    # Outlook year simply because it is closer to the metric label.
    outlook_actual = _OUTLOOK_ACTUAL_COLUMNS_V33.search(clause)
    if outlook_actual and fact.fiscal_period == f"FY{outlook_actual.group(2)}":
        return "outlook_actual_column_period_misbind"

    if ms is not None:
        metric_local = clause[max(0, ms - 45):min(len(clause), (me or ms) + 45)]
        if fact.metric is GuidanceMetric.REVENUE and re.search(
            r"\bcosts?\s+of\s+(?:contract\s+)?revenue\b", metric_local, re.I
        ):
            return "revenue_token_inside_cost_metric"

    if vs is not None and ve is not None:
        before = clause[max(0, vs - 260):vs]
        after = clause[ve:min(len(clause), ve + 120)]

        # Realized financial highlights/results followed by YoY comparison are
        # historical actuals, not forward guidance.
        if (
            re.search(r"\bfinancial\s+(?:results|highlights)\b", before, re.I)
            and re.match(r"\s*,?\s*(?:up|down)\s+\d+(?:\.\d+)?%", after, re.I)
        ):
            return "financial_highlights_actual"

        # Dollar amount in "up/down ... YoY" is a change, not a guidance level.
        if (
            re.search(r"\b(?:up|down)\s+(?:by\s+|more\s+than\s+|approximately\s+)?\$?\s*$", before, re.I)
            and re.match(r"\s*(?:million|billion|thousand|mm|bn|m|b)?\s*(?:YoY|Y/Y|year[- ]over[- ]year)\b", after, re.I)
        ):
            return "yoy_change_not_guidance_level"

        # Flattened revised-guidance rows can put two Net Income ranges directly
        # before the EBITDA label. Do not let the second Net Income range become
        # a same-snapshot quoted-prior EBITDA value.
        if fact.metric is GuidanceMetric.EBITDA and ve <= (ms if ms is not None else ve):
            local = clause[max(0, vs - 220):min(len(clause), (me or ve) + 40)]
            money_range = r"\$?\s*\d[\d,]*(?:\.\d+)?\s*(?:-|–|—|to)\s*\$?\s*\d[\d,]*(?:\.\d+)?"
            if (
                re.search(r"\bnet\s+(?:income|loss)\b", local, re.I)
                and len(re.findall(money_range, local, re.I)) >= 2
            ):
                return "parallel_row_value_owned_by_net_income"

    return None


def _suppress_manual_audit_defects_v33(
    facts: Iterable[TypedGuidanceFact],
    rejected: list[dict],
) -> list[TypedGuidanceFact]:
    kept: list[TypedGuidanceFact] = []
    for fact in facts:
        reason = _manual_audit_semantic_reason_v33(fact)
        if reason is None:
            kept.append(fact)
            continue
        rejected.append({
            "reason": reason,
            "metric": fact.metric.value,
            "period": fact.fiscal_period,
            "value": [fact.low, fact.high],
        })
    return kept


# Phase 1.1E fresh 100-case manual-audit hardening (v34). These guards remain
# evidence-conservative: ambiguous accounting disclosures, realized results,
# cross-period table bleed, and mechanical per-share restatements are rejected
# rather than converted into economic guidance changes. Frozen SOE thresholds,
# weights, and classifier rules are unchanged.
_RPO_ACCOUNTING_DISCLOSURE_V34 = re.compile(
    r"\b(?:remaining\s+performance\s+obligations?|deferred\s+revenue)\b",
    re.I,
)
_RECOGNIZED_REVENUE_ACTUAL_V34 = re.compile(
    r"\b(?:during|for)\s+the\s+(?:three|six|nine|twelve)\s+months?\s+ended\b"
    r".{0,260}\brecognized\s+revenue\b",
    re.I | re.S,
)
_OUTLOOK_CURRENT_ACTUAL_HEADER_V34 = re.compile(
    r"\bOutlook\s+(20\d{2})\s+(20\d{2})\b",
    re.I,
)
_QUARTER_RESULTS_HEADER_V34 = re.compile(
    r"\b(?:First|Second|Third|Fourth)\s+Quarter\s+20\d{2}(?:\s+Results)?\s*:?",
    re.I,
)
_GENERIC_FINANCIAL_GUIDANCE_HEADING_V34 = re.compile(
    r"\bFinancial\s+Guidance\s+20\d{2}\s+Guidance\b",
    re.I,
)
_STOCK_SPLIT_RESTATEMENT_V34 = re.compile(
    r"\b(?:two[- ]for[- ]one|three[- ]for[- ]one|\d+[- ]for[- ]\d+)\s+stock\s+split\b"
    r".{0,280}\b(?:guidance|outlook)\b.{0,180}\b(?:pre[- ]split|post[- ]split|following)\b"
    r"|\bfollowing\s+(?:the\s+)?(?:two[- ]for[- ]one|three[- ]for[- ]one|\d+[- ]for[- ]\d+)\s+stock\s+split\b"
    r".{0,260}\b(?:guidance|outlook)\b",
    re.I | re.S,
)
_NAMED_ENTITY_GENERATE_REVENUE_V34 = re.compile(
    r"\bFor\s+the\s+full\s+calendar\s+year\s+20\d{2}\s*,?\s*"
    r"(?P<owner>[A-Z][A-Za-z0-9&.'-]{2,})\s+expects?\s+to\s+generate\s+revenue\b",
    re.I,
)


def _fresh_manual_audit_reason_v34(fact: TypedGuidanceFact) -> str | None:
    if not fact.provenance:
        return None
    evidence = fact.provenance[0].evidence
    clause = evidence.full_text or ""
    if not clause:
        return None
    ms, me = evidence.metric_start, evidence.metric_end
    vs, ve = evidence.value_start, evidence.value_end

    # Remaining-performance-obligation and deferred-revenue schedules describe
    # accounting recognition, not management guidance.
    if fact.metric is GuidanceMetric.REVENUE and _RPO_ACCOUNTING_DISCLOSURE_V34.search(clause):
        if re.search(
            r"\b(?:expects?\s+to\s+recognize|expected\s+to\s+be\s+recognized|recognize[d]?\s+as)\s+revenue\b"
            r"|\brevenue\s+is\s+expected\s+to\s+be\s+recognized\b",
            clause,
            re.I,
        ):
            return "remaining_performance_obligation_not_guidance"

    # Realized recognized-revenue disclosures must not become annual guidance.
    if fact.metric is GuidanceMetric.REVENUE and _RECOGNIZED_REVENUE_ACTUAL_V34.search(clause):
        return "recognized_revenue_historical_actual"

    # In flattened Outlook YYYY YYYY tables, the second year is the historical
    # actual/comparator column. Do not bind it as current guidance.
    if fact.metric is GuidanceMetric.REVENUE:
        header = _OUTLOOK_CURRENT_ACTUAL_HEADER_V34.search(clause)
        if header and fact.fiscal_period == f"FY{header.group(2)}":
            return "outlook_historical_column_not_guidance"

    # Result bullets can inherit a nearby "raising full-year guidance" action.
    # Reject the realized quarter value rather than treating GAAP/adjusted actuals
    # as a same-snapshot guidance revision.
    if fact.metric is GuidanceMetric.REVENUE and vs is not None and ve is not None:
        before = clause[max(0, vs - 360):vs]
        after = clause[ve:min(len(clause), ve + 90)]
        result_headers = list(_QUARTER_RESULTS_HEADER_V34.finditer(before))
        if result_headers:
            latest = result_headers[-1]
            result_tail = before[latest.end():]
            if not re.search(r"\b(?:guidance|outlook|forecast)\b", result_tail, re.I) and re.match(
                r"\s*,?\s*(?:up|down|\+|-)?\s*\d+(?:\.\d+)?%",
                after,
                re.I,
            ):
                return "quarter_results_actual_with_guidance_action_leak"

    # Historical FCF rows immediately preceding a generic Financial Guidance
    # heading are realized results, not the new full-year FCF outlook.
    if fact.metric is GuidanceMetric.FCF and vs is not None and ve is not None:
        after = clause[ve:min(len(clause), ve + 260)]
        before = clause[max(0, vs - 170):vs]
        if _GENERIC_FINANCIAL_GUIDANCE_HEADING_V34.search(after) and not re.search(
            r"\b(?:guidance|outlook|forecast|expects?|expected|reaffirm|reiterate|raise|lower)\b",
            before,
            re.I,
        ):
            return "historical_fcf_before_guidance_section"

    # "cost of revenues" / "costs of revenues" is an expense metric. The
    # revenue token inside that phrase cannot own a revenue guidance action.
    if fact.metric is GuidanceMetric.REVENUE and ms is not None:
        metric_local = clause[max(0, ms - 55):min(len(clause), (me or ms) + 55)]
        if re.search(r"\bcosts?\s+of\s+(?:contract\s+)?revenues?\b", metric_local, re.I):
            return "revenue_token_inside_cost_of_revenues"

    # If a quarter fact's selected value is explicitly introduced as full-year
    # guidance for the same metric, the quarter period is table/phrase bleed.
    if fact.period_kind is GuidancePeriodKind.QUARTER and vs is not None:
        before = clause[max(0, vs - 220):vs]
        metric_word = {
            GuidanceMetric.REVENUE: r"(?:revenue|net\s+sales)",
            GuidanceMetric.EPS: r"(?:EPS|earnings\s+per\s+(?:common\s+)?share)",
            GuidanceMetric.EBITDA: r"(?:adjusted\s+)?EBITDA",
            GuidanceMetric.FCF: r"(?:free\s+cash\s+flow|FCF)",
            GuidanceMetric.GROSS_MARGIN: r"gross(?:\s+profit)?\s+margin",
            GuidanceMetric.OPERATING_MARGIN: r"operating\s+margin",
        }.get(fact.metric)
        if metric_word and re.search(
            rf"\b(?:rais(?:e|es|ed|ing)|lower(?:s|ed|ing)?|provid(?:e|es|ed|ing)|maintain(?:s|ed|ing)?)\b"
            rf"[^.;•]{{0,80}}\b{metric_word}\b[^.;•]{{0,45}}\b(?:guidance|outlook)\b"
            rf"[^.;•]{{0,55}}\b(?:fiscal(?:\s+year)?|full[- ]year)\s+20\d{{2}}\b"
            r"|"
            rf"\b{metric_word}\b[^.;•]{{0,35}}\b(?:guidance|outlook)\b"
            rf"[^.;•]{{0,35}}\b(?:fiscal(?:\s+year)?|full[- ]year)\s+20\d{{2}}\b",
            before,
            re.I,
        ):
            return "full_year_guidance_misbound_to_quarter"

    # Per-share guidance mechanically restated for a stock split is not an
    # economic cut. Reject the nominal restatement so the classifier fails closed
    # rather than comparing pre-split and post-split EPS as like-for-like levels.
    if fact.metric is GuidanceMetric.EPS and _STOCK_SPLIT_RESTATEMENT_V34.search(clause):
        return "stock_split_eps_restatement_not_economic_cut"

    # A named non-issuer entity's stand-alone annual revenue expectation inside
    # an issuer filing is scope-ambiguous. Without issuer/entity resolution,
    # fail closed instead of treating it as consolidated company guidance.
    if fact.metric is GuidanceMetric.REVENUE and fact.scope_kind is GuidanceScopeKind.COMPANY:
        owner = _NAMED_ENTITY_GENERATE_REVENUE_V34.search(clause)
        if owner and owner.group("owner").lower() not in {"company", "management"}:
            return "named_entity_revenue_forecast_scope_ambiguous"

    return None


def _suppress_fresh_manual_audit_defects_v34(
    facts: Iterable[TypedGuidanceFact],
    rejected: list[dict],
) -> list[TypedGuidanceFact]:
    kept: list[TypedGuidanceFact] = []
    for fact in facts:
        reason = _fresh_manual_audit_reason_v34(fact)
        if reason is None:
            kept.append(fact)
            continue
        rejected.append({
            "reason": reason,
            "metric": fact.metric.value,
            "period": fact.fiscal_period,
            "value": [fact.low, fact.high],
        })
    return kept

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

    # Suppress an unscaled point/range shadow when its raw numeric token(s)
    # duplicate endpoint(s) of a scaled observation for the exact same economic
    # identity. Compare raw numbers deliberately: base-currency comparison cannot
    # detect the omitted "million/billion" token that created the shadow.
    for i, fact in enumerate(items):
        if i in remove or fact.low is None or fact.high is None or fact.unit is not GuidanceUnit.USD:
            continue
        if max(abs(fact.low), abs(fact.high)) >= 10_000:
            continue
        for j, other in enumerate(items):
            if i == j or j in remove or other.unit not in scaled_units:
                continue
            if not _same_economic_identity(fact, other):
                continue
            if other.low is None or other.high is None:
                continue
            raw_point_endpoint = (
                fact.low == fact.high
                and (abs(fact.low - other.low) <= 1e-9 or abs(fact.low - other.high) <= 1e-9)
            )
            raw_range_match = (
                abs(fact.low - other.low) <= 1e-9 and abs(fact.high - other.high) <= 1e-9
            )
            if raw_point_endpoint or raw_range_match:
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


_PENDING_GUIDANCE_REVIEW = re.compile(
    r"(?:\b(?:reviewing|reassessing|evaluating)\b.{0,260}\b(?:guidance|outlook)\b.{0,260}\b(?:will|expects?\s+to)\s+(?:provide|issue|announce|give)\b.{0,100}\bupdate\b"
    r"|\b(?:guidance|outlook)\b.{0,180}\bunder\s+review\b.{0,220}\bupdate\b)",
    re.I | re.S,
)


def _pending_guidance_review(clause: str) -> bool:
    """Identify an explicit pending-review state without treating prior bounds as current.

    The issuer has not withdrawn guidance, but the prior quantitative range is no
    longer a clean current reaffirmation. Emit a qualitative current observation
    at the new source timestamp so canonical assessment cannot fall back through
    the unresolved update to an older numeric snapshot.
    """
    return bool(_PENDING_GUIDANCE_REVIEW.search(clause))

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
            if _ambiguous_eps_basis_window(clause, anchor, mention):
                rejected.append({"reason": "ambiguous_accounting_basis", "metric": mention.metric.value, "evidence": clause[:500]}); continue
            pending_review = _pending_guidance_review(clause)
            previous_now_value, previous_now_prior = _previous_now_value_pair(clause, mention)
            directional_value, directional_prior = _directional_value_pair(clause, anchor, mention, local_action)
            suffix_value = _suffix_owned_money_range(clause, anchor, mention)
            breakeven_value = _breakeven_value(clause, anchor, mention)
            compact_forward_value = _compact_metric_forward_guidance_value(clause, anchor, mention)
            owned_value = previous_now_value or directional_value or suffix_value or breakeven_value or compact_forward_value
            value = owned_value or _bind_value(clause, mention, anchor)
            value = _prefer_same_sentence_value(clause, anchor, mention, value)
            value = _normalize_margin_level(clause, anchor, mention, value)
            explicit_prior = previous_now_prior or directional_prior
            if pending_review:
                value = None
                explicit_prior = None
            if value is not None and value.low > value.high:
                rejected.append({"reason": "invalid_reversed_range", "metric": mention.metric.value, "value_text": value.text, "evidence": clause[:500]}); continue
            if _value_crosses_other_metric_owner(clause, anchor, mention, value):
                rejected.append({"reason": "metric_value_cross_owner", "metric": mention.metric.value, "value_text": value.text, "evidence": clause[:500]}); continue
            if _value_is_guidance_delta_not_level(clause, value):
                rejected.append({"reason": "guidance_delta_not_absolute_level", "metric": mention.metric.value, "value_text": value.text, "evidence": clause[:500]}); continue
            if _metric_value_crosses_sentence(clause, anchor, mention, value):
                rejected.append({"reason": "metric_value_cross_sentence", "metric": mention.metric.value, "value_text": value.text, "evidence": clause[:500]}); continue
            if _money_metric_margin_percent(clause, mention, value):
                rejected.append({"reason": "metric_margin_not_metric_level", "metric": mention.metric.value, "value_text": value.text, "evidence": clause[:500]}); continue
            if value is not None and _syntactic_cross_metric_owner_v19(clause, anchor, mention, value):
                rejected.append({"reason": "syntactic_cross_metric_owner", "metric": mention.metric.value, "value_text": value.text, "evidence": clause[:500]}); continue
            if value is not None and owned_value is None and not _value_has_local_metric_owner(clause, anchor, mention, value):
                rejected.append({"reason": "metric_value_locality", "metric": mention.metric.value, "value_text": value.text, "evidence": clause[:500]}); continue
            if value is not None and _value_starts_inside_period_token_v19(clause, value):
                rejected.append({"reason": "period_token_numeric_fragment", "metric": mention.metric.value, "value_text": value.text, "evidence": clause[:500]}); continue
            if _ambiguous_current_guidance_columns_v19(clause, anchor, mention, value):
                rejected.append({"reason": "ambiguous_current_guidance_columns", "metric": mention.metric.value, "value_text": value.text if value is not None else None, "evidence": clause[:500]}); continue
            if value is not None and (_value_is_historical_actual(clause, anchor, value) or _value_precedes_forward_heading(clause, anchor, value) or _local_preliminary_actual(clause, anchor, mention, value)):
                rejected.append({"reason": "historical_actual", "metric": mention.metric.value, "value_text": value.text, "evidence": clause[:500]}); continue
            role = GuidanceFactRole.CURRENT if pending_review or previous_now_value is not None else _fact_role(clause, value)
            if (
                role is GuidanceFactRole.QUOTED_PRIOR
                and _quoted_prior_marker_owned_by_other_metric(clause, anchor, mention, value)
            ):
                role = GuidanceFactRole.CURRENT
            canonical_period = _canonical_period_binding(clause, anchor, mention)
            direct_period = _direct_guidance_period(clause, anchor, mention)
            period = canonical_period
            # A direct metric/year guidance phrase may override only an earlier
            # competing period. This repairs result-period bleed into later
            # guidance (e.g. Q1-2024 results -> 2025 revenue guidance) without
            # stealing a later, more-specific quarter or forward-year period.
            if direct_period is not None and (canonical_period is None or canonical_period.end <= direct_period.start):
                period = direct_period
            section_period = _nearest_section_heading_period(segment, clause, anchor, mention)
            compact_forward_period_owned = _compact_forward_period_is_owned(clause, compact_forward_value, period)
            if period is not None and period is not direct_period and not compact_forward_period_owned and (
                _selected_following_period_crosses_sentence(clause, anchor, mention, value, period)
                or _following_period_is_new_outlook_heading(clause, anchor, mention, value, period)
                or _following_period_is_reference_v19(clause, value, period)
            ):
                period = None
            if period is None:
                period = section_period
            local_quarter_period_v29 = _local_explicit_quarter_before_value_v29(clause, anchor, mention, value)
            if local_quarter_period_v29 is not None:
                period = local_quarter_period_v29
            strict_segment_quarter_v32 = _strict_segment_quarter_heading_v32(segment, clause, anchor, mention)
            if strict_segment_quarter_v32 is not None and (period is None or period.kind is GuidancePeriodKind.FULL_YEAR):
                period = strict_segment_quarter_v32
            if period is None:
                trailing_full_year_v32 = _trailing_full_year_heading_v32(clause, anchor, mention, value)
                if trailing_full_year_v32 is not None:
                    period = trailing_full_year_v32
            if _period_is_presentation_footer(clause, period):
                period = section_period if section_period is not None and not _period_is_presentation_footer(clause, section_period) else None
            # Narrow document-context recovery for flattened annual outlook rows.
            # A current value explicitly paired with a previous outlook/guidance
            # may inherit only a strict YYYY Annual/Financial Guidance/Outlook
            # heading from the preceding full-document context. Generic FY
            # headings remain excluded from this special fallback.
            if period is None and value is not None and re.search(
                r"\bprevious(?:\s+(?:non[- ]GAAP\s+)?)?(?:outlook|guidance)\b",
                clause,
                re.I,
            ):
                prior_pair_period = _document_heading_period(text, segment, clause, anchor, mention)
                if (
                    prior_pair_period is not None
                    and prior_pair_period.kind is GuidancePeriodKind.FULL_YEAR
                    and re.search(
                        r"\b20\d{2}\s+(?:annual|financial)\s+(?:guidance|outlook)(?:\s+update)?\b",
                        prior_pair_period.text,
                        re.I,
                    )
                ):
                    period = prior_pair_period
            directional_section = {GuidanceAction.RAISE, GuidanceAction.LOWER, GuidanceAction.REAFFIRM}
            if period is None and (local_action in directional_section or _action(segment) in directional_section):
                period = _document_heading_period(text, segment, clause, anchor, mention)
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
            if value is None and not pending_review and local_action not in {GuidanceAction.RAISE, GuidanceAction.LOWER, GuidanceAction.REAFFIRM, GuidanceAction.WITHDRAW}:
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
    facts = _suppress_manual_audit_defects_v33(facts, rejected)
    facts = _suppress_fresh_manual_audit_defects_v34(facts, rejected)
    facts = _suppress_document_fragments(facts, rejected)
    facts = _suppress_semantic_aliases_v29(facts, rejected)
    return RawTypedGuidanceExtraction(ticker=document.ticker, document_id=document.document_id, facts=tuple(facts), rejected_candidates=tuple(rejected))
