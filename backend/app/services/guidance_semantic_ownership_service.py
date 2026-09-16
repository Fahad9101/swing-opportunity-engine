from __future__ import annotations

import re
from functools import lru_cache

from app.domain.guidance_canonical_v1 import (
    GuidanceFactRole,
    GuidancePeriodKind,
    GuidanceScopeKind,
    GuidanceUnit,
    GuidanceValueKind,
    TypedGuidanceFact,
)
from app.domain.soe_v1_1 import GuidanceAction, GuidanceMetric, SourceDocument
from app.services.guidance_raw_typed_extractor import _PERCENT_RANGE
from app.services.fact_extraction_service import html_to_text


_SEMANTIC_VERSION = "semantic-ownership-v1"

_FORWARD_CUE = re.compile(
    r"\b(?:guidance|outlook|forecast|expects?|expected|anticipat(?:e|es|ed|ing)|"
    r"project(?:s|ed|ing)|provid(?:e|es|ed|ing)|issu(?:e|es|ed|ing)|"
    r"rais(?:e|es|ed|ing)|increas(?:e|es|ed|ing)|lower(?:s|ed|ing)?|"
    r"reduc(?:e|es|ed|ing)|reaffirm(?:s|ed|ing)?|reiterat(?:e|es|ed|ing)|"
    r"maintain(?:s|ed|ing)?)\b",
    re.I,
)
_CURRENT_CUE = re.compile(
    r"\b(?:current|updated|revised|now|currently|expects?|expected|"
    r"rais(?:e|es|ed|ing)|increas(?:e|es|ed|ing)|lower(?:s|ed|ing)?|"
    r"reduc(?:e|es|ed|ing)|reaffirm(?:s|ed|ing)?|maintain(?:s|ed|ing)?)\b",
    re.I,
)
_PRIOR_CUE = re.compile(
    r"\b(?:prior|previous|previously|former|earlier|original)\b(?!\s+(?:year|quarter)\b)", re.I,
)
_SENTENCE_BOUNDARY = re.compile(r"(?<!\d)\.(?!\d)|[;\n•·●]")
_STRONG_ACTUAL_CUE = re.compile(
    r"\b(?:reported|generated|delivered|achieved|realized|recognized|recorded|"
    r"exceeded|totaled|came\s+in\s+at|preliminary|unaudited|"
    r"(?:revenue|revenues|sales|EBITDA|free\s+cash\s+flow|FCF|EPS)\s+"
    r"(?:(?:was|were)|(?:increased|decreased|rose|fell|grew|declined)\s+to))\b",
    re.I,
)
_RESULT_CONTEXT = re.compile(r"\b(?:results?|actuals?|preliminary(?:\s+unaudited)?|unaudited)\b", re.I)
_LONG_TERM_TARGET = re.compile(
    r"\blong[- ]term\b|\bmulti[- ]year\b|\bover\s+the\s+next\s+\d+\s+years?\b|"
    r"\boutlook\s+by\s+20\d{2}\b|\bby\s+20\d{2}\b.{0,80}\b(?:target|goal|objective|outlook)\b",
    re.I | re.S,
)
_SUBCOMPONENT_REVENUE = re.compile(
    r"\brun[- ]rate\b|\bannual\s+recurring\s+revenue\b|\bremaining\s+performance\s+obligations?\b|"
    r"\b(?:deferred|collaboration|milestone|inorganic|other)\s+revenue\b|"
    r"\brevenue\b.{0,100}\b(?:deferred|collaboration|milestone|inorganic)\b|"
    r"\b(?:recognize|recognized|recognition)\b.{0,120}\b(?:RPO|revenue)\b|"
    r"\bproportionate\s+recognition\b",
    re.I | re.S,
)
_PORTFOLIO_EFFECT = re.compile(
    r"\b(?:divestitures?|business\s+exits?|portfolio\s+pruning|pruning|non[- ]strategic\s+revenue|"
    r"sale\s+of\s+(?:the\s+)?[A-Za-z0-9&' -]{2,60}\s+business)\b|"
    r"\b(?:reduction|impact|headwind)\b.{0,120}\b(?:sale|divestiture|pruning|business\s+exit)\b",
    re.I | re.S,
)
_TRANSACTION_EFFECT = re.compile(
    r"\b(?:annual|run[- ]rate)?\s*(?:EBITDA\s+)?synerg(?:y|ies)\b|"
    r"\bEPS\s+(?:accretion|dilution|headwind|tailwind)\b|"
    r"\b(?:accretive|dilutive)\s+to\s+(?:adjusted\s+)?EPS\b|"
    r"\b(?:transaction|acquisition)\b.{0,100}\b(?:accretion|dilution|synerg(?:y|ies))\b",
    re.I | re.S,
)
_NAMED_OWNER_COLON = re.compile(r"(?:^|[.;•\n\r])\s*(?P<label>[A-Z][A-Za-z0-9&'(). /-]{2,70})\s*:\s*$")
_OWNER_RESERVED = re.compile(
    r"^(?:financial\s+)?(?:guidance|outlook|forecast|results?|highlights?)$|"
    r"^(?:full[- ]year|fiscal(?:\s+year)?|annual|quarterly?)\b.*(?:guidance|outlook|forecast|results?)$|"
    r"^(?:the\s+)?(?:company|consolidated|total)$",
    re.I,
)
_LOSS_OWNER = re.compile(
    r"\b(?:adjusted\s+|non[- ]GAAP\s+)?(?:EBITDA|free\s+cash\s+flow|FCF)\s+"
    r"(?:guidance\s+)?(?:is\s+)?(?:an?\s+)?loss\b|"
    r"\b(?:EBITDA|free\s+cash\s+flow|FCF)\b.{0,55}\bloss\b",
    re.I | re.S,
)
_BREAKEVEN_LOSS = re.compile(r"\bbreakeven\b.{0,60}\bloss\b|\bloss\b.{0,60}\bbreakeven\b", re.I | re.S)
_RESPECTIVELY = re.compile(r"\brespectively\b", re.I)
_QUARTER = re.compile(
    r"\bQ(?P<q>[1-4])\s*(?:FY)?\s*'?(?P<year>20\d{2})\b|"
    r"\b(?P<word>first|second|third|fourth)\s+(?:fiscal\s+)?quarter"
    r"(?:\s+(?:of\s+)?(?:fiscal(?:\s+year)?\s*)?(?P<year2>20\d{2}))",
    re.I,
)
_FULL_YEAR = re.compile(
    r"\b(?:FY|fiscal(?:\s+year)?|full[- ]year)\s*'?(?P<year>20\d{2})\b|"
    r"\b(?P<year2>20\d{2})\s+(?:full[- ]year|annual)\b|"
    r"\b(?:for\s+(?:the\s+)?year\s+ending|year\s+ending)\b.{0,35}\b(?P<year3>20\d{2})\b|"
    r"\b(?P<year4>20\d{2})\s+(?:guidance|outlook|forecast)\b",
    re.I,
)
_QWORD = {"first": "1", "second": "2", "third": "3", "fourth": "4"}
_METRIC_TOKEN = re.compile(
    r"\b(?:revenue|revenues|net\s+sales|EPS|earnings\s+per\s+share|EBITDA|free\s+cash\s+flow|FCF|"
    r"gross\s+margin|operating\s+margin)\b",
    re.I,
)
_MONEY = re.compile(r"\$?\s*(?P<num>\d+(?:\.\d+)?)\s*(?P<scale>billion|million|thousand|bn|mm|m|b|k)?\b", re.I)
_RANGE_CONNECTOR = re.compile(r"\s*(?:to|through|[-–—])\s*", re.I)
_TABLE_CUE = re.compile(
    r"\b(?:low\s+high|date\s+issued|guidance\s+low\s+high|net\s+revenue\s+adjusted\s+EBITDA|"
    r"GAAP\s+.*non[- ]GAAP)\b",
    re.I | re.S,
)
_PRODUCT_NET_SALES = re.compile(r"\b[A-Z][A-Z0-9-]{3,}(?:\s*\([^)]{1,50}\))?\s+Net\s+Sales(?:\s+Guidance)?\b|\([a-z][a-z -]{2,40}\)\s+(?:20\d{2}\s+)?Net\s+Sales\b")


