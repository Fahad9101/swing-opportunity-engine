from __future__ import annotations

import re
from collections import defaultdict

from app.domain.soe_v1_1 import (
    GuidanceAction,
    GuidanceExtractionResult,
    GuidanceMetricRecord,
    SourceDocument,
)
from app.services.phase_1_1e_evidence_hygiene_round3_v1_1 import _quality
from app.services.phase_1_1e_evidence_hygiene_round4_v1_1 import _action_consistent_history
from app.services.phase_1_1e_evidence_hygiene_round3_patch_v1_1 import _metric_occurrences
from app.services.phase_1_1e_guidance_actual_guard_round6_v1_1 import (
    extract_guidance_facts_round6,
    tighten_guidance_record_round6,
)
from app.services.phase_1_1e_guidance_period_guard_round7_v1_1 import (
    _GUIDANCE_AFTER_METRIC,
    _GUIDANCE_BEFORE_METRIC,
    _metric_bound_annual_periods,
)

# Round 8 repairs a systematic scope-binding defect found by the independent
# audit: a header such as "Q2 FY2027 Outlook" must remain Q2FY2027 and must not
# be collapsed into FY2027 merely because the header contains an FY token.
#
# Evidence scope only. No SOE threshold, score, weight, scanner, classifier,
# technical rule, catalyst rule, penalty, SOE-1.0.0 rule, or IEE logic changes.

_QUARTER_WORDS = {
    "first": 1,
    "second": 2,
    "third": 3,
    "fourth": 4,
}


def _year(token: str) -> int:
    value = int(token)
    return value + 2000 if value < 100 else value


def _same_clause_quarter_periods(text: str, start: int, end: int) -> set[str]:
    """Return quarter fiscal scopes grammatically bound to one metric occurrence.

    Supported primary-source constructions include:
      - "Q2 FY2027 Outlook ... Total revenue"
      - "Third Quarter FY2027 Guidance ... Revenue"
      - "Q2 FY2027 revenue guidance"
      - "revenue guidance for Q2 FY2027"

    The search does not cross sentence/newline boundaries and requires local
    guidance/outlook/forecast context so ordinary historical quarter labels do
    not become forward-guidance periods.
    """
    left = max(0, start - 190)
    right = min(len(text), end + 190)
    prefix = text[left:start]
    suffix = text[end:right]

    guidance_after = bool(_GUIDANCE_AFTER_METRIC.search(suffix))
    guidance_before = bool(_GUIDANCE_BEFORE_METRIC.search(prefix))
    periods: set[str] = set()

    # Quarter header before metric, e.g. "Q2 FY2027 Outlook ... Total revenue".
    for match in re.finditer(
        r"\bQ([1-4])\s*(?:FY|fiscal(?:\s+year)?)?\s*'?((?:20)?\d{2})\b"
        r"[^.!?\n]{0,120}\b(?:guidance|outlook|forecast)\b[^.!?\n]{0,100}$",
        prefix,
        re.I,
    ):
        periods.add(f"Q{match.group(1)}FY{_year(match.group(2))}")

    for match in re.finditer(
        r"\b(first|second|third|fourth)\s+quarter(?:\s+of)?\s+"
        r"(?:(?:FY|fiscal(?:\s+year)?)\s*)?'?((?:20)?\d{2})\b"
        r"[^.!?\n]{0,120}\b(?:guidance|outlook|forecast)\b[^.!?\n]{0,100}$",
        prefix,
        re.I,
    ):
        periods.add(f"Q{_QUARTER_WORDS[match.group(1).lower()]}FY{_year(match.group(2))}")

    # Quarter token immediately before metric when guidance wording follows it,
    # e.g. "Q2 FY2027 revenue guidance".
    if guidance_after:
        for match in re.finditer(
            r"\bQ([1-4])\s*(?:FY|fiscal(?:\s+year)?)?\s*'?((?:20)?\d{2})\b[^.!?\n]{0,80}$",
            prefix,
            re.I,
        ):
            periods.add(f"Q{match.group(1)}FY{_year(match.group(2))}")
        for match in re.finditer(
            r"\b(first|second|third|fourth)\s+quarter(?:\s+of)?\s+"
            r"(?:(?:FY|fiscal(?:\s+year)?)\s*)?'?((?:20)?\d{2})\b[^.!?\n]{0,80}$",
            prefix,
            re.I,
        ):
            periods.add(f"Q{_QUARTER_WORDS[match.group(1).lower()]}FY{_year(match.group(2))}")

    # Period after metric guidance, e.g. "revenue guidance for Q2 FY2027".
    if guidance_after or guidance_before:
        for match in re.finditer(
            r"^[^.!?\n]{0,100}\b(?:guidance|outlook|forecast)\b[^.!?\n]{0,80}?"
            r"\b(?:for\s+(?:the\s+)?)?Q([1-4])\s*(?:FY|fiscal(?:\s+year)?)?\s*'?((?:20)?\d{2})\b",
            suffix,
            re.I,
        ):
            periods.add(f"Q{match.group(1)}FY{_year(match.group(2))}")

    return periods


