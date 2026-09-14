from __future__ import annotations

import re

from app.domain.guidance_canonical_v1 import GuidancePeriodKind
from app.domain.soe_v1_1 import GuidanceMetric, SourceDocument
from app.services.guidance_evidence_binder import GuidanceEvidenceBindingResult
from app.services.guidance_evidence_binder_v2 import GuidanceEvidenceBinder as StrictV2GuidanceEvidenceBinder


_QUARTER_ENDED = re.compile(
    r"\b(?:for\s+the\s+)?quarter\s+ended\s+[A-Za-z]+\s+\d{1,2},?\s*20\d{2}\b",
    re.I,
)
_GUIDANCE_HEADING = re.compile(
    r"\b(?:raising|maintaining|updated|updating|initial|reaffirming)?\s*"
    r"(?:FY\s*)?(?P<year>20\d{2})\s+(?:financial\s+)?guidance\b",
    re.I,
)
_YEAR_ENDED_RESULTS = re.compile(
    r"\bYear\s+Ended\s+[A-Za-z]+\s+\d{1,2},?\s*20\d{2}\b.{0,220}"
    r"\b(?:revenues?|net\s+sales|adjusted\s+EBITDA|EBITDA|EPS|earnings\s+per\s+share)\b",
    re.I | re.S,
)
_REALIZED_QUARTER_PERFORMANCE = re.compile(
    r"\bPerformance\s+for\s+the\s+(?:first|second|third|fourth)\s+(?:fiscal\s+)?quarter\b.{0,260}"
    r"\b(?:net\s+sales|revenues?|adjusted\s+EBITDA|EBITDA)\b.{0,100}"
    r"\b(?:increased|decreased|grew|declined|rose|fell|to)\b",
    re.I | re.S,
)
_PRELIMINARY_RESULTS = re.compile(
    r"\bpreliminary,?\s+unaudited\s+(?:results|(?:first|second|third|fourth)\s+quarter|full[- ]year)\b",
    re.I,
)
_TRANSACTION_EPS_ACCRETION = re.compile(
    r"\b(?:transaction|acquisition)\b.{0,180}\b(?:EPS|earnings\s+per\s+share)\s+accret(?:ion|ive)\b|"
    r"\b(?:EPS|earnings\s+per\s+share)\s+accret(?:ion|ive)\b.{0,180}\b(?:transaction|acquisition)\b",
    re.I | re.S,
)
_TRANSACTION_EBITDA_ASSUMPTION = re.compile(
    r"\b(?:projected\s+20\d{2}\s+EBITDA\s+multiple|\d+(?:\.\d+)?x\s+projected\s+20\d{2}\s+EBITDA|"
    r"run[- ]rate\s+(?:cost\s+)?synerg(?:y|ies))\b",
    re.I,
)
_TAM_REFERENCE = re.compile(r"\b(?:TAM|total\s+addressable\s+market)\b", re.I)
_CONTRACT_CONTRIBUTION = re.compile(
    r"\b(?:agreement|contract)\b.{0,220}\b(?:contribut(?:e|es|ed|ing)|annual\s+revenue)\b",
    re.I | re.S,
)
_PORTFOLIO_PRUNING_AMOUNT = re.compile(
    r"\b(?:prun(?:e|ed|ing)|business\s+exits?|non[- ]strategic\s+revenue)\b.{0,120}"
    r"(?:\$\s*)?\d[\d,.]*(?:\s*(?:million|billion|mm|bn|m|b))?\b|"
    r"(?:\$\s*)?\d[\d,.]*(?:\s*(?:million|billion|mm|bn|m|b))?\b.{0,120}"
    r"\b(?:prun(?:e|ed|ing)|business\s+exits?|non[- ]strategic\s+revenue)\b",
    re.I | re.S,
)


def _fail(base: GuidanceEvidenceBindingResult, dimension: str, reason: str) -> GuidanceEvidenceBindingResult:
    dimensions = dict(base.dimensions)
    dimensions[dimension] = False
    return GuidanceEvidenceBindingResult(
        accepted=False,
        dimensions=dimensions,
        reasons=tuple([*base.reasons, reason]),
    )


def _window(fact, *, before: int = 260, after: int = 220) -> str:
    evidence = fact.provenance[0].evidence
    text = evidence.full_text or ""
    start = evidence.metric_start if evidence.metric_start is not None else evidence.value_start
    end = evidence.value_end if evidence.value_end is not None else evidence.metric_end
    if start is None:
        start = 0
    if end is None:
        end = start
    return text[max(0, start - before):min(len(text), end + after)]


