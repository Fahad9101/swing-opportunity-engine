from __future__ import annotations

import re

from app.domain.guidance_canonical_v1 import GuidancePeriodKind
from app.domain.soe_v1_1 import GuidanceAction, GuidanceMetric, SourceDocument
from app.services.guidance_evidence_binder import (
    GuidanceEvidenceBinder as StrictV1GuidanceEvidenceBinder,
    GuidanceEvidenceBindingResult,
)


_ACCOUNTING_LITERATURE = re.compile(
    r"\b(?:FASB|ASU\s+(?:No\.?\s*)?20\d{2}[-–]\d+|Accounting\s+Standards?\s+Update|Topic\s+\d{3})\b",
    re.I,
)
_RPO_SCHEDULE = re.compile(
    r"\b(?:remaining\s+performance\s+obligations?|performance\s+obligations\s+associated\s+with\s+contracts|"
    r"recognize\s+(?:net\s+sales|revenues?)\s+(?:relating\s+to|as)\s+(?:existing\s+)?(?:performance\s+)?obligations?|"
    r"contracts?\s+exceeding\s+one\s+year)\b",
    re.I,
)
_THIRD_PARTY_FORECAST = re.compile(
    r"\b(?:according\s+to\s+[A-Z][A-Za-z&. -]{2,40}|IBISWorld|industry\s+(?:forecast|estimate)|"
    r"market\s+for\s+.{0,100}\bexpected\s+(?:total\s+)?revenue)\b",
    re.I | re.S,
)
_RATE_CASE = re.compile(
    r"\b(?:general\s+rate\s+case|rate\s+case|request(?:ed|ing)?\s+to\s+increase\s+revenues?\s+by|"
    r"rates?\s+anticipated\s+to\s+become\s+effective)\b",
    re.I,
)
_RPO_OR_REGULATORY = re.compile(
    rf"(?:{_RPO_SCHEDULE.pattern})|(?:{_RATE_CASE.pattern})",
    re.I | re.S,
)
_GENERIC_QUARTER = re.compile(
    r"\b(?:first|second|third|fourth)\s+(?:fiscal\s+)?quarter\b|"
    r"\bquarter\s+(?:of\s+)?(?:fiscal\s+year\s+)?20\d{2}\b|"
    r"\bQ[1-4]\s*(?:FY)?\s*'?20\d{2}\b",
    re.I,
)
_EXPLICIT_QUARTER = re.compile(
    r"\bQ[1-4]\s*(?:FY)?\s*'?20\d{2}\b|"
    r"\b(?:first|second|third|fourth)\s+(?:fiscal\s+)?quarter(?:\s+(?:of\s+)?(?:fiscal(?:\s+year)?\s*)?20\d{2}|\s+ending\s+[A-Za-z]+\s+\d{1,2},?\s*20\d{2})",
    re.I,
)
_UPDATE_TIMING_QUARTER = re.compile(
    r"\b(?:reviewing|reassessing|evaluating)\b.{0,220}\b(?:guidance|outlook)\b.{0,220}"
    r"\b(?:update|announcement)\b.{0,60}\b(?:during|in)\s+(?:the\s+)?"
    r"(?:first|second|third|fourth)\s+quarter\b",
    re.I | re.S,
)
_ACTUAL_GUIDANCE_TABLE = re.compile(
    r"\bActual\s+FY\s*(?P<year>20\d{2})\s+Results\b.{0,500}\b(?:FY\s*)?20\d{2}\s+Guidance\s+Range\b|"
    r"\b(?:FY\s*)?20\d{2}\s+Guidance\s+Range\b.{0,500}\bActual\s+FY\s*(?P<year2>20\d{2})\s+Results\b",
    re.I | re.S,
)
_HISTORICAL_CHANGE = re.compile(
    r"\b(?:increased|decreased|declined|grew)\b.{0,120}\b(?:year[- ]over[- ]year|sequential(?:ly)?|compared\s+(?:with|to))\b|"
    r"\b(?:year[- ]over[- ]year|sequential(?:ly)?)\b.{0,120}\b(?:increased|decreased|declined|grew)\b",
    re.I | re.S,
)
_OPERATIONAL_LOWER = re.compile(
    r"\blower\s+(?:fuel\s+costs?|activity|volumes?|pricing|costs?|demand|production|revenue)\b",
    re.I,
)
_LONG_TERM_TARGET = re.compile(
    r"\blong[- ]term\b.{0,80}\b(?:target|goal|revenue|sales|EBITDA|EPS|FCF)\b|"
    r"\b(?:target|goal)\b.{0,80}\blong[- ]term\b",
    re.I | re.S,
)
_BASE_YEAR = re.compile(r"\b(?:CAGR\s+)?base\s+year\b", re.I)
_COMMODITY_SUFFIX = re.compile(r"^\s*(?:/\s*)?(?:Bbl|WTI|MMBtu|Henry\s+Hub)\b", re.I)
_SUBCOMPONENT_REVENUE = re.compile(
    r"\brevenue\s+from\s+(?:the\s+)?(?:new\s+)?(?:acquisitions?|segment|business|project)\b",
    re.I,
)
_QUARTER_GUIDANCE_HEADER = re.compile(
    r"\b(?:Q[1-4]\s+(?:FY\s*)?20\d{2}|"
    r"(?:first|second|third|fourth)\s+(?:fiscal\s+)?quarter(?:\s+(?:of\s+)?(?:FY\s*)?20\d{2})?)\s+guidance\b",
    re.I,
)
_FULL_YEAR_GUIDANCE_HEADER = re.compile(
    r"\b(?:FY\s*20\d{2}|full[- ]year(?:\s+20\d{2})?)\s+guidance\b",
    re.I,
)
_METRIC_LABEL = re.compile(
    r"\b(?:revenue|revenues|net\s+sales|EPS|earnings\s+per\s+share|EBITDA|free\s+cash\s+flow|FCF|"
    r"gross\s+margin|operating\s+margin)\b",
    re.I,
)
_TABLE_VALUE_TOKEN = re.compile(
    r"(?:\$\s*-?\d[\d,.]*(?:\s*(?:million|billion|thousand|mm|bn|m|b))?|"
    r"-?\d+(?:\.\d+)?\s*%)",
    re.I,
)

