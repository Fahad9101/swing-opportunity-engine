from __future__ import annotations

import re
from dataclasses import dataclass

from app.domain.guidance_canonical_v1 import (
    GuidanceFactRole,
    GuidanceInvariantCode,
    GuidanceInvariantViolation,
    GuidancePeriodKind,
    GuidanceScopeKind,
    TypedGuidanceFact,
    ValidatedGuidanceFact,
)
from app.domain.soe_v1_1 import GuidanceAction, GuidanceMetric, SourceDocument


# The binder is deliberately conservative. Raw extraction may nominate a value,
# but a fact is not eligible for the canonical ledger until every dimension below
# can be tied to the same local piece of primary-source evidence.
_GUIDANCE_SIGNAL = re.compile(
    r"\b(?:guidance|outlook|forecast|expects?|expected|anticipat(?:e|es|ed|ing)|"
    r"project(?:s|ed|ing)\s+(?:full[- ]year|fiscal|annual|quarterly?|revenue|revenues|sales|EPS|earnings|EBITDA|free\s+cash\s+flow|FCF|gross\s+margin|operating\s+margin)|"
    r"provid(?:e|es|ed|ing)|issu(?:e|es|ed|ing)|"
    r"reaffirm(?:s|ed|ing)?|reiterat(?:e|es|ed|ing)|maintain(?:s|ed|ing)?|"
    r"rais(?:e|es|ed|ing)|lower(?:s|ed|ing)?|reduc(?:e|es|ed|ing)|withdraw(?:s|n|ing)?)\b",
    re.I,
)
_HISTORICAL_RESULT = re.compile(
    r"\b(?:financial\s+(?:results|highlights)|results?)\b|"
    r"\b(?:during|for)\s+the\s+(?:three|six|nine|twelve)\s+months?\s+ended\b|"
    r"\b(?:year|quarter)\s+ended\b|"
    r"\b(?:reported|generated|delivered|achieved|realized)\b|"
    r"\b(?:increase|decrease|increased|decreased|grew|declined)\b.{0,120}\b(?:from|compared\s+(?:with|to))\b",
    re.I | re.S,
)
_HISTORICAL_VS_GUIDANCE = re.compile(
    r"\b(?:was|were)\b.{0,160}\b(?:above|below|within|at|better\s+than|worse\s+than)\b"
    r".{0,120}\bguidance\s+range\b",
    re.I | re.S,
)

_METRIC_PATTERNS: dict[GuidanceMetric, re.Pattern[str]] = {
    GuidanceMetric.GROSS_MARGIN: re.compile(r"\b(?:adjusted\s+|non[- ]GAAP\s+)?gross(?:\s+profit)?\s+margin\b", re.I),
    GuidanceMetric.OPERATING_MARGIN: re.compile(r"\b(?:adjusted\s+|non[- ]GAAP\s+)?operating\s+margin\b", re.I),
    GuidanceMetric.FCF: re.compile(r"\b(?:adjusted\s+)?(?:free\s+cash\s+flow|FCF)\b", re.I),
    GuidanceMetric.EPS: re.compile(r"\b(?:adjusted\s+|non[- ]GAAP\s+|GAAP\s+)?(?:diluted\s+)?(?:EPS|earnings\s+per\s+(?:common\s+)?share|per\s+diluted\s+share)\b", re.I),
    GuidanceMetric.EBITDA: re.compile(r"\b(?:adjusted\s+|non[- ]GAAP\s+)?EBITDA\b(?!\s+margin)", re.I),
    GuidanceMetric.REVENUE: re.compile(r"\b(?:total\s+(?:product\s+)?revenue|consolidated\s+revenue|net\s+sales|revenues?|revenue)\b", re.I),
}
_ALL_METRIC_PATTERNS = tuple(_METRIC_PATTERNS.items())

