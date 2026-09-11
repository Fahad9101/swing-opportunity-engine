from __future__ import annotations

import re
from typing import Iterable

from app.domain.soe_v1_1 import GuidanceExtractionResult, GuidanceMetric, GuidanceMetricRecord, SourceDocument
from app.services.fact_extraction_service import html_to_text
from app.services.phase_1_1e_run87_repairs_v1_1 import extract_guidance_facts_run87


# Run-88 manual-audit repair. Evidence normalization only: no score, threshold,
# scanner, ranking, classification, SOE-1.0.0, or IEE rule is changed.
_MARGINS = {GuidanceMetric.GROSS_MARGIN, GuidanceMetric.OPERATING_MARGIN}
_MONEY = {GuidanceMetric.REVENUE, GuidanceMetric.EBITDA, GuidanceMetric.FCF}
_QUARTERS = {"first": 1, "second": 2, "third": 3, "fourth": 4}

_HISTORICAL_HIGHLIGHTS = re.compile(
    r"\b(?:first|second|third|fourth|Q[1-4]|full[- ]year|fiscal[- ]year)?\s*"
    r"20\d{2}\s+(?:financial\s+)?highlights\b",
    re.I,
)
_REPORTED_RESULTS = re.compile(
    r"\bQ[1-4]\s+20\d{2}\s+"
    r"(?:revenue|revenues|net sales|adjusted EBITDA|EBITDA|earnings per share|EPS)\s+of\s+\$",
    re.I,
)
_EXCLUDED_EPS = re.compile(
    r"\bexclud(?:e|es|ed|ing)\b.{0,180}?\$?\s*(\d+(?:\.\d+)?)\s+per\s+(?:diluted\s+)?share\b",
    re.I | re.S,
)
_TABLE_SCALE = re.compile(
    r"\(\s*in\s+(thousands?|millions?|billions?)\s*\)|"
    r"\b(?:values?\s+)?in\s+(thousands?|millions?|billions?)\b",
    re.I,
)
_SCALE = {
    "thousand": 1_000.0,
    "thousands": 1_000.0,
    "million": 1_000_000.0,
    "millions": 1_000_000.0,
    "billion": 1_000_000_000.0,
    "billions": 1_000_000_000.0,
}

_QUARTER_PATTERNS = (
    re.compile(r"\b(?:fiscal\s+)?(20\d{2})\s+(first|second|third|fourth)\s+quarter(?:\s+(?:outlook|guidance))?\b", re.I),
    re.compile(r"\b(first|second|third|fourth)\s+quarter(?:\s+of)?(?:\s+fiscal(?:\s+year)?)?\s+(20\d{2})\b", re.I),
    re.compile(r"\bQ([1-4])\s*(?:FY)?\s*(20\d{2})\b", re.I),
)
_ANNUAL_PATTERNS = (
    re.compile(r"\bfull[- ]year(?:\s+of)?\s+(20\d{2})\b", re.I),
    re.compile(r"\bfiscal\s+year\s+(20\d{2})\b", re.I),
    re.compile(r"\bFY\s*(20\d{2})\b", re.I),
    re.compile(r"\b(20\d{2})\s+(?:full[- ]year|annual)\s+(?:guidance|outlook)\b", re.I),
    re.compile(r"\byear\s+ending\s+[A-Za-z]+\s+\d{1,2},?\s+(20\d{2})\b", re.I),
)
_LOCAL_QUARTER = re.compile(r"\bfor\s+(?:the\s+)?(first|second|third|fourth)\s+quarter\b", re.I)
_LOCAL_ANNUAL = re.compile(r"\bfor\s+(?:the\s+)?full\s+year\b", re.I)
_YEAR_GUIDANCE_HEADER = re.compile(
    r".{0,180}\b(20\d{2})\b.{0,80}\b(?:guidance|outlook)\b",
    re.I | re.S,
)

_MARGIN_LABEL = re.compile(r"\b(?:adjusted|non[- ]GAAP|GAAP)?\s*(?:gross|operating)\s+margin\b", re.I)
_PERCENT = re.compile(r"(?<!\d)(\d{1,3}(?:\.\d+)?)\s*%")


def _flat_text(document: SourceDocument) -> str:
    return re.sub(r"\s+", " ", html_to_text(document.content or "")).strip()


def _source_evidence(record: GuidanceMetricRecord) -> str:
    evidence = re.sub(r"\s+", " ", record.evidence_span or "").strip()
    if evidence.startswith("normalized_explicit_guidance_scope;"):
        parts = evidence.split(";", 2)
        return parts[2].strip() if len(parts) == 3 else evidence
    return evidence


def _find_all(text: str, needle: str) -> list[int]:
    needle = re.sub(r"\s+", " ", needle).strip()
    if len(needle) < 12:
        return []
    hay = text.lower()
    key = needle.lower()
    result: list[int] = []
    start = 0
    while True:
        idx = hay.find(key, start)
        if idx < 0:
            break
        result.append(idx)
        start = idx + 1
    return result