_METRIC_AFTER_VALUE: list[tuple[GuidanceMetric, re.Pattern[str]]] = [
    (GuidanceMetric.FCF, re.compile(r"^\s*(?:of\s+)?(?:adjusted\s+)?(?:free\s+cash\s+flow|FCF)\b", re.I)),
    (GuidanceMetric.EBITDA, re.compile(r"^\s*(?:of\s+)?(?:adjusted\s+|non[- ]GAAP\s+)?EBITDA\b", re.I)),
    (GuidanceMetric.EPS, re.compile(r"^\s*(?:of\s+)?(?:adjusted\s+|non[- ]GAAP\s+|GAAP\s+)?(?:diluted\s+)?(?:EPS|earnings\s+per\s+share)\b", re.I)),
    (GuidanceMetric.REVENUE, re.compile(r"^\s*(?:of\s+)?(?:total\s+)?(?:revenue|revenues|net\s+sales)\b", re.I)),
]


def _fail(base: GuidanceEvidenceBindingResult, dimension: str, reason: str) -> GuidanceEvidenceBindingResult:
    dimensions = dict(base.dimensions)
    dimensions[dimension] = False
    return GuidanceEvidenceBindingResult(
        accepted=False,
        dimensions=dimensions,
        reasons=tuple([*base.reasons, reason]),
    )


def _local_value_context(fact, radius: int = 180) -> str:
    evidence = fact.provenance[0].evidence
    text = evidence.full_text or ""
    pivot = evidence.value_start
    if pivot is None:
        pivot = evidence.metric_start if evidence.metric_start is not None else 0
    return text[max(0, pivot - radius):min(len(text), pivot + radius)]


def _selected_suffix(fact, width: int = 100) -> str:
    evidence = fact.provenance[0].evidence
    text = evidence.full_text or ""
    if evidence.value_end is None:
        return ""
    return text[evidence.value_end:min(len(text), evidence.value_end + width)]


def _selected_prefix(fact, width: int = 120) -> str:
    evidence = fact.provenance[0].evidence
    text = evidence.full_text or ""
    if evidence.value_start is None:
        return ""
    return text[max(0, evidence.value_start - width):evidence.value_start]


def _period_year(fiscal_period: str) -> int | None:
    match = re.search(r"FY(20\d{2})", fiscal_period or "", re.I)
    return int(match.group(1)) if match else None


