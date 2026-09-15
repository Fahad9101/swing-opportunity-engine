from __future__ import annotations

import re

from app.domain.guidance_canonical_v1 import (
    GuidanceFactRole,
    GuidancePeriodKind,
    GuidanceScopeKind,
    GuidanceValueKind,
    TypedGuidanceFact,
)
from app.domain.soe_v1_1 import GuidanceMetric, SourceDocument


_SEMANTIC_VERSION = "semantic-ownership-v1"

_FORWARD_CUE = re.compile(
    r"\b(?:guidance|outlook|forecast|expects?|expected|anticipat(?:e|es|ed|ing)|"
    r"project(?:s|ed|ing)|provid(?:e|es|ed|ing)|issu(?:e|es|ed|ing)|"
    r"rais(?:e|es|ed|ing)|lower(?:s|ed|ing)?|reduc(?:e|es|ed|ing)|"
    r"reaffirm(?:s|ed|ing)?|reiterat(?:e|es|ed|ing)|maintain(?:s|ed|ing)?)\b",
    re.I,
)
_CURRENT_CUE = re.compile(
    r"\b(?:current|updated|revised|now|currently|expects?|expected|"
    r"reaffirm(?:s|ed|ing)?|maintain(?:s|ed|ing)?)\b",
    re.I,
)
_PRIOR_CUE = re.compile(
    r"\b(?:prior|previous|previously|former|earlier|original)\b"
    r"(?:\s+[A-Za-z0-9*.'/-]+){0,6}\s*"
    r"(?:guidance|outlook|forecast|estimate|expected|provided|stated)?\b",
    re.I,
)
_STRONG_ACTUAL_CUE = re.compile(
    r"\b(?:reported|generated|delivered|achieved|realized|recognized|"
    r"recorded|totaled|came\s+in\s+at|"
    r"(?:revenue|revenues|sales|EBITDA|free\s+cash\s+flow|FCF|EPS)\s+"
    r"(?:(?:was|were)|(?:increased|decreased|rose|fell|grew|declined)\s+to))\b",
    re.I,
)
_LONG_TERM_TARGET = re.compile(
    r"\b(?:long[- ]term|multi[- ]year|over\s+the\s+next\s+\d+\s+years?)\b"
    r".{0,100}\b(?:target|goal|objective|opportunity)\b|"
    r"\b(?:target|goal|objective)\b.{0,100}\b(?:long[- ]term|multi[- ]year)\b",
    re.I | re.S,
)
_SUBCOMPONENT_REVENUE = re.compile(
    r"\bremaining\s+performance\s+obligations?\b|"
    r"\b(?:deferred|collaboration|milestone)\s+revenue\b|"
    r"\brevenue\b.{0,100}\b(?:deferred|collaboration|milestone)\b|"
    r"\b(?:recognize|recognized|recognition)\b.{0,100}\b(?:RPO|revenue)\b",
    re.I | re.S,
)
_PORTFOLIO_EFFECT = re.compile(
    r"\b(?:divestitures?|business\s+exits?|portfolio\s+pruning|pruning)\b"
    r".{0,160}\b(?:revenue|revenues|net\s+sales|sales)\b|"
    r"\b(?:revenue|revenues|net\s+sales|sales)\b.{0,160}"
    r"\b(?:divestitures?|business\s+exits?|portfolio\s+pruning|pruning)\b",
    re.I | re.S,
)
_TRANSACTION_EFFECT = re.compile(
    r"\b(?:annual|run[- ]rate)?\s*(?:EBITDA\s+)?synerg(?:y|ies)\b|"
    r"\bEPS\s+(?:accretion|dilution|headwind|tailwind)\b|"
    r"\b(?:accretive|dilutive)\s+to\s+(?:adjusted\s+)?EPS\b|"
    r"\b(?:transaction|acquisition)\b.{0,100}\b(?:accretion|dilution|synerg(?:y|ies))\b",
    re.I | re.S,
)
_NAMED_OWNER = re.compile(
    r"(?:^|[.;•\n\r])\s*(?P<label>[A-Z][A-Za-z0-9&'(). /-]{2,70})\s*:\s*$"
)
_OWNER_RESERVED = re.compile(
    r"^(?:financial\s+)?(?:guidance|outlook|forecast|results?|highlights?)$|"
    r"^(?:full[- ]year|fiscal(?:\s+year)?|annual|quarterly?)\b.*"
    r"(?:guidance|outlook|forecast|results?)$|"
    r"^(?:the\s+)?(?:company|consolidated|total)$",
    re.I,
)
_LOSS_OWNER = re.compile(
    r"\b(?:adjusted\s+|non[- ]GAAP\s+)?"
    r"(?:EBITDA|free\s+cash\s+flow|FCF)\s+(?:guidance\s+)?(?:is\s+)?(?:an?\s+)?loss\b|"
    r"\b(?:EBITDA|free\s+cash\s+flow|FCF)\b.{0,45}\bloss\b",
    re.I | re.S,
)
_BREAKEVEN_LOSS = re.compile(
    r"\bbreakeven\b.{0,50}\bloss\b|\bloss\b.{0,50}\bbreakeven\b",
    re.I | re.S,
)
_RESPECTIVELY = re.compile(r"\brespectively\b", re.I)