def _period_mentions(text: str) -> list[tuple[int, int, str]]:
    mentions: list[tuple[int, int, str, int]] = []
    for pattern_index, pattern in enumerate(_QUARTER_PATTERNS):
        for match in pattern.finditer(text):
            if pattern_index == 0:
                year, word = match.group(1), match.group(2).lower()
                quarter = _QUARTERS[word]
            elif pattern_index == 1:
                word, year = match.group(1).lower(), match.group(2)
                quarter = _QUARTERS[word]
            else:
                quarter, year = int(match.group(1)), match.group(2)
            mentions.append((match.start(), match.end(), f"Q{quarter}FY{year}", 0))
    for pattern in _ANNUAL_PATTERNS:
        for match in pattern.finditer(text):
            mentions.append((match.start(), match.end(), f"FY{match.group(1)}", 1))

    # Local clauses such as "For the third quarter" and "For the full year"
    # inherit the year only from a nearby guidance/outlook header.
    for pattern, kind in ((_LOCAL_QUARTER, "quarter"), (_LOCAL_ANNUAL, "annual")):
        for match in pattern.finditer(text):
            context = text[max(0, match.start() - 500):match.start()]
            headers = list(_YEAR_GUIDANCE_HEADER.finditer(context))
            if not headers:
                continue
            year = headers[-1].group(1)
            if kind == "quarter":
                period = f"Q{_QUARTERS[match.group(1).lower()]}FY{year}"
            else:
                period = f"FY{year}"
            mentions.append((match.start(), match.end(), period, 0 if kind == "quarter" else 1))

    mentions.sort(key=lambda item: (item[0], item[3], -(item[1] - item[0])))
    chosen: list[tuple[int, int, str]] = []
    for start, end, period, _ in mentions:
        if any(start < old_end and end > old_start for old_start, old_end, _ in chosen):
            continue
        chosen.append((start, end, period))
    return sorted(chosen)


def _nearest_preceding_period(text: str, position: int) -> str | None:
    candidates = [
        (position - end, start, period)
        for start, end, period in _period_mentions(text)
        if end <= position and position - end <= 1400
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda item: (item[0], -item[1]))[2]


def _last_source_clause(record: GuidanceMetricRecord) -> str:
    evidence = re.sub(r"\s+", " ", record.evidence_span or "").strip()
    if evidence.startswith("normalized_explicit_guidance_scope;"):
        pieces = [piece.strip() for piece in evidence.split(";") if piece.strip()]
        return pieces[-1] if pieces else ""
    return ""


def _rebind_explicit_period(
    document_text: str,
    record: GuidanceMetricRecord,
) -> GuidanceMetricRecord:
    if not (record.evidence_span or "").startswith("normalized_explicit_guidance_scope;"):
        return record
    clause = _last_source_clause(record)
    positions = _find_all(document_text, clause)
    if not positions:
        return record
    scoped: list[tuple[int, str]] = []
    for position in positions:
        period = _nearest_preceding_period(document_text, position)
        if period is not None:
            scoped.append((position, period))
    if not scoped:
        return record

    # Prefer an occurrence whose current period is already local; otherwise the
    # last exact clause occurrence is typically the detailed outlook section,
    # rather than a headline summary.
    same = [item for item in scoped if item[1] == record.fiscal_period]
    _, period = same[-1] if same else scoped[-1]
    if period == record.fiscal_period:
        return record
    return record.model_copy(
        update={
            "fiscal_period": period,
            "evidence_span": (
                f"phase_1_1e_run88_period_rebind; from={record.fiscal_period}; to={period}; "
                f"{record.evidence_span or ''}"
            )[:1000],
        }
    )


def _rebind_run85_margin_period(record: GuidanceMetricRecord) -> GuidanceMetricRecord:
    if record.metric not in _MARGINS or "phase_1_1e_run85" not in (record.evidence_span or ""):
        return record
    source = _source_evidence(record)
    label = _MARGIN_LABEL.search(source)
    if label is None:
        return record
    preceding = source[max(0, label.start() - 900):label.start()]
    mentions = _period_mentions(preceding)
    if not mentions:
        return record
    period = mentions[-1][2]
    if period == record.fiscal_period:
        return record
    return record.model_copy(
        update={
            "fiscal_period": period,
            "evidence_span": (
                f"phase_1_1e_run88_period_rebind; from={record.fiscal_period}; to={period}; "
                f"{record.evidence_span or ''}"
            )[:1000],
        }
    )


def _historical_actual(record: GuidanceMetricRecord) -> bool:
    evidence = _source_evidence(record)
    if record.metric in _MARGINS and (
        _HISTORICAL_HIGHLIGHTS.search(evidence)
        or (
            re.search(r"\b(?:financial\s+results|reported\s+results)\b", evidence, re.I)
            and re.search(r"\bcompared\s+to\b", evidence, re.I)
        )
    ):
        return True
    if record.low == record.high and _REPORTED_RESULTS.search(evidence):
        return True
    return False


