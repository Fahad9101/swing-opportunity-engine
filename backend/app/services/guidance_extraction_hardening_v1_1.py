from __future__ import annotations

import re
from collections import defaultdict
from typing import Iterable

from app.domain.soe_v1_1 import (
    ExtractionMethod,
    GuidanceAction,
    GuidanceExtractionResult,
    GuidanceMetric,
    GuidanceMetricRecord,
    SourceDocument,
)
from app.services import fact_extraction_service as base_extraction


# Phase 1.1E manual-audit repair. These guards are deliberately evidence-layer
# only: they do not alter any SOE threshold, scanner gate, weight, or score.
_ACCOUNTING_CONTEXT = re.compile(
    r"\b(?:FASB|ASU\s+20\d{2}-\d+|accounting\s+pronouncements?|codification|"
    r"accounting\s+standards?|adopt(?:ed|ion)\s+(?:of\s+)?(?:this\s+)?guidance)\b",
    re.I,
)
_GUIDANCE_NOUN = r"(?:guidance|outlook|forecast|financial\s+targets?|targets?)"
_FORWARD_CONTEXT = re.compile(
    rf"\b(?:{_GUIDANCE_NOUN}|expects?|anticipat(?:e|es|ed|ing)|project(?:s|ed|ing)|"
    r"rais(?:e|es|ed|ing)|increas(?:e|es|ed|ing)|reaffirm(?:s|ed|ing)?|reiterat(?:e|es|ed|ing)|"
    r"update(?:s|d|ing)|narrow(?:s|ed|ing))\b",
    re.I,
)
_ACTUAL_CONTEXT = re.compile(
    r"\b(?:reported|actual|results?|generated|achieved|delivered|year[-\s]?to[-\s]?date|compared\s+(?:with|to))\b",
    re.I,
)

_METRIC_ALIASES: dict[GuidanceMetric, tuple[str, ...]] = {
    GuidanceMetric.FCF: ("adjusted free cash flow", "free cash flow", "fcf"),
    GuidanceMetric.OPERATING_MARGIN: ("adjusted operating margin", "operating margin"),
    GuidanceMetric.GROSS_MARGIN: ("adjusted gross margin", "gross margin"),
    GuidanceMetric.EBITDA: ("adjusted ebitda", "ebitda"),
    GuidanceMetric.EPS: (
        "adjusted diluted earnings per share",
        "diluted earnings per common share",
        "adjusted earnings per share",
        "earnings per common share",
        "earnings per share",
        "adjusted diluted eps",
        "adjusted eps",
        "diluted eps",
        "eps",
    ),
    GuidanceMetric.REVENUE: ("total revenue", "consolidated revenue", "net sales", "revenue", "sales"),
}

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

_PERIOD_PATTERNS = [
    (re.compile(r"\bQ([1-4])\s*(?:FY|fiscal(?:\s+year)?)?\s*'?((?:20)?\d{2})\b", re.I), "quarter_numeric"),
    (re.compile(r"\b(first|second|third|fourth)\s+quarter(?:\s+of)?\s+(?:fiscal(?:\s+year)?\s*)?(20\d{2})\b", re.I), "quarter_word"),
    (re.compile(r"\b(?:FY|fiscal\s+year|full[-\s]?year)\s*(20\d{2})\b", re.I), "full_year"),
    (re.compile(r"\b(20\d{2})\s*(?:fiscal\s+year|full[-\s]?year)\b", re.I), "full_year"),
    (re.compile(r"\byear\s+ending\s+[A-Za-z]+\s+\d{1,2},?\s*(20\d{2})\b", re.I), "full_year"),
]
_QUARTER_WORD = {"first": 1, "second": 2, "third": 3, "fourth": 4}


def _normalize_year(token: str) -> int:
    year = int(token)
    return year + 2000 if year < 100 else year


