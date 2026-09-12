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
_FORWARD_SIGNAL = re.compile(
    r"\b(?:guidance|outlook|forecast|expects?|expected|anticipat(?:e|es|ed|ing)|"
    r"project(?:s|ed|ing)|rais(?:e|es|ed|ing)|lower(?:s|ed|ing)?|"
    r"reaffirm(?:s|ed|ing)?|reiterat(?:e|es|ed|ing)|maintain(?:s|ed|ing)?)\b",
    re.I,
)
_ACTUAL_VALUE = re.compile(
    r"\b(?:was|were|totaled|reported|generated|delivered|grew|increased|decreased|"
    r"for\s+the\s+quarter\s+ended|year[- ]to[- ]date)\b",
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
    re.compile(
        r"\b(first|second|third|fourth)\s+quarter\s+ending\s+"
        r"[A-Za-z]+\s+\d{1,2},?\s*(20\d{2})\b",
        re.I,
    ),
]
_QUARTER_WORD = {"first": "1", "second": "2", "third": "3", "fourth": "4"}
_BARE_YEAR = re.compile(r"\b(20\d{2})\b")

# Scope is fail-closed only on explicit economic qualifiers immediately bound
# to the revenue noun. Generic verbs, issuer names, bullets, or table labels are
# never treated as segment identity.
_SEGMENT_REVENUE_QUALIFIER = re.compile(
    r"\b(?:cloud\s+subscriptions?|subscriptions?|services?|licensing|commercial|"
    r"government|enterprise|consumer|advertising|international|domestic|platform|"
    r"software|hardware|maintenance|support|professional\s+services|annualized|"
    r"incremental|acquisition|u\.?s\.?\s+commercial|u\.?s\.?\s+government)\s*$",
    re.I,
)
_PRODUCT_REVENUE_QUALIFIER = re.compile(r"\bproduct\s*$", re.I)

_VALUE_OWNER_PATTERNS: list[tuple[GuidanceMetric | str, re.Pattern[str]]] = [
    (
        GuidanceMetric.GROSS_MARGIN,
        re.compile(r"\b(?:(?:adj(?:usted)?|non[- ]GAAP)\s+)?gross(?:\s+profit)?\s+margin\b", re.I),
    ),
    (
        GuidanceMetric.OPERATING_MARGIN,
        re.compile(r"\b(?:(?:adj(?:usted)?|non[- ]GAAP)\s+)?operating\s+margin\b", re.I),
    ),
    (
        GuidanceMetric.FCF,
        re.compile(r"\b(?:free\s+cash\s+flow|FCF)\b", re.I),
    ),
    (
        GuidanceMetric.EPS,
        re.compile(
            r"\b(?:(?:adj(?:usted)?|non[- ]GAAP|GAAP)\s+)?(?:diluted\s+)?"
            r"(?:EPS|earnings\s+per\s+(?:common\s+)?share)\b",
            re.I,
        ),
    ),
    (
        GuidanceMetric.EBITDA,
        re.compile(r"\b(?:(?:adj(?:usted)?|non[- ]GAAP)\s+)?EBITDA\b(?!\s+margin)", re.I),
    ),
    (
        GuidanceMetric.REVENUE,
        re.compile(r"\b(?:total\s+(?:product\s+)?revenue|consolidated\s+revenue|net\s+sales|revenues?)\b", re.I),
    ),
    ("net_income", re.compile(r"\b(?:(?:adjusted|GAAP)\s+)?net\s+(?:income|loss)\b", re.I)),
    (
        "operating_cash",
        re.compile(r"\b(?:net\s+cash\s+provided\s+by\s+operating\s+activities|operating\s+cash\s+flow)\b", re.I),
    ),
    ("capex", re.compile(r"\b(?:capital\s+expenditures?|capex)\b", re.I)),
    ("repurchase", re.compile(r"\b(?:share|stock)\s+repurchase\b", re.I)),
    ("contract_value", re.compile(r"\b(?:contract\s+wins?|contracts?\s+valued|transaction\s+consideration)\b", re.I)),
]


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
        return directional if has_forward_context else GuidanceAction.NONE

    local_action = _action(local)
    if local_action is GuidanceAction.INITIATE and has_forward_context:
        return local_action

    segment_action = _action(segment)
    if segment_action is GuidanceAction.INITIATE and _explicit_forward_context(clause):
        return segment_action
    return GuidanceAction.NONE


