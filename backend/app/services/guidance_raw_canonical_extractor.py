from __future__ import annotations

import re

from app.domain.guidance_canonical_v1 import (
    EvidenceBinding,
    GuidanceFactRole,
    GuidanceProvenance,
    GuidanceScopeKind,
    GuidanceUnit,
    GuidanceValueKind,
    TypedGuidanceFact,
)
from app.domain.soe_v1_1 import ExtractionMethod, GuidanceAction, SourceDocument
from app.services.fact_extraction_service import html_to_text
from app.services.guidance_raw_typed_extractor import (
    RawTypedGuidanceExtraction,
    _ACTUAL,
    _ACTION_PATTERNS,
    _action,
    _basis,
    _bind_value,
    _local_forward_context,
    _metric_clause,
    _metric_mentions,
    _period_binding,
    _scope,
    _segments,
)


def _owned_directional_action(clause: str, anchor: int, metric_text: str, metric) -> GuidanceAction:
    """Bind a directional action only when the metric owns that verb.

    Directional guidance verbs are never inherited from an entire filing/table
    segment. If another recognized metric sits between the action verb and the
    candidate metric, the action belongs elsewhere and is not propagated.
    """
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
                intervening = [
                    item for item in mentions
                    if match.end() <= item.start < current.start
                ]
                if intervening:
                    continue
                owned.append((gap, action))
            elif match.start() >= current.end:
                gap = match.start() - current.end
                if gap > 120:
                    continue
                intervening = [
                    item for item in mentions
                    if current.end < item.start <= match.start()
                ]
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
    directional = _owned_directional_action(clause, anchor, mention.text, mention.metric)
    if directional is not GuidanceAction.NONE:
        return directional

    local = clause[
        max(0, anchor - 90): min(len(clause), anchor + len(mention.text) + 110)
    ]
    local_action = _action(local)
    if local_action is GuidanceAction.INITIATE:
        return local_action

    # Header-wide initiation is non-directional and safe to inherit. Never
    # inherit RAISE/LOWER/REAFFIRM/WITHDRAW across metrics.
    segment_action = _action(segment)
    if segment_action is GuidanceAction.INITIATE:
        return segment_action
    return GuidanceAction.NONE


def extract_canonical_typed_guidance_facts(document: SourceDocument) -> RawTypedGuidanceExtraction:
    """Raw SEC -> typed facts with fail-closed binding and no repair stack.

    The function deliberately rejects impossible ranges before constructing the
    typed model and binds directional actions to the owning metric only. It uses
    the proven lexical/period/value primitives from the raw extractor, but this
    is the canonical policy boundary used by population replay.
    """
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
            local_action = _metric_action(segment, clause, anchor, mention)

            if not _local_forward_context(clause, anchor, mention) and local_action is GuidanceAction.NONE:
                continue

            local = clause[
                max(0, anchor - 100): min(len(clause), anchor + len(mention.text) + 120)
            ]
            if _ACTUAL.search(local) and not re.search(
                r"\b(?:guidance|outlook|forecast|expects?|anticipat(?:e|es|ed|ing)|project(?:s|ed|ing))\b",
                local,
                re.I,
            ):
                rejected.append(
                    {"reason": "historical_actual", "metric": mention.metric.value, "evidence": clause[:500]}
                )
                continue

            period = _period_binding(segment, mention)
            if period is None:
                rejected.append(
                    {"reason": "ambiguous_or_missing_period", "metric": mention.metric.value, "evidence": clause[:500]}
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

            scope_kind, scope_label = _scope(mention)
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
                        "raw_document_extractor": "guidance-canonical-raw-v1",
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
