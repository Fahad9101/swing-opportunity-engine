from __future__ import annotations

import re
from collections import defaultdict

from app.domain.distress_v1_1 import DistressHardFlag
from app.domain.soe_v1_1 import GuidanceAction, GuidanceExtractionResult, GuidanceMetric, GuidanceMetricRecord, SourceDocument
from app.services import guidance_extraction_hardening_v1_1 as hardened
from app.services.catalyst_primary_evidence_service import ExtractedCatalystCandidate
from app.services.distress_fact_extraction_service import extract_hard_distress_flags as _base_distress_flags
from app.services.fact_extraction_service import html_to_text
from app.services.phase_1_1e_evidence_hygiene_v1_1 import (
    extract_guidance_facts_hygienic as _base_guidance_extract,
    extract_sec_catalyst_candidates_hygienic as _base_catalyst_extract,
    install_binding_patch,
)

# Round-3 hardening is deliberately fail-closed and evidence-only. It must not
# change any SOE threshold, gate, score, weight, penalty, or market-regime rule.

_FORWARD = re.compile(
    r"\b(?:guidance|outlook|forecast|expects?|anticipat(?:e|es|ed|ing)|project(?:s|ed|ing)|"
    r"rais(?:e|es|ed|ing)|increas(?:e|es|ed|ing)|reaffirm(?:s|ed|ing)?|reiterat(?:e|es|ed|ing)|"
    r"maintain(?:s|ed|ing)|update(?:s|d|ing)|narrow(?:s|ed|ing)|lower(?:s|ed|ing)?|"
    r"reduc(?:e|es|ed|ing)|cut(?:s|ting)?|initiat(?:e|es|ed|ing)|provid(?:e|es|ed|ing))\b",
    re.I,
)
_ACTUAL = re.compile(
    r"\b(?:reported|actual|results?|generated|achieved|delivered|was|were|quarter\s+ended|"
    r"three\s+months\s+ended|six\s+months\s+ended|nine\s+months\s+ended|year\s+ended|"
    r"year[-\s]?to[-\s]?date)\b",
    re.I,
)
_LONG_TERM_SCOPE = re.compile(
    r"\b(?:long[-\s]?term\s+(?:target|goal|objective)|2030\s*(?:to|-|–|—)\s*2035|"
    r"2030\s+target|2035\s+target|five\s+to\s+ten\s+years?)\b",
    re.I,
)

_SCALE = {
    "k": 1_000.0,
    "thousand": 1_000.0,
    "m": 1_000_000.0,
    "mm": 1_000_000.0,
    "million": 1_000_000.0,
    "b": 1_000_000_000.0,
    "bn": 1_000_000_000.0,
    "billion": 1_000_000_000.0,
}
_QUARTER_WORD = {"first": 1, "second": 2, "third": 3, "fourth": 4}


def _year(token: str) -> int:
    value = int(token)
    return value + 2000 if value < 100 else value


def _period_mentions(text: str) -> list[tuple[str, int, int, bool]]:
    found: list[tuple[str, int, int, bool]] = []
    quarter_patterns = [
        re.compile(r"\bQ([1-4])\s*(?:FY|fiscal(?:\s+year)?)?\s*'?(\d{2}|20\d{2})\b", re.I),
        re.compile(r"\b([1-4])Q\s*'?(\d{2}|20\d{2})\b", re.I),
        re.compile(r"\b(first|second|third|fourth)\s+quarter(?:\s+of)?\s+(?:fiscal(?:\s+year)?\s*)?(?:FY\s*)?(\d{2}|20\d{2})\b", re.I),
    ]
    for idx, pattern in enumerate(quarter_patterns):
        for match in pattern.finditer(text):
            if idx < 2:
                quarter = int(match.group(1))
            else:
                quarter = _QUARTER_WORD[match.group(1).lower()]
            found.append((f"Q{quarter}FY{_year(match.group(2))}", match.start(), match.end(), True))

    full_patterns = [
        re.compile(r"\b(?:FY|fiscal\s+year|full[-\s]?year)\s*'?((?:20)?\d{2})\b", re.I),
        re.compile(r"\b(20\d{2})\s*(?:fiscal\s+year|full[-\s]?year)\b", re.I),
        re.compile(r"\byear\s+ending\s+[A-Za-z]+\s+\d{1,2},?\s*(20\d{2})\b", re.I),
    ]
    for pattern in full_patterns:
        for match in pattern.finditer(text):
            found.append((f"FY{_year(match.group(1))}", match.start(), match.end(), False))

    # A bare year is accepted as annual scope only when it directly modifies a
    # guidance/outlook phrase, not when it is simply a historical table column.
    for match in re.finditer(r"\b(20\d{2})\s+(?:guidance|outlook|forecast)\b|\b(?:guidance|outlook|forecast)\s+(?:for\s+)?(20\d{2})\b", text, re.I):
        token = match.group(1) or match.group(2)
        found.append((f"FY{int(token)}", match.start(), match.end(), False))

    result: list[tuple[str, int, int, bool]] = []
    for item in sorted(found, key=lambda row: (row[1], -int(row[3]), -(row[2] - row[1]))):
        label, start, end, quarterly = item
        if not quarterly and any(start >= qstart and end <= qend for _, qstart, qend, qtr in result if qtr):
            continue
        result.append(item)
    return result


