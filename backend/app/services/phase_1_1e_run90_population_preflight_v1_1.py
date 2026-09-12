from __future__ import annotations

import re
from collections import defaultdict
from typing import Iterable

from app.domain.soe_v1_1 import (
    GuidanceAction,
    GuidanceExtractionResult,
    GuidanceMetric,
    GuidanceMetricRecord,
    SourceDocument,
)
from app.services.fact_extraction_service import html_to_text
from app.services.guidance_ledger_service import GuidanceLedger
from app.services.phase_1_1e_guidance_table_dedupe_v1_1 import (
    dedupe_guidance_records_table_normalized,
)
from app.services.phase_1_1e_run88_guidance_repairs_v1_1 import extract_guidance_facts_run88
from app.services.phase_1_1e_run89_guidance_repairs_v1_1 import extract_guidance_facts_run89


# Run-90 full-population preflight repair.  This module changes evidence
# eligibility/normalization only.  It does not change any frozen SOE threshold,
# score, scanner, ranking rule, classification rule, or IEE v1.7.2 logic.
_MONEY_METRICS = {GuidanceMetric.REVENUE, GuidanceMetric.EBITDA, GuidanceMetric.FCF}
_MARGIN_METRICS = {GuidanceMetric.GROSS_MARGIN, GuidanceMetric.OPERATING_MARGIN}
_RUN89 = "phase_1_1e_run89_authoritative_forward_scope;"
_RUN90_SCALE = "phase_1_1e_run90_scale_applied="
_RUN90_SCOPE = "phase_1_1e_run90_scope_change_sensitive;"
_SCALE_MARKER = re.compile(
    r"phase_1_1e_run88_inherited_table_scale=(?P<scale>\d+(?:\.\d+)?(?:e[+-]?\d+)?)",
    re.I,
)
_RUN90_SCALE_MARKER = re.compile(
    r"phase_1_1e_run90_scale_applied=(?P<scale>\d+(?:\.\d+)?(?:e[+-]?\d+)?)",
    re.I,
)
_RAW_MONEY_RANGE = re.compile(
    r"(?P<d1>\$)?\s*(?P<lo>\d[\d,]*(?:\.\d+)?)\s*"
    r"(?:to|through|and|-|–|—)\s*"
    r"(?P<d2>\$)?\s*(?P<hi>\d[\d,]*(?:\.\d+)?)",
    re.I,
)
_EXPLICIT_SCALE = re.compile(
    r"(?:\(\s*\$?\s*in\s+|\b\$?\s*in\s+)"
    r"(?P<scale>thousands?|millions?|billions?)\s*\)?",
    re.I,
)
_SCALE = {
    "thousand": 1e3,
    "thousands": 1e3,
    "million": 1e6,
    "millions": 1e6,
    "billion": 1e9,
    "billions": 1e9,
}
_PAREN_EPS_RANGE = re.compile(
    r"(?P<lo_par>\()?\s*\$\s*(?P<lo>\d+(?:\.\d+)?)\s*(?(lo_par)\))\s*"
    r"(?:to|through|and|-|–|—)\s*"
    r"(?P<hi_par>\()?\s*\$\s*(?P<hi>\d+(?:\.\d+)?)\s*(?(hi_par)\))",
    re.I,
)
_SCOPE_CHANGE = re.compile(
    r"\b(?:discontinued\s+operations?|spin[-\s]?off|spinoff|separation)\b",
    re.I,
)
_GUIDANCE_CONTEXT = re.compile(r"\b(?:guidance|outlook|forecast|expects?|targets?)\b", re.I)