_QUARTER_PATTERNS = (
    re.compile(r"\bQ(?P<q>[1-4])\s*(?:FY)?\s*'?(?P<year>20\d{2})\b", re.I),
    re.compile(
        r"\b(?P<word>first|second|third|fourth)\s+(?:fiscal\s+)?quarter"
        r"(?:\s+(?:of\s+)?(?:fiscal(?:\s+year)?\s*)?(?P<year1>20\d{2})"
        r"|\s+ending\s+[A-Za-z]+\s+\d{1,2},?\s*(?P<year2>20\d{2}))",
        re.I,
    ),
)
_FULL_YEAR_PATTERN = re.compile(
    r"\b(?:FY|fiscal(?:\s+year)?|full[- ]year)\s*'?(?P<year>20\d{2})\b"
    r"|\b(?P<year2>20\d{2})\s+(?:full[- ]year|annual)\b",
    re.I,
)
_QUARTER_WORD = {"first": "1", "second": "2", "third": "3", "fourth": "4"}

_MONEY_RANGE = re.compile(
    r"\$?\s*-?\d[\d,]*(?:\.\d+)?\s*(?:million|billion|thousand|mm|bn|m|b)?\s*"
    r"(?:-|–|—|to|through)\s*\$?\s*-?\d[\d,]*(?:\.\d+)?\s*"
    r"(?:million|billion|thousand|mm|bn|m|b)?",
    re.I,
)
_NUMBER_TOKEN = re.compile(r"\$?\s*-?\d[\d,]*(?:\.\d+)?\s*(?:%|million|billion|thousand|mm|bn|m|b)?", re.I)

_ACTION_SOURCE_PATTERNS: dict[GuidanceAction, re.Pattern[str]] = {
    GuidanceAction.INITIATE: re.compile(r"\b(?:issu(?:e|es|ed|ing)|provid(?:e|es|ed|ing)|initiat(?:e|es|ed|ing)|expects?)\b", re.I),
    GuidanceAction.RAISE: re.compile(r"\b(?:rais(?:e|es|ed|ing)|increas(?:e|es|ed|ing)|boost(?:s|ed|ing)?)\b", re.I),
    GuidanceAction.LOWER: re.compile(r"\b(?:lower(?:s|ed|ing)?|reduc(?:e|es|ed|ing)|cut(?:s|ting)?)\b", re.I),
    GuidanceAction.REAFFIRM: re.compile(r"\b(?:reaffirm(?:s|ed|ing)?|reiterat(?:e|es|ed|ing)|maintain(?:s|ed|ing)?|affirm(?:s|ed|ing)?)\b", re.I),
    GuidanceAction.WITHDRAW: re.compile(r"\b(?:withdraw(?:s|n|ing)?|suspend(?:s|ed|ing)?|no\s+longer\s+(?:provid(?:e|ing)|issu(?:e|ing)))\b", re.I),
}

_BASIS_METRICS = {
    GuidanceMetric.EPS,
    GuidanceMetric.EBITDA,
    GuidanceMetric.FCF,
    GuidanceMetric.GROSS_MARGIN,
    GuidanceMetric.OPERATING_MARGIN,
}


@dataclass(frozen=True)
class GuidanceEvidenceBindingResult:
    accepted: bool
    dimensions: dict[str, bool]
    reasons: tuple[str, ...]

    def as_quarantined(self, fact: TypedGuidanceFact) -> ValidatedGuidanceFact:
        violations = [
            GuidanceInvariantViolation(
                code=GuidanceInvariantCode.AMBIGUOUS_EVIDENCE,
                message=reason,
            )
            for reason in self.reasons
        ]
        return ValidatedGuidanceFact(fact=fact, violations=violations, accepted=False)


