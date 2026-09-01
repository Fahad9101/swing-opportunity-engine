from __future__ import annotations

import html
import re
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Iterable

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
    (GuidanceMetric.OPERATING_MARGIN, ("operating margin",)),
    (GuidanceMetric.GROSS_MARGIN, ("gross margin",)),
    (GuidanceMetric.EBITDA, ("adjusted ebitda", "ebitda")),
    (GuidanceMetric.EPS, ("adjusted eps", "diluted eps", "earnings per share", "eps")),
    (GuidanceMetric.REVENUE, ("net sales", "revenue", "sales")),
]

_ACTION_PATTERNS: list[tuple[GuidanceAction, re.Pattern[str]]] = [
    (GuidanceAction.WITHDRAW, re.compile(r"\b(withdraw(?:s|n|ing)?|suspend(?:s|ed|ing)?)\b", re.I)),
    (GuidanceAction.LOWER, re.compile(r"\b(lower(?:s|ed|ing)?|reduc(?:e|es|ed|ing)|cut(?:s|ting)?)\b", re.I)),
    (GuidanceAction.RAISE, re.compile(r"\b(rais(?:e|es|ed|ing)|increas(?:e|es|ed|ing)|boost(?:s|ed|ing)?)\b", re.I)),
    (GuidanceAction.REAFFIRM, re.compile(r"\b(reaffirm(?:s|ed|ing)?|reiterat(?:e|es|ed|ing)|maintain(?:s|ed|ing)?)\b", re.I)),
    (GuidanceAction.INITIATE, re.compile(r"\b(initiat(?:e|es|ed|ing)|provid(?:e|es|ed|ing)|expect(?:s|ed|ing)?)\b", re.I)),
]

_PERIOD_PATTERNS = [
    re.compile(r"\b(?:FY|fiscal\s+year|full[-\s]?year)\s*(20\d{2})\b", re.I),
    re.compile(r"\b(20\d{2})\s*(?:fiscal\s+year|full[-\s]?year)\b", re.I),
]

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


def html_to_text(content: str) -> str:
    if "<" not in content or ">" not in content:
        return html.unescape(content)
    parser = _TextExtractor()
    parser.feed(content)
    return html.unescape(parser.text())


def _segments(text: str) -> Iterable[str]:
    normalized = re.sub(r"[ \t]+", " ", text.replace("\xa0", " "))
    for part in re.split(r"[\r\n]+|(?<=[.;])\s+(?=[A-Z0-9])", normalized):
        cleaned = part.strip()
        if 20 <= len(cleaned) <= 1200:
            yield cleaned


def _metric(segment: str) -> GuidanceMetric | None:
    lower = segment.lower()
    for metric, aliases in _METRIC_ALIASES:
        if any(re.search(rf"\b{re.escape(alias)}\b", lower) for alias in aliases):
            return metric
    return None


def _action(segment: str) -> GuidanceAction:
    for action, pattern in _ACTION_PATTERNS:
        if pattern.search(segment):
            return action
    return GuidanceAction.NONE


def _period(segment: str) -> str | None:
    for pattern in _PERIOD_PATTERNS:
        match = pattern.search(segment)
        if match:
            return f"FY{match.group(1)}"
    return None


def _accounting_basis(segment: str) -> str:
    lower = segment.lower()
    if "adjusted" in lower or "non-gaap" in lower or "non gaap" in lower:
        return "ADJUSTED"
    if "gaap" in lower:
        return "GAAP"
    return "UNSPECIFIED"


def _amount(token: str, scale_token: str | None) -> float:
    value = float(token.replace(",", ""))
    if scale_token:
        value *= _SCALE.get(scale_token.lower().rstrip("."), 1.0)
    return value