def _prefix_to_value(fact, width: int = 650) -> str:
    evidence = fact.provenance[0].evidence
    text = evidence.full_text or ""
    pivot = evidence.value_start if evidence.value_start is not None else evidence.metric_start
    if pivot is None:
        return ""
    return text[max(0, pivot - width):pivot]


def _period_year(fiscal_period: str) -> int | None:
    match = re.search(r"FY(20\d{2})", fiscal_period or "", re.I)
    return int(match.group(1)) if match else None


def _nearest_guidance_heading_year(fact) -> int | None:
    matches = list(_GUIDANCE_HEADING.finditer(_prefix_to_value(fact)))
    if not matches:
        return None
    return int(matches[-1].group("year"))


def _actual_result_contamination(fact) -> bool:
    local = _window(fact, before=260, after=120)
    if _YEAR_ENDED_RESULTS.search(local):
        return True
    if _REALIZED_QUARTER_PERFORMANCE.search(local):
        return True
    if _PRELIMINARY_RESULTS.search(local):
        # Preliminary/unaudited result announcements are realized or near-realized
        # observations, not management guidance, even when the release says a
        # reported geography/component "is expected to be approximately" X.
        return True
    return False


class GuidanceEvidenceBinder:
    """Final semantic-ownership binder layered on strict-v2.

    V3 does not alter any SOE decision rule. It only prevents non-comparable
    evidence from entering the canonical ledger: realized results, comparison
    base years, transaction/accretion assumptions, TAM/contract subcomponents,
    and quarter-ended values misbound as full-year guidance all fail closed.
    """

    DIMENSIONS = StrictV2GuidanceEvidenceBinder.DIMENSIONS

    def __init__(self) -> None:
        self._v2 = StrictV2GuidanceEvidenceBinder()

    def bind(self, fact, document: SourceDocument) -> GuidanceEvidenceBindingResult:
        base = self._v2.bind(fact, document)
        if not base.accepted:
            return base

        local = _window(fact)

        # A statement explicitly describing a quarter-ended outlook cannot own a
        # full-year fact. The fiscal year in the date is not the guidance period.
        if fact.period_kind is GuidancePeriodKind.FULL_YEAR and _QUARTER_ENDED.search(local):
            return _fail(base, "period", "period-v3: quarter-ended outlook cannot be bound as full-year guidance")

        # Headings such as "Raising 2026 Guidance (all comparisons against the
        # full year 2025)" establish 2026 as the value-column owner. A nearby
        # comparison-base year must not become the fact period.
        fact_year = _period_year(fact.fiscal_period)
        heading_year = _nearest_guidance_heading_year(fact)
        if fact.period_kind is GuidancePeriodKind.FULL_YEAR and fact_year and heading_year and fact_year != heading_year:
            return _fail(base, "period", "period-v3: comparison/base year does not match the owning guidance heading")

        if _actual_result_contamination(fact):
            return _fail(base, "action", "action-v3: realized/preliminary financial result is not forward guidance")

        if fact.metric is GuidanceMetric.EPS and _TRANSACTION_EPS_ACCRETION.search(local):
            return _fail(base, "row", "row-v3: transaction EPS accretion is not issuer EPS guidance")

        if fact.metric is GuidanceMetric.EBITDA and _TRANSACTION_EBITDA_ASSUMPTION.search(local):
            return _fail(base, "row", "row-v3: transaction multiple/synergy assumption is not issuer EBITDA guidance")

        if fact.metric is GuidanceMetric.REVENUE and _TAM_REFERENCE.search(local):
            return _fail(base, "row", "row-v3: TAM/market-size value is not issuer revenue guidance")

        if fact.metric is GuidanceMetric.REVENUE and _CONTRACT_CONTRIBUTION.search(local):
            if not re.search(r"\b(?:total|consolidated)\s+(?:revenue|revenues|net\s+sales)\b", local, re.I):
                return _fail(base, "row", "row-v3: contract/agreement contribution is not consolidated revenue guidance")

        if fact.metric is GuidanceMetric.REVENUE and _PORTFOLIO_PRUNING_AMOUNT.search(local):
            # Preserve genuine issuer outlooks that merely explain YoY growth
            # excluding a divestiture; reject amounts whose own semantic role is
            # pruning/business exits/non-strategic revenue.
            evidence = fact.provenance[0].evidence
            text = evidence.full_text or ""
            value_start = evidence.value_start if evidence.value_start is not None else 0
            value_end = evidence.value_end if evidence.value_end is not None else value_start
            tight = text[max(0, value_start - 110):min(len(text), value_end + 110)]
            if re.search(r"\b(?:prun(?:e|ed|ing)|business\s+exits?|non[- ]strategic\s+revenue)\b", tight, re.I):
                return _fail(base, "row", "row-v3: portfolio-pruning amount is not consolidated revenue guidance")

        return base
