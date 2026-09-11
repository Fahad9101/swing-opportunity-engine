from __future__ import annotations

import re
from typing import Iterable

from app.domain.soe_v1_1 import (
    ExtractionMethod,
    GuidanceAction,
    GuidanceExtractionResult,
    GuidanceMetric,
    GuidanceMetricRecord,
    SourceDocument,
)
from app.services.fact_extraction_service import html_to_text
from app.services.phase_1_1e_run88_guidance_repairs_v1_1 import extract_guidance_facts_run88


# Run-89 manual-audit repair: deterministic source normalization only.
# Frozen SOE thresholds/scores/scanners/classifiers and IEE are unchanged.
_Q = {"first": 1, "second": 2, "third": 3, "fourth": 4}
_SCALE = {
    "k": 1e3, "thousand": 1e3, "thousands": 1e3,
    "m": 1e6, "mm": 1e6, "million": 1e6, "millions": 1e6,
    "b": 1e9, "bn": 1e9, "billion": 1e9, "billions": 1e9,
}
_NUM = r"\d[\d,]*(?:\.\d+)?"
_ST = r"(?:billions?|millions?|thousands?|bn|mm|[bmk])"
_MONEY = re.compile(
    rf"(?P<d1>\$)?\s*(?P<lo>{_NUM})\s*(?P<s1>{_ST})?\s*"
    rf"(?:to|through|and|-|–|—)\s*(?P<d2>\$)?\s*(?P<hi>{_NUM})\s*(?P<s2>{_ST})?",
    re.I,
)
_PCT = re.compile(
    r"(?P<lo>\d{1,3}(?:\.\d+)?)\s*%\s*(?:to|through|and|-|–|—)\s*"
    r"(?P<hi>\d{1,3}(?:\.\d+)?)\s*%",
    re.I,
)

_HEADERS = (
    re.compile(
        r"\b(?P<q>first|second|third|fourth)\s+quarter(?:\s+of)?\s+"
        r"(?:fiscal(?:\s+year)?\s+)?(?P<y>20\d{2})\s+(?:outlook|guidance)\b", re.I
    ),
    re.compile(
        r"\b(?:financial\s+guidance\s+for\s+)?full[-\s]?year\s+"
        r"(?P<y>20\d{2})\s*(?:outlook|guidance)?\b", re.I
    ),
    re.compile(r"\b(?P<y>20\d{2})\s+(?:full[-\s]?year|annual)\s+(?:outlook|guidance)\b", re.I),
    re.compile(r"\bfiscal\s+year\s+(?P<y>20\d{2})\s+(?:outlook|guidance)\b", re.I),
)
_REVENUE = re.compile(
    r"\b(?:total\s+(?:[A-Za-z][A-Za-z0-9&.\-]*\s+){0,3}revenue"
    r"(?:\s+and\s+other\s+income)?|consolidated\s+(?:net\s+)?revenues?|"
    r"total\s+revenues?|revenue)\b", re.I
)
_EBITDA = re.compile(r"\b(?:adjusted|non[-\s]?GAAP)\s+EBITDA(?:\s*\(?\d+\)?)?\b", re.I)
_EPS = re.compile(
    r"\b(?:adjusted|non[-\s]?GAAP)?\s*(?:earnings\s+per\s+share"
    r"(?:\s*[-–—]?\s*diluted)?|diluted\s+earnings\s+per\s+share|diluted\s+EPS|EPS)\b", re.I
)
_GM = re.compile(r"\b(?:adjusted|non[-\s]?GAAP)?\s*gross\s+margin(?:\s+percentage)?\b", re.I)
_OM = re.compile(r"\b(?:adjusted|non[-\s]?GAAP)?\s*operating\s+margin(?:\s+percentage)?\b", re.I)
_SEGMENT = re.compile(r"\b(?:segment|product|service|division|business\s+unit)\b", re.I)

_TOTAL_Q_SENTENCE = re.compile(
    rf"\b(?:the\s+company\s+)?(?:now\s+)?expects?\s+"
    rf"(?P<label>total\s+(?:[A-Za-z][A-Za-z0-9&.\-]*\s+){{0,3}}revenue)"
    rf".{{0,90}}?(?P<range>\$?\s*{_NUM}\s*{_ST}?\s*"
    rf"(?:to|through|and|-|–|—)\s*\$?\s*{_NUM}\s*{_ST}?)"
    rf".{{0,100}}?\b(?:in|for)\s+(?:the\s+)?"
    rf"(?P<q>first|second|third|fourth)\s+quarter(?:\s+of)?\s+fiscal\s+(?P<y>20\d{{2}})\b",
    re.I | re.S,
)
_SCALE_WORD = re.compile(r"\b(?:in\s+)?(thousands?|millions?|billions?)\b", re.I)