def _evidence(fact: TypedGuidanceFact):
    return fact.provenance[0].evidence


def _value_window(fact: TypedGuidanceFact, before: int = 220, after: int = 180) -> str:
    evidence = _evidence(fact)
    text = evidence.full_text or ""
    start = evidence.value_start
    end = evidence.value_end
    if start is None:
        start = evidence.metric_start or 0
    if end is None:
        end = start
    return text[max(0, start - before):min(len(text), end + after)]


def _binding_sentence(fact: TypedGuidanceFact) -> str:
    evidence = _evidence(fact)
    text = evidence.full_text or ""
    starts = [x for x in (evidence.metric_start, evidence.value_start) if x is not None]
    ends = [x for x in (evidence.metric_end, evidence.value_end) if x is not None]
    if not starts:
        return text
    left_anchor = min(starts)
    right_anchor = max(ends) if ends else left_anchor
    boundaries = list(_SENTENCE_BOUNDARY.finditer(text))
    left = max((m.end() for m in boundaries if m.end() <= left_anchor), default=0)
    right = min((m.start() for m in boundaries if m.start() >= right_anchor), default=len(text))
    return text[left:right].strip()


def _named_owner_label(fact: TypedGuidanceFact) -> str | None:
    evidence = _evidence(fact)
    text = evidence.full_text or ""
    if evidence.metric_start is None:
        return None
    prefix = text[max(0, evidence.metric_start - 100):evidence.metric_start]
    match = _NAMED_OWNER_COLON.search(prefix)
    if match is not None:
        label = re.sub(r"\s+", " ", match.group("label")).strip()
        if not _OWNER_RESERVED.search(label) and not re.search(r"\b(?:guidance|outlook|forecast|results?|company|consolidated)\b", label, re.I):
            return label
    tail = re.sub(r"\s+", " ", prefix).strip()
    match = re.search(r"(?:^|[.;•|])\s*(?P<label>[A-Z][A-Za-z0-9&'()./-]{2,35})$", tail)
    if match is None:
        match = re.search(r"\b(?P<label>[A-Z][A-Za-z0-9&'()./-]{2,35})$", tail)
    if match is None:
        return None
    label = match.group("label").strip()
    if _OWNER_RESERVED.search(label) or re.search(r"\b(?:total|company|consolidated|adjusted|(?:non[- ])?GAAP|full[- ]year|fiscal)\b", label, re.I):
        return None
    return label


