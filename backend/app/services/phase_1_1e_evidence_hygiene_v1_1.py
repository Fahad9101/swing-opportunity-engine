from __future__ import annotations

import re
from collections import defaultdict
from pathlib import PurePosixPath
from urllib.parse import urlparse

from app.domain.soe_v1_1 import (
    GuidanceAction,
    GuidanceExtractionResult,
    GuidanceMetric,
    GuidanceMetricRecord,
    GuidancePolicyEvidence,
    SourceDocument,
)
from app.services import guidance_extraction_hardening_v1_1 as hardened
from app.services.catalyst_primary_evidence_service import (
    ExtractedCatalystCandidate,
    extract_sec_catalyst_candidates as _base_catalyst_candidates,
)
from app.services.guidance_binding_patch_v1_1 import (
    extract_guidance_facts_hardened as _base_guidance_extract,
    install_binding_patch,
)


_ACTUAL_LOCAL = re.compile(
    r"\b(?:reported|actual|results?|generated|achieved|delivered|quarter\s+ended|"
    r"three\s+months\s+ended|six\s+months\s+ended|nine\s+months\s+ended|year\s+ended|"
    r"year[-\s]?to[-\s]?date|net\s+sales\s+(?:were|was)|revenues?\s+(?:were|was))\b",
    re.I,
)
_DIRECT_FORWARD = re.compile(
    r"\b(?:expects?|anticipat(?:e|es|ed|ing)|project(?:s|ed|ing)|forecast(?:s|ed|ing)?|"
    r"rais(?:e|es|ed|ing)|increas(?:e|es|ed|ing)|lower(?:s|ed|ing)?|reduc(?:e|es|ed|ing)|"
    r"cut(?:s|ting)?|reaffirm(?:s|ed|ing)?|reiterat(?:e|es|ed|ing)|maintain(?:s|ed|ing)|"
    r"update(?:s|d|ing)|initiat(?:e|es|ed|ing)|provid(?:e|es|ed|ing))\b",
    re.I,
)
_GUIDANCE_LABEL = re.compile(r"\b(?:guidance|outlook|forecast|financial\s+targets?)\b", re.I)
_QUARTER_PERIOD = re.compile(
    r"\b(?:Q[1-4]\s*(?:FY|fiscal(?:\s+year)?)?\s*'?(?:20)?\d{2}|"
    r"(?:first|second|third|fourth)\s+quarter(?:\s+of)?\s+(?:fiscal(?:\s+year)?\s*)?(?:FY\s*)?20\d{2})\b",
    re.I,
)
_FULL_YEAR_EXPLICIT = re.compile(
    r"\b(?:full[-\s]?year\s+20\d{2}|fiscal\s+year\s+20\d{2}|year\s+ending\s+[A-Za-z]+\s+\d{1,2},?\s*20\d{2})\b",
    re.I,
)
_BARE_FY = re.compile(r"\bFY\s*'?20\d{2}\b", re.I)
_QUARTER_PREFIX = re.compile(r"(?:\bQ[1-4]|\b(?:first|second|third|fourth)\s+quarter)\s*$", re.I)
_POLICY_SCOPE_NOISE = re.compile(
    r"\b(?:reconcil(?:e|es|ed|iation)|non[-\s]?GAAP|without\s+unreasonable\s+effort|"
    r"certain\s+items|stock[-\s]?based\s+compensation|share[-\s]?based\s+compensation|"
    r"amortization|tax\s+rate|purchase\s+accounting|mark[-\s]?to[-\s]?market)\b",
    re.I,
)
_POLICY_SPECIFIC_SCOPE = re.compile(
    r"\b(?:does\s+not|do\s+not|doesn't|doesn’t|will\s+not)\s+(?:provide|issue|give)\s+"
    r"(?:quantitative\s+)?(?:financial\s+)?guidance\s+(?:for|on)\s+"
    r"(?:adjusted|non[-\s]?GAAP|GAAP|tax|amortization|stock|share|reconciliation|free\s+cash\s+flow|"
    r"EPS|earnings|margin|interest|depreciation)",
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


def _metric_windows(text: str, metric: GuidanceMetric, *, left: int = 110, right: int = 170) -> list[str]:
    windows: list[str] = []
    for alias in sorted(hardened._METRIC_ALIASES[metric], key=len, reverse=True):
        for match in re.finditer(rf"\b{re.escape(alias)}\b", text, re.I):
            windows.append(text[max(0, match.start() - left) : min(len(text), match.end() + right)])
    return windows


def _has_standalone_full_year(text: str) -> bool:
    if _FULL_YEAR_EXPLICIT.search(text):
        return True
    for match in _BARE_FY.finditer(text):
        prefix = text[max(0, match.start() - 40) : match.start()]
        if not _QUARTER_PREFIX.search(prefix):
            return True
    return False


def _record_admissible(record: GuidanceMetricRecord) -> bool:
    """Fail closed on actual-result contamination and fiscal-period ambiguity."""
    if not record.verified:
        return False
    evidence = (record.evidence_span or "").strip()
    if not evidence:
        return True
    windows = _metric_windows(evidence, record.metric)
    if not windows:
        return False

    for window in windows:
        if _ACTUAL_LOCAL.search(window) and not _DIRECT_FORWARD.search(window):
            return False

    if record.fiscal_period.startswith("FY") and _QUARTER_PERIOD.search(evidence) and not _has_standalone_full_year(evidence):
        return False

    if record.midpoint is not None and not any(
        _DIRECT_FORWARD.search(window) or _GUIDANCE_LABEL.search(window) for window in windows
    ):
        return False
    return True


def _policy_admissible(policy: GuidancePolicyEvidence | None) -> GuidancePolicyEvidence | None:
    if policy is None or not policy.verified:
        return None
    evidence = (policy.evidence_span or "").strip()
    if not evidence or _POLICY_SCOPE_NOISE.search(evidence) or _POLICY_SPECIFIC_SCOPE.search(evidence):
        return None
    broad = re.search(
        r"\b(?:we|the\s+company|company|management)\s+(?:does\s+not|do\s+not|doesn't|doesn’t|will\s+not)\s+"
        r"(?:provide|issue|give)\s+(?:quantitative\s+)?(?:financial\s+)?guidance\b",
        evidence,
        re.I,
    )
    return policy if broad else None


def _amount(token: str, scale: str | None) -> float:
    value = float(token.replace(",", ""))
    if scale:
        value *= _SCALE.get(scale.lower().rstrip("."), 1.0)
    return value


def _parse_current_value(fragment: str, metric: GuidanceMetric) -> tuple[float, float, str] | None:
    if metric in {GuidanceMetric.GROSS_MARGIN, GuidanceMetric.OPERATING_MARGIN}:
        rng = re.search(r"(?P<lo>\d{1,3}(?:\.\d+)?)\s*%\s*(?:-|–|—|to|through)\s*(?P<hi>\d{1,3}(?:\.\d+)?)\s*%", fragment, re.I)
        if rng:
            lo, hi = float(rng.group("lo")) / 100, float(rng.group("hi")) / 100
            return (lo, hi, "fraction") if lo <= hi else None
        one = re.search(r"(?P<v>\d{1,3}(?:\.\d+)?)\s*%", fragment)
        if one:
            value = float(one.group("v")) / 100
            return value, value, "fraction"
        return None

    if metric is GuidanceMetric.EPS:
        rng = re.search(r"\$\s*(?P<lo>-?\d+(?:\.\d+)?)\s*(?:-|–|—|to|through)\s*\$?\s*(?P<hi>-?\d+(?:\.\d+)?)", fragment, re.I)
        if rng:
            lo, hi = float(rng.group("lo")), float(rng.group("hi"))
            return (lo, hi, "USD/share") if lo <= hi else None
        one = re.search(r"\$\s*(?P<v>-?\d+(?:\.\d+)?)", fragment)
        if one:
            value = float(one.group("v"))
            return value, value, "USD/share"
        return None

    rng = re.search(
        r"(?P<d1>\$)?\s*(?P<lo>\d[\d,]*(?:\.\d+)?)\s*(?P<s1>billion|million|thousand|bn|mm|[bmk])?\s*"
        r"(?:-|–|—|to|through)\s*(?P<d2>\$)?\s*(?P<hi>\d[\d,]*(?:\.\d+)?)\s*(?P<s2>billion|million|thousand|bn|mm|[bmk])?",
        fragment,
        re.I,
    )
    if rng and (rng.group("d1") or rng.group("d2") or rng.group("s1") or rng.group("s2")):
        shared = rng.group("s2") or rng.group("s1")
        lo = _amount(rng.group("lo"), rng.group("s1") or shared)
        hi = _amount(rng.group("hi"), rng.group("s2") or shared)
        return (lo, hi, "USD") if lo <= hi else None
    one = re.search(r"\$\s*(?P<v>\d[\d,]*(?:\.\d+)?)\s*(?P<s>billion|million|thousand|bn|mm|[bmk])?", fragment, re.I)
    if one:
        value = _amount(one.group("v"), one.group("s"))
        return value, value, "USD"
    return None


def _directional_rebind(record: GuidanceMetricRecord) -> GuidanceMetricRecord:
    if record.explicit_action not in {GuidanceAction.RAISE, GuidanceAction.LOWER}:
        return record
    evidence = (record.evidence_span or "").strip()
    if not evidence:
        return record
    action = r"(?:rais(?:e|es|ed|ing)|increas(?:e|es|ed|ing)|boost(?:s|ed|ing)|lower(?:s|ed|ing)?|reduc(?:e|es|ed|ing)|cut(?:s|ting)?)"

    transition = re.search(
        rf"\b{action}\b.{{0,220}}?\bfrom\b.{{0,140}}?\bto\b(?P<new>.{{0,180}})",
        evidence,
        re.I | re.S,
    )
    if transition:
        numeric = _parse_current_value(transition.group("new"), record.metric)
        if numeric is not None:
            lo, hi, unit = numeric
            return record.model_copy(update={"low": lo, "high": hi, "midpoint": (lo + hi) / 2, "unit": unit})

    reverse = re.search(
        rf"\b{action}\b.{{0,180}}?\bto\b(?P<new>.{{0,150}}?)(?:\bfrom\b|\bversus\b|\bcompared\s+to\b|\bprevious(?:ly)?\b|\bprior\b)",
        evidence,
        re.I | re.S,
    )
    if reverse:
        numeric = _parse_current_value(reverse.group("new"), record.metric)
        if numeric is not None:
            lo, hi, unit = numeric
            return record.model_copy(update={"low": lo, "high": hi, "midpoint": (lo + hi) / 2, "unit": unit})
    return record


def extract_guidance_facts_hygienic(document: SourceDocument, *, rules_hash: str) -> GuidanceExtractionResult:
    install_binding_patch()
    base = _base_guidance_extract(document, rules_hash=rules_hash)
    records = [
        rebound
        for record in base.records
        if _record_admissible(rebound := _directional_rebind(record))
    ]
    policy = _policy_admissible(base.policy_evidence)
    if any(record.midpoint is not None for record in records):
        policy = None
    return base.model_copy(update={"records": records, "policy_evidence": policy})


def _source_score(record: GuidanceMetricRecord) -> int:
    evidence = record.evidence_span or ""
    filename = PurePosixPath(urlparse(record.source_url).path).name.lower()
    score = 0
    if re.search(r"(?:ex(?:hibit)?[-_]?99|ex99|99[._-]?1|earn|release|press)", filename, re.I):
        score += 6
    if record.explicit_action in {GuidanceAction.RAISE, GuidanceAction.LOWER, GuidanceAction.REAFFIRM}:
        score += 5
    if _DIRECT_FORWARD.search(evidence):
        score += 3
    if _ACTUAL_LOCAL.search(evidence) and not _DIRECT_FORWARD.search(evidence):
        score -= 10
    return score


def dedupe_guidance_records_hygienic(records: list[GuidanceMetricRecord]) -> list[GuidanceMetricRecord]:
    grouped: dict[tuple[tuple[str, str, str], object], list[GuidanceMetricRecord]] = defaultdict(list)
    for record in records:
        rebound = _directional_rebind(record)
        if _record_admissible(rebound):
            grouped[(rebound.comparison_key, rebound.source_timestamp)].append(rebound)

    chosen: list[GuidanceMetricRecord] = []
    for rows in grouped.values():
        raises = [row for row in rows if row.explicit_action is GuidanceAction.RAISE and row.midpoint is not None]
        lowers = [row for row in rows if row.explicit_action is GuidanceAction.LOWER and row.midpoint is not None]
        if raises and not lowers:
            item = max(raises, key=lambda row: (row.midpoint or float("-inf"), _source_score(row), row.source_url))
        elif lowers and not raises:
            item = min(lowers, key=lambda row: (row.midpoint if row.midpoint is not None else float("inf"), -_source_score(row), row.source_url))
        else:
            item = max(rows, key=lambda row: (_source_score(row), row.midpoint is not None, -len(row.evidence_span or ""), row.source_url))
        chosen.append(item)
    return sorted(chosen, key=lambda item: (item.source_timestamp, item.metric.value, item.fiscal_period, item.accounting_basis, item.source_url))


_LEGAL_FILENAME = re.compile(r"^(?:ex(?:hibit)?[-_]?10|ex10|ex(?:hibit)?[-_]?4|ex4)|(?:credit|loan|indenture|employment|purchase)[-_ ]?agreement", re.I)
_LEGAL_DOCUMENT = re.compile(r"\b(?:CREDIT\s+AGREEMENT|LOAN\s+AGREEMENT|INDENTURE|EMPLOYMENT\s+AGREEMENT|SECURITY\s+AGREEMENT)\b", re.I)
_STRONG_EARNINGS_HEADLINE = re.compile(
    r"\b(?:reports?|announces?)\b.{0,140}\b(?:first|second|third|fourth|Q[1-4]|quarter|fiscal)\b.{0,140}\b(?:financial\s+results|results|earnings)\b|"
    r"\b(?:first|second|third|fourth)\s+quarter(?:\s+fiscal\s+(?:20)?\d{2})?\s+(?:financial\s+)?results\b|"
    r"\bfinancial\s+results\s+for\s+(?:the\s+)?(?:quarter|three\s+months|six\s+months|nine\s+months)\b",
    re.I | re.S,
)
_STRONG_FILENAME = re.compile(r"(?:ex(?:hibit)?[-_]?99|ex99|99[._-]?1|earn|release|press)", re.I)


def earnings_document_admissible(document: SourceDocument) -> bool:
    filename = PurePosixPath(urlparse(document.source_url).path).name.lower()
    text = hardened.base_extraction.html_to_text(document.content or "")[:12_000]
    strong_headline = bool(_STRONG_EARNINGS_HEADLINE.search(text))
    if _LEGAL_FILENAME.search(filename):
        return False
    if _LEGAL_DOCUMENT.search(text) and not strong_headline:
        return False
    if document.form in {"10-K", "10-Q"}:
        return strong_headline or not _LEGAL_DOCUMENT.search(text)
    return strong_headline or bool(_STRONG_FILENAME.search(filename))


def extract_sec_catalyst_candidates_hygienic(
    document: SourceDocument,
    *,
    is_biotech: bool = False,
) -> list[ExtractedCatalystCandidate]:
    candidates = _base_catalyst_candidates(document, is_biotech=is_biotech)
    if earnings_document_admissible(document):
        return candidates
    return [candidate for candidate in candidates if candidate.input.event_type != "quarterly_earnings"]