_LABELS = {
    GuidanceMetric.REVENUE: re.compile(
        r"\b(?:total\s+(?:[A-Za-z][A-Za-z0-9&.\-]*\s+){0,3}revenue"
        r"(?:\s+and\s+other\s+income)?|consolidated\s+(?:net\s+)?revenues?|"
        r"total\s+revenues?|net\s+sales|revenue)\b",
        re.I,
    ),
    GuidanceMetric.EBITDA: re.compile(r"\b(?:adjusted|non[-\s]?GAAP)?\s*EBITDA\b", re.I),
    GuidanceMetric.FCF: re.compile(r"\b(?:free\s+cash\s+flow|FCF)\b", re.I),
    GuidanceMetric.EPS: re.compile(
        r"\b(?:adjusted|non[-\s]?GAAP|GAAP)?\s*(?:earnings\s+per\s+share"
        r"(?:\s*[-–—]?\s*diluted)?|diluted\s+(?:earnings\s+per\s+share|EPS)|EPS)\b",
        re.I,
    ),
    GuidanceMetric.GROSS_MARGIN: re.compile(
        r"\b(?:adjusted|non[-\s]?GAAP|GAAP)?\s*gross\s+margin(?:\s+percentage)?\b",
        re.I,
    ),
    GuidanceMetric.OPERATING_MARGIN: re.compile(
        r"\b(?:adjusted|non[-\s]?GAAP|GAAP)?\s*operating\s+margin(?:\s+percentage)?\b",
        re.I,
    ),
}
_ANY_METRIC_LABEL = re.compile(
    r"\b(?:"
    r"total\s+(?:[A-Za-z][A-Za-z0-9&.\-]*\s+){0,3}revenue(?:\s+and\s+other\s+income)?|"
    r"consolidated\s+(?:net\s+)?revenues?|total\s+revenues?|net\s+sales|revenue|"
    r"(?:adjusted|non[-\s]?GAAP)?\s*EBITDA|"
    r"free\s+cash\s+flow|FCF|"
    r"(?:adjusted|non[-\s]?GAAP|GAAP)?\s*(?:earnings\s+per\s+share|diluted\s+EPS|EPS)|"
    r"(?:adjusted|non[-\s]?GAAP|GAAP)?\s*gross\s+margin|"
    r"(?:adjusted|non[-\s]?GAAP|GAAP)?\s*operating\s+margin|"
    r"GAAP\s+net\s+income|net\s+income|corporate\s+unallocated\s+expense|"
    r"cash\s+flow\s+from\s+operations"
    r")\b",
    re.I,
)
_RANGE_START = re.compile(
    r"\$\s*\(?\s*\d|\b\d[\d,]*(?:\.\d+)?\s*(?:%|million|billion|thousand|mm|bn)\b",
    re.I,
)
_MIXED_EPS_BASIS = re.compile(
    r"\bGAAP\b.{0,500}\b(?:adjusted|non[-\s]?GAAP)\b|"
    r"\b(?:adjusted|non[-\s]?GAAP)\b.{0,500}\bGAAP\b",
    re.I | re.S,
)


def _flat_text(document: SourceDocument) -> str:
    return re.sub(r"\s+", " ", html_to_text(document.content or "")).strip()


def _record_evidence(record: GuidanceMetricRecord) -> str:
    return re.sub(r"\s+", " ", record.evidence_span or "").strip()


def _numeric(record: GuidanceMetricRecord) -> bool:
    return record.low is not None and record.high is not None


def _explicit_action(record: GuidanceMetricRecord) -> bool:
    return record.explicit_action in {
        GuidanceAction.RAISE,
        GuidanceAction.REAFFIRM,
        GuidanceAction.LOWER,
        GuidanceAction.WITHDRAW,
    }


def _with_evidence(record: GuidanceMetricRecord, prefix: str, **updates) -> GuidanceMetricRecord:
    updates["evidence_span"] = f"{prefix} {_record_evidence(record)}"[:1000]
    return record.model_copy(update=updates)


def _nearly_equal(left: float, right: float) -> bool:
    return abs(left - right) <= max(1e-9, abs(right) * 1e-9)