def _canonical_period_binding(segment: str, mention) -> _PeriodBinding | None:
    """Bind explicit quarter/FY authority before considering a bare year.

    Any explicit preceding quarter/FY expression in the current bounded segment
    outranks a following expression. This prevents a later full-year section from
    relabeling an earlier quarterly block. Following authority is considered only
    when no preceding explicit period exists and remains distance-limited.
    """
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
        for match in pattern.finditer(segment):
            year = _normalize_year(match.group(1))
            add(_PeriodBinding(f"FY{year}", GuidancePeriodKind.FULL_YEAR, match.group(0), match.start(), match.end()))

    for pattern in _CANONICAL_QUARTER:
        for match in pattern.finditer(segment):
            token = match.group(1)
            q = token if token.isdigit() else _QUARTER_WORD[token.lower()]
            year = _normalize_year(match.group(2))
            add(_PeriodBinding(f"Q{q}FY{year}", GuidancePeriodKind.QUARTER, match.group(0), match.start(), match.end()))

    if explicit:
        preceding = [item for item in explicit if item[0] == 0 and item[3].end <= mention.start]
        if preceding:
            preceding.sort(key=lambda item: (item[1], item[2]))
            best = preceding[0]
            tied = [item for item in preceding if item[1] == best[1]]
            periods = {item[3].period for item in tied}
            return best[3] if len(periods) == 1 else None

        following = [item for item in explicit if item[0] == 1 and item[1] <= 320]
        if following:
            following.sort(key=lambda item: (item[1], item[2]))
            best = following[0]
            tied = [item for item in following if item[1] == best[1]]
            periods = {item[3].period for item in tied}
            return best[3] if len(periods) == 1 else None

    # Bare-year fallback is deliberately local and weaker than every explicit
    # quarter/FY expression.
    left = max(0, mention.start - 180)
    right = min(len(segment), mention.end + 140)
    local = segment[left:right]
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
    pool = preceding or [item for item in bare if item[1] <= 120]
    if not pool:
        return None
    pool.sort(key=lambda item: (item[0], item[1], -item[2].end))
    best = pool[0]
    tied = [item for item in pool if item[:2] == best[:2]]
    periods = {item[2].period for item in tied}
    return best[2] if len(periods) == 1 else None


def _span_gap(a_start: int, a_end: int, b_start: int, b_end: int) -> int:
    if a_end <= b_start:
        return b_start - a_end
    if b_end <= a_start:
        return a_start - b_end
    return 0


def _value_has_local_metric_owner(clause: str, anchor: int, mention, value) -> bool:
    """Reject a value when another economic metric is closer than its owner."""
    current_start = anchor
    current_end = anchor + len(mention.text)
    current_gap = _span_gap(current_start, current_end, value.start, value.end)

    nearest_other: tuple[int, GuidanceMetric | str] | None = None
    for owner, pattern in _VALUE_OWNER_PATTERNS:
        for match in pattern.finditer(clause):
            if owner is mention.metric and not (match.end() <= current_start or match.start() >= current_end):
                continue
            gap = _span_gap(match.start(), match.end(), value.start, value.end)
            if nearest_other is None or gap < nearest_other[0]:
                nearest_other = (gap, owner)

    if nearest_other is None:
        return True
    other_gap, other_owner = nearest_other
    if other_owner is mention.metric:
        return True
    return current_gap < other_gap


def _historical_value_before_guidance(clause: str, anchor: int, mention, value) -> bool:
    """Prevent a reported result immediately before a guidance header from leaking in."""
    if value is None:
        return False

    before_value = clause[max(0, value.start - 180):value.start]
    after_value = clause[value.end:min(len(clause), value.end + 180)]
    actual_before = _ACTUAL_VALUE.search(before_value)
    if actual_before is None:
        return False

    # A true forecast such as "EBITDA is expected to be $58.4m" has its forward
    # signal before the value and must survive. A historical sentence such as
    # "EBITDA was $58.4m. Raising 2026 guidance..." has an actual verb before the
    # value and its first forward signal only after it, so it is rejected.
    tail_after_actual = before_value[actual_before.end():]
    if _FORWARD_SIGNAL.search(tail_after_actual):
        return False
    return bool(_FORWARD_SIGNAL.search(after_value))


