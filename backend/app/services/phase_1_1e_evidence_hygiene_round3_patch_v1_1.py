from __future__ import annotations

import re
from collections import defaultdict

from app.domain.soe_v1_1 import GuidanceAction, GuidanceExtractionResult, GuidanceMetricRecord, SourceDocument
from app.services import guidance_extraction_hardening_v1_1 as hardened
from app.services.phase_1_1e_evidence_hygiene_round3_v1_1 import (
    _LONG_TERM_SCOPE,
    _metric_occurrences,
    _nearest_period,
    _quality,
    extract_guidance_facts_round3 as _base_guidance_extract,
    extract_hard_distress_flags_round3,
    extract_sec_catalyst_candidates_round3,
    install_binding_patch,
)

# A numeric guidance fact must have a grammatical forward bridge to the same
# metric/number. A later qualitative outlook must not convert a preceding actual
# ("revenue was ...") into quantitative guidance.
_EXPECT_PREFIX = re.compile(
    r"\b(?:expects?|anticipat(?:e|es)|project(?:s)?|forecast(?:s)?)\s+(?:approximately\s+|about\s+|"
    r"adjusted\s+|total\s+|consolidated\s+|net\s+|diluted\s+|GAAP\s+|non[-\s]?GAAP\s+)*$",
    re.I,
)
_GUIDANCE_PREFIX = re.compile(r"\b(?:guidance|outlook|forecast)\b[^.!?]{0,150}$", re.I | re.S)
_FORWARD_SUFFIX = re.compile(
    r"^\s*(?:guidance\s+)?(?:is|are|was|were)?\s*(?:now\s+)?(?:expected|forecast|projected|guided)\s+(?:to\s+be\s+)?",
    re.I,
)
_GUIDANCE_SUFFIX = re.compile(r"^\s*(?:guidance|outlook|forecast)\b", re.I)
_ACTUAL_SUFFIX = re.compile(
    r"^\s*(?:was|were|totaled|amounted\s+to|came\s+in\s+at|increased|decreased|grew|declined)\b",
    re.I,
)
_ACTION_GUIDANCE_PREFIX = re.compile(
    r"\b(?:rais(?:e|es|ed|ing)|increas(?:e|es|ed|ing)|lower(?:s|ed|ing)?|reduc(?:e|es|ed|ing)|"
    r"cut(?:s|ting)?|reaffirm(?:s|ed|ing)?|reiterat(?:e|es|ed|ing)|maintain(?:s|ed|ing)|"
    r"update(?:s|d|ing)|narrow(?:s|ed|ing))\b[^.!?]{0,100}\b(?:guidance|outlook|forecast)\b[^.!?]{0,120}$",
    re.I | re.S,
)


def _strict_candidate(record: GuidanceMetricRecord, text: str, start: int, end: int):
    prefix = text[max(0, start - 220):start]
    suffix = text[end:min(len(text), end + 260)]
    if _ACTUAL_SUFFIX.search(suffix) and not _FORWARD_SUFFIX.search(suffix):
        return None

    forward_link = bool(
        _EXPECT_PREFIX.search(prefix)
        or _GUIDANCE_PREFIX.search(prefix)
        or _ACTION_GUIDANCE_PREFIX.search(prefix)
        or _FORWARD_SUFFIX.search(suffix)
        or _GUIDANCE_SUFFIX.search(suffix)
    )
    if not forward_link:
        return None

    left = max(0, start - 320)
    right = min(len(text), end + 360)
    clause = text[left:right]
    anchor = start - left
    metric_end = end - left
    if _LONG_TERM_SCOPE.search(clause[max(0, anchor - 180):min(len(clause), metric_end + 220)]):
        return None
    period = _nearest_period(clause, anchor)
    if period is None:
        return None
    numeric = hardened._range_after_metric(clause, record.metric, metric_end=metric_end)
    if numeric is None:
        return None
    low, high, unit = numeric
    if low > high:
        return None
    return {"period": period, "low": low, "high": high, "midpoint": (low + high) / 2, "unit": unit}


def tighten_guidance_record_round3_patched(record: GuidanceMetricRecord) -> GuidanceMetricRecord | None:
    if not record.verified:
        return None
    text = (record.evidence_span or "").strip()
    if not text:
        return record
    install_binding_patch()

    occurrences = _metric_occurrences(text, record.metric)
    candidates = [item for start, end in occurrences if (item := _strict_candidate(record, text, start, end)) is not None]

    if record.midpoint is None:
        if record.explicit_action not in {GuidanceAction.RAISE, GuidanceAction.LOWER, GuidanceAction.REAFFIRM, GuidanceAction.WITHDRAW}:
            return None
        periods = []
        for start, end in occurrences:
            prefix = text[max(0, start - 220):start]
            suffix = text[end:min(len(text), end + 220)]
            if not (_EXPECT_PREFIX.search(prefix) or _GUIDANCE_PREFIX.search(prefix) or _ACTION_GUIDANCE_PREFIX.search(prefix) or _FORWARD_SUFFIX.search(suffix) or _GUIDANCE_SUFFIX.search(suffix)):
                continue
            left = max(0, start - 320)
            period = _nearest_period(text[left:min(len(text), end + 360)], start - left)
            if period:
                periods.append(period)
        unique = sorted(set(periods))
        if len(unique) != 1:
            return None
        return record.model_copy(update={"fiscal_period": unique[0]})

    if not candidates:
        return None

    if record.explicit_action is GuidanceAction.RAISE:
        chosen = max(candidates, key=lambda item: (item["midpoint"], item["period"]))
    elif record.explicit_action is GuidanceAction.LOWER:
        chosen = min(candidates, key=lambda item: (item["midpoint"], item["period"]))
    else:
        def distance(item):
            scale = max(abs(record.midpoint or 0.0), abs(item["midpoint"]), 1.0)
            return abs(item["midpoint"] - (record.midpoint or 0.0)) / scale
        chosen = min(candidates, key=lambda item: (distance(item), item["period"]))

    return record.model_copy(update={
        "fiscal_period": chosen["period"],
        "low": chosen["low"],
        "high": chosen["high"],
        "midpoint": chosen["midpoint"],
        "unit": chosen["unit"],
    })


def extract_guidance_facts_round3_patched(document: SourceDocument, *, rules_hash: str) -> GuidanceExtractionResult:
    base = _base_guidance_extract(document, rules_hash=rules_hash)
    records = [item for record in base.records if (item := tighten_guidance_record_round3_patched(record)) is not None]
    policy = base.policy_evidence
    if any(record.midpoint is not None for record in records):
        policy = None
    return base.model_copy(update={"records": records, "policy_evidence": policy})


def dedupe_guidance_records_round3_patched(records: list[GuidanceMetricRecord]) -> list[GuidanceMetricRecord]:
    grouped: dict[tuple[tuple[str, str, str], object], list[GuidanceMetricRecord]] = defaultdict(list)
    for record in records:
        tightened = tighten_guidance_record_round3_patched(record)
        if tightened is not None:
            grouped[(tightened.comparison_key, tightened.source_timestamp)].append(tightened)

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
    return sorted(selected, key=lambda item: (item.source_timestamp, item.metric.value, item.fiscal_period, item.accounting_basis, item.source_url))
