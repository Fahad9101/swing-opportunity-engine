from __future__ import annotations

import re

from app.domain.guidance_canonical_v1 import GuidancePeriodKind
from app.domain.soe_v1_1 import GuidanceMetric, SourceDocument
from app.services.guidance_evidence_binder import GuidanceEvidenceBindingResult
from app.services.guidance_evidence_binder_v3 import GuidanceEvidenceBinder as StrictV3GuidanceEvidenceBinder


_FULL_YEAR_TOKEN = re.compile(r"\b(?:full[- ]year|FY\s*'?20\d{2})\b", re.I)
_EXPLICIT_QUARTER_TOKEN = re.compile(
    r"\bQ[1-4]\s*(?:FY)?\s*'?20\d{2}\b|"
    r"\b(?:first|second|third|fourth)\s+(?:fiscal\s+)?quarter(?:\s+(?:of\s+)?(?:fiscal(?:\s+year)?\s*)?20\d{2})?\b",
    re.I,
)
_QUARTER_GUIDANCE_HEADER = re.compile(
    r"\bQ(?P<q>[1-4])\s*(?:FY\s*)?'?(?P<year>20\d{2})\s+Guidance\b",
    re.I,
)
_QUARTER_RESULTS_HEADER = re.compile(
    r"\bQ(?P<q>[1-4])\s*(?:FY\s*)?'?(?P<year>20\d{2})\s+(?:Results?|Actuals?)\b",
    re.I,
)
_RUN_RATE_EBITDA = re.compile(r"\brun[- ]rate\s+(?:adjusted\s+|non[- ]GAAP\s+)?EBITDA\b", re.I)
_NAMED_REVENUE_CONTRIBUTION = re.compile(
    r"\brevenue\s+contributions?\s+from\b|"
    r"\b(?:acquisition|acquired\s+(?:business|company)|subsidiary|segment|product|program)\b.{0,100}\brevenue\s+contributions?\b",
    re.I | re.S,
)
_ANNUALIZED_RUN_RATE = re.compile(r"\bannuali[sz]ed\s+run[- ]rate\b", re.I)
_TOTAL_REVENUE_LABEL = re.compile(r"\b(?:total|consolidated|company[- ]wide)\s+(?:net\s+sales|revenue|revenues)\b", re.I)


def _fail(base: GuidanceEvidenceBindingResult, dimension: str, reason: str) -> GuidanceEvidenceBindingResult:
    dimensions = dict(base.dimensions)
    dimensions[dimension] = False
    return GuidanceEvidenceBindingResult(
        accepted=False,
        dimensions=dimensions,
        reasons=tuple([*base.reasons, reason]),
    )


def _semantic_issue_dimension(issue: str) -> str:
    prefix = issue.split(":", 1)[0].strip().lower()
    return {
        "metric": "metric",
        "period": "period",
        "basis": "basis",
        "row": "row",
        "column": "column",
        "issuer": "issuer",
        "role": "column",
        "action": "action",
        "value": "row",
    }.get(prefix, "column")


def _apply_semantic_quarantine(
    base: GuidanceEvidenceBindingResult,
    fact,
) -> GuidanceEvidenceBindingResult:
    """Honor deterministic pre-binder ownership diagnostics without re-parsing.

    The semantic ownership stage is responsible for discovering and normalizing
    generic defects. Strict-v4 remains the final fail-closed admission verifier:
    any unresolved ownership issue recorded on the typed fact is rejected here.
    """
    issues = tuple(str(item) for item in (fact.metadata or {}).get("semantic_ownership_issues", []))
    result = base
    for issue in issues:
        result = _fail(
            result,
            _semantic_issue_dimension(issue),
            f"semantic-v1: {issue}",
        )
    return result


def _period_from_fact(fact) -> str:
    return (fact.fiscal_period or "").upper().replace(" ", "")


def _selected_value_window(fact, before: int = 240, after: int = 180) -> str:
    evidence = fact.provenance[0].evidence
    text = evidence.full_text or ""
    if evidence.value_start is None:
        pivot = evidence.metric_start if evidence.metric_start is not None else 0
    else:
        pivot = evidence.value_start
    end = evidence.value_end if evidence.value_end is not None else pivot
    return text[max(0, pivot - before):min(len(text), end + after)]


