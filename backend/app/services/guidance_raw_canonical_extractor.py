from __future__ import annotations

import re

from app.domain.guidance_canonical_v1 import (
    EvidenceBinding,
    GuidanceFactRole,
    GuidancePeriodKind,
    GuidanceProvenance,
    GuidanceScopeKind,
    GuidanceUnit,
    GuidanceValueKind,
    TypedGuidanceFact,
)
from app.domain.soe_v1_1 import ExtractionMethod, GuidanceAction, GuidanceMetric, SourceDocument
from app.services.fact_extraction_service import html_to_text
from app.services.guidance_raw_typed_extractor import (
    RawTypedGuidanceExtraction,
    _ACTUAL,
    _ACTION_PATTERNS,
    _PeriodBinding,
    _action,
    _basis,
    _bind_value,
    _metric_clause,
    _metric_mentions,
    _normalize_year,
    _segments,
)


_EXPLICIT_FORWARD = re.compile(
    r"\b(?:guidance|outlook|forecast|expects?|expected|anticipat(?:e|es|ed|ing)|"
    r"project(?:s|ed|ing)|provid(?:e|es|ed|ing)\s+(?:guidance|outlook)|"
    r"issu(?:e|es|ed|ing)\s+(?:guidance|outlook))\b",
    re.I,
)

_CANONICAL_FULL_YEAR = [
    re.compile(r"\b(?:FY|fiscal\s+year|full[- ]year)\s*'?((?:20)?\d{2})\b", re.I),
    re.compile(r"\b(20\d{2})\s+(?:full[- ]year|fiscal\s+year|annual)\b", re.I),
    re.compile(r"\byear\s+ending\s+[A-Za-z]+\s+\d{1,2},?\s*(20\d{2})\b", re.I),
]
_CANONICAL_QUARTER = [
    re.compile(r"\bQ([1-4])\s*(?:FY)?\s*'?((?:20)?\d{2})\b", re.I),
    re.compile(r"\b([1-4])Q\s*(?:FY)?\s*'?((?:20)?\d{2})\b", re.I),
    re.compile(
        r"\b(first|second|third|fourth)\s+quarter(?:\s+of)?\s+"
        r"(?:fiscal(?:\s+year)?\s*)?(20\d{2})\b",
        re.I,
    ),
]
_QUARTER_WORD = {"first": "1", "second": "2", "third": "3", "fourth": "4"}
_BARE_YEAR = re.compile(r"\b(20\d{2})\b")

_SCOPE_CONTEXT_WORDS = {
    "a", "an", "and", "approximately", "about", "company", "companywide", "company-wide",
    "consolidated", "current", "expects", "expect", "expected", "forecast", "for", "full",
    "fiscal", "first", "fourth", "guidance", "is", "its", "maintains", "management", "net",
    "now", "of", "our", "outlook", "prior", "previous", "projects", "projected", "quarter",
    "reaffirms", "second", "the", "third", "to", "total", "we", "will", "year",
}


def _explicit_forward_context(text: str) -> bool:
    return bool(_EXPLICIT_FORWARD.search(text))


def _owned_directional_action(clause: str, anchor: int, metric_text: str, metric) -> GuidanceAction:
    """Bind a directional action only when the metric owns that verb."""
    mentions = _metric_mentions(clause)
    candidates = [
        item
        for item in mentions
        if item.metric is metric and item.text.lower() == metric_text.lower()
    ]
    if not candidates:
        return GuidanceAction.NONE
    current = min(candidates, key=lambda item: abs(item.start - anchor))

    owned: list[tuple[int, GuidanceAction]] = []
    for action, pattern in _ACTION_PATTERNS:
        for match in pattern.finditer(clause):
            if match.end() <= current.start:
                gap = current.start - match.end()
                if gap > 120:
                    continue
                intervening = [item for item in mentions if match.end() <= item.start < current.start]
                if intervening:
                    continue
                owned.append((gap, action))
            elif match.start() >= current.end:
                gap = match.start() - current.end
                if gap > 120:
                    continue
                intervening = [item for item in mentions if current.end < item.start <= match.start()]
                if intervening:
                    continue
                owned.append((gap, action))
            else:
                owned.append((0, action))

    if not owned:
        return GuidanceAction.NONE
    owned.sort(key=lambda item: item[0])
    nearest = owned[0][0]
    actions = {action for distance, action in owned if distance == nearest}
    return next(iter(actions)) if len(actions) == 1 else GuidanceAction.NONE


def _metric_action(segment: str, clause: str, anchor: int, mention) -> GuidanceAction:
    local = clause[max(0, anchor - 140): min(len(clause), anchor + len(mention.text) + 160)]
    has_forward_context = _explicit_forward_context(local)

    directional = _owned_directional_action(clause, anchor, mention.text, mention.metric)
    if directional is not GuidanceAction.NONE:
        # Words such as "reduced" in risk-factor prose must never create a
        # guidance action by themselves. Directional actions require an
        # independently explicit forward-guidance context.
        return directional if has_forward_context else GuidanceAction.NONE

    local_action = _action(local)
    if local_action is GuidanceAction.INITIATE and has_forward_context:
        return local_action

    # Header-wide initiation is non-directional and may be inherited only when
    # the candidate clause itself retains explicit forward context.
    segment_action = _action(segment)
    if segment_action is GuidanceAction.INITIATE and _explicit_forward_context(clause):
        return segment_action
    return GuidanceAction.NONE