def strict_guidance_action(text: str) -> GuidanceAction:
    """Recognize only verbs that syntactically act on guidance/outlook itself."""
    if not text or _ACCOUNTING_CONTEXT.search(text):
        return GuidanceAction.NONE

    direct_specs: list[tuple[GuidanceAction, str]] = [
        (GuidanceAction.WITHDRAW, r"(?:withdraw(?:s|n|ing)?|suspend(?:s|ed|ing)?)"),
        (GuidanceAction.LOWER, r"(?:lower(?:s|ed|ing)?|reduc(?:e|es|ed|ing)|cut(?:s|ting)?)"),
        (GuidanceAction.RAISE, r"(?:rais(?:e|es|ed|ing)|increas(?:e|es|ed|ing)|boost(?:s|ed|ing)?)"),
        (GuidanceAction.REAFFIRM, r"(?:reaffirm(?:s|ed|ing)?|reiterat(?:e|es|ed|ing)|maintain(?:s|ed|ing)?)"),
        (GuidanceAction.INITIATE, r"(?:initiat(?:e|es|ed|ing)|provid(?:e|es|ed|ing)|issu(?:e|es|ed|ing))"),
    ]
    # Active voice: "raised our full-year guidance". The bounded token bridge
    # prevents unrelated phrases such as "lower volume growth expectations ... guidance".
    bridge = r"(?:\s+(?:its|our|the|company's|management's|updated|revised|fiscal|full[-\s]?year|FY\s*20\d{2}|20\d{2}|financial|quantitative)){0,7}\s+"
    passive_bridge = r"(?:\s+(?:has|have|had|was|were|is|are|been|being|now|previously|further)){0,5}\s+"
    for action, verb in direct_specs:
        if re.search(rf"\b{verb}\b{bridge}\b{_GUIDANCE_NOUN}\b", text, re.I):
            return action
        if re.search(rf"\b{_GUIDANCE_NOUN}\b{passive_bridge}\b{verb}\b", text, re.I):
            return action

    # Explicit forward metric statements initiate a guidance fact without
    # pretending that ordinary uses of "lower" or "suspended" are actions.
    if re.search(
        r"\b(?:the\s+company|company|management|we)\s+(?:now\s+)?expects?\b",
        text,
        re.I,
    ) or re.search(
        r"\bexpects?\s+(?:net\s+sales|total\s+revenue|revenue|adjusted\s+ebitda|ebitda|"
        r"free\s+cash\s+flow|adjusted\s+eps|diluted\s+eps|operating\s+margin|gross\s+margin)\b",
        text,
        re.I,
    ):
        return GuidanceAction.INITIATE
    return GuidanceAction.NONE


def _period_mentions(text: str) -> list[tuple[str, int, int]]:
    found: list[tuple[str, int, int]] = []
    for pattern, kind in _PERIOD_PATTERNS:
        for match in pattern.finditer(text):
            if kind == "quarter_numeric":
                label = f"Q{match.group(1)}FY{_normalize_year(match.group(2))}"
            elif kind == "quarter_word":
                label = f"Q{_QUARTER_WORD[match.group(1).lower()]}FY{int(match.group(2))}"
            else:
                label = f"FY{int(match.group(1))}"
            found.append((label, match.start(), match.end()))
    # Prefer a quarter mention over an embedded FY token occupying the same span.
    result: list[tuple[str, int, int]] = []
    for item in sorted(found, key=lambda row: (row[1], -(row[2] - row[1]))):
        if any(item[1] >= old[1] and item[2] <= old[2] and old[0].startswith("Q") for old in result):
            continue
        result.append(item)
    return result


def infer_fiscal_period(text: str, *, anchor: int) -> str | None:
    mentions = _period_mentions(text)
    if not mentions:
        return None

    def distance(item: tuple[str, int, int]) -> tuple[int, int, int]:
        _, start, end = item
        if start <= anchor <= end:
            d = 0
        else:
            d = min(abs(start - anchor), abs(end - anchor))
        # When distances are similar, prefer the following period because many
        # earnings releases use "FCF ... in fiscal year 2027" after the metric.
        following_penalty = 0 if start >= anchor else 1
        return d, following_penalty, start

    label, start, end = min(mentions, key=distance)
    if min(abs(start - anchor), abs(end - anchor)) > 260:
        return None
    return label