def _explicit_period_mentions(text: str, offset: int = 0) -> list[tuple[str, int, int]]:
    periods: list[tuple[str, int, int]] = []
    quarter_spans: list[tuple[int, int, str]] = []
    for match in _QUARTER.finditer(text):
        q = match.group("q") or _QWORD.get((match.group("word") or "").lower())
        year = match.group("year") or match.group("year2")
        if q and year:
            periods.append((f"Q{q}FY{year}", offset + match.start(), offset + match.end()))
            quarter_spans.append((match.start(), match.end(), year))
    for match in _FULL_YEAR.finditer(text):
        year = match.group("year") or match.group("year2") or match.group("year3") or match.group("year4")
        if not year:
            continue
        # A permissive annual token such as "2026 Guidance" can be a substring
        # of an explicit quarter heading (for example "Third Quarter 2026 Guidance").
        # In that case the quarter is the semantic owner; emitting FY2026 as an
        # overlapping owner creates a false period conflict downstream.
        overlaps_same_year_quarter = any(
            q_year == year and q_start < match.end() and match.start() < q_end
            for q_start, q_end, q_year in quarter_spans
        )
        if overlaps_same_year_quarter:
            continue
        periods.append((f"FY{year}", offset + match.start(), offset + match.end()))
    return periods


def _is_comparator_context(text: str, start: int) -> bool:
    before = text[max(0, start - 55):start]
    return bool(re.search(r"\b(?:compared\s+(?:with|to)|versus|vs\.?|prior[- ]year|year[- ]ago|from\s+the\s+same\s+period)\b", before, re.I))


def _owned_period(fact: TypedGuidanceFact) -> str | None:
    evidence = _evidence(fact)
    text = evidence.full_text or ""
    pivot = evidence.value_start if evidence.value_start is not None else evidence.metric_start
    if pivot is None:
        return None
    lo = max(0, pivot - 220)
    hi = min(len(text), (evidence.value_end or pivot) + 100)
    mentions = _explicit_period_mentions(text[lo:hi], offset=lo)
    if not mentions:
        return None
    preceding: list[tuple[int, str]] = []
    following: list[tuple[int, str]] = []
    for period, start, end in mentions:
        if _is_comparator_context(text, start):
            continue
        if end <= pivot:
            preceding.append((pivot - end, period))
        else:
            following.append((start - pivot, period))
    if preceding:
        preceding.sort(key=lambda item: item[0])
        return preceding[0][1]
    if following:
        following.sort(key=lambda item: item[0])
        return following[0][1]
    if mentions and all(_is_comparator_context(text, start) for _, start, _ in mentions):
        return "UNRESOLVED_COMPARATOR"
    return None


def _local_period_conflict(fact: TypedGuidanceFact) -> bool:
    owner = _owned_period(fact)
    return owner is not None and owner != fact.fiscal_period


def _long_term_owner(fact: TypedGuidanceFact) -> bool:
    evidence = _evidence(fact)
    text = evidence.full_text or ""
    pivot = evidence.value_start if evidence.value_start is not None else evidence.metric_start
    if pivot is None:
        return False
    end = evidence.value_end if evidence.value_end is not None else pivot
    return bool(_LONG_TERM_TARGET.search(text[max(0, pivot - 100):min(len(text), end + 100)]))