def _canonical_period_binding(segment: str, mention) -> _PeriodBinding | None:
    """Bind explicit quarter/FY authority before considering a bare year.

    Explicit quarter and full-year phrases have equal authority. The nearest
    preceding explicit phrase wins; a following phrase is considered only when
    there is no preceding explicit phrase. A bare year is a last-resort fallback
    and can never override an explicit quarter/FY expression.
    """
    left = max(0, mention.start - 360)
    right = min(len(segment), mention.end + 240)
    local = segment[left:right]
    explicit: list[tuple[int, int, int, _PeriodBinding]] = []

    def add(binding: _PeriodBinding) -> None:
        if binding.end <= mention.start:
            direction = 0
            distance = mention.start - binding.end
        elif binding.start >= mention.end:
            direction = 1
            distance = binding.start - mention.end
        else:
            direction = 0
            distance = 0
        explicit.append((direction, distance, -binding.end, binding))

    for pattern in _CANONICAL_FULL_YEAR:
        for match in pattern.finditer(local):
            year = _normalize_year(match.group(1))
            start, end = left + match.start(), left + match.end()
            add(_PeriodBinding(f"FY{year}", GuidancePeriodKind.FULL_YEAR, match.group(0), start, end))

    for pattern in _CANONICAL_QUARTER:
        for match in pattern.finditer(local):
            token = match.group(1)
            q = token if token.isdigit() else _QUARTER_WORD[token.lower()]
            year = _normalize_year(match.group(2))
            start, end = left + match.start(), left + match.end()
            add(_PeriodBinding(f"Q{q}FY{year}", GuidancePeriodKind.QUARTER, match.group(0), start, end))

    if explicit:
        preceding = [item for item in explicit if item[0] == 0 and item[3].end <= mention.start]
        pool = preceding or explicit
        pool.sort(key=lambda item: (item[0], item[1], item[2]))
        best = pool[0]
        tied = [item for item in pool if item[:2] == best[:2]]
        periods = {item[3].period for item in tied}
        if len(periods) != 1:
            return None
        return best[3]

    # Bare-year fallback is deliberately weaker than every explicit period.
    bare: list[tuple[int, int, _PeriodBinding]] = []
    for match in _BARE_YEAR.finditer(local):
        start, end = left + match.start(), left + match.end()
        around = segment[max(0, start - 100): min(len(segment), end + 140)]
        if not _explicit_forward_context(around):
            continue
        direct_prefix = segment[max(0, start - 12):start]
        if re.search(r"(?:Q[1-4]|[1-4]Q)\s*(?:FY)?\s*'?\s*$", direct_prefix, re.I):
            continue
        binding = _PeriodBinding(
            f"FY{int(match.group(1))}",
            GuidancePeriodKind.FULL_YEAR,
            match.group(0),
            start,
            end,
        )
        if end <= mention.start:
            bare.append((0, mention.start - end, binding))
        else:
            bare.append((1, max(0, start - mention.end), binding))

    if not bare:
        return None
    preceding = [item for item in bare if item[0] == 0]
    pool = preceding or bare
    pool.sort(key=lambda item: (item[0], item[1], -item[2].end))
    best = pool[0]
    tied = [item for item in pool if item[:2] == best[:2]]
    periods = {item[2].period for item in tied}
    return best[2] if len(periods) == 1 else None


def _canonical_scope(clause: str, anchor: int, mention) -> tuple[GuidanceScopeKind, str | None]:
    if mention.metric is not GuidanceMetric.REVENUE:
        return GuidanceScopeKind.COMPANY, None

    label = mention.text.strip()
    lower = label.lower()
    if "total product revenue" in lower or "total revenue" in lower or "consolidated revenue" in lower or "net sales" in lower:
        return GuidanceScopeKind.COMPANY, label
    if "segment revenue" in lower:
        return GuidanceScopeKind.SEGMENT, label
    if "product revenue" in lower:
        return GuidanceScopeKind.PRODUCT, label

    # For a plain "revenue" token, inspect only its immediate noun phrase.
    # Qualified measures such as "cloud subscriptions revenue" must not be
    # promoted into company-wide total revenue merely because the lexical metric
    # matcher returned the terminal word "revenue".
    prefix = clause[max(0, anchor - 80):anchor]
    prefix = re.split(r"[.;:•|]", prefix)[-1]
    words = re.findall(r"[A-Za-z][A-Za-z0-9&'/-]*", prefix)[-4:]
    meaningful = [
        word for word in words
        if word.lower() not in _SCOPE_CONTEXT_WORDS and not re.fullmatch(r"20\d{2}", word)
    ]
    if not meaningful:
        return GuidanceScopeKind.COMPANY, None
    qualifier = " ".join(meaningful)
    if any(word.lower() == "product" for word in meaningful):
        return GuidanceScopeKind.PRODUCT, qualifier
    return GuidanceScopeKind.SEGMENT, qualifier


