from __future__ import annotations

import html
import re
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Iterable, NamedTuple

from app.domain.soe_v1_1 import (
    ExtractionMethod,
    GuidanceAction,
    GuidanceExtractionResult,
    GuidanceMetric,
    GuidanceMetricRecord,
    GuidancePolicyEvidence,
    SourceDocument,
)


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data.strip())

    def text(self) -> str:
        return "\n".join(self.parts)


_METRIC_ALIASES: list[tuple[GuidanceMetric, tuple[str, ...]]] = [
    (GuidanceMetric.FCF, ("free cash flow", "fcf")),
    (GuidanceMetric.OPERATING_MARGIN, ("adjusted operating margin", "operating margin")),
    (GuidanceMetric.GROSS_MARGIN, ("adjusted gross margin", "gross margin")),
    (GuidanceMetric.EBITDA, ("adjusted ebitda", "ebitda")),
    (
        GuidanceMetric.EPS,
        (
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
    ),
    (GuidanceMetric.REVENUE, ("consolidated revenue", "net sales", "revenue", "sales")),
]

_GUIDANCE_NOUN = r"(?:guidance|outlook|forecast|financial\s+targets?|targets?)"
_GUIDANCE_HINT = re.compile(
    rf"\b(?:guidance|outlook|forecast|financial\s+targets?|reaffirm(?:s|ed|ing)?|reiterat(?:e|es|ed|ing)|"
    rf"rais(?:e|es|ed|ing)|lower(?:s|ed|ing)?|reduc(?:e|es|ed|ing)|withdraw(?:s|n|ing)?|suspend(?:s|ed|ing)?|"
    rf"expects?|anticipat(?:e|es|ed|ing)|project(?:s|ed|ing)|target(?:s|ed|ing)?)\b",
    re.I,
)

_PERIOD_PATTERNS = [
    re.compile(r"\b(?:FY|fiscal\s+year|full[-\s]?year)\s*(20\d{2})\b", re.I),
    re.compile(r"\b(20\d{2})\s*(?:fiscal\s+year|full[-\s]?year)\b", re.I),
    re.compile(r"\byear\s+ending\s+[A-Za-z]+\s+\d{1,2},?\s*(20\d{2})\b", re.I),
]
_QUARTER_NUMERIC = re.compile(
    r"\bQ([1-4])\s*(?:FY|fiscal(?:\s+year)?)?\s*'?((?:20)?\d{2})\b",
    re.I,
)
_QUARTER_WORD = re.compile(
    r"\b(first|second|third|fourth)\s+quarter(?:\s+of)?\s+(?:fiscal(?:\s+year)?\s*)?(20\d{2})\b",
    re.I,
)
_FISCAL_QUARTER_WORD = re.compile(
    r"\bfiscal(?:\s+year)?\s*(20\d{2})\s+(first|second|third|fourth)\s+quarter\b",
    re.I,
)
_QUARTER_MAP = {"first": 1, "second": 2, "third": 3, "fourth": 4}

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


class _MetricMention(NamedTuple):
    metric: GuidanceMetric
    alias: str
    start: int
    end: int


class _PeriodMention(NamedTuple):
    label: str
    start: int
    end: int
    quarterly: bool


class _NumericCandidate(NamedTuple):
    low: float
    high: float
    unit: str
    start: int
    end: int


def html_to_text(content: str) -> str:
    if "<" not in content or ">" not in content:
        return html.unescape(content)
    parser = _TextExtractor()
    parser.feed(content)
    return html.unescape(parser.text())


def _segments(text: str) -> Iterable[str]:
    """Yield sentence/line segments plus short sliding windows for HTML tables."""
    normalized = text.replace("\xa0", " ")
    raw_lines = [re.sub(r"[ \t]+", " ", line).strip() for line in re.split(r"[\r\n]+", normalized)]
    lines = [line for line in raw_lines if line]
    yielded: set[str] = set()

    for line in lines:
        for part in re.split(r"(?<=[.;])\s+(?=[A-Z0-9])", line):
            cleaned = part.strip()
            if 20 <= len(cleaned) <= 1200 and _GUIDANCE_HINT.search(cleaned) and cleaned not in yielded:
                yielded.add(cleaned)
                yield cleaned

    for index in range(len(lines)):
        parts: list[str] = []
        for offset in range(6):
            pos = index + offset
            if pos >= len(lines):
                break
            parts.append(lines[pos])
            joined = " ".join(parts)
            if len(joined) > 1200:
                break
            if len(joined) >= 20 and _GUIDANCE_HINT.search(joined) and joined not in yielded:
                yielded.add(joined)
                yield joined


def _metric_mentions(segment: str) -> list[_MetricMention]:
    raw: list[_MetricMention] = []
    for metric, aliases in _METRIC_ALIASES:
        for alias in sorted(aliases, key=len, reverse=True):
            for match in re.finditer(rf"\b{re.escape(alias)}\b", segment, re.I):
                raw.append(_MetricMention(metric, alias, match.start(), match.end()))
    raw.sort(key=lambda item: (item.start, -(item.end - item.start)))
    non_overlapping: list[_MetricMention] = []
    for item in raw:
        if any(not (item.end <= chosen.start or item.start >= chosen.end) for chosen in non_overlapping):
            continue
        non_overlapping.append(item)
    non_overlapping.sort(key=lambda item: item.start)

    # SEC prose often spells out a metric and immediately repeats its acronym,
    # e.g. "diluted earnings per common share (EPS)". Treat that as one mention.
    result: list[_MetricMention] = []
    for item in non_overlapping:
        if result and result[-1].metric == item.metric:
            connector = segment[result[-1].end : item.start]
            if len(connector) <= 14 and re.fullmatch(r"[\s()\[\]“”\"'.,:/-]*", connector):
                continue
        result.append(item)
    return result


def _guidance_context(segment: str) -> bool:
    if re.search(rf"\b{_GUIDANCE_NOUN}\b", segment, re.I):
        return True
    return bool(
        re.search(
            r"\b(?:expects?|anticipat(?:e|es|ed|ing)|project(?:s|ed|ing)|estimat(?:e|es|ed|ing))\b",
            segment,
            re.I,
        )
    )


def _action(segment: str) -> GuidanceAction:
    """Return an explicit management guidance action, not ordinary growth language."""
    action_specs: list[tuple[GuidanceAction, str]] = [
        (GuidanceAction.WITHDRAW, r"(?:withdraw(?:s|n|ing)?|suspend(?:s|ed|ing)?)"),
        (GuidanceAction.LOWER, r"(?:lower(?:s|ed|ing)?|reduc(?:e|es|ed|ing)|cut(?:s|ting)?)"),
        (GuidanceAction.RAISE, r"(?:rais(?:e|es|ed|ing)|boost(?:s|ed|ing)?)"),
        (GuidanceAction.REAFFIRM, r"(?:reaffirm(?:s|ed|ing)?|reiterat(?:e|es|ed|ing)|maintain(?:s|ed|ing)?)"),
        (GuidanceAction.INITIATE, r"(?:initiat(?:e|es|ed|ing)|provid(?:e|es|ed|ing)|issu(?:e|es|ed|ing))"),
    ]
    for action, verb in action_specs:
        if re.search(rf"\b{verb}\b.{{0,140}}\b{_GUIDANCE_NOUN}\b", segment, re.I | re.S) or re.search(
            rf"\b{_GUIDANCE_NOUN}\b.{{0,140}}\b{verb}\b", segment, re.I | re.S
        ):
            return action
    if re.search(r"\b(?:we|company|management|[A-Z][A-Za-z&'.-]+)\s+expects?\b", segment, re.I) or re.search(
        r"\bexpects?\s+(?:revenue|net\s+sales|adjusted|gaap|ebitda|free\s+cash\s+flow|operating\s+margin|gross\s+margin)",
        segment,
        re.I,
    ):
        return GuidanceAction.INITIATE
    return GuidanceAction.NONE


def _normalize_year(token: str) -> int:
    year = int(token)
    return year + 2000 if year < 100 else year


def _period_mentions(segment: str) -> list[_PeriodMention]:
    mentions: list[_PeriodMention] = []
    for match in _QUARTER_NUMERIC.finditer(segment):
        year = _normalize_year(match.group(2))
        mentions.append(_PeriodMention(f"Q{match.group(1)}FY{year}", match.start(), match.end(), True))
    for match in _QUARTER_WORD.finditer(segment):
        mentions.append(
            _PeriodMention(
                f"Q{_QUARTER_MAP[match.group(1).lower()]}FY{int(match.group(2))}",
                match.start(),
                match.end(),
                True,
            )
        )
    for match in _FISCAL_QUARTER_WORD.finditer(segment):
        mentions.append(
            _PeriodMention(
                f"Q{_QUARTER_MAP[match.group(2).lower()]}FY{int(match.group(1))}",
                match.start(),
                match.end(),
                True,
            )
        )
    for pattern in _PERIOD_PATTERNS:
        for match in pattern.finditer(segment):
            mentions.append(_PeriodMention(f"FY{int(match.group(1))}", match.start(), match.end(), False))
    result: list[_PeriodMention] = []
    for item in sorted(mentions, key=lambda value: (value.start, not value.quarterly, value.end)):
        if any(item.start >= existing.start and item.end <= existing.end and existing.quarterly for existing in result):
            continue
        result.append(item)
    return result


def _period_for_metric(segment: str, metric_start: int) -> str | None:
    mentions = _period_mentions(segment)
    if not mentions:
        return None
    preceding = [item for item in mentions if item.start <= metric_start and metric_start - item.end <= 320]
    if preceding:
        return max(preceding, key=lambda item: item.end).label
    following = [item for item in mentions if item.start >= metric_start and item.start - metric_start <= 240]
    if following:
        return min(following, key=lambda item: item.start).label
    return None


def _accounting_basis(segment: str, mention: _MetricMention) -> str:
    if mention.metric == GuidanceMetric.REVENUE:
        return "UNSPECIFIED"
    window = segment[max(0, mention.start - 55) : min(len(segment), mention.end + 35)].lower()
    alias = mention.alias.lower()
    if "adjusted" in alias or "non-gaap" in window or "non gaap" in window or "adjusted" in window:
        return "ADJUSTED"
    if re.search(r"(?<!non[- ])\bgaap\b", window):
        return "GAAP"
    return "UNSPECIFIED"


def _amount(token: str, scale_token: str | None) -> float:
    value = float(token.replace(",", ""))
    if scale_token:
        value *= _SCALE.get(scale_token.lower().rstrip("."), 1.0)
    return value


def _distance(candidate: _NumericCandidate, anchor: int) -> int:
    if candidate.start <= anchor <= candidate.end:
        return 0
    return min(abs(candidate.start - anchor), abs(candidate.end - anchor))


def _numeric_range(text: str, metric: GuidanceMetric, *, anchor: int) -> tuple[float, float, str] | None:
    ranges: list[_NumericCandidate] = []
    singles: list[_NumericCandidate] = []
    qualifier = r"(?:approximately|about|around|at\s+least|greater\s+than|more\s+than|of(?:\s+approximately)?|at|to(?:\s+approximately)?|is(?:\s+approximately)?)"

    if metric in {GuidanceMetric.GROSS_MARGIN, GuidanceMetric.OPERATING_MARGIN}:
        for match in re.finditer(
            r"(?P<low>\d{1,3}(?:\.\d+)?)\s*%\s*(?:to|through|-|–|—)\s*(?P<high>\d{1,3}(?:\.\d+)?)\s*%",
            text,
            re.I,
        ):
            ranges.append(
                _NumericCandidate(
                    float(match.group("low")) / 100,
                    float(match.group("high")) / 100,
                    "fraction",
                    match.start(),
                    match.end(),
                )
            )
        for match in re.finditer(rf"{qualifier}\s*(?P<value>\d{{1,3}}(?:\.\d+)?)\s*%", text, re.I):
            value = float(match.group("value")) / 100
            singles.append(_NumericCandidate(value, value, "fraction", match.start(), match.end()))
    elif metric == GuidanceMetric.EPS:
        for match in re.finditer(
            r"\$?\s*(?P<low>-?\d+(?:\.\d+)?)\s*(?:to|through|-|–|—)\s*\$?\s*(?P<high>-?\d+(?:\.\d+)?)(?!\s*%)",
            text,
            re.I,
        ):
            if "%" in match.group(0):
                continue
            ranges.append(
                _NumericCandidate(float(match.group("low")), float(match.group("high")), "USD/share", match.start(), match.end())
            )
        for match in re.finditer(rf"{qualifier}\s*\$\s*(?P<value>-?\d+(?:\.\d+)?)(?!\s*%)", text, re.I):
            value = float(match.group("value"))
            singles.append(_NumericCandidate(value, value, "USD/share", match.start(), match.end()))
    else:
        for match in re.finditer(
            r"(?P<d1>\$)?\s*(?P<low>\d[\d,]*(?:\.\d+)?)\s*(?P<scale1>billion|million|thousand|bn|mm|[bmk])?"
            r"\s*(?:to|through|-|–|—)\s*(?P<d2>\$)?\s*(?P<high>\d[\d,]*(?:\.\d+)?)\s*(?P<scale2>billion|million|thousand|bn|mm|[bmk])?",
            text,
            re.I,
        ):
            if not (match.group("d1") or match.group("d2") or match.group("scale1") or match.group("scale2")):
                continue
            if "%" in match.group(0):
                continue
            scale1 = match.group("scale1")
            scale2 = match.group("scale2")
            shared_scale = scale2 or scale1
            low = _amount(match.group("low"), scale1 or shared_scale)
            high = _amount(match.group("high"), scale2 or shared_scale)
            if low <= high:
                ranges.append(_NumericCandidate(low, high, "USD", match.start(), match.end()))
        for match in re.finditer(
            rf"{qualifier}\s*(?P<d>\$)?\s*(?P<value>\d[\d,]*(?:\.\d+)?)\s*(?P<scale>billion|million|thousand|bn|mm|[bmk])?",
            text,
            re.I,
        ):
            if not (match.group("d") or match.group("scale")):
                continue
            if "%" in match.group(0):
                continue
            value = _amount(match.group("value"), match.group("scale"))
            singles.append(_NumericCandidate(value, value, "USD", match.start(), match.end()))

    pool = ranges if ranges else singles
    if not pool:
        return None
    chosen = min(pool, key=lambda item: (_distance(item, anchor), item.start))
    return chosen.low, chosen.high, chosen.unit


def _metric_clause(segment: str, mentions: list[_MetricMention], index: int) -> tuple[str, int]:
    mention = mentions[index]
    previous_end = mentions[index - 1].end if index > 0 else 0
    next_start = mentions[index + 1].start if index + 1 < len(mentions) else len(segment)
    left = max(previous_end, mention.start - 100)
    right = min(next_start, mention.end + 260) if index + 1 < len(mentions) else min(len(segment), mention.end + 260)
    if right <= mention.end:
        right = min(len(segment), mention.end + 120)
    clause = segment[left:right]
    return clause, mention.start - left


def extract_guidance_facts(document: SourceDocument, *, rules_hash: str) -> GuidanceExtractionResult:
    """Conservative deterministic primary-source text-to-fact extraction.

    The extractor may structure facts, but it never decides whether guidance is
    deteriorated and never assigns an SOE score. Ambiguous facts are rejected.
    """
    text = html_to_text(document.content or "")
    records: list[GuidanceMetricRecord] = []
    rejected: list[dict] = []
    seen: set[tuple] = set()
    now = document.fetched_at or datetime.now(UTC)

    no_guidance_policy = None
    policy_match = re.search(
        r"\b(?:do(?:es)?\s+not|doesn['’]t|will\s+not)\s+(?:provide|issue|give)\s+(?:quantitative\s+)?(?:financial\s+)?guidance\b",
        text,
        re.I,
    )
    if policy_match:
        start = max(0, policy_match.start() - 160)
        end = min(len(text), policy_match.end() + 160)
        no_guidance_policy = GuidancePolicyEvidence(
            ticker=document.ticker,
            standing_no_guidance_policy=True,
            source=document.source,
            source_url=document.source_url,
            source_timestamp=document.source_timestamp,
            evidence_span=text[start:end].strip(),
        )

    for segment in _segments(text):
        mentions = _metric_mentions(segment)
        if not mentions:
            continue
        action = _action(segment)
        if not _guidance_context(segment) and action == GuidanceAction.NONE:
            continue

        for index, mention in enumerate(mentions):
            period = _period_for_metric(segment, mention.start)
            if period is None:
                rejected.append(
                    {"reason": "missing_fiscal_period", "metric": mention.metric.value, "segment": segment[:400]}
                )
                continue
            clause, anchor = _metric_clause(segment, mentions, index)
            numeric = _numeric_range(clause, mention.metric, anchor=anchor)
            if numeric is None and action not in {
                GuidanceAction.WITHDRAW,
                GuidanceAction.REAFFIRM,
                GuidanceAction.LOWER,
                GuidanceAction.RAISE,
            }:
                rejected.append(
                    {"reason": "missing_numeric_guidance", "metric": mention.metric.value, "segment": segment[:400]}
                )
                continue
            low = high = None
            unit = "UNKNOWN"
            if numeric is not None:
                low, high, unit = numeric
            basis = _accounting_basis(segment, mention)
            key = (
                mention.metric.value,
                period,
                basis,
                low,
                high,
                action.value,
                document.source_timestamp.isoformat(),
            )
            if key in seen:
                continue
            seen.add(key)
            records.append(
                GuidanceMetricRecord(
                    rules_hash=rules_hash,
                    ticker=document.ticker,
                    fiscal_period=period,
                    metric=mention.metric,
                    accounting_basis=basis,
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
                    evidence_span=segment[:1000],
                    source_document_hash=document.content_hash,
                    as_of=document.source_timestamp,
                    fetched_at=now,
                    stale=document.stale,
                )
            )

    return GuidanceExtractionResult(
        ticker=document.ticker,
        document_id=document.document_id,
        records=records,
        policy_evidence=no_guidance_policy,
        rejected_candidates=rejected,
    )