def _nearest_period(text: str, anchor: int) -> str | None:
    mentions = _period_mentions(text)
    if not mentions:
        return None

    def key(item: tuple[str, int, int, bool]) -> tuple[int, int, int]:
        _, start, end, _ = item
        distance = 0 if start <= anchor <= end else min(abs(start - anchor), abs(end - anchor))
        return distance, 0 if start >= anchor else 1, start

    label, start, end, _ = min(mentions, key=key)
    if min(abs(start - anchor), abs(end - anchor)) > 300:
        return None
    return label


def _metric_occurrences(text: str, metric: GuidanceMetric) -> list[tuple[int, int]]:
    found: list[tuple[int, int]] = []
    for alias in sorted(hardened._METRIC_ALIASES[metric], key=len, reverse=True):
        for match in re.finditer(rf"\b{re.escape(alias)}\b", text, re.I):
            span = (match.start(), match.end())
            if not any(span[0] >= old[0] and span[1] <= old[1] for old in found):
                found.append(span)
    return sorted(found)


def _candidate(record: GuidanceMetricRecord, text: str, start: int, end: int):
    left = max(0, start - 300)
    right = min(len(text), end + 340)
    clause = text[left:right]
    anchor = start - left
    metric_end = end - left
    context = clause[max(0, anchor - 220): min(len(clause), metric_end + 220)]
    if _LONG_TERM_SCOPE.search(context):
        return None
    if not _FORWARD.search(context):
        return None

    # Historical actuals near the metric are admissible only when a true local
    # forward phrase also occurs between/adjacent to the same metric and number.
    actual_local = clause[max(0, anchor - 105): min(len(clause), metric_end + 135)]
    forward_local = clause[max(0, anchor - 125): min(len(clause), metric_end + 170)]
    if _ACTUAL.search(actual_local) and not _FORWARD.search(forward_local):
        return None

    period = _nearest_period(clause, anchor)
    if period is None:
        return None
    numeric = hardened._range_after_metric(clause, record.metric, metric_end=metric_end)
    if numeric is None:
        return None
    low, high, unit = numeric
    if low > high:
        return None
    return {
        "period": period,
        "low": low,
        "high": high,
        "midpoint": (low + high) / 2,
        "unit": unit,
        "context": context,
    }


def tighten_guidance_record_round3(record: GuidanceMetricRecord) -> GuidanceMetricRecord | None:
    if not record.verified:
        return None
    text = (record.evidence_span or "").strip()
    if not text:
        return record
    install_binding_patch()

    occurrences = _metric_occurrences(text, record.metric)
    candidates = [item for start, end in occurrences if (item := _candidate(record, text, start, end)) is not None]

    if record.midpoint is None:
        # Qualitative RAISE/LOWER/REAFFIRM evidence can survive without a number,
        # but it still needs an unambiguous local fiscal period.
        if record.explicit_action not in {GuidanceAction.RAISE, GuidanceAction.LOWER, GuidanceAction.REAFFIRM, GuidanceAction.WITHDRAW}:
            return None
        periods = []
        for start, end in occurrences:
            left = max(0, start - 300)
            period = _nearest_period(text[left:min(len(text), end + 340)], start - left)
            if period:
                periods.append(period)
        if not periods:
            return None
        # Multiple distinct scopes in one qualitative record are ambiguous.
        unique = sorted(set(periods))
        if len(unique) != 1:
            return None
        return record.model_copy(update={"fiscal_period": unique[0]})

    if not candidates:
        return None

    # Explicit directional actions supply a monotonicity constraint. When a
    # current release repeats previous and current guidance in one evidence span,
    # choose the economically current side rather than whichever number happened
    # to be nearest in HTML order.
    if record.explicit_action is GuidanceAction.RAISE:
        chosen = max(candidates, key=lambda item: (item["midpoint"], item["period"]))
    elif record.explicit_action is GuidanceAction.LOWER:
        chosen = min(candidates, key=lambda item: (item["midpoint"], item["period"]))
    else:
        def distance(item):
            if record.midpoint is None:
                return 0.0
            scale = max(abs(record.midpoint), abs(item["midpoint"]), 1.0)
            return abs(item["midpoint"] - record.midpoint) / scale
        chosen = min(candidates, key=lambda item: (distance(item), item["period"]))

    return record.model_copy(update={
        "fiscal_period": chosen["period"],
        "low": chosen["low"],
        "high": chosen["high"],
        "midpoint": chosen["midpoint"],
        "unit": chosen["unit"],
    })