def _margin_value_is_local(record: GuidanceMetricRecord) -> bool:
    if record.metric not in _MARGINS or "phase_1_1e_run85" not in (record.evidence_span or ""):
        return True
    evidence = _source_evidence(record)
    labels = list(_MARGIN_LABEL.finditer(evidence))
    if not labels or record.low is None or record.high is None:
        return False
    expected = [100.0 * record.low, 100.0 * record.high]
    percentages = [(m.start(), float(m.group(1))) for m in _PERCENT.finditer(evidence)]
    for label in labels:
        for pos, value in percentages:
            if abs(pos - label.end()) > 120 and abs(label.start() - pos) > 120:
                continue
            if any(abs(value - target) <= 1e-6 for target in expected):
                bridge = evidence[min(label.end(), pos):max(label.start(), pos)]
                if not re.search(
                    r"\b(?:net\s+sales|revenue|advertising|cash|adjusted\s+EBITDA|capital\s+expenditures?)\b",
                    bridge,
                    re.I,
                ):
                    return True
    return False


def _scale_from_evidence(record: GuidanceMetricRecord) -> float | None:
    if record.metric not in _MONEY or record.unit != "USD" or record.low is None or record.high is None:
        return None
    if max(abs(record.low), abs(record.high)) >= 1_000_000:
        return None
    evidence = record.evidence_span or ""
    matches = list(_TABLE_SCALE.finditer(evidence))
    if not matches:
        return None
    token = matches[-1].group(1) or matches[-1].group(2)
    return _SCALE.get(token.lower()) if token else None


def _apply_inherited_scale(record: GuidanceMetricRecord) -> GuidanceMetricRecord:
    scale = _scale_from_evidence(record)
    if scale is None:
        return record
    low = record.low * scale if record.low is not None else None
    high = record.high * scale if record.high is not None else None
    return record.model_copy(
        update={
            "low": low,
            "high": high,
            "midpoint": ((low + high) / 2.0) if low is not None and high is not None else None,
            "evidence_span": (
                f"phase_1_1e_run88_inherited_table_scale={scale:g}; {record.evidence_span or ''}"
            )[:1000],
        }
    )


def _excluded_eps_adjustment(record: GuidanceMetricRecord) -> bool:
    if record.metric is not GuidanceMetric.EPS or record.low is None or record.high is None:
        return False
    if abs(record.low - record.high) > 1e-12:
        return False
    evidence = record.evidence_span or ""
    target = record.low
    for match in _EXCLUDED_EPS.finditer(evidence):
        if abs(float(match.group(1)) - target) <= 1e-9:
            return True
    return False


def _dedupe(records: Iterable[GuidanceMetricRecord]) -> list[GuidanceMetricRecord]:
    unique: dict[tuple, GuidanceMetricRecord] = {}
    for record in records:
        key = (
            record.metric,
            record.fiscal_period,
            record.accounting_basis,
            record.low,
            record.high,
            record.source_timestamp,
            record.source_url,
            record.supersedes_record_id,
        )
        unique[key] = record
    return sorted(
        unique.values(),
        key=lambda item: (
            item.source_timestamp,
            item.metric.value,
            item.fiscal_period,
            item.accounting_basis,
            item.source_url,
        ),
    )


def extract_guidance_facts_run88(
    document: SourceDocument,
    *,
    rules_hash: str,
) -> GuidanceExtractionResult:
    """Repair Run-88 guidance evidence boundaries conservatively.

    The wrapper corrects only source binding/normalization:
    * explicit quarter-vs-annual scope bleed,
    * historical actuals mislabeled as guidance,
    * non-local margin percentages from flattened tables,
    * inherited monetary table scales, and
    * EPS reconciliation/exclusion amounts mistaken for guided EPS.
    """
    result = extract_guidance_facts_run87(document, rules_hash=rules_hash)
    text = _flat_text(document)
    records: list[GuidanceMetricRecord] = []
    rejected: list[dict] = list(result.rejected_candidates)

    for original in result.records:
        record = _rebind_explicit_period(text, original)
        record = _rebind_run85_margin_period(record)
        record = _apply_inherited_scale(record)

        reason = None
        if _historical_actual(record):
            reason = "historical_reported_actual_not_guidance"
        elif not _margin_value_is_local(record):
            reason = "margin_value_not_locally_bound_to_margin_label"
        elif _excluded_eps_adjustment(record):
            reason = "eps_reconciliation_adjustment_not_guidance"

        if reason is not None:
            rejected.append(
                {
                    "reason": f"phase_1_1e_run88_{reason}",
                    "metric": record.metric.value,
                    "fiscal_period": record.fiscal_period,
                    "source_url": record.source_url,
                    "evidence": (record.evidence_span or "")[:500],
                }
            )
            continue
        records.append(record)

    records = _dedupe(records)
    policy = result.policy_evidence
    if any(record.midpoint is not None for record in records):
        policy = None
    return result.model_copy(
        update={
            "records": records,
            "policy_evidence": policy,
            "rejected_candidates": rejected,
        }
    )