def _apply_scale(record: GuidanceMetricRecord) -> GuidanceMetricRecord:
    """Apply explicit inherited table scale exactly once, even after re-deduping.

    Older evidence hardening can reconstruct an unscaled numeric range from the
    preserved source span on a later dedupe pass.  The Run-90 marker therefore
    cannot by itself prove that the current numeric values are still scaled.
    When a prior scale marker exists, compare the current values with raw dollar
    ranges retained in the immutable evidence.  Reapply only when the current
    values match a raw range; leave them unchanged when they already match the
    scaled range.  If neither relationship can be proven, fail closed by keeping
    the current record unchanged.
    """
    if record.metric not in _MONEY_METRICS or record.unit != "USD" or not _numeric(record):
        return record
    evidence = _record_evidence(record)

    applied = _RUN90_SCALE_MARKER.search(evidence)
    if applied:
        scale = float(applied.group("scale"))
        if scale == 1:
            return record
        for match in _RAW_MONEY_RANGE.finditer(evidence):
            if not (match.group("d1") or match.group("d2")):
                continue
            raw_low = float(match.group("lo").replace(",", ""))
            raw_high = float(match.group("hi").replace(",", ""))
            if raw_low > raw_high:
                continue
            scaled_low = raw_low * scale
            scaled_high = raw_high * scale
            if _nearly_equal(record.low, scaled_low) and _nearly_equal(record.high, scaled_high):
                return record
            if _nearly_equal(record.low, raw_low) and _nearly_equal(record.high, raw_high):
                return record.model_copy(
                    update={
                        "low": scaled_low,
                        "high": scaled_high,
                        "midpoint": (scaled_low + scaled_high) / 2.0,
                    }
                )
        return record

    scale: float | None = None
    marker = _SCALE_MARKER.search(evidence)
    if marker:
        scale = float(marker.group("scale"))
    elif _RUN89 in evidence:
        explicit = _EXPLICIT_SCALE.search(evidence)
        if explicit and max(abs(record.low), abs(record.high)) < 1_000_000:
            scale = _SCALE[explicit.group("scale").lower()]

    if scale is None or scale == 1:
        return record
    low = record.low * scale
    high = record.high * scale
    return _with_evidence(
        record,
        f"{_RUN90_SCALE}{scale:g};",
        low=low,
        high=high,
        midpoint=(low + high) / 2.0,
    )


def _restore_parenthesized_eps(record: GuidanceMetricRecord) -> GuidanceMetricRecord:
    if record.metric is not GuidanceMetric.EPS or not _numeric(record):
        return record
    evidence = _record_evidence(record)
    match = _PAREN_EPS_RANGE.search(evidence)
    if not match:
        return record
    lo = -float(match.group("lo")) if match.group("lo_par") else float(match.group("lo"))
    hi = -float(match.group("hi")) if match.group("hi_par") else float(match.group("hi"))
    if lo > hi:
        return record
    if abs(record.low - lo) < 1e-12 and abs(record.high - hi) < 1e-12:
        return record
    if abs(abs(record.low) - abs(lo)) > 1e-9 or abs(abs(record.high) - abs(hi)) > 1e-9:
        return record
    return _with_evidence(
        record,
        "phase_1_1e_run90_parenthesized_eps_sign_restore;",
        low=lo,
        high=hi,
        midpoint=(lo + hi) / 2.0,
    )


def _metric_locality_clean(record: GuidanceMetricRecord) -> bool:
    """Reject a Run-89 row when another metric label intervenes before its range."""
    evidence = _record_evidence(record)
    if _RUN89 not in evidence:
        return True
    tail = evidence.rsplit(";", 1)[-1]
    range_match = _RANGE_START.search(tail)
    if range_match is None:
        return False
    own = [m for m in _LABELS[record.metric].finditer(tail) if m.start() < range_match.start()]
    if not own:
        return False
    anchor = own[-1]
    between = tail[anchor.end():range_match.start()]
    return _ANY_METRIC_LABEL.search(between) is None


def _magnitude_plausible(record: GuidanceMetricRecord) -> bool:
    if record.metric not in _MONEY_METRICS or record.unit != "USD" or not _numeric(record):
        return True
    if _RUN89 not in _record_evidence(record):
        return True
    return max(abs(record.low), abs(record.high)) >= 100_000


def _basis_binding_clean(record: GuidanceMetricRecord) -> bool:
    if record.metric is not GuidanceMetric.EPS or not _numeric(record):
        return True
    if _explicit_action(record) or record.supersedes_record_id is not None:
        return True
    evidence = _record_evidence(record)
    if not _MIXED_EPS_BASIS.search(evidence):
        return True
    basis = record.accounting_basis.upper()
    if basis == "GAAP":
        return bool(re.search(r"\bGAAP\b.{0,80}\b(?:EPS|earnings\s+per\s+share)\b", evidence, re.I))
    if basis == "ADJUSTED":
        return bool(
            re.search(
                r"\b(?:adjusted|non[-\s]?GAAP)\b.{0,80}\b(?:EPS|earnings\s+per\s+share)\b",
                evidence,
                re.I,
            )
        )
    return False


