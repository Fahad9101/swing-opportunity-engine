from __future__ import annotations

import re
from collections import defaultdict

from app.domain.soe_v1_1 import GuidanceAction, GuidanceExtractionResult, GuidanceMetricRecord, SourceDocument
from app.services import guidance_extraction_hardening_v1_1 as hardened
from app.services.phase_1_1e_evidence_hygiene_round3_patch_v1_1 import (
    _ACTUAL_SUFFIX,
    _FORWARD_SUFFIX,
    _metric_occurrences,
    _nearest_period,
    extract_guidance_facts_round3_patched,
    tighten_guidance_record_round3_patched,
)
from app.services.phase_1_1e_evidence_hygiene_round3_v1_1 import _quality

# Round 4 is an evidence-binding repair only. It does not alter any SOE rule,
# threshold, score, scanner, penalty, market-regime rule, or classification logic.
#
# Two generic defects are addressed:
#   1) an explicit year attached to the metric's guidance phrase must outrank a
#      nearby historical-results fiscal-year header; and
#   2) a reported actual metric must not become guidance merely because the word
#      "guidance" occurs elsewhere in the evidence window.

_DIRECT_FORWARD_PREFIX = re.compile(
    r"\b(?:expects?|anticipat(?:e|es)|project(?:s)?|forecast(?:s)?|guides?)\b[^.!?\n]{0,90}$",
    re.I,
)
_GUIDANCE_PREFIX_LOCAL = re.compile(
    r"\b(?:guidance|outlook|forecast)\b[^.!?\n]{0,110}$",
    re.I,
)
_METRIC_GUIDANCE_SUFFIX = re.compile(
    r"^[^.!?\n]{0,45}\b(?:guidance|outlook|forecast)\b",
    re.I,
)
_ACTION_PREFIX = re.compile(
    r"\b(?:rais(?:e|es|ed|ing)|increas(?:e|es|ed|ing)|lower(?:s|ed|ing)?|"
    r"reduc(?:e|es|ed|ing)|cut(?:s|ting)?|reaffirm(?:s|ed|ing)?|"
    r"reiterat(?:e|es|ed|ing)|maintain(?:s|ed|ing)|update(?:s|d|ing)|"
    r"narrow(?:s|ed|ing))\b[^.!?\n]{0,100}$",
    re.I,
)
_ACTUAL_STRUCTURE = re.compile(
    r"\b(?:three\s+months\s+ended|six\s+months\s+ended|nine\s+months\s+ended|"
    r"quarter\s+ended|year\s+ended|financial\s+results|results\s+for\s+the|"
    r"%\s*change|summary\s+and\s+review\s+of\s+financial\s+results)\b",
    re.I,
)


def _metric_bound_period(text: str, start: int, end: int) -> str | None:
    """Return a fiscal period grammatically attached to this metric guidance.

    This deliberately recognizes constructions such as "2026 revenue guidance"
    and "EBITDA guidance for the full year 2026". Those are stronger than a
    nearby historical-results header such as "Full Year 2025 Financial Results".
    """
    prefix = text[max(0, start - 180) : start]
    suffix = text[end : min(len(text), end + 220)]

    # "maintains initial 2026 revenue guidance" / "2026 adjusted EBITDA guidance"
    match = re.search(r"\b(20\d{2})\b[\s,:;()\-–—]*$", prefix, re.I)
    if match and _METRIC_GUIDANCE_SUFFIX.search(suffix):
        return f"FY{int(match.group(1))}"

    # "FY2026 revenue guidance"
    match = re.search(r"\bFY\s*'?(20\d{2})\b[\s,:;()\-–—]*$", prefix, re.I)
    if match and _METRIC_GUIDANCE_SUFFIX.search(suffix):
        return f"FY{int(match.group(1))}"

    # "revenue guidance for 2026" / "EBITDA guidance for the full year 2026"
    match = re.search(
        r"^[^.!?\n]{0,45}\b(?:guidance|outlook|forecast)\b[^.!?\n]{0,100}?"
        r"\b(?:for\s+(?:the\s+)?)?(?:full[-\s]?year|fiscal\s+year|FY)?\s*'?(20\d{2})\b",
        suffix,
        re.I,
    )
    if match:
        return f"FY{int(match.group(1))}"

    # "2026 Outlook ... revenue" or "FY2026 guidance ... revenue" in the same
    # sentence/line. Do not cross a results paragraph boundary.
    match = re.search(
        r"\b(?:FY\s*)?(20\d{2})\s+(?:guidance|outlook|forecast)\b[^.!?\n]{0,110}$",
        prefix,
        re.I,
    )
    if match:
        return f"FY{int(match.group(1))}"

    return None


def _direct_metric_forward_relation(text: str, start: int, end: int) -> int:
    """Score whether forward wording is grammatically linked to this metric."""
    prefix = text[max(0, start - 180) : start]
    suffix = text[end : min(len(text), end + 180)]

    if _METRIC_GUIDANCE_SUFFIX.search(suffix):
        # "revenue guidance" / "adjusted EBITDA guidance" is the strongest
        # metric-specific construction. An action immediately before the metric
        # makes the directional binding stronger still.
        return 6 if _ACTION_PREFIX.search(prefix) else 5
    if _DIRECT_FORWARD_PREFIX.search(prefix):
        return 5
    if _FORWARD_SUFFIX.search(suffix):
        return 4
    if _GUIDANCE_PREFIX_LOCAL.search(prefix):
        return 3
    return 0