def _metric_occurrence(text: str, metric: GuidanceMetric) -> tuple[int, int] | None:
    candidates: list[tuple[int, int]] = []
    for alias in sorted(_METRIC_ALIASES[metric], key=len, reverse=True):
        for match in re.finditer(rf"\b{re.escape(alias)}\b", text, re.I):
            candidates.append((match.start(), match.end()))
    if not candidates:
        return None
    # Prefer a metric occurrence near explicit forward/guidance wording.
    def quality(span: tuple[int, int]) -> tuple[int, int]:
        start, end = span
        window = text[max(0, start - 100) : min(len(text), end + 180)]
        forward = 0 if _FORWARD_CONTEXT.search(window) else 1
        return forward, start
    return min(candidates, key=quality)


def _amount(token: str, scale: str | None) -> float:
    value = float(token.replace(",", ""))
    if scale:
        value *= _SCALE.get(scale.lower().rstrip("."), 1.0)
    return value


def _range_after_metric(text: str, metric: GuidanceMetric, *, metric_end: int) -> tuple[float, float, str] | None:
    tail = text[metric_end : min(len(text), metric_end + 230)]
    # Stop before an explicit historical/prior comparator. This is critical for
    # lines like "FCF $1.5-$1.6B; relative to previous $1.8-$1.9B".
    split = re.split(r"\b(?:prior|previous|formerly|compared\s+(?:with|to))\b", tail, maxsplit=1, flags=re.I)
    tail = split[0]

    if metric in {GuidanceMetric.GROSS_MARGIN, GuidanceMetric.OPERATING_MARGIN}:
        m = re.search(r"(?P<low>\d{1,3}(?:\.\d+)?)\s*%\s*(?:to|through|and|-|–|—)\s*(?P<high>\d{1,3}(?:\.\d+)?)\s*%", tail, re.I)
        if m:
            low, high = float(m.group("low")) / 100, float(m.group("high")) / 100
            return (low, high, "fraction") if low <= high else None
        m = re.search(r"(?:approximately|about|around|at\s+least|of|to|is)?\s*(?P<v>\d{1,3}(?:\.\d+)?)\s*%", tail, re.I)
        if m:
            value = float(m.group("v")) / 100
            return value, value, "fraction"
        return None

    if metric is GuidanceMetric.EPS:
        m = re.search(r"\$\s*(?P<low>-?\d+(?:\.\d+)?)\s*(?:to|through|and|-|–|—)\s*\$?\s*(?P<high>-?\d+(?:\.\d+)?)", tail, re.I)
        if m:
            low, high = float(m.group("low")), float(m.group("high"))
            return (low, high, "USD/share") if low <= high else None
        m = re.search(r"\$\s*(?P<v>-?\d+(?:\.\d+)?)", tail, re.I)
        if m:
            value = float(m.group("v"))
            return value, value, "USD/share"
        return None

    range_pattern = re.compile(
        r"(?:between|range\s+of|of|to\s+be\s+(?:in\s+the\s+range\s+of\s+)?)?\s*"
        r"(?P<d1>\$)?\s*(?P<low>\d[\d,]*(?:\.\d+)?)\s*(?P<s1>billion|million|thousand|bn|mm|[bmk])?\s*"
        r"(?:to|through|and|-|–|—)\s*(?P<d2>\$)?\s*(?P<high>\d[\d,]*(?:\.\d+)?)\s*(?P<s2>billion|million|thousand|bn|mm|[bmk])?",
        re.I,
    )
    for m in range_pattern.finditer(tail):
        if not (m.group("d1") or m.group("d2") or m.group("s1") or m.group("s2")):
            continue
        shared = m.group("s2") or m.group("s1")
        low = _amount(m.group("low"), m.group("s1") or shared)
        high = _amount(m.group("high"), m.group("s2") or shared)
        if low <= high:
            return low, high, "USD"

    single = re.search(
        r"(?:approximately|about|around|at\s+least|of|to)?\s*\$\s*(?P<v>\d[\d,]*(?:\.\d+)?)\s*(?P<s>billion|million|thousand|bn|mm|[bmk])?",
        tail,
        re.I,
    )
    if single:
        value = _amount(single.group("v"), single.group("s"))
        return value, value, "USD"
    return None