_QUARTER = re.compile(
    r"\bQ(?P<q>[1-4])\s*(?:FY)?\s*'?(?P<year>20\d{2})\b|"
    r"\b(?P<word>first|second|third|fourth)\s+(?:fiscal\s+)?quarter"
    r"(?:\s+(?:of\s+)?(?:fiscal(?:\s+year)?\s*)?(?P<year2>20\d{2}))",
    re.I,
)
_FULL_YEAR = re.compile(
    r"\b(?:FY|fiscal(?:\s+year)?|full[- ]year)\s*'?(?P<year>20\d{2})\b|"
    r"\b(?P<year2>20\d{2})\s+(?:full[- ]year|annual)\b",
    re.I,
)
_QWORD = {"first": "1", "second": "2", "third": "3", "fourth": "4"}

_METRIC_TOKEN = re.compile(
    r"\b(?:revenue|revenues|net\s+sales|EPS|earnings\s+per\s+share|"
    r"EBITDA|free\s+cash\s+flow|FCF|gross\s+margin|operating\s+margin)\b",
    re.I,
)


def _evidence(fact: TypedGuidanceFact):
    return fact.provenance[0].evidence


def _value_window(fact: TypedGuidanceFact, before: int = 180, after: int = 120) -> str:
    evidence = _evidence(fact)
    text = evidence.full_text or ""
    start = evidence.value_start
    end = evidence.value_end
    if start is None:
        start = evidence.metric_start or 0
    if end is None:
        end = start
    return text[max(0, start - before): min(len(text), end + after)]


def _binding_sentence(fact: TypedGuidanceFact) -> str:
    evidence = _evidence(fact)
    text = evidence.full_text or ""
    starts = [x for x in (evidence.metric_start, evidence.value_start) if x is not None]
    ends = [x for x in (evidence.metric_end, evidence.value_end) if x is not None]
    if not starts:
        return text
    left_anchor = min(starts)
    right_anchor = max(ends) if ends else left_anchor
    left = max(
        text.rfind(".", 0, left_anchor),
        text.rfind(";", 0, left_anchor),
        text.rfind("\n", 0, left_anchor),
        text.rfind("•", 0, left_anchor),
    ) + 1
    rights = [
        pos for token in (".", ";", "\n", "•")
        if (pos := text.find(token, right_anchor)) >= 0
    ]
    right = min(rights) if rights else len(text)
    return text[left:right].strip()


def _named_owner_label(fact: TypedGuidanceFact) -> str | None:
    evidence = _evidence(fact)
    text = evidence.full_text or ""
    if evidence.metric_start is None:
        return None
    prefix = text[max(0, evidence.metric_start - 110): evidence.metric_start]
    match = _NAMED_OWNER.search(prefix)
    if match is None:
        return None
    label = re.sub(r"\s+", " ", match.group("label")).strip()
    if _OWNER_RESERVED.search(label):
        return None
    if re.search(r"\b(?:guidance|outlook|forecast|results?|company|consolidated)\b", label, re.I):
        return None
    return label


def _explicit_periods(text: str) -> set[str]:
    periods: set[str] = set()
    for match in _QUARTER.finditer(text):
        q = match.group("q") or _QWORD[(match.group("word") or "").lower()]
        year = match.group("year") or match.group("year2")
        if q and year:
            periods.add(f"Q{q}FY{year}")
    for match in _FULL_YEAR.finditer(text):
        year = match.group("year") or match.group("year2")
        if year:
            periods.add(f"FY{year}")
    return periods


def _local_period_conflict(fact: TypedGuidanceFact) -> bool:
    periods = _explicit_periods(_binding_sentence(fact))
    if not periods:
        return False
    return fact.fiscal_period not in periods


def _historical_actual(fact: TypedGuidanceFact) -> bool:
    evidence = _evidence(fact)
    text = evidence.full_text or ""
    if evidence.value_start is None:
        return False
    before = text[max(0, evidence.value_start - 150): evidence.value_start]
    matches = list(_STRONG_ACTUAL_CUE.finditer(before))
    if not matches:
        return False
    cue = matches[-1]
    tail = before[cue.end():]
    return not bool(_FORWARD_CUE.search(tail))