def _ambiguous_parallel_period_table(clause: str) -> bool:
    return bool(
        re.search(r"\bthree\s+months\s+ending\b", clause, re.I)
        and re.search(r"\byear\s+ending\b", clause, re.I)
        and re.search(r"\b(?:table|reconciliation|guidance)\b", clause, re.I)
    )


def _ambiguous_current_prior_table(clause: str) -> bool:
    return bool(
        re.search(r"\b(?:updated|current)\b.{0,40}\bguidance\b", clause, re.I)
        and re.search(r"\bprior\b.{0,40}\bguidance\b", clause, re.I)
    )


def _fact_role(clause: str, value) -> GuidanceFactRole:
    if value is None:
        return GuidanceFactRole.CURRENT
    before = clause[max(0, value.start - 150):value.start]
    if re.search(
        r"\b(?:from\s+(?:our\s+)?)?prior(?:\s+[A-Za-z0-9*.-]+){0,4}\s+(?:guidance|outlook)\b",
        before,
        re.I,
    ) or re.search(
        r"\bprevious(?:\s+[A-Za-z0-9*.-]+){0,4}\s+(?:guidance|outlook)\b",
        before,
        re.I,
    ):
        return GuidanceFactRole.QUOTED_PRIOR
    return GuidanceFactRole.CURRENT


def _canonical_scope(clause: str, anchor: int, mention) -> tuple[GuidanceScopeKind, str | None]:
    if mention.metric is not GuidanceMetric.REVENUE:
        return GuidanceScopeKind.COMPANY, None

    label = mention.text.strip()
    lower = label.lower()
    if (
        "total product revenue" in lower
        or "total revenue" in lower
        or "consolidated revenue" in lower
        or "net sales" in lower
    ):
        return GuidanceScopeKind.COMPANY, label
    if "segment revenue" in lower:
        return GuidanceScopeKind.SEGMENT, label
    if "product revenue" in lower and "total product revenue" not in lower:
        return GuidanceScopeKind.PRODUCT, label

    prefix = clause[max(0, anchor - 70):anchor]
    prefix = re.split(r"[.;:•|\n\r]", prefix)[-1].strip()
    if _PRODUCT_REVENUE_QUALIFIER.search(prefix):
        return GuidanceScopeKind.PRODUCT, prefix
    segment_match = _SEGMENT_REVENUE_QUALIFIER.search(prefix)
    if segment_match:
        return GuidanceScopeKind.SEGMENT, segment_match.group(0).strip()

    contribution_context = clause[max(0, anchor - 180):anchor]
    if re.search(r"\bacquisitions?\b.{0,120}\bcontribut(?:e|es|ed|ing)\b", contribution_context, re.I):
        return GuidanceScopeKind.SEGMENT, "acquisition contribution"
    return GuidanceScopeKind.COMPANY, None


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

            if not explicit_forward and local_action is GuidanceAction.NONE:
                continue

            if _ambiguous_parallel_period_table(clause):
                rejected.append(
                    {"reason": "ambiguous_parallel_period_table", "metric": mention.metric.value, "evidence": clause[:500]}
                )
                continue
            if _ambiguous_current_prior_table(clause):
                rejected.append(
                    {"reason": "ambiguous_current_prior_table", "metric": mention.metric.value, "evidence": clause[:500]}
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
            if value is not None and not _value_has_local_metric_owner(clause, anchor, mention, value):
                rejected.append(
                    {
                        "reason": "metric_value_locality",
                        "metric": mention.metric.value,
                        "value_text": value.text,
                        "evidence": clause[:500],
                    }
                )
                continue
            if value is not None and _historical_value_before_guidance(clause, anchor, mention, value):
                rejected.append(
                    {
                        "reason": "historical_actual",
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
            role = _fact_role(clause, value)

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
                        "raw_document_extractor": "guidance-canonical-raw-v3",
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