def _round4_candidate(record: GuidanceMetricRecord, text: str, start: int, end: int):
    relation = _direct_metric_forward_relation(text, start, end)
    if relation <= 0:
        return None

    local = text[max(0, start - 150) : min(len(text), end + 180)]
    suffix = text[end : min(len(text), end + 180)]
    # Reported-result structures are admissible only when this exact metric has
    # a direct forward relation. A bare table row such as "Revenue | $4,578"
    # therefore cannot borrow a distant guidance label from the same release.
    if (_ACTUAL_STRUCTURE.search(local) or _ACTUAL_SUFFIX.search(suffix)) and relation < 4:
        return None

    left = max(0, start - 320)
    right = min(len(text), end + 360)
    clause = text[left:right]
    metric_end = end - left

    period = _metric_bound_period(text, start, end) or _nearest_period(clause, start - left)
    if period is None:
        return None

    numeric = hardened._range_after_metric(clause, record.metric, metric_end=metric_end)
    if numeric is None:
        return None
    low, high, unit = numeric
    if low > high:
        return None
    return {
        "period": period,
        "low": low,
        "high": high,
        "midpoint": (low + high) / 2,
        "unit": unit,
        "relation": relation,
    }


def tighten_guidance_record_round4(record: GuidanceMetricRecord) -> GuidanceMetricRecord | None:
    base = tighten_guidance_record_round3_patched(record)
    if base is None:
        return None

    text = (record.evidence_span or "").strip()
    if not text or base.midpoint is None:
        return base

    candidates = []
    for start, end in _metric_occurrences(text, base.metric):
        item = _round4_candidate(base, text, start, end)
        if item is not None:
            candidates.append(item)

    if not candidates:
        # If the evidence locally looks like a reported-results structure, fail
        # closed rather than allowing a weak/distant guidance label to turn an
        # actual metric into forward guidance. Otherwise preserve the already
        # hardened Round-3 record for compatibility with compact guidance tables.
        if _ACTUAL_STRUCTURE.search(text):
            return None
        return base

    best_relation = max(item["relation"] for item in candidates)
    strongest = [item for item in candidates if item["relation"] == best_relation]

    if base.explicit_action is GuidanceAction.RAISE:
        chosen = max(strongest, key=lambda item: (item["midpoint"], item["period"]))
    elif base.explicit_action is GuidanceAction.LOWER:
        chosen = min(strongest, key=lambda item: (item["midpoint"], item["period"]))
    else:
        def distance(item):
            scale = max(abs(base.midpoint or 0.0), abs(item["midpoint"]), 1.0)
            return abs(item["midpoint"] - (base.midpoint or 0.0)) / scale
        chosen = min(strongest, key=lambda item: (distance(item), item["period"]))

    return base.model_copy(update={
        "fiscal_period": chosen["period"],
        "low": chosen["low"],
        "high": chosen["high"],
        "midpoint": chosen["midpoint"],
        "unit": chosen["unit"],
    })


def _action_consistent_history(records: list[GuidanceMetricRecord]) -> list[GuidanceMetricRecord]:
    """Fail closed on impossible directional transitions for the same key."""
    by_ticker_key: dict[tuple[str, tuple[str, str, str]], list[GuidanceMetricRecord]] = defaultdict(list)
    for item in records:
        by_ticker_key[(item.ticker, item.comparison_key)].append(item)

    kept: list[GuidanceMetricRecord] = []
    for rows in by_ticker_key.values():
        history: list[GuidanceMetricRecord] = []
        for row in sorted(rows, key=lambda item: (item.source_timestamp, item.source_url)):
            prior_numeric = [item for item in history if item.midpoint is not None]
            prior = prior_numeric[-1] if prior_numeric else None
            inconsistent = False
            if prior is not None and row.midpoint is not None:
                if row.explicit_action is GuidanceAction.RAISE and row.midpoint < prior.midpoint:
                    inconsistent = True
                elif row.explicit_action is GuidanceAction.LOWER and row.midpoint > prior.midpoint:
                    inconsistent = True
            if not inconsistent:
                kept.append(row)
                history.append(row)
    return kept


def dedupe_guidance_records_round4(records: list[GuidanceMetricRecord]) -> list[GuidanceMetricRecord]:
    # Do not call the Round-3 deduper here: it re-runs the Round-3 period binder
    # and could undo a stronger Round-4 metric-bound period correction.
    tightened = [item for record in records if (item := tighten_guidance_record_round4(record)) is not None]
    grouped: dict[tuple[tuple[str, str, str], object], list[GuidanceMetricRecord]] = defaultdict(list)
    for item in tightened:
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
        key=lambda item: (item.source_timestamp, item.metric.value, item.fiscal_period, item.accounting_basis, item.source_url),
    )


def extract_guidance_facts_round4(document: SourceDocument, *, rules_hash: str) -> GuidanceExtractionResult:
    base = extract_guidance_facts_round3_patched(document, rules_hash=rules_hash)
    records = [item for record in base.records if (item := tighten_guidance_record_round4(record)) is not None]
    records = dedupe_guidance_records_round4(records)
    policy = base.policy_evidence
    if any(record.midpoint is not None for record in records):
        policy = None
    return base.model_copy(update={"records": records, "policy_evidence": policy})