def _basis(text: str, metric: GuidanceMetric, start: int, end: int) -> str:
    if metric is GuidanceMetric.REVENUE:
        return "UNSPECIFIED"
    window = text[max(0, start - 70) : min(len(text), end + 70)].lower()
    if "adjusted" in window or "non-gaap" in window or "non gaap" in window:
        return "ADJUSTED"
    if re.search(r"(?<!non[- ])\bgaap\b", window):
        return "GAAP"
    return "UNSPECIFIED"


def _forward_evidence(text: str, metric: GuidanceMetric) -> bool:
    if not text or _ACCOUNTING_CONTEXT.search(text):
        return False
    occurrence = _metric_occurrence(text, metric)
    if occurrence is None:
        return False
    start, end = occurrence
    window = text[max(0, start - 140) : min(len(text), end + 230)]
    if not _FORWARD_CONTEXT.search(window):
        return False
    # Historical results can sit near a generic forward-looking disclaimer. If
    # there is actual-result language but no local guidance/expect verb, reject.
    if _ACTUAL_CONTEXT.search(window) and not re.search(
        rf"\b(?:{_GUIDANCE_NOUN}|expects?|anticipat(?:e|es|ed|ing)|rais(?:e|es|ed|ing)|"
        r"increas(?:e|es|ed|ing)|reaffirm(?:s|ed|ing)?|update(?:s|d|ing))\b",
        window,
        re.I,
    ):
        return False
    return True


def _sanitize_record(record: GuidanceMetricRecord) -> GuidanceMetricRecord | None:
    evidence = (record.evidence_span or "").strip()
    if evidence and _ACCOUNTING_CONTEXT.search(evidence):
        return None
    if evidence and not _forward_evidence(evidence, record.metric):
        return None

    action = strict_guidance_action(evidence) if evidence else record.explicit_action
    occurrence = _metric_occurrence(evidence, record.metric) if evidence else None
    period = record.fiscal_period
    numeric = None
    basis = record.accounting_basis
    if occurrence is not None:
        start, end = occurrence
        inferred = infer_fiscal_period(evidence, anchor=start)
        if inferred is not None:
            period = inferred
        numeric = _range_after_metric(evidence, record.metric, metric_end=end)
        basis = _basis(evidence, record.metric, start, end)

    update: dict[str, object] = {
        "explicit_action": action,
        "fiscal_period": period,
        "accounting_basis": basis,
    }
    if numeric is not None:
        low, high, unit = numeric
        update.update({"low": low, "high": high, "midpoint": (low + high) / 2, "unit": unit})
    elif record.midpoint is None and action is GuidanceAction.NONE:
        return None
    return record.model_copy(update=update)


def _direct_records(document: SourceDocument, *, rules_hash: str) -> list[GuidanceMetricRecord]:
    text = base_extraction.html_to_text(document.content or "")
    if not text or _ACCOUNTING_CONTEXT.fullmatch(text.strip()):
        return []
    now = document.fetched_at
    records: list[GuidanceMetricRecord] = []

    # Sliding evidence windows around metric occurrences. This catches dense SEC
    # tables while keeping the metric, range, action and fiscal period local.
    for metric in GuidanceMetric:
        aliases = sorted(_METRIC_ALIASES[metric], key=len, reverse=True)
        spans: list[tuple[int, int]] = []
        for alias in aliases:
            spans.extend((m.start(), m.end()) for m in re.finditer(rf"\b{re.escape(alias)}\b", text, re.I))
        for start, end in sorted(set(spans)):
            window_start = max(0, start - 220)
            window_end = min(len(text), end + 330)
            window = text[window_start:window_end]
            local_start = start - window_start
            local_end = end - window_start
            if _ACCOUNTING_CONTEXT.search(window):
                continue
            if not _forward_evidence(window, metric):
                continue
            period = infer_fiscal_period(window, anchor=local_start)
            if period is None:
                continue
            numeric = _range_after_metric(window, metric, metric_end=local_end)
            action = strict_guidance_action(window)
            if numeric is None:
                continue
            low, high, unit = numeric
            records.append(
                GuidanceMetricRecord(
                    rules_hash=rules_hash,
                    ticker=document.ticker,
                    fiscal_period=period,
                    metric=metric,
                    accounting_basis=_basis(window, metric, local_start, local_end),
                    low=low,
                    high=high,
                    unit=unit,
                    source=document.source,
                    source_url=document.source_url,
                    source_accession=document.accession,
                    source_timestamp=document.source_timestamp,
                    explicit_action=action,
                    verified=True,
                    extraction_method=ExtractionMethod.DETERMINISTIC_TEXT,
                    evidence_span=window[:1000],
                    source_document_hash=document.content_hash,
                    as_of=document.source_timestamp,
                    fetched_at=now,
                    stale=document.stale,
                )
            )
    return records