def _historical_actual(fact: TypedGuidanceFact) -> bool:
    evidence = _evidence(fact)
    text = evidence.full_text or ""
    if evidence.value_start is None:
        return False
    before = text[max(0, evidence.value_start - 180):evidence.value_start]
    if re.search(r"\bexceeded\b.{0,40}\bguidance\b", before, re.I):
        return True
    after = text[evidence.value_end or evidence.value_start:]
    if re.search(r"\b(?:above|exceed(?:ed|ing)?)\s+(?:the\s+)?(?:previously\s+reported\s+|prior\s+)?guidance\b", after, re.I):
        return True
    # A quarter-result bullet cannot borrow guidance from an adjacent bullet.
    bullet_before = re.split(r"[•·●]", before)[-1]
    if re.search(r"\bQ[1-4]\s+20\d{2}\b", bullet_before, re.I) and not _FORWARD_CUE.search(bullet_before):
        return True
    matches = list(_STRONG_ACTUAL_CUE.finditer(before))
    if matches:
        cue = matches[-1]
        if not _FORWARD_CUE.search(before[cue.end():]):
            return True
    results = list(_RESULT_CONTEXT.finditer(before))
    if results:
        cue = results[-1]
        if not _FORWARD_CUE.search(before[cue.end():]):
            return True
    return False


def _from_to_role(fact: TypedGuidanceFact) -> GuidanceFactRole | None:
    evidence = _evidence(fact)
    text = evidence.full_text or ""
    if evidence.value_start is None:
        return None
    before = text[max(0, evidence.value_start - 75):evidence.value_start]
    if re.search(r"\bfrom(?:\s+(?:at\s+least|approximately|about))?\s*$", before, re.I):
        return GuidanceFactRole.QUOTED_PRIOR
    if re.search(r"\bto(?:\s+(?:at\s+least|approximately|about))?\s*$", before, re.I):
        return GuidanceFactRole.CURRENT
    return None


def _role_owner(fact: TypedGuidanceFact) -> tuple[GuidanceFactRole, str | None]:
    positional = _from_to_role(fact)
    if positional is not None:
        return positional, None
    evidence = _evidence(fact)
    text = evidence.full_text or ""
    if evidence.value_start is None:
        if re.search(r"\b(?:prior|previous|earlier)\s+(?:decision|action)\b", text, re.I):
            return GuidanceFactRole.QUOTED_PRIOR, None
        return fact.role, None
    metric_start = evidence.metric_start or 0
    left = max(0, evidence.value_start - 170)
    # A prior marker for a preceding metric or sentence cannot own this value.
    boundaries = list(_SENTENCE_BOUNDARY.finditer(text[:metric_start]))
    if boundaries:
        left = max(left, boundaries[-1].end())
    previous_metrics = list(_METRIC_TOKEN.finditer(text[:metric_start]))
    if previous_metrics:
        between = text[previous_metrics[-1].end():metric_start]
        # Only carry shared prior headings across a list when no previous value intervenes.
        if re.search(r"\d", between):
            left = max(left, metric_start - len(re.search(r"[A-Za-z -]*$", between).group(0)))
    before = text[left:evidence.value_start]
    if re.search(r"\b(?:confirm|re[- ]?affirm|reiterate|maintain)(?:s|ed|ing)?\b.{0,30}\b(?:prior|previous)\b", before, re.I):
        return GuidanceFactRole.CURRENT, None
    prior = list(_PRIOR_CUE.finditer(before))
    current = list(_CURRENT_CUE.finditer(before))
    if prior and (not current or prior[-1].start() > current[-1].start()):
        return GuidanceFactRole.QUOTED_PRIOR, None
    if fact.role is GuidanceFactRole.QUOTED_PRIOR:
        # An explicitly paired old value still needs local ownership; don't guess.
        if prior or left > max(0, evidence.value_start - 170):
            return GuidanceFactRole.CURRENT, None
        return fact.role, "role: quoted-prior fact lacks local prior-guidance ownership"
    return fact.role, None


def _scale_multiplier(token: str | None) -> float:
    if not token:
        return 1.0
    token = token.lower()
    if token in {"billion", "bn", "b"}:
        return 1e9
    if token in {"million", "mm", "m"}:
        return 1e6
    if token in {"thousand", "k"}:
        return 1e3
    return 1.0


def _unit_multiplier(unit: GuidanceUnit) -> float:
    if unit is GuidanceUnit.USD_BILLION:
        return 1e9
    if unit is GuidanceUnit.USD_MILLION:
        return 1e6
    if unit is GuidanceUnit.USD_THOUSAND:
        return 1e3
    return 1.0