def _safe_run89(record: GuidanceMetricRecord) -> bool:
    if _RUN89 not in _record_evidence(record):
        return True
    return (
        _metric_locality_clean(record)
        and _magnitude_plausible(record)
        and _basis_binding_clean(record)
    )


def _scope_change_sensitive(document: SourceDocument) -> bool:
    text = _flat_text(document)
    for match in _SCOPE_CHANGE.finditer(text):
        window = text[max(0, match.start() - 900):min(len(text), match.end() + 900)]
        if _GUIDANCE_CONTEXT.search(window):
            return True
    return False


def _mark_scope_change(record: GuidanceMetricRecord) -> GuidanceMetricRecord:
    if _RUN90_SCOPE in _record_evidence(record):
        return record
    return _with_evidence(record, _RUN90_SCOPE)


def _dedupe_exact(records: Iterable[GuidanceMetricRecord]) -> list[GuidanceMetricRecord]:
    unique: dict[tuple, GuidanceMetricRecord] = {}
    for record in records:
        key = (
            record.metric,
            record.fiscal_period,
            record.accounting_basis,
            record.low,
            record.high,
            record.source_timestamp,
            record.source_url,
            record.explicit_action,
            record.supersedes_record_id,
        )
        unique[key] = record
    return sorted(
        unique.values(),
        key=lambda r: (
            r.source_timestamp,
            r.metric.value,
            r.fiscal_period,
            r.accounting_basis,
            r.source_url,
        ),
    )


def extract_guidance_facts_run90(
    document: SourceDocument, *, rules_hash: str
) -> GuidanceExtractionResult:
    """Run-90 population-preflight extraction with conservative fallback."""
    run89 = extract_guidance_facts_run89(document, rules_hash=rules_hash)
    run88 = extract_guidance_facts_run88(document, rules_hash=rules_hash)

    processed89: list[GuidanceMetricRecord] = []
    unsafe_metrics: set[GuidanceMetric] = set()
    rejected = list(run89.rejected_candidates)
    for raw in run89.records:
        record = _restore_parenthesized_eps(_apply_scale(raw))
        if not _safe_run89(record):
            unsafe_metrics.add(record.metric)
            rejected.append(
                {
                    "reason": "phase_1_1e_run90_unsafe_run89_authoritative_binding",
                    "metric": record.metric.value,
                    "fiscal_period": record.fiscal_period,
                    "source_url": record.source_url,
                    "evidence": _record_evidence(record)[:500],
                }
            )
            continue
        processed89.append(record)

    covered = {(r.metric, r.fiscal_period) for r in processed89 if _RUN89 in _record_evidence(r)}
    restored: list[GuidanceMetricRecord] = []
    if unsafe_metrics:
        for raw in run88.records:
            if raw.metric not in unsafe_metrics:
                continue
            record = _restore_parenthesized_eps(_apply_scale(raw))
            if (record.metric, record.fiscal_period) in covered:
                continue
            restored.append(record)

    records = _dedupe_exact([*processed89, *restored])
    if _scope_change_sensitive(document):
        records = [_mark_scope_change(record) for record in records]

    policy = run89.policy_evidence
    if records:
        policy = None
    return run89.model_copy(
        update={
            "records": records,
            "policy_evidence": policy,
            "rejected_candidates": rejected,
        }
    )


def _ambiguous_same_scope(records: list[GuidanceMetricRecord]) -> set[int]:
    groups: dict[tuple, list[tuple[int, GuidanceMetricRecord]]] = defaultdict(list)
    for idx, record in enumerate(records):
        if not _numeric(record):
            continue
        key = (
            record.ticker,
            record.source_timestamp,
            record.fiscal_period,
            record.metric,
            record.accounting_basis,
        )
        groups[key].append((idx, record))

    reject: set[int] = set()
    for rows in groups.values():
        distinct = {(r.low, r.high) for _, r in rows}
        if len(distinct) <= 1:
            continue
        if any(_explicit_action(r) or r.supersedes_record_id is not None for _, r in rows):
            continue
        reject.update(idx for idx, _ in rows)
    return reject