def extract_guidance_facts_round3(document: SourceDocument, *, rules_hash: str) -> GuidanceExtractionResult:
    base = _base_guidance_extract(document, rules_hash=rules_hash)
    records = [item for record in base.records if (item := tighten_guidance_record_round3(record)) is not None]
    policy = base.policy_evidence
    if any(record.midpoint is not None for record in records):
        policy = None
    return base.model_copy(update={"records": records, "policy_evidence": policy})


def _quality(record: GuidanceMetricRecord) -> tuple[int, int, int, str]:
    text = record.evidence_span or ""
    score = 0
    if record.midpoint is not None:
        score += 4
    if record.explicit_action in {GuidanceAction.RAISE, GuidanceAction.LOWER, GuidanceAction.REAFFIRM}:
        score += 5
    if _FORWARD.search(text):
        score += 3
    if _ACTUAL.search(text) and not _FORWARD.search(text):
        score -= 10
    return score, -len(text), 1 if record.midpoint is not None else 0, record.source_url


def dedupe_guidance_records_round3(records: list[GuidanceMetricRecord]) -> list[GuidanceMetricRecord]:
    grouped: dict[tuple[tuple[str, str, str], object], list[GuidanceMetricRecord]] = defaultdict(list)
    for record in records:
        tightened = tighten_guidance_record_round3(record)
        if tightened is not None:
            grouped[(tightened.comparison_key, tightened.source_timestamp)].append(tightened)

    selected: list[GuidanceMetricRecord] = []
    for rows in grouped.values():
        raises = [row for row in rows if row.explicit_action is GuidanceAction.RAISE and row.midpoint is not None]
        lowers = [row for row in rows if row.explicit_action is GuidanceAction.LOWER and row.midpoint is not None]
        if raises and not lowers:
            chosen = max(raises, key=lambda row: (row.midpoint or float("-inf"), _quality(row)))
        elif lowers and not raises:
            chosen = min(lowers, key=lambda row: (row.midpoint if row.midpoint is not None else float("inf"), tuple(-x if isinstance(x, int) else x for x in _quality(row)[:3]), row.source_url))
        else:
            chosen = max(rows, key=_quality)
        selected.append(chosen)
    return sorted(selected, key=lambda item: (item.source_timestamp, item.metric.value, item.fiscal_period, item.accounting_basis, item.source_url))


_SCHEDULING_NOTICE = re.compile(
    r"\b(?:will|plans?\s+to|expects?\s+to|scheduled\s+to|intends?\s+to)\s+"
    r"(?:report|release|announce|publish)\b.{0,180}\b(?:quarterly|quarter|financial|fiscal)\b.{0,120}\bresults\b|"
    r"\bannounces?\s+(?:the\s+)?date\s+of\b.{0,180}\b(?:financial\s+)?results\b",
    re.I | re.S,
)
_COMPLETED_RESULTS = re.compile(
    r"\b(?:today\s+)?(?:reported|announced|released)\b.{0,160}\b(?:quarterly|quarter|financial|fiscal)\b.{0,140}\bresults\b|"
    r"\b(?:quarterly|quarter|financial|fiscal)\b.{0,120}\bresults\b.{0,100}\b(?:revenue|net\s+sales|earnings|net\s+income|EPS)\b",
    re.I | re.S,
)


def extract_sec_catalyst_candidates_round3(document: SourceDocument, *, is_biotech: bool = False) -> list[ExtractedCatalystCandidate]:
    candidates = _base_catalyst_extract(document, is_biotech=is_biotech)
    text = html_to_text(document.content or "")[:16000]
    scheduling_only = bool(_SCHEDULING_NOTICE.search(text)) and not bool(_COMPLETED_RESULTS.search(text))
    if not scheduling_only:
        return candidates
    return [candidate for candidate in candidates if candidate.input.event_type != "quarterly_earnings"]


_HYPOTHETICAL_OR_THIRD_PARTY_DEFAULT = re.compile(
    r"\b(?:regardless\s+of\s+whether(?:\s+or\s+not)?|whether\s+or\s+not|if)\s+(?:we|the\s+company|company)\s+(?:are|is|were|was|be|become)\s+in\s+default\b|"
    r"\b(?:customer|customers|counterparty|counterparties|supplier|suppliers|tenant|tenants)\b.{0,180}\b(?:default|breach|noncompliance)\b",
    re.I | re.S,
)
_DEBT_COVENANT_CONTEXT = re.compile(
    r"\b(?:covenant|credit\s+agreement|credit\s+facility|revolver|loan|debt|notes?|indenture|principal|interest|lender|borrowing)\b",
    re.I,
)


def extract_hard_distress_flags_round3(document: SourceDocument) -> list[dict]:
    items = _base_distress_flags(document)
    filtered: list[dict] = []
    for item in items:
        if item.get("flag") != DistressHardFlag.UNRESOLVED_COVENANT_BREACH.value:
            filtered.append(item)
            continue
        span = str(item.get("evidence_span") or "")
        if _HYPOTHETICAL_OR_THIRD_PARTY_DEFAULT.search(span):
            continue
        if not _DEBT_COVENANT_CONTEXT.search(span):
            continue
        filtered.append(item)
    return filtered