def _parse_range_at_selected_value(fact: TypedGuidanceFact) -> tuple[float, float] | None:
    evidence = _evidence(fact)
    text = evidence.full_text or ""
    if evidence.value_start is None:
        return None
    if fact.unit is GuidanceUnit.PERCENT:
        for match in _PERCENT_RANGE.finditer(text):
            if match.start() <= evidence.value_start < match.end() or (evidence.value_end is not None and evidence.value_start <= match.start() < evidence.value_end):
                return float(match.group("lo")), float(match.group("hi"))
    fragment = text[evidence.value_start:min(len(text), evidence.value_start + 110)]
    first = _MONEY.match(fragment)
    if first is None:
        return None
    rest = fragment[first.end():]
    connector = _RANGE_CONNECTOR.match(rest)
    if connector is None:
        return None
    second = _MONEY.match(rest[connector.end():])
    if second is None:
        return None
    n1, n2 = float(first.group("num")), float(second.group("num"))
    s1, s2 = first.group("scale"), second.group("scale")
    if s1 is None and s2 is not None:
        s1 = s2
    if s2 is None and s1 is not None:
        s2 = s1
    unit_scale = _unit_multiplier(fact.unit)
    scale1 = _scale_multiplier(s1) if s1 is not None else unit_scale
    scale2 = _scale_multiplier(s2) if s2 is not None else unit_scale
    return (n1 * scale1) / unit_scale, (n2 * scale2) / unit_scale


_PAREN_NEGATIVE_RANGE = re.compile(
    r"\$\s*\(\s*(?P<n1>\d+(?:\.\d+)?)\s*\)\s*(?P<s1>billion|million|thousand|bn|mm|m|b|k)?\s*"
    r"(?:to|through|[-–—])\s*\$?\s*(?P<n2>\d+(?:\.\d+)?)\s*(?P<s2>billion|million|thousand|bn|mm|m|b|k)?\b",
    re.I,
)
_FOLLOWING_GUIDANCE_HEADING = re.compile(r"\b(?:F|FY)?\s*20\d{2}\s+(?:GUIDANCE|OUTLOOK)\b|\bOutlook\s+For\b|\bReconciliation\s+of\b.{0,100}\bGuidance\b", re.I)


def _parenthesized_negative_interval(fact: TypedGuidanceFact) -> tuple[float, float] | None:
    if fact.metric not in {GuidanceMetric.EBITDA, GuidanceMetric.FCF}:
        return None
    local = _value_window(fact, 170, 100)
    match = _PAREN_NEGATIVE_RANGE.search(local)
    if match is None:
        return None
    s1 = match.group("s1") or match.group("s2")
    s2 = match.group("s2") or match.group("s1")
    unit_scale = _unit_multiplier(fact.unit)
    first = -(float(match.group("n1")) * _scale_multiplier(s1)) / unit_scale
    second = (float(match.group("n2")) * _scale_multiplier(s2)) / unit_scale
    return min(first, second), max(first, second)


def _period_year(fact: TypedGuidanceFact) -> int | None:
    match = re.search(r"FY(20\d{2})$", fact.fiscal_period or "", re.I)
    return int(match.group(1)) if match else None


def _post_period_preliminary_result(fact: TypedGuidanceFact, document: SourceDocument) -> bool:
    if fact.period_kind not in {GuidancePeriodKind.FULL_YEAR, GuidancePeriodKind.QUARTER}:
        return False
    year = _period_year(fact)
    source_ts = document.source_timestamp or document.fetched_at
    if year is None or source_ts is None or source_ts.year <= year:
        return False
    sentence = _binding_sentence(fact)
    if re.search(r"\b(?:guidance|outlook|forecast)\b", sentence, re.I):
        return False
    return bool(re.search(r"\b(?:expects?|expected|anticipates?|anticipated)\b", sentence, re.I))


def _table_actual_before_guidance_heading(fact: TypedGuidanceFact) -> bool:
    evidence = _evidence(fact)
    text = evidence.full_text or ""
    if evidence.value_end is None:
        return False
    after = text[evidence.value_end:min(len(text), evidence.value_end + 120)]
    heading = _FOLLOWING_GUIDANCE_HEADING.search(after)
    if heading is None:
        return False
    left = evidence.metric_start if evidence.metric_start is not None else max(0, evidence.value_end - 100)
    boundary = evidence.value_end + heading.start()
    fragment = text[left:boundary]
    # A later quarter heading does not turn an earlier annual-guidance range
    # into actuals. Require independent table cells, not the two endpoints
    # of one explicitly bound range.
    if _parse_range_at_selected_value(fact) is not None:
        return False
    cells = len(list(_MONEY.finditer(fragment)))
    period_after_value = evidence.period_start is not None and evidence.period_start >= evidence.value_end
    return (cells >= 2 or (cells >= 1 and period_after_value)) and not _FORWARD_CUE.search(fragment)