def _norm(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip().lower()


def _sentence_window(text: str, start: int, end: int) -> str:
    left_candidates = [text.rfind(token, 0, start) for token in (".", ";", "\n", "•", "▪", "●")]
    left = max(left_candidates) + 1
    right_candidates = [pos for token in (".", ";", "\n", "•", "▪", "●") if (pos := text.find(token, end)) >= 0]
    right = min(right_candidates) if right_candidates else len(text)
    return text[left:right].strip()


def _periods(text: str) -> set[str]:
    found: set[str] = set()
    for pattern in _QUARTER_PATTERNS:
        for match in pattern.finditer(text):
            if match.groupdict().get("q"):
                found.add(f"Q{match.group('q')}FY{match.group('year')}")
            else:
                year = match.groupdict().get("year1") or match.groupdict().get("year2")
                if year:
                    found.add(f"Q{_QUARTER_WORD[match.group('word').lower()]}FY{year}")
    for match in _FULL_YEAR_PATTERN.finditer(text):
        year = match.group("year") or match.group("year2")
        found.add(f"FY{year}")
    return found


def _metric_mentions(text: str) -> list[tuple[int, int, GuidanceMetric]]:
    mentions: list[tuple[int, int, GuidanceMetric]] = []
    for metric, pattern in _ALL_METRIC_PATTERNS:
        for match in pattern.finditer(text):
            # Revenue embedded in an expense label is never a revenue row owner.
            if metric is GuidanceMetric.REVENUE:
                local = text[max(0, match.start() - 24):min(len(text), match.end() + 12)]
                if re.search(r"\bcosts?\s+of\s+(?:contract\s+)?revenues?\b", local, re.I):
                    continue
            mentions.append((match.start(), match.end(), metric))
    mentions.sort(key=lambda item: (item[0], -(item[1] - item[0])))
    return mentions


def _metric_dimension(fact: TypedGuidanceFact, text: str) -> tuple[bool, str | None]:
    evidence = fact.provenance[0].evidence
    if evidence.metric_start is None or evidence.metric_end is None or not evidence.metric_text:
        return False, "metric: missing explicit metric span"
    if not (0 <= evidence.metric_start < evidence.metric_end <= len(text)):
        return False, "metric: metric span is outside evidence bounds"
    declared = text[evidence.metric_start:evidence.metric_end]
    if _norm(declared) != _norm(evidence.metric_text):
        return False, "metric: declared metric span does not match bound metric text"
    pattern = _METRIC_PATTERNS[fact.metric]
    if not pattern.search(evidence.metric_text):
        return False, f"metric: bound label {evidence.metric_text!r} does not identify {fact.metric.value}"
    if fact.metric is GuidanceMetric.REVENUE:
        local = text[max(0, evidence.metric_start - 32):min(len(text), evidence.metric_end + 20)]
        if re.search(r"\bcosts?\s+of\s+(?:contract\s+)?revenues?\b", local, re.I):
            return False, "metric: revenue token belongs to cost-of-revenue expense"
    return True, None


def _period_dimension(fact: TypedGuidanceFact, text: str, binding_sentence: str) -> tuple[bool, str | None]:
    evidence = fact.provenance[0].evidence
    if not evidence.period_text:
        return False, "period: missing explicit period evidence"
    if fact.authoritative_period != fact.fiscal_period:
        return False, "period: authoritative period differs from fiscal period"
    sentence_periods = _periods(binding_sentence)
    if fact.period_kind is GuidancePeriodKind.FULL_YEAR and any(item.startswith("Q") for item in sentence_periods):
        return False, "period: quarter evidence cannot be admitted as full-year guidance"
    if fact.period_kind is GuidancePeriodKind.QUARTER and sentence_periods and fact.fiscal_period not in sentence_periods:
        return False, "period: selected quarter is not the quarter stated with the metric/value"
    explicit_periods = _periods(evidence.period_text)
    if explicit_periods and fact.fiscal_period not in explicit_periods:
        return False, "period: bound period text does not resolve to the selected fiscal period"
    # A bare year may support a full-year fact only when the same binding sentence
    # is explicitly annual/full-year guidance, never when it describes a quarter.
    if fact.period_kind is GuidancePeriodKind.FULL_YEAR and not explicit_periods:
        quarter_pattern = re.compile(r"\b(?:first|second|third|fourth)\s+(?:fiscal\s+)?quarter\b", re.I)
        for quarter_match in quarter_pattern.finditer(binding_sentence):
            before = binding_sentence[max(0, quarter_match.start() - 90):quarter_match.start()]
            after = binding_sentence[quarter_match.end():min(len(binding_sentence), quarter_match.end() + 110)]
            # A quarter may describe when management will provide the next update,
            # not the period of the guidance being reviewed (e.g. IOVA). That
            # timing reference must not displace the issuer's FY guidance state.
            if re.search(
                r"\b(?:update|announcement)\b.{0,32}\b(?:during|in)\s+(?:the\s+)?$",
                before,
                re.I,
            ):
                continue
            local = f"{before[-70:]} {after[:90]}"
            if re.search(
                r"\b(?:guidance|outlook|forecast|expects?|expected|revenue|revenues|net\s+sales|EPS|earnings\s+per\s+share|EBITDA|free\s+cash\s+flow|FCF|gross\s+margin|operating\s+margin)\b",
                local,
                re.I,
            ):
                return False, "period: bare year was taken from a quarterly guidance sentence"
    return True, None


def _basis_dimension(fact: TypedGuidanceFact, binding_sentence: str) -> tuple[bool, str | None]:
    if fact.metric not in _BASIS_METRICS:
        return True, None
    basis = (fact.accounting_basis or "UNSPECIFIED").upper()
    metric_text = fact.provenance[0].evidence.metric_text or ""
    local = f"{metric_text} {binding_sentence}"
    has_adjusted = bool(re.search(r"\b(?:adjusted|non[- ]GAAP)\b", local, re.I))
    has_gaap = bool(re.search(r"\bGAAP\b", local, re.I)) and not bool(re.search(r"\bnon[- ]GAAP\b", local, re.I))
    if basis == "ADJUSTED" and not has_adjusted:
        return False, "basis: adjusted/non-GAAP basis is not locally evidenced"
    if basis == "GAAP" and not has_gaap:
        return False, "basis: GAAP basis is not locally evidenced"
    if basis == "UNSPECIFIED" and has_adjusted and fact.metric in {GuidanceMetric.EPS, GuidanceMetric.EBITDA, GuidanceMetric.FCF}:
        return False, "basis: explicit adjusted/non-GAAP evidence was bound as unspecified"
    return True, None


def _row_dimension(fact: TypedGuidanceFact, text: str) -> tuple[bool, str | None]:
    evidence = fact.provenance[0].evidence
    if fact.low is None and fact.high is None:
        return True, None
    if evidence.value_start is None or evidence.value_end is None or not evidence.value_text:
        return False, "row: numeric fact has no explicit value span"
    if not (0 <= evidence.value_start < evidence.value_end <= len(text)):
        return False, "row: value span is outside evidence bounds"
    declared = text[evidence.value_start:evidence.value_end]
    if _norm(declared) != _norm(evidence.value_text):
        return False, "row: declared value span does not match bound value text"
    ms = evidence.metric_start
    me = evidence.metric_end
    if ms is None or me is None:
        return False, "row: metric span unavailable for metric/value ownership"
    if evidence.value_start < me:
        return False, "row: selected value precedes its metric label; ownership is not deterministic"
    if evidence.value_start - me > 240:
        return False, "row: selected value is too distant from its metric label"
    for start, end, metric in _metric_mentions(text):
        if me <= start < evidence.value_start and metric is not fact.metric:
            return False, f"row: value crosses intervening {metric.value} row ownership"
    return True, None


def _column_dimension(fact: TypedGuidanceFact, text: str) -> tuple[bool, str | None]:
    evidence = fact.provenance[0].evidence
    if fact.low is None and fact.high is None:
        return True, None
    vs = evidence.value_start
    if vs is None:
        return False, "column: numeric fact has no value position"

    periods = _periods(text)
    table_markers = bool(re.search(r"\bLow\s+High\b", text, re.I)) or bool(
        re.search(r"\bThree\s+Months\s+Ended\b.{0,140}\bTwelve\s+Months\s+Ended\b", text, re.I | re.S)
    )
    numeric_tokens = list(_NUMBER_TOKEN.finditer(text))
    if table_markers and len(periods) >= 2 and len(numeric_tokens) >= 4:
        return False, "column: flattened multi-period table has no deterministic row×column coordinate"

    if re.search(r"\brespectively\b", text, re.I):
        owners = _metric_mentions(text)
        ranges = list(_MONEY_RANGE.finditer(text))
        if len(owners) >= 2 and len(ranges) >= 2:
            matching_owner_indexes = [idx for idx, (_, _, metric) in enumerate(owners) if metric is fact.metric]
            selected_range_indexes = [idx for idx, match in enumerate(ranges) if match.start() <= vs < match.end()]
            if matching_owner_indexes and selected_range_indexes:
                owner_idx = matching_owner_indexes[-1]
                value_idx = selected_range_indexes[0]
                # Compare within the coordinated list, not against unrelated metric
                # mentions that may occur earlier in the evidence span.
                first_owner = max(0, len(owners) - len(ranges))
                owner_idx -= first_owner
                if owner_idx >= 0 and owner_idx != value_idx:
                    return False, "column: respectively-linked metric/value order is inconsistent"
    return True, None


def _issuer_dimension(fact: TypedGuidanceFact, document: SourceDocument) -> tuple[bool, str | None]:
    if fact.ticker != document.ticker:
        return False, "issuer: fact ticker differs from source document ticker"
    if fact.scope_kind is not GuidanceScopeKind.COMPANY:
        return False, "issuer: only issuer-level company guidance may enter the canonical ledger"
    matching = False
    for provenance in fact.provenance:
        if provenance.source_url != document.source_url:
            continue
        if provenance.source_document_hash and provenance.source_document_hash != document.content_hash:
            continue
        if provenance.document_id and provenance.document_id != document.document_id:
            continue
        matching = True
        break
    if not matching:
        return False, "issuer: provenance does not resolve to the source document"
    return True, None


def _action_dimension(fact: TypedGuidanceFact, binding_sentence: str, text: str) -> tuple[bool, str | None]:
    if fact.role not in {GuidanceFactRole.CURRENT, GuidanceFactRole.QUOTED_PRIOR}:
        return False, f"action: role {fact.role.value} is not admissible guidance evidence"

    if fact.role is GuidanceFactRole.CURRENT:
        if _HISTORICAL_VS_GUIDANCE.search(binding_sentence):
            return False, "action: historical result-versus-guidance comparison is not current guidance"
        if _HISTORICAL_RESULT.search(binding_sentence) and not _GUIDANCE_SIGNAL.search(binding_sentence):
            return False, "action: historical/realized result lacks a local forward-guidance signal"

    if fact.explicit_action is not GuidanceAction.NONE:
        pattern = _ACTION_SOURCE_PATTERNS.get(fact.explicit_action)
        local = binding_sentence or text
        if pattern is not None and not pattern.search(local):
            return False, f"action: {fact.explicit_action.value} is not evidenced in the bound sentence"
    elif fact.role is GuidanceFactRole.CURRENT:
        if not _GUIDANCE_SIGNAL.search(binding_sentence) and not re.search(r"\bguidance\b", text, re.I):
            return False, "action: current fact has no local guidance/outlook/expectation evidence"
    return True, None


class GuidanceEvidenceBinder:
    """Strict metric×period×basis×row×column×issuer×action admission gate.

    Raw extraction remains recall-oriented. This binder is precision-oriented and
    fail-closed: every dimension must be internally consistent before a fact can
    proceed to invariant validation and canonical normalization.
    """

    DIMENSIONS = ("metric", "period", "basis", "row", "column", "issuer", "action")

    def bind(self, fact: TypedGuidanceFact, document: SourceDocument) -> GuidanceEvidenceBindingResult:
        if not fact.provenance:
            return GuidanceEvidenceBindingResult(
                accepted=False,
                dimensions={name: False for name in self.DIMENSIONS},
                reasons=("issuer: fact has no provenance",),
            )
        evidence = fact.provenance[0].evidence
        text = evidence.full_text or ""
        if not text:
            return GuidanceEvidenceBindingResult(
                accepted=False,
                dimensions={name: False for name in self.DIMENSIONS},
                reasons=("metric: empty evidence span",),
            )
        starts = [value for value in (evidence.metric_start, evidence.value_start, evidence.period_start) if value is not None]
        ends = [value for value in (evidence.metric_end, evidence.value_end, evidence.period_end) if value is not None]
        start = min(starts) if starts else 0
        end = max(ends) if ends else len(text)
        binding_sentence = _sentence_window(text, start, end)

        checks = {
            "metric": _metric_dimension(fact, text),
            "period": _period_dimension(fact, text, binding_sentence),
            "basis": _basis_dimension(fact, binding_sentence),
            "row": _row_dimension(fact, text),
            "column": _column_dimension(fact, text),
            "issuer": _issuer_dimension(fact, document),
            "action": _action_dimension(fact, binding_sentence, text),
        }
        dimensions = {name: passed for name, (passed, _) in checks.items()}
        reasons = tuple(reason for passed, reason in checks.values() if not passed and reason)
        return GuidanceEvidenceBindingResult(
            accepted=all(dimensions.values()),
            dimensions=dimensions,
            reasons=reasons,
        )