def _numeric_range(segment: str, metric: GuidanceMetric) -> tuple[float | None, float | None, str] | None:
    if metric in {GuidanceMetric.GROSS_MARGIN, GuidanceMetric.OPERATING_MARGIN}:
        range_match = re.search(
            r"(?P<low>\d{1,3}(?:\.\d+)?)\s*%\s*(?:to|through|-|–|—)\s*(?P<high>\d{1,3}(?:\.\d+)?)\s*%",
            segment,
            re.I,
        )
        if range_match:
            return float(range_match.group("low")) / 100, float(range_match.group("high")) / 100, "fraction"
        single = re.search(r"(?:approximately|about|around|of|at)\s*(?P<value>\d{1,3}(?:\.\d+)?)\s*%", segment, re.I)
        if single:
            value = float(single.group("value")) / 100
            return value, value, "fraction"
        return None

    if metric == GuidanceMetric.EPS:
        range_match = re.search(
            r"\$?\s*(?P<low>-?\d+(?:\.\d+)?)\s*(?:to|through|-|–|—)\s*\$?\s*(?P<high>-?\d+(?:\.\d+)?)",
            segment,
            re.I,
        )
        if range_match:
            return float(range_match.group("low")), float(range_match.group("high")), "USD/share"
        single = re.search(r"(?:approximately|about|around|of|at)\s*\$?\s*(?P<value>-?\d+(?:\.\d+)?)", segment, re.I)
        if single:
            value = float(single.group("value"))
            return value, value, "USD/share"
        return None

    range_match = re.search(
        r"\$?\s*(?P<low>\d[\d,]*(?:\.\d+)?)\s*(?P<scale1>billion|million|thousand|bn|mm|[bmk])?"
        r"\s*(?:to|through|-|–|—)\s*\$?\s*(?P<high>\d[\d,]*(?:\.\d+)?)\s*(?P<scale2>billion|million|thousand|bn|mm|[bmk])?",
        segment,
        re.I,
    )
    if range_match:
        scale1 = range_match.group("scale1")
        scale2 = range_match.group("scale2")
        shared_scale = scale2 or scale1
        low = _amount(range_match.group("low"), scale1 or shared_scale)
        high = _amount(range_match.group("high"), scale2 or shared_scale)
        if low <= high:
            return low, high, "USD"
    single = re.search(
        r"(?:approximately|about|around|of|at)\s*\$?\s*(?P<value>\d[\d,]*(?:\.\d+)?)\s*(?P<scale>billion|million|thousand|bn|mm|[bmk])?",
        segment,
        re.I,
    )
    if single:
        value = _amount(single.group("value"), single.group("scale"))
        return value, value, "USD"
    return None


def extract_guidance_facts(document: SourceDocument, *, rules_hash: str) -> GuidanceExtractionResult:
    """Conservative deterministic text-to-fact extraction.

    This function emits candidate structured facts only. It does not classify
    deterioration and does not assign any SOE score.
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
        metric = _metric(segment)
        if metric is None:
            continue
        action = _action(segment)
        period = _period(segment)
        has_guidance_context = bool(
            re.search(r"\b(guidance|outlook|forecast|expects?|targets?|full[-\s]?year|fiscal\s+year|FY20\d{2})\b", segment, re.I)
        )
        if not has_guidance_context and action == GuidanceAction.NONE:
            continue
        if period is None:
            rejected.append({"reason": "missing_fiscal_period", "segment": segment[:400]})
            continue
        numeric = _numeric_range(segment, metric)
        if numeric is None and action not in {
            GuidanceAction.WITHDRAW,
            GuidanceAction.REAFFIRM,
            GuidanceAction.LOWER,
            GuidanceAction.RAISE,
        }:
            rejected.append({"reason": "missing_numeric_guidance", "metric": metric.value, "segment": segment[:400]})
            continue
        low = high = None
        unit = "UNKNOWN"
        if numeric is not None:
            low, high, unit = numeric
        basis = _accounting_basis(segment)
        key = (metric.value, period, basis, low, high, action.value, document.source_timestamp.isoformat())
        if key in seen:
            continue
        seen.add(key)
        records.append(
            GuidanceMetricRecord(
                rules_hash=rules_hash,
                ticker=document.ticker,
                fiscal_period=period,
                metric=metric,
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