def _actual_growth_point(fact: TypedGuidanceFact) -> bool:
    if fact.low is None or fact.high is None or fact.low != fact.high:
        return False
    sentence = _binding_sentence(fact)
    if _FORWARD_CUE.search(sentence):
        return False
    evidence = _evidence(fact)
    text = evidence.full_text or ""
    end = evidence.value_end if evidence.value_end is not None else 0
    tail = text[end:min(len(text), end + 90)]
    metric_of = re.search(
        r"\b(?:revenue|revenues|net\s+sales|EBITDA|free\s+cash\s+flow|FCF)\b.{0,30}\b(?:of|was|were)\b",
        sentence,
        re.I | re.S,
    )
    growth_suffix = re.search(r"(?:,\s*[+-](?:\s*\d|\s*$)|\b(?:grew|growth|increased|decreased|up|down)\b)", tail, re.I)
    return bool(metric_of and growth_suffix)


def _normalize_loss_sign(fact: TypedGuidanceFact) -> tuple[float | None, float | None, str | None]:
    if fact.metric not in {GuidanceMetric.EBITDA, GuidanceMetric.FCF}:
        return fact.low, fact.high, None
    parenthesized = _parenthesized_negative_interval(fact)
    if parenthesized is not None:
        return parenthesized[0], parenthesized[1], None
    local = _value_window(fact, 130, 100)
    if not _LOSS_OWNER.search(local):
        return fact.low, fact.high, None
    parsed = _parse_range_at_selected_value(fact)
    if parsed is not None:
        p1, p2 = parsed
        if _BREAKEVEN_LOSS.search(local):
            return -max(abs(p1), abs(p2)), 0.0, None
        return -max(abs(p1), abs(p2)), -min(abs(p1), abs(p2)), None
    if fact.low is None or fact.high is None:
        return fact.low, fact.high, "value: explicit loss evidence lacks a complete numeric interval"
    if fact.low < 0 or fact.high < 0:
        return fact.low, fact.high, None
    magnitude_low = min(abs(fact.low), abs(fact.high))
    magnitude_high = max(abs(fact.low), abs(fact.high))
    if _BREAKEVEN_LOSS.search(local) or min(fact.low, fact.high) == 0:
        return -magnitude_high, 0.0, None
    return -magnitude_high, -magnitude_low, None


def _range_endpoint_issue(fact: TypedGuidanceFact) -> str | None:
    parsed = _parse_range_at_selected_value(fact)
    if parsed is None or fact.low is None or fact.high is None:
        return None
    p_low, p_high = sorted(parsed)
    f_low, f_high = sorted((fact.low, fact.high))
    scale = max(abs(p_low), abs(p_high), 1.0)
    if abs(p_low - f_low) > scale * 1e-6 or abs(p_high - f_high) > scale * 1e-6:
        if fact.metric in {GuidanceMetric.EBITDA, GuidanceMetric.FCF} and _LOSS_OWNER.search(_value_window(fact, 130, 100)):
            return None
        return "value: selected numeric range endpoints do not match the locally bound textual range"
    return None


def _is_total_metric_label(fact: TypedGuidanceFact) -> bool:
    label = (_evidence(fact).metric_text or "").strip()
    return bool(re.search(r"\b(?:total|consolidated|company[- ]wide)\b", label, re.I))


def _flattened_coordinate_issue(fact: TypedGuidanceFact) -> bool:
    sentence = _binding_sentence(fact)
    local = _value_window(fact, 180, 140)
    metrics = list(_METRIC_TOKEN.finditer(sentence))
    if _TABLE_CUE.search(local) and len(metrics) >= 2:
        return True
    money = list(re.finditer(r"\$\s*\d", sentence))
    if len({m.group(0).lower() for m in metrics}) >= 2 and len(money) >= 3:
        evidence = _evidence(fact)
        metric_text = re.escape((evidence.metric_text or "").strip())
        value_text = re.escape((evidence.value_text or "").strip())
        if metric_text and value_text and not re.search(
            rf"{metric_text}.{{0,55}}(?:is|of|between|range|expected|guidance|:)\s*.{{0,25}}{value_text}",
            sentence,
            re.I | re.S,
        ):
            return True
    return False