def _record_quality(record: GuidanceMetricRecord) -> tuple[int, int, int, str]:
    evidence = record.evidence_span or ""
    score = 0
    if record.midpoint is not None:
        score += 3
    if strict_guidance_action(evidence) in {
        GuidanceAction.RAISE,
        GuidanceAction.REAFFIRM,
        GuidanceAction.LOWER,
        GuidanceAction.WITHDRAW,
    }:
        score += 5
    if re.search(r"\b(?:guidance|outlook|forecast)\b", evidence, re.I):
        score += 3
    if re.search(r"\b(?:expects?|anticipat(?:e|es|ed|ing)|project(?:s|ed|ing))\b", evidence, re.I):
        score += 2
    if _ACTUAL_CONTEXT.search(evidence):
        score -= 2
    if _ACCOUNTING_CONTEXT.search(evidence):
        score -= 20
    # Prefer compact local evidence when scores tie; UUID is intentionally not
    # used so same-timestamp selection is deterministic across runs.
    return score, -len(evidence), 1 if record.midpoint is not None else 0, evidence


def dedupe_guidance_records(records: Iterable[GuidanceMetricRecord]) -> list[GuidanceMetricRecord]:
    chosen: dict[tuple[tuple[str, str, str], object], GuidanceMetricRecord] = {}
    for record in records:
        sanitized = _sanitize_record(record)
        if sanitized is None:
            continue
        key = (sanitized.comparison_key, sanitized.source_timestamp)
        existing = chosen.get(key)
        if existing is None or _record_quality(sanitized) > _record_quality(existing):
            chosen[key] = sanitized
    return sorted(
        chosen.values(),
        key=lambda item: (item.source_timestamp, item.metric.value, item.fiscal_period, item.accounting_basis, item.source_url),
    )


def _has_quantitative_guidance(records: Iterable[GuidanceMetricRecord]) -> bool:
    return any(record.midpoint is not None for record in records)


def extract_guidance_facts_hardened(document: SourceDocument, *, rules_hash: str) -> GuidanceExtractionResult:
    """Run the existing extractor, then fail-closed on the 1.1E audit defects.

    The base extractor is preserved; this layer only tightens evidence context,
    rebinds period/range locally, deterministically collapses duplicate keys, and
    supplements high-confidence metric/range statements that dense SEC tables can
    otherwise miss.
    """
    base = base_extraction.extract_guidance_facts(document, rules_hash=rules_hash)
    sanitized = [item for record in base.records if (item := _sanitize_record(record)) is not None]
    direct = _direct_records(document, rules_hash=rules_hash)

    # Direct local extraction wins within a document/key because it binds the
    # metric, range and period from one bounded evidence window.
    by_key: dict[tuple[tuple[str, str, str], object], GuidanceMetricRecord] = {}
    for record in sanitized:
        by_key[(record.comparison_key, record.source_timestamp)] = record
    for record in direct:
        key = (record.comparison_key, record.source_timestamp)
        existing = by_key.get(key)
        if existing is None or _record_quality(record) >= _record_quality(existing):
            by_key[key] = record
    records = list(by_key.values())

    policy = base.policy_evidence
    if policy is not None and _has_quantitative_guidance(records):
        policy = None

    rejected = list(base.rejected_candidates)
    rejected.append({
        "reason": "phase_1_1e_guidance_hardening",
        "base_records": len(base.records),
        "hardened_records": len(records),
        "policy_suppressed_by_quantitative_guidance": base.policy_evidence is not None and policy is None,
    })
    return base.model_copy(update={"records": records, "policy_evidence": policy, "rejected_candidates": rejected})