def _mixed_quarter_full_year_guidance_table(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", text or "").strip()
    quarter_headers = list(_QUARTER_GUIDANCE_HEADER.finditer(normalized))
    full_year_headers = list(_FULL_YEAR_GUIDANCE_HEADER.finditer(normalized))
    if not quarter_headers or not full_year_headers:
        return False

    for quarter in quarter_headers:
        for full_year in full_year_headers:
            first, second = sorted((quarter, full_year), key=lambda match: match.start())
            between = normalized[first.end():second.start()]
            # Flattened SEC/XBRL table text may serialize the period headers before
            # OR after the metric/value rows. Adjacent quarter/FY headers with no
            # metric between them are therefore treated as a column-header pair.
            # If a dense metric/value neighborhood exists on either side, row×column
            # ownership is not deterministic and the facts must fail closed.
            if len(between) <= 40 and not _METRIC_LABEL.search(between):
                neighborhood = normalized[
                    max(0, first.start() - 500):min(len(normalized), second.end() + 500)
                ]
                numeric_count = len(_TABLE_VALUE_TOKEN.findall(neighborhood))
                metric_count = len(_METRIC_LABEL.findall(neighborhood))
                if numeric_count >= 4 and metric_count >= 1:
                    return True
    return False


class GuidanceEvidenceBinder:
    """Strict-v2 semantic binder layered on strict-v1.

    V1 proves structural metric×period×basis×row×column×issuer×action
    consistency. V2 adds negative semantic ownership tests learned from
    the exhaustive Phase 1.1E population audit. Any ambiguity fails closed.
    """

    DIMENSIONS = StrictV1GuidanceEvidenceBinder.DIMENSIONS

    def __init__(self) -> None:
        self._v1 = StrictV1GuidanceEvidenceBinder()

    def bind(self, fact, document: SourceDocument) -> GuidanceEvidenceBindingResult:
        evidence = fact.provenance[0].evidence
        text = evidence.full_text or ""
        base = self._v1.bind(fact, document)

        # Document-level row/column ambiguity is evaluated even when strict-v1
        # has already rejected another dimension so the quarantine retains the
        # true mixed-period-table defect explicitly.
        if _mixed_quarter_full_year_guidance_table(text):
            return _fail(base, "column", "column-v2: flattened quarter/full-year table is ambiguous")

        if not base.accepted:
            return base

        local = _local_value_context(fact)
        suffix = _selected_suffix(fact)
        prefix = _selected_prefix(fact)

        period_blob = f"{evidence.period_text or ''} {local}"
        if fact.period_kind is GuidancePeriodKind.QUARTER and not _EXPLICIT_QUARTER.search(period_blob):
            return _fail(base, "period", "period-v2: quarter fact lacks an explicit quarter identifier")
        if (
            fact.period_kind is GuidancePeriodKind.FULL_YEAR
            and _GENERIC_QUARTER.search(local)
            and not _UPDATE_TIMING_QUARTER.search(local)
        ):
            if not re.search(r"\b(?:full[- ]year|fiscal\s+year|FY\s*20\d{2})\b", local, re.I):
                return _fail(base, "period", "period-v2: quarterly context cannot supply a full-year fact")
        year = _period_year(fact.fiscal_period)
        if year is not None and year > document.source_timestamp.year + 3:
            return _fail(base, "period", "period-v2: remote-horizon year is not near-term issuer guidance")

        if _ACCOUNTING_LITERATURE.search(local) and re.search(r"\bguidance\b", local, re.I):
            return _fail(base, "action", "action-v2: accounting-standard guidance is not company financial guidance")

        if _RPO_OR_REGULATORY.search(local):
            return _fail(base, "action", "action-v2: contractual recognition or regulatory request is not issuer financial guidance")

        if _THIRD_PARTY_FORECAST.search(local):
            return _fail(base, "issuer", "issuer-v2: third-party market forecast is not issuer guidance")

        table_match = _ACTUAL_GUIDANCE_TABLE.search(text)
        if table_match:
            actual_year = table_match.group("year") or table_match.group("year2")
            if actual_year and fact.fiscal_period.upper() == f"FY{actual_year}":
                return _fail(base, "column", "column-v2: selected value belongs to the Actual FY Results column")

        if _HISTORICAL_CHANGE.search(local) and not re.search(r"\b(?:guidance|outlook|forecast)\b.{0,90}$", prefix, re.I):
            return _fail(base, "action", "action-v2: realized sequential/YoY result is not forward guidance")

        if fact.explicit_action is GuidanceAction.LOWER and _OPERATIONAL_LOWER.search(local):
            if not re.search(r"\b(?:lower(?:ed|ing)?|reduc(?:ed|ing)?|cut)\b.{0,90}\b(?:guidance|outlook|forecast)\b", local, re.I):
                return _fail(base, "action", "action-v2: operational 'lower' language is not a guidance cut")

        if _LONG_TERM_TARGET.search(local) and not re.search(r"\b(?:full[- ]year|fiscal\s+year|FY\s*20\d{2})\b", local, re.I):
            return _fail(base, "period", "period-v2: long-term target is not the selected fiscal-period guidance")
        if _BASE_YEAR.search(local):
            return _fail(base, "action", "action-v2: CAGR/base-year datum is historical, not current guidance")

        if _COMMODITY_SUFFIX.search(suffix):
            return _fail(base, "row", "row-v2: selected value is a commodity-price assumption")

        for owner_metric, pattern in _METRIC_AFTER_VALUE:
            if owner_metric is not fact.metric and pattern.search(suffix):
                return _fail(base, "row", f"row-v2: selected value is owned by following {owner_metric.value} label")

        if fact.metric is GuidanceMetric.REVENUE and _SUBCOMPONENT_REVENUE.search(local):
            if not re.search(r"\b(?:total|consolidated)\s+(?:net\s+sales|revenue|revenues)\b", local, re.I):
                return _fail(base, "row", "row-v2: revenue subcomponent is not consolidated revenue guidance")

        return base