def _basis_update(fact: TypedGuidanceFact) -> str | None:
    evidence = _evidence(fact)
    text = evidence.full_text or ""
    if evidence.metric_start is None:
        return None
    if fact.metric is GuidanceMetric.REVENUE:
        return "UNSPECIFIED"
    local = text[max(0, evidence.metric_start - 30):(evidence.metric_end or evidence.metric_start)]
    if re.search(r"\b(?:adjusted|non[- ]GAAP)\b", local, re.I):
        return "ADJUSTED"
    if re.search(r"\bGAAP\b", local, re.I) and not re.search(r"\bnon[- ]GAAP\b", local, re.I):
        return "GAAP"
    return None


@lru_cache(maxsize=8)
def _flat_source(content: str) -> str:
    return re.sub(r"\s+", " ", html_to_text(content)).strip()


_SOURCE_OUTLOOK_PERIOD = re.compile(
    r"\b(?:For\s+(?:the\s+)?|expectations\s+for\s+(?:the\s+)?)(?:"
    r"(?P<annual>(?:full[- ](?:fiscal\s+)?year|fiscal\s+year))\s+(?P<ay>20\d{2})|"
    r"year\s+ending\s+[A-Za-z]+\s+\d{1,2},?\s+(?P<ey>20\d{2})|"
    r"(?P<quarter>first|second|third|fourth)\s+quarter(?:\s+of)?(?:\s+fiscal(?:\s+year)?)?\s+(?P<qy>20\d{2})"
    r")(?P<tail>[^.;]{0,120}?(?:expects?|anticipates?|are\s+as\s+follows)\s*:?)", re.I,
)


def _source_period_issue(fact: TypedGuidanceFact, document: SourceDocument) -> str | None:
    evidence = _evidence(fact)
    needle = re.sub(r"\s+", " ", evidence.full_text or "").strip()
    if not needle or evidence.metric_start is None:
        return None
    source = _flat_source(document.content)
    metric_offset = len(re.sub(r"\s+", " ", (evidence.full_text or "")[:evidence.metric_start]).lstrip())
    owners = set()
    for occurrence in re.finditer(re.escape(needle), source):
        pivot = occurrence.start() + metric_offset
        prefix = source[max(0, pivot - 900):pivot]
        headings = list(_SOURCE_OUTLOOK_PERIOD.finditer(prefix))
        if not headings:
            continue
        heading = headings[-1]
        year = heading.group("ay") or heading.group("ey") or heading.group("qy")
        quarter = heading.group("quarter")
        period = f"Q{_QWORD[quarter.lower()]}FY{year}" if quarter else f"FY{year}"
        following = prefix[heading.end():]
        subheadings = list(re.finditer(r"\b(Annual|Quarterly)\s+Outlook\s*:", following, re.I))
        if subheadings:
            kind = subheadings[-1].group(1).lower()
            if kind == "annual" and re.search(r"\bfull\s+year\b", heading.group("tail"), re.I):
                period = f"FY{year}"
            elif kind == "quarterly" and not quarter:
                continue  # An unqualified quarter cannot inherit an annual period.
        # A new explicit guidance section terminates ownership by the earlier heading.
        if re.search(r"\b(?:20\d{2}\s+(?:Guidance|Outlook)|(?:Guidance|Outlook)\s+For)\b", following, re.I):
            continue
        owners.add(period)
    if len(owners) == 1 and fact.fiscal_period not in owners:
        return f"period: source outlook section owns {next(iter(owners))}, not {fact.fiscal_period}"
    if len(owners) > 1:
        return "period: repeated evidence fragment has ambiguous source section ownership"
    return None


def _source_fragment_issue(fact: TypedGuidanceFact, document: SourceDocument) -> str | None:
    """Validate fragment boundaries against the original document, not a clipped window."""
    evidence = _evidence(fact)
    if evidence.value_end is None or evidence.value_start is None:
        return None
    text = evidence.full_text or ""
    needle = re.sub(r"\s+", " ", text).strip()
    source = _flat_source(document.content)
    starts = [m.start() for m in re.finditer(re.escape(needle), source)] if needle else []
    if not starts:
        return None
    relative_end = len(re.sub(r"\s+", " ", text[:evidence.value_end]).strip())
    for start in starts:
        tail = source[start + relative_end:start + relative_end + 60]
        selected = text[evidence.value_start:evidence.value_end].rstrip()
        if selected and selected[-1].isdigit() and re.match(r"(?:[.,]?\d|\s+\d+(?:\.\d+)?\s+(?:million|billion|thousand)\b)", tail, re.I):
            return "value: selected numeric token is truncated or split in source document"
    return None