def _same_range_cross_metric(records: list[GuidanceMetricRecord]) -> set[int]:
    groups: dict[tuple, list[tuple[int, GuidanceMetricRecord]]] = defaultdict(list)
    for idx, record in enumerate(records):
        if not _numeric(record):
            continue
        key = (
            record.ticker,
            record.source_timestamp,
            record.fiscal_period,
            record.unit,
            record.low,
            record.high,
        )
        groups[key].append((idx, record))

    reject: set[int] = set()
    for rows in groups.values():
        metrics = {r.metric for _, r in rows}
        if len(metrics) <= 1:
            continue
        if any(_explicit_action(r) or r.supersedes_record_id is not None for _, r in rows):
            continue
        clean = [(idx, r) for idx, r in rows if _metric_locality_clean(r)]
        if len(clean) == 1:
            reject.update(idx for idx, _ in rows if idx != clean[0][0])
        else:
            reject.update(idx for idx, _ in rows)
    return reject


def _annual_quarter_impossible(records: list[GuidanceMetricRecord]) -> set[int]:
    groups: dict[tuple, list[tuple[int, GuidanceMetricRecord]]] = defaultdict(list)
    for idx, record in enumerate(records):
        if (
            record.metric not in _MONEY_METRICS
            or not _numeric(record)
            or record.low <= 0
            or record.high <= 0
        ):
            continue
        match = re.fullmatch(r"(?:Q[1-4])?FY(20\d{2})", record.fiscal_period)
        if not match:
            continue
        key = (
            record.ticker,
            record.source_timestamp,
            record.metric,
            record.accounting_basis,
            match.group(1),
        )
        groups[key].append((idx, record))

    reject: set[int] = set()
    for rows in groups.values():
        annual = [(idx, r) for idx, r in rows if r.fiscal_period.startswith("FY")]
        quarter = [(idx, r) for idx, r in rows if r.fiscal_period.startswith("Q")]
        if not annual or not quarter:
            continue
        q_max = max(r.midpoint or 0 for _, r in quarter)
        for idx, record in annual:
            if _explicit_action(record) or record.supersedes_record_id is not None:
                continue
            if (record.midpoint or 0) <= q_max:
                reject.add(idx)
    return reject


def _same_eps_across_bases(records: list[GuidanceMetricRecord]) -> set[int]:
    groups: dict[tuple, list[tuple[int, GuidanceMetricRecord]]] = defaultdict(list)
    for idx, record in enumerate(records):
        if record.metric is not GuidanceMetric.EPS or not _numeric(record):
            continue
        key = (
            record.ticker,
            record.source_timestamp,
            record.fiscal_period,
            record.low,
            record.high,
        )
        groups[key].append((idx, record))

    reject: set[int] = set()
    for rows in groups.values():
        bases = {r.accounting_basis.upper() for _, r in rows}
        if len(bases) <= 1:
            continue
        if any(_explicit_action(r) or r.supersedes_record_id is not None for _, r in rows):
            continue
        reject.update(idx for idx, _ in rows)
    return reject


def dedupe_guidance_records_run90(
    records: list[GuidanceMetricRecord],
) -> list[GuidanceMetricRecord]:
    """Population-level guidance ledger sanitizer."""
    # Preserve the established Round-8/table authority semantics first. The
    # Run-90 transforms intentionally prepend audit markers, so applying them
    # before the established deduper could hide the original structured-record
    # prefix and make valid evidence look generic.
    established = dedupe_guidance_records_table_normalized(records)
    normalized = [_restore_parenthesized_eps(_apply_scale(r)) for r in established]

    prelim: list[GuidanceMetricRecord] = []
    for record in normalized:
        if not _safe_run89(record):
            continue
        if not _basis_binding_clean(record):
            continue
        prelim.append(record)

    reject = set()
    reject |= _ambiguous_same_scope(prelim)
    reject |= _same_range_cross_metric(prelim)
    reject |= _annual_quarter_impossible(prelim)
    reject |= _same_eps_across_bases(prelim)

    return [record for idx, record in enumerate(prelim) if idx not in reject]


class GuidanceLedgerRun90(GuidanceLedger):
    """Phase-1.1E ledger that fails closed across scope-changing guidance."""

    def current_and_prior(self, ticker: str, *, as_of=None):
        current, prior = super().current_and_prior(ticker, as_of=as_of)
        if not current or not prior:
            return current, prior
        combined = [*current, *prior]
        if any(_RUN90_SCOPE in _record_evidence(record) for record in combined):
            return [], []
        return current, prior
