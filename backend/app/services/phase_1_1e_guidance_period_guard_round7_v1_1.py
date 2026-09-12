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

# Round 7 repairs one evidence-binding defect discovered by the independent
# full-market audit: explicit annual guidance periods such as
# "full-year 2025 global ARIKAYCE revenue guidance" must remain FY2025 even
# when unrelated 2026 clinical/regulatory milestones occur nearby in the same
# SEC release.
#
# This module changes evidence binding only. It does not alter any SOE rule,
# threshold, score, weight, scanner, classifier, technical rule, or penalty.

_GUIDANCE_AFTER_METRIC = re.compile(
    r"^[^.!?\n]{0,70}\b(?:guidance|outlook|forecast)\b",
    re.I,
)
_GUIDANCE_BEFORE_METRIC = re.compile(
    r"\b(?:guidance|outlook|forecast)\b[^.!?\n]{0,90}$",
    re.I,
)


def _same_clause_periods(text: str, start: int, end: int) -> set[str]:
    """Return annual fiscal periods grammatically bound to this metric.

    The search never crosses a sentence/newline boundary. It deliberately allows
    issuer/product descriptors between the annual period and metric, e.g.:

      "full-year 2025 global ARIKAYCE revenue guidance"
      "2026 global ARIKAYCE revenue guidance"
      "revenue guidance for full-year 2026"

    A bare year is accepted only when the same clause also binds this exact
    metric to guidance/outlook/forecast wording. This prevents unrelated trial
    dates, historical table columns, and release dates from becoming a guidance
    fiscal period.
    """
    left = max(0, start - 180)
    right = min(len(text), end + 190)
    prefix = text[left:start]
    suffix = text[end:right]

    metric_has_guidance_after = bool(_GUIDANCE_AFTER_METRIC.search(suffix))
    metric_has_guidance_before = bool(_GUIDANCE_BEFORE_METRIC.search(prefix))
    periods: set[str] = set()

    if metric_has_guidance_after:
        # Strong annual forms before the metric. Up to 100 non-sentence chars are
        # allowed so product/geography descriptors do not break the binding.
        for match in re.finditer(
            r"\b(?:full[-\s]?year|fiscal(?:\s+year)?|FY)\s*'?((?:20)?\d{2})\b[^.!?\n]{0,100}$",
            prefix,
            re.I,
        ):
            year = int(match.group(1))
            if year < 100:
                year += 2000
            periods.add(f"FY{year}")

        # Bare year form, e.g. "2026 global ARIKAYCE revenue guidance". Require
        # the year to be relatively close and reject table-like numeric context.
        for match in re.finditer(r"\b(20\d{2})\b[^.!?\n]{0,80}$", prefix, re.I):
            between = prefix[match.end():]
            if re.search(r"[$%]|\b(?:three|six|nine)\s+months?\s+ended\b|\bquarter\s+ended\b", between, re.I):
                continue
            periods.add(f"FY{int(match.group(1))}")

    if metric_has_guidance_after or metric_has_guidance_before:
        # Period after "metric guidance", e.g. "revenue guidance for full-year
        # 2026" or "revenue outlook for fiscal year 2026".
        for match in re.finditer(
            r"^[^.!?\n]{0,90}\b(?:guidance|outlook|forecast)\b[^.!?\n]{0,80}?"
            r"\b(?:for\s+(?:the\s+)?)?(?:full[-\s]?year|fiscal(?:\s+year)?|FY)?\s*'?(20\d{2})\b",
            suffix,
            re.I,
        ):
            periods.add(f"FY{int(match.group(1))}")

    return periods


def _metric_bound_annual_periods(record: GuidanceMetricRecord, text: str) -> set[str]:
    periods: set[str] = set()
    for start, end in _metric_occurrences(text, record.metric):
        periods.update(_same_clause_periods(text, start, end))
    return periods


def tighten_guidance_record_round7(record: GuidanceMetricRecord) -> GuidanceMetricRecord | None:
    base = tighten_guidance_record_round6(record)
    if base is None:
        return None

    text = (record.evidence_span or "").strip()
    if not text:
        return base

    periods = _metric_bound_annual_periods(base, text)
    if len(periods) > 1:
        # Multiple distinct annual scopes bound to the same metric in one record
        # are ambiguous; do not manufacture a current/prior relation.
        return None
    if len(periods) == 1:
        period = next(iter(periods))
        return base.model_copy(update={"fiscal_period": period})
    return base


def dedupe_guidance_records_round7(records: list[GuidanceMetricRecord]) -> list[GuidanceMetricRecord]:
    """Deduplicate already-corrected records without re-running old binders."""
    corrected = [
        item
        for record in records
        if (item := tighten_guidance_record_round7(record)) is not None
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


def extract_guidance_facts_round7(
    document: SourceDocument,
    *,
    rules_hash: str,
) -> GuidanceExtractionResult:
    base = extract_guidance_facts_round6(document, rules_hash=rules_hash)
    records = [
        item
        for record in base.records
        if (item := tighten_guidance_record_round7(record)) is not None
    ]
    records = dedupe_guidance_records_round7(records)

    policy = base.policy_evidence
    if any(record.midpoint is not None for record in records):
        policy = None

    return base.model_copy(update={"records": records, "policy_evidence": policy})