def _text(document: SourceDocument) -> str:
    return re.sub(r"\s+", " ", html_to_text(document.content or "")).strip()


def _year(token: str) -> int:
    value = int(token)
    return value + 2000 if value < 100 else value


def _sections(text: str) -> list[tuple[int, int, str, str]]:
    found: list[tuple[int, int, str, str]] = []
    for pattern in _HEADERS:
        for m in pattern.finditer(text):
            q = m.groupdict().get("q")
            period = f"Q{_Q[q.lower()]}FY{m.group('y')}" if q else f"FY{m.group('y')}"
            found.append((m.start(), m.end(), period, m.group(0)))
    found.sort(key=lambda x: (x[0], -(x[1] - x[0])))
    headers: list[tuple[int, int, str, str]] = []
    for row in found:
        if not any(row[0] < old[1] and row[1] > old[0] for old in headers):
            headers.append(row)
    out = []
    for i, (start, end, period, header) in enumerate(headers):
        stop = min(len(text), end + 1800)
        if i + 1 < len(headers):
            stop = min(stop, headers[i + 1][0])
        out.append((start, stop, period, header))
    return out


def _money(m: re.Match[str], *, eps: bool = False, inherited: float | None = None):
    lo, hi = float(m.group("lo").replace(",", "")), float(m.group("hi").replace(",", ""))
    if lo > hi:
        return None
    if eps:
        return None if (m.group("s1") or m.group("s2")) else (lo, hi, "USD/share")
    token = m.group("s1") or m.group("s2")
    if token:
        scale = _SCALE[token.lower()]
    elif inherited is not None and (m.group("d1") or m.group("d2")):
        scale = inherited
    elif m.group("d1") or m.group("d2"):
        scale = 1.0
    else:
        return None
    return lo * scale, hi * scale, "USD"


def _basis(label: str) -> str:
    if re.search(r"\badjusted\b|non[-\s]?GAAP", label, re.I):
        return "ADJUSTED"
    if re.search(r"\bGAAP\b", label, re.I):
        return "GAAP"
    return "UNSPECIFIED"


def _record(document, rules_hash, period, metric, label, lo, hi, unit, evidence):
    return GuidanceMetricRecord(
        rules_hash=rules_hash, ticker=document.ticker, fiscal_period=period, metric=metric,
        accounting_basis=_basis(label), low=lo, high=hi, unit=unit,
        source=document.source, source_url=document.source_url,
        source_accession=document.accession, source_timestamp=document.source_timestamp,
        explicit_action=GuidanceAction.NONE, verified=True,
        extraction_method=ExtractionMethod.STRUCTURED,
        evidence_span=f"phase_1_1e_run89_authoritative_forward_scope; {evidence}"[:1000],
        source_document_hash=document.content_hash, as_of=document.source_timestamp,
        fetched_at=document.fetched_at, stale=document.stale,
    )


def _range_after(section: str, end: int, *, eps=False, inherited=None):
    window = section[end:min(len(section), end + 220)]
    m = _MONEY.search(window)
    if m is None:
        return None
    parsed = _money(m, eps=eps, inherited=inherited)
    return None if parsed is None else (*parsed, window[:m.end()])


def _pct_after(section: str, end: int):
    window = section[end:min(len(section), end + 180)]
    m = _PCT.search(window)
    if m is None:
        return None
    lo, hi = float(m.group("lo")) / 100.0, float(m.group("hi")) / 100.0
    return None if lo > hi else (lo, hi, window[:m.end()])


def _normalize_sections(document: SourceDocument, rules_hash: str):
    text = _text(document)
    out = []
    for start, stop, period, header in _sections(text):
        section = text[start:stop]
        scales = list(_SCALE_WORD.finditer(section[:500]))
        inherited = _SCALE.get(scales[-1].group(1).lower()) if scales else None

        mentions = list(_REVENUE.finditer(section))
        if mentions:
            explicit = [m for m in mentions if re.match(r"(?:total|consolidated)", m.group(0), re.I)]
            m = explicit[0] if explicit else mentions[0]
            prefix = section[max(0, m.start() - 80):m.start()]
            if explicit or not _SEGMENT.search(prefix):
                parsed = _range_after(section, m.end(), inherited=inherited)
                if parsed:
                    lo, hi, unit, ev = parsed
                    out.append(_record(document, rules_hash, period, GuidanceMetric.REVENUE,
                                       m.group(0), lo, hi, unit, f"{header}; {m.group(0)}{ev}"))

        for pattern, metric in ((_EBITDA, GuidanceMetric.EBITDA), (_EPS, GuidanceMetric.EPS)):
            m = pattern.search(section)
            if m:
                parsed = _range_after(section, m.end(), eps=metric is GuidanceMetric.EPS, inherited=inherited)
                if parsed:
                    lo, hi, unit, ev = parsed
                    out.append(_record(document, rules_hash, period, metric, m.group(0),
                                       lo, hi, unit, f"{header}; {m.group(0)}{ev}"))

        for pattern, metric in ((_GM, GuidanceMetric.GROSS_MARGIN), (_OM, GuidanceMetric.OPERATING_MARGIN)):
            m = pattern.search(section)
            if m:
                parsed = _pct_after(section, m.end())
                if parsed:
                    lo, hi, ev = parsed
                    out.append(_record(document, rules_hash, period, metric, m.group(0),
                                       lo, hi, "fraction", f"{header}; {m.group(0)}{ev}"))
    return out