def _full_year_owns_selected_quarter_value(fact) -> bool:
    """Return True when the selected value is explicitly owned by full-year guidance.

    Quarter documents often contain both quarterly and annual guidance. The mere
    presence of both is valid. What is invalid is serializing a value as QxFYyyyy
    when the nearest ownership phrase says 'full year ... <metric> guidance' and
    no intervening explicit quarter rebinds the value.
    """
    if fact.period_kind is not GuidancePeriodKind.QUARTER:
        return False
    evidence = fact.provenance[0].evidence
    text = evidence.full_text or ""
    if evidence.value_start is None:
        return False
    left = text[max(0, evidence.value_start - 260):evidence.value_start]
    full_year_matches = list(_FULL_YEAR_TOKEN.finditer(left))
    if not full_year_matches:
        return False
    nearest = full_year_matches[-1]
    ownership = left[nearest.start():]
    if _EXPLICIT_QUARTER_TOKEN.search(ownership[nearest.end() - nearest.start():]):
        return False
    metric_label = (evidence.metric_text or "").strip()
    if metric_label and re.search(re.escape(metric_label), ownership, re.I):
        return True
    metric_patterns = {
        GuidanceMetric.REVENUE: r"\b(?:total\s+)?(?:revenue|revenues|net\s+sales)\b",
        GuidanceMetric.EPS: r"\b(?:adjusted\s+|non[- ]GAAP\s+|GAAP\s+)?(?:EPS|earnings\s+per\s+share)\b",
        GuidanceMetric.EBITDA: r"\b(?:adjusted\s+|non[- ]GAAP\s+)?EBITDA\b",
        GuidanceMetric.FCF: r"\b(?:adjusted\s+)?(?:free\s+cash\s+flow|FCF)\b",
        GuidanceMetric.GROSS_MARGIN: r"\bgross(?:\s+profit)?\s+margin\b",
        GuidanceMetric.OPERATING_MARGIN: r"\boperating\s+margin\b",
    }
    pattern = metric_patterns.get(fact.metric)
    return bool(pattern and re.search(pattern, ownership, re.I))


def _quarter_results_column_mismatch(fact, text: str) -> bool:
    if fact.period_kind is not GuidancePeriodKind.QUARTER:
        return False
    guidance_periods = {
        f"Q{m.group('q')}FY{m.group('year')}".upper()
        for m in _QUARTER_GUIDANCE_HEADER.finditer(text)
    }
    results_periods = {
        f"Q{m.group('q')}FY{m.group('year')}".upper()
        for m in _QUARTER_RESULTS_HEADER.finditer(text)
    }
    selected = _period_from_fact(fact)
    if selected not in results_periods:
        return False
    return bool(guidance_periods and selected not in guidance_periods)


class GuidanceEvidenceBinder:
    """Strict-v4 binder: closes residual period/entity/column ownership gaps.

    V4 is deliberately additive to strict-v3. It does not reinterpret frozen
    investment logic; it only prevents non-comparable evidence from entering the
    canonical guidance ledger.
    """

    DIMENSIONS = StrictV3GuidanceEvidenceBinder.DIMENSIONS

    def __init__(self) -> None:
        self._v3 = StrictV3GuidanceEvidenceBinder()

    def bind(self, fact, document: SourceDocument) -> GuidanceEvidenceBindingResult:
        base = self._v3.bind(fact, document)
        evidence = fact.provenance[0].evidence
        text = evidence.full_text or ""
        local = _selected_value_window(fact)

        semantic = _apply_semantic_quarantine(base, fact)
        if not semantic.accepted and semantic.reasons != base.reasons:
            return semantic

        if _full_year_owns_selected_quarter_value(fact):
            return _fail(base, "period", "period-v4: selected value is explicitly owned by full-year guidance, not the quarter")

        if _quarter_results_column_mismatch(fact, text):
            return _fail(base, "column", "column-v4: selected quarter is a results/comparison column, not the guidance column")

        if fact.metric is GuidanceMetric.EBITDA and _RUN_RATE_EBITDA.search(local):
            return _fail(base, "period", "period-v4: run-rate EBITDA is not period-level issuer EBITDA guidance")

        if fact.metric is GuidanceMetric.REVENUE:
            metric_text = evidence.metric_text or ""
            if (
                (_NAMED_REVENUE_CONTRIBUTION.search(local) or _ANNUALIZED_RUN_RATE.search(local))
                and not _TOTAL_REVENUE_LABEL.search(metric_text)
            ):
                return _fail(base, "issuer", "issuer-v4: named-business revenue contribution/run-rate is not consolidated issuer revenue guidance")

        return base