def normalize_typed_guidance_fact(fact: TypedGuidanceFact, document: SourceDocument) -> TypedGuidanceFact:
    """Normalize deterministic semantic ownership before strict-v4 admission."""
    updates: dict = {}
    issues: list[str] = []
    metadata = dict(fact.metadata or {})
    metadata["semantic_ownership_version"] = _SEMANTIC_VERSION

    owner = _named_owner_label(fact)
    if owner is not None:
        updates["scope_kind"] = GuidanceScopeKind.SEGMENT
        updates["scope_label"] = owner

    sentence = _binding_sentence(fact)
    local = _value_window(fact)
    if _PRODUCT_NET_SALES.search(local) and not _is_total_metric_label(fact):
        updates["scope_kind"] = GuidanceScopeKind.PRODUCT
        updates["scope_label"] = "product net sales"
    if fact.low is not None and re.search(r"\b(?:midpoint|mid-point)\s+guidance\b", sentence, re.I):
        issues.append("value: quoted guidance midpoint does not establish complete forecast endpoints")
    if re.search(r"\b(?:treatment|clinical)\s+guidance\b", local, re.I) and fact.low is None:
        issues.append("action: clinical guidance does not establish a financial guidance action")
    if _long_term_owner(fact):
        updates["role"] = GuidanceFactRole.LONG_TERM_TARGET
        updates["period_kind"] = GuidancePeriodKind.LONG_TERM
    if (
        _historical_actual(fact)
        or _post_period_preliminary_result(fact, document)
        or _table_actual_before_guidance_heading(fact)
        or _actual_growth_point(fact)
    ):
        updates["role"] = GuidanceFactRole.ACTUAL

    role, role_issue = _role_owner(fact)
    if "role" not in updates and role is not fact.role:
        updates["role"] = role
    effective_role = updates.get("role", fact.role)
    if role_issue:
        issues.append(role_issue)

    low, high, loss_issue = _normalize_loss_sign(fact)
    if (low, high) != (fact.low, fact.high):
        updates["low"] = low
        updates["high"] = high
        metadata["semantic_sign_normalized"] = True
    if loss_issue:
        issues.append(loss_issue)
    period_issue = _source_period_issue(fact, document)
    if period_issue:
        issues.append(period_issue)
    source_issue = _source_fragment_issue(fact, document)
    if source_issue:
        issues.append(source_issue)
    range_issue = _range_endpoint_issue(fact)
    if range_issue:
        issues.append(range_issue)

    if _local_period_conflict(fact):
        owner_period = _owned_period(fact)
        issues.append(f"period: locally owned period {owner_period} conflicts with selected fiscal period {fact.fiscal_period}")

    effective_scope = updates.get("scope_kind", fact.scope_kind)
    if (
        fact.metric is GuidanceMetric.REVENUE
        and effective_scope is not GuidanceScopeKind.PRODUCT
        and not _is_total_metric_label(fact)
        and _SUBCOMPONENT_REVENUE.search(local)
    ):
        updates["scope_kind"] = GuidanceScopeKind.UNKNOWN
        updates["scope_label"] = "revenue subcomponent"
        issues.append("issuer: revenue subcomponent/recognition amount is not consolidated issuer revenue")

    if fact.metric in {GuidanceMetric.REVENUE, GuidanceMetric.EBITDA, GuidanceMetric.EPS} and _PORTFOLIO_EFFECT.search(local):
        updates["value_kind"] = GuidanceValueKind.DELTA
        issues.append("row: portfolio/divestiture/business-exit effect is not consolidated issuer guidance")
    if fact.metric in {GuidanceMetric.EBITDA, GuidanceMetric.EPS, GuidanceMetric.REVENUE} and _TRANSACTION_EFFECT.search(local):
        updates["scope_kind"] = GuidanceScopeKind.UNKNOWN
        updates["scope_label"] = "transaction effect"
        issues.append("issuer: transaction synergy/accretion/dilution effect is not issuer operating guidance")
    if _RESPECTIVELY.search(sentence):
        metric_tokens = {match.group(0).lower() for match in _METRIC_TOKEN.finditer(sentence)}
        if len(metric_tokens) >= 2:
            issues.append("column: multi-metric 'respectively' evidence requires explicit coordinate ownership")
    if _flattened_coordinate_issue(fact):
        issues.append("column: flattened multi-metric/table evidence lacks deterministic row-column ownership")

    basis = _basis_update(fact)
    if basis is not None and basis != fact.accounting_basis:
        updates["accounting_basis"] = basis
        metadata["semantic_basis_normalized"] = True
    if effective_role is GuidanceFactRole.QUOTED_PRIOR and fact.explicit_action is not GuidanceAction.NONE:
        updates["explicit_action"] = GuidanceAction.NONE
        metadata["semantic_prior_action_normalized"] = True

    if issues:
        metadata["semantic_ownership_issues"] = list(dict.fromkeys(issues))
    else:
        metadata.pop("semantic_ownership_issues", None)
    updates["metadata"] = metadata
    return fact.model_copy(update=updates)