def extract_canonical_typed_guidance_facts(document: SourceDocument) -> RawTypedGuidanceExtraction:
    """Raw SEC -> typed facts with fail-closed binding and no repair stack."""
    text = html_to_text(document.content or "")
    facts: list[TypedGuidanceFact] = []
    rejected: list[dict] = []
    seen: set[tuple] = set()

    for segment in _segments(text):
        mentions = _metric_mentions(segment)
        if not mentions:
            continue

        for index, mention in enumerate(mentions):
            clause, anchor = _metric_clause(segment, mentions, index)
            local = clause[max(0, anchor - 140): min(len(clause), anchor + len(mention.text) + 160)]
            explicit_forward = _explicit_forward_context(local)
            local_action = _metric_action(segment, clause, anchor, mention)

            # A directional word alone is not forward evidence. Numeric facts
            # need explicit forecast/guidance context in the local clause.
            if not explicit_forward and local_action is GuidanceAction.NONE:
                continue

            if _ACTUAL.search(local) and not explicit_forward:
                rejected.append(
                    {"reason": "historical_actual", "metric": mention.metric.value, "evidence": clause[:500]}
                )
                continue

            value = _bind_value(clause, mention, anchor)
            if value is not None and value.low > value.high:
                rejected.append(
                    {
                        "reason": "invalid_reversed_range",
                        "metric": mention.metric.value,
                        "value_text": value.text,
                        "evidence": clause[:500],
                    }
                )
                continue

            period = _canonical_period_binding(segment, mention)
            if period is None:
                rejected.append(
                    {"reason": "ambiguous_or_missing_period", "metric": mention.metric.value, "evidence": clause[:500]}
                )
                continue

            if value is None and local_action not in {
                GuidanceAction.RAISE,
                GuidanceAction.LOWER,
                GuidanceAction.REAFFIRM,
                GuidanceAction.WITHDRAW,
            }:
                rejected.append(
                    {"reason": "missing_bound_value", "metric": mention.metric.value, "evidence": clause[:500]}
                )
                continue

            scope_kind, scope_label = _canonical_scope(clause, anchor, mention)
            basis = _basis(segment, mention)
            role = GuidanceFactRole.CURRENT
            if re.search(r"\b(?:previous|prior|former)\s+guidance\b", clause, re.I):
                role = GuidanceFactRole.QUOTED_PRIOR

            low = high = None
            unit = GuidanceUnit.UNKNOWN
            value_kind = GuidanceValueKind.QUALITATIVE
            value_text = None
            value_start = value_end = None
            if value is not None:
                low, high = value.low, value.high
                unit, value_kind = value.unit, value.value_kind
                value_text = value.text
                value_start, value_end = value.start, value.end

            clause_left = mention.start - anchor
            period_start = period.start - clause_left if clause_left <= period.start < clause_left + len(clause) else None
            period_end = period.end - clause_left if clause_left < period.end <= clause_left + len(clause) else None
            evidence = EvidenceBinding(
                full_text=clause,
                metric_text=mention.text,
                value_text=value_text,
                period_text=period.text,
                action_text=local_action.value if local_action is not GuidanceAction.NONE else None,
                metric_start=anchor,
                metric_end=anchor + len(mention.text),
                value_start=value_start,
                value_end=value_end,
                period_start=period_start,
                period_end=period_end,
            )
            provenance = GuidanceProvenance(
                document_id=document.document_id,
                source=document.source,
                source_url=document.source_url,
                source_accession=document.accession,
                source_timestamp=document.source_timestamp,
                source_document_hash=document.content_hash,
                evidence=evidence,
            )

            key = (
                document.ticker,
                mention.metric.value,
                period.period,
                basis,
                scope_kind.value,
                scope_label or "",
                role.value,
                low,
                high,
                unit.value,
                value_kind.value,
                local_action.value,
            )
            if key in seen:
                continue
            seen.add(key)
            facts.append(
                TypedGuidanceFact(
                    ticker=document.ticker,
                    metric=mention.metric,
                    raw_metric_label=mention.raw_label,
                    fiscal_period=period.period,
                    authoritative_period=period.period,
                    period_kind=period.kind,
                    accounting_basis=basis,
                    scope_kind=scope_kind,
                    scope_label=scope_label,
                    value_kind=value_kind,
                    role=role,
                    low=low,
                    high=high,
                    unit=unit,
                    explicit_action=local_action,
                    extraction_method=ExtractionMethod.DETERMINISTIC_TEXT,
                    provenance=[provenance],
                    metadata={
                        "raw_document_extractor": "guidance-canonical-raw-v2",
                        "source_form": document.form,
                    },
                )
            )

    return RawTypedGuidanceExtraction(
        ticker=document.ticker,
        document_id=document.document_id,
        facts=tuple(facts),
        rejected_candidates=tuple(rejected),
    )