def _normalize_total_q_sentence(document: SourceDocument, rules_hash: str):
    text = _text(document)
    out = []
    for m in _TOTAL_Q_SENTENCE.finditer(text):
        rm = _MONEY.search(m.group("range"))
        parsed = _money(rm) if rm else None
        if parsed:
            lo, hi, unit = parsed
            period = f"Q{_Q[m.group('q').lower()]}FY{m.group('y')}"
            out.append(_record(document, rules_hash, period, GuidanceMetric.REVENUE,
                               m.group("label"), lo, hi, unit, m.group(0)))
    return out


def _normalize_two_column_total_revenue(document: SourceDocument, rules_hash: str):
    text = _text(document)
    out = []
    header = re.compile(
        r"\bQ(?P<q>[1-4])\s*FY\s*'?(?P<qy>\d{2,4})\b.{0,80}?"
        r"(?:full\s+fiscal\s+year\s+)?FY\s*'?(?P<fy>\d{2,4})\b", re.I | re.S
    )
    for h in header.finditer(text):
        qy, fy = _year(h.group("qy")), _year(h.group("fy"))
        if qy != fy:
            continue
        section = text[h.end():min(len(text), h.end() + 1400)]
        label = re.search(
            r"\b(total\s+(?:[A-Za-z][A-Za-z0-9&.\-]*\s+){0,3}revenue)\s*:?", section, re.I
        )
        if label is None:
            continue
        after = section[label.end():min(len(section), label.end() + 260)]
        ranges = list(_MONEY.finditer(after))
        if len(ranges) < 2:
            continue
        first, second = _money(ranges[0]), _money(ranges[1])
        if first is None or second is None:
            continue
        for period, parsed in ((f"Q{h.group('q')}FY{qy}", first), (f"FY{fy}", second)):
            lo, hi, unit = parsed
            out.append(_record(document, rules_hash, period, GuidanceMetric.REVENUE,
                               label.group(1), lo, hi, unit,
                               f"{h.group(0)}; {label.group(1)}; {after[:ranges[1].end()]}"))
    return out


def _dedupe(records: Iterable[GuidanceMetricRecord]):
    unique = {}
    for r in records:
        key = (r.metric, r.fiscal_period, r.accounting_basis, r.low, r.high,
               r.source_timestamp, r.source_url)
        unique[key] = r
    return sorted(unique.values(), key=lambda r: (
        r.source_timestamp, r.metric.value, r.fiscal_period, r.accounting_basis, r.source_url
    ))


def extract_guidance_facts_run89(
    document: SourceDocument, *, rules_hash: str
) -> GuidanceExtractionResult:
    """Make directly parsed company-level forward rows authoritative per filing/metric."""
    base = extract_guidance_facts_run88(document, rules_hash=rules_hash)
    normalized = _dedupe([
        *_normalize_sections(document, rules_hash),
        *_normalize_total_q_sentence(document, rules_hash),
        *_normalize_two_column_total_revenue(document, rules_hash),
    ])
    if not normalized:
        return base

    metrics = {r.metric for r in normalized}
    removed = [r for r in base.records if r.metric in metrics]
    records = _dedupe([r for r in base.records if r.metric not in metrics] + normalized)
    rejected = list(base.rejected_candidates)
    for metric in sorted(metrics, key=lambda x: x.value):
        count = sum(r.metric is metric for r in removed)
        if count:
            rejected.append({
                "reason": "phase_1_1e_run89_authoritative_forward_scope_replaced_ambiguous_rows",
                "metric": metric.value, "replaced_record_count": count,
                "source_url": document.source_url,
            })
    return base.model_copy(update={
        "records": records,
        "policy_evidence": None if records else base.policy_evidence,
        "rejected_candidates": rejected,
    })