def _role_owner(fact: TypedGuidanceFact) -> tuple[GuidanceFactRole, str | None]:
    evidence = _evidence(fact)
    text = evidence.full_text or ""
    if evidence.value_start is None:
        return fact.role, None
    before = text[max(0, evidence.value_start - 160): evidence.value_start]
    prior = list(_PRIOR_CUE.finditer(before))
    current = list(_CURRENT_CUE.finditer(before))
    latest_prior = prior[-1] if prior else None
    latest_current = current[-1] if current else None

    if fact.role is GuidanceFactRole.QUOTED_PRIOR:
        if latest_current is not None and (
            latest_prior is None or latest_current.end() > latest_prior.end()
        ):
            return GuidanceFactRole.CURRENT, None
        if latest_prior is None:
            return fact.role, "role: quoted-prior fact lacks local prior-guidance ownership"
    elif fact.role is GuidanceFactRole.CURRENT and latest_prior is not None:
        if latest_current is None or latest_prior.end() > latest_current.end():
            return GuidanceFactRole.QUOTED_PRIOR, None
    return fact.role, None


def _normalize_loss_sign(fact: TypedGuidanceFact) -> tuple[float | None, float | None]:
    if fact.metric not in {GuidanceMetric.EBITDA, GuidanceMetric.FCF}:
        return fact.low, fact.high
    if fact.low is None or fact.high is None:
        return fact.low, fact.high
    if fact.low < 0 or fact.high < 0:
        return fact.low, fact.high
    local = _value_window(fact, 120, 70)
    if not _LOSS_OWNER.search(local):
        return fact.low, fact.high
    magnitude_low = min(abs(fact.low), abs(fact.high))
    magnitude_high = max(abs(fact.low), abs(fact.high))
    if _BREAKEVEN_LOSS.search(local) or min(fact.low, fact.high) == 0:
        return -magnitude_high, 0.0
    return -magnitude_high, -magnitude_low


def _is_total_metric_label(fact: TypedGuidanceFact) -> bool:
    label = (_evidence(fact).metric_text or "").strip()
    return bool(re.search(r"\b(?:total|consolidated|company[- ]wide)\b", label, re.I))


def normalize_typed_guidance_fact(
    fact: TypedGuidanceFact,
    document: SourceDocument,
) -> TypedGuidanceFact:
    """Normalize deterministic semantic ownership before strict-v4 admission.

    This stage may correct semantics only when primary-source ownership is
    deterministic. Ambiguity is recorded in metadata for the strict binder to
    fail closed; no investment threshold, score, or classifier rule is changed.
    """
    del document

    updates: dict = {}
    issues: list[str] = []
    metadata = dict(fact.metadata or {})
    metadata["semantic_ownership_version"] = _SEMANTIC_VERSION

    owner = _named_owner_label(fact)
    if owner is not None:
        updates["scope_kind"] = GuidanceScopeKind.SEGMENT
        updates["scope_label"] = owner

    sentence = _binding_sentence(fact)
    local = _value_window(fact)

    if _LONG_TERM_TARGET.search(local):
        updates["role"] = GuidanceFactRole.LONG_TERM_TARGET
        updates["period_kind"] = GuidancePeriodKind.LONG_TERM

    if _historical_actual(fact):
        updates["role"] = GuidanceFactRole.ACTUAL

    role, role_issue = _role_owner(fact)
    if "role" not in updates and role is not fact.role:
        updates["role"] = role
    if role_issue:
        issues.append(role_issue)

    low, high = _normalize_loss_sign(fact)
    if (low, high) != (fact.low, fact.high):
        updates["low"] = low
        updates["high"] = high
        metadata["semantic_sign_normalized"] = True

    if _local_period_conflict(fact):
        issues.append("period: locally owned explicit period conflicts with selected fiscal period")

    if fact.metric is GuidanceMetric.REVENUE and not _is_total_metric_label(fact) and _SUBCOMPONENT_REVENUE.search(local):
        updates["scope_kind"] = GuidanceScopeKind.UNKNOWN
        updates["scope_label"] = "revenue subcomponent"
        issues.append("issuer: revenue subcomponent/recognition amount is not consolidated issuer revenue")

    if fact.metric is GuidanceMetric.REVENUE and not _is_total_metric_label(fact) and _PORTFOLIO_EFFECT.search(local):
        updates["value_kind"] = GuidanceValueKind.DELTA
        issues.append("row: portfolio-pruning/divestiture/business-exit effect is not consolidated revenue level")

    if fact.metric in {GuidanceMetric.EBITDA, GuidanceMetric.EPS, GuidanceMetric.REVENUE} and _TRANSACTION_EFFECT.search(local):
        updates["scope_kind"] = GuidanceScopeKind.UNKNOWN
        updates["scope_label"] = "transaction effect"
        issues.append("issuer: transaction synergy/accretion/dilution effect is not issuer operating guidance")

    if _RESPECTIVELY.search(sentence):
        metric_tokens = {m.group(0).lower() for m in _METRIC_TOKEN.finditer(sentence)}
        if len(metric_tokens) >= 2:
            issues.append("column: multi-metric 'respectively' evidence requires explicit coordinate ownership")

    if issues:
        metadata["semantic_ownership_issues"] = list(dict.fromkeys(issues))
    else:
        metadata.pop("semantic_ownership_issues", None)
    updates["metadata"] = metadata
    return fact.model_copy(update=updates)