def _metric_bound_quarter_periods(record: GuidanceMetricRecord, text: str) -> set[str]:
    periods: set[str] = set()
    for start, end in _metric_occurrences(text, record.metric):
        periods.update(_same_clause_quarter_periods(text, start, end))
    return periods


def tighten_guidance_record_round8(record: GuidanceMetricRecord) -> GuidanceMetricRecord | None:
    # Start from Round 6, not Round 7, because Round-7 dedupe may already have
    # collapsed a quarter and annual row onto one key before Round 8 can repair it.
    base = tighten_guidance_record_round6(record)
    if base is None:
        return None

    text = (record.evidence_span or "").strip()
    if not text:
        return base

    quarter_periods = _metric_bound_quarter_periods(base, text)
    if len(quarter_periods) > 1:
        return None
    if len(quarter_periods) == 1:
        return base.model_copy(update={"fiscal_period": next(iter(quarter_periods))})

    annual_periods = _metric_bound_annual_periods(base, text)
    if len(annual_periods) > 1:
        return None
    if len(annual_periods) == 1:
        return base.model_copy(update={"fiscal_period": next(iter(annual_periods))})
    return base


def dedupe_guidance_records_round8(records: list[GuidanceMetricRecord]) -> list[GuidanceMetricRecord]:
    corrected = [
        item
        for record in records
        if (item := tighten_guidance_record_round8(record)) is not None
    ]

    grouped: dict[tuple[tuple[str, str, str], object], list[GuidanceMetricRecord]] = defaultdict(list)
    for item in corrected:
        grouped[(item.comparison_key, item.source_timestamp)].append(item)

    selected: list[GuidanceMetricRecord] = []
    for rows in grouped.values():
        raises = [row for row in rows if row.explicit_action is GuidanceAction.RAISE and row.midpoint is not None]
        lowers = [row for row in rows if row.explicit_action is GuidanceAction.LOWER and row.midpoint is not None]
        if raises and not lowers:
            chosen = max(raises, key=lambda row: (row.midpoint or float("-inf"), _quality(row)))
        elif lowers and not raises:
            chosen = min(lowers, key=lambda row: row.midpoint if row.midpoint is not None else float("inf"))
        else:
            chosen = max(rows, key=_quality)
        selected.append(chosen)

    selected = _action_consistent_history(selected)
    return sorted(
        selected,
        key=lambda item: (
            item.source_timestamp,
            item.metric.value,
            item.fiscal_period,
            item.accounting_basis,
            item.source_url,
        ),
    )


def extract_guidance_facts_round8(
    document: SourceDocument,
    *,
    rules_hash: str,
) -> GuidanceExtractionResult:
    # Re-enter at Round 6 so both quarterly and annual raw records survive long
    # enough for the most-specific-scope binder to separate them.
    base = extract_guidance_facts_round6(document, rules_hash=rules_hash)
    records = [
        item
        for record in base.records
        if (item := tighten_guidance_record_round8(record)) is not None
    ]
    records = dedupe_guidance_records_round8(records)

    policy = base.policy_evidence
    if any(record.midpoint is not None for record in records):
        policy = None

    return base.model_copy(update={"records": records, "policy_evidence": policy})
