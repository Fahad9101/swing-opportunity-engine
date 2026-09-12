from __future__ import annotations

import re
from typing import Iterable

from app.domain.soe_v1_1 import GuidanceExtractionResult, GuidanceMetric, GuidanceMetricRecord, SourceDocument
from app.services.phase_1_1e_run90_population_preflight_v1_1 import (
    GuidanceLedgerRun90,
    dedupe_guidance_records_run90,
    extract_guidance_facts_run90,
)


# Run-94 final-acceptance evidence repair. This layer is deliberately limited to
# evidence integrity. It does not change any SOE threshold, score, scanner,
# ranking/classification rule, frozen SOE-1.0.0 rule, or IEE v1.7.2 logic.
_REBIND = re.compile(
    r"phase_1_1e_run88_period_rebind;\s*from=(?P<from>[^;]+);\s*to=(?P<to>[^;]+);",
    re.I,
)
_RUN88_SCALE = re.compile(
    r"phase_1_1e_run88_inherited_table_scale=(?P<scale>\d+(?:\.\d+)?(?:e[+-]?\d+)?)",
    re.I,
)
_RUN90_SCALE = re.compile(
    r"phase_1_1e_run90_scale_applied=(?P<scale>\d+(?:\.\d+)?(?:e[+-]?\d+)?)",
    re.I,
)
_RAW_RANGE = re.compile(
    r"(?P<d1>\$)?\s*(?P<lo>\d[\d,]*(?:\.\d+)?)\s*"
    r"(?:to|through|and|-|–|—)\s*"
    r"(?P<d2>\$)?\s*(?P<hi>\d[\d,]*(?:\.\d+)?)",
    re.I,
)
_QUARTER_WORD = {"first": 1, "second": 2, "third": 3, "fourth": 4}
_MONEY = {GuidanceMetric.REVENUE, GuidanceMetric.EBITDA, GuidanceMetric.FCF}

_LABELS = {
    GuidanceMetric.REVENUE: re.compile(
        r"\b(?:total\s+(?:[A-Za-z][A-Za-z0-9&.\-]*\s+){0,3}revenue(?:\s+and\s+other\s+income)?|"
        r"consolidated\s+(?:net\s+)?revenues?|total\s+revenues?|net\s+sales|revenue)\b",
        re.I,
    ),
    GuidanceMetric.EBITDA: re.compile(r"\b(?:adjusted|non[-\s]?GAAP)?\s*EBITDA\b", re.I),
    GuidanceMetric.FCF: re.compile(r"\b(?:free\s+cash\s+flow|FCF)\b", re.I),
    GuidanceMetric.EPS: re.compile(
        r"\b(?:adjusted|non[-\s]?GAAP|GAAP)?\s*(?:earnings\s+per\s+share(?:\s*[-–—]?\s*diluted)?|"
        r"diluted\s+(?:earnings\s+per\s+share|EPS)|EPS)\b",
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

_ANNUAL_PATTERNS = (
    re.compile(r"\b(?P<year>20\d{2})\s+(?:full[- ]year|annual)(?:\s+financial)?\s+(?:guidance|outlook)\b", re.I),
    re.compile(r"\b(?:full[- ]year|fiscal\s+year|FY)\s*(?P<year>20\d{2})\s+(?:guidance|outlook)\b", re.I),
    re.compile(r"\b(?:guidance|outlook)\s+(?:for\s+)?(?:full[- ]year|fiscal\s+year|FY)\s*(?P<year>20\d{2})\b", re.I),
)
_QUARTER_PATTERNS = (
    re.compile(r"\bQ(?P<q>[1-4])\s*(?:FY)?\s*(?P<year>20\d{2})\s+(?:guidance|outlook)\b", re.I),
    re.compile(
        r"\b(?P<year>20\d{2})\s+(?P<word>first|second|third|fourth)\s+quarter\s+(?:guidance|outlook)\b",
        re.I,
    ),
    re.compile(
        r"\b(?P<word>first|second|third|fourth)\s+quarter(?:\s+of)?(?:\s+fiscal(?:\s+year)?)?\s+"
        r"(?P<year>20\d{2})\s+(?:guidance|outlook)\b",
        re.I,
    ),
)


def _evidence(record: GuidanceMetricRecord) -> str:
    return re.sub(r"\s+", " ", record.evidence_span or "").strip()


def _nearly_equal(left: float, right: float) -> bool:
    return abs(left - right) <= max(1e-8, abs(right) * 1e-8)


def _explicit_periods(text: str) -> set[str]:
    periods: set[str] = set()
    for pattern in _ANNUAL_PATTERNS:
        for match in pattern.finditer(text):
            periods.add(f"FY{match.group('year')}")
    for pattern in _QUARTER_PATTERNS:
        for match in pattern.finditer(text):
            q = match.groupdict().get("q")
            word = match.groupdict().get("word")
            quarter = int(q) if q else _QUARTER_WORD[word.lower()]
            periods.add(f"Q{quarter}FY{match.group('year')}")
    return periods


def _repair_period(record: GuidanceMetricRecord) -> tuple[GuidanceMetricRecord | None, str | None]:
    """Make explicit issuer period language authoritative; otherwise fail closed.

    Run-88's nearest-preceding-period heuristic can bind an annual row to a
    nearby quarter header. A single explicit issuer phrase such as "2025
    Full-Year Guidance" or "Q4 2025 Guidance" is stronger evidence than that
    heuristic and becomes authoritative here. If a changed Run-88 rebind has no
    unambiguous explicit period in its preserved evidence, the row is excluded
    rather than guessed.
    """
    text = _evidence(record)
    explicit = _explicit_periods(text)
    if len(explicit) == 1:
        authoritative = next(iter(explicit))
        if authoritative == record.fiscal_period:
            return record, None
        return (
            record.model_copy(
                update={
                    "fiscal_period": authoritative,
                    "evidence_span": (
                        f"phase_1_1e_run94_explicit_period_authority; "
                        f"from={record.fiscal_period}; to={authoritative}; {record.evidence_span or ''}"
                    )[:1000],
                }
            ),
            None,
        )

    changed_rebind = [
        match
        for match in _REBIND.finditer(text)
        if match.group("from").strip() != match.group("to").strip()
    ]
    if changed_rebind:
        return None, "ambiguous_run88_period_rebind_without_single_explicit_issuer_period"

    if len(explicit) > 1 and record.fiscal_period not in explicit:
        return None, "conflicting_explicit_issuer_periods"
    return record, None


def _scale(record: GuidanceMetricRecord) -> float | None:
    text = _evidence(record)
    matches = list(_RUN90_SCALE.finditer(text))
    if matches:
        return float(matches[-1].group("scale"))
    matches = list(_RUN88_SCALE.finditer(text))
    if matches:
        return float(matches[-1].group("scale"))
    return None


def _nearest_metric_before(text: str, position: int, *, max_distance: int = 260) -> GuidanceMetric | None:
    best: tuple[int, GuidanceMetric] | None = None
    start = max(0, position - max_distance)
    window = text[start:position]
    for metric, pattern in _LABELS.items():
        for match in pattern.finditer(window):
            absolute_end = start + match.end()
            distance = position - absolute_end
            if best is None or distance < best[0]:
                best = (distance, metric)
    return best[1] if best else None


def _scaled_table_metric_locality_clean(record: GuidanceMetricRecord) -> bool:
    """Verify that a scaled table range belongs to the record's own metric.

    This closes the Celestica failure where an adjusted-EPS range in a flattened
    table inherited the revenue table scale and was persisted as revenue.
    """
    if record.metric not in _MONEY or record.low is None or record.high is None:
        return True
    scale = _scale(record)
    if scale is None or scale <= 0:
        return True

    text = _evidence(record)
    candidates = [(record.low, record.high)]
    if scale != 1:
        candidates.append((record.low / scale, record.high / scale))

    matched_range = False
    for match in _RAW_RANGE.finditer(text):
        low = float(match.group("lo").replace(",", ""))
        high = float(match.group("hi").replace(",", ""))
        if low > high:
            continue
        if not any(_nearly_equal(low, want_low) and _nearly_equal(high, want_high) for want_low, want_high in candidates):
            continue
        matched_range = True
        if _nearest_metric_before(text, match.start()) is record.metric:
            return True
    return not matched_range and False


def _sanitize_after_run90(
    records: Iterable[GuidanceMetricRecord],
) -> tuple[list[GuidanceMetricRecord], list[dict]]:
    established = dedupe_guidance_records_run90(list(records))
    accepted: list[GuidanceMetricRecord] = []
    rejected: list[dict] = []
    for original in established:
        record, period_reason = _repair_period(original)
        if record is None:
            rejected.append(
                {
                    "reason": f"phase_1_1e_run94_{period_reason}",
                    "metric": original.metric.value,
                    "fiscal_period": original.fiscal_period,
                    "source_url": original.source_url,
                    "evidence": _evidence(original)[:500],
                }
            )
            continue
        if not _scaled_table_metric_locality_clean(record):
            rejected.append(
                {
                    "reason": "phase_1_1e_run94_scaled_table_metric_locality_mismatch",
                    "metric": record.metric.value,
                    "fiscal_period": record.fiscal_period,
                    "source_url": record.source_url,
                    "evidence": _evidence(record)[:500],
                }
            )
            continue
        accepted.append(record)

    # Period correction can place formerly separated rows into the same scope;
    # re-run the established fail-closed population sanitizer after correction.
    return dedupe_guidance_records_run90(accepted), rejected


def dedupe_guidance_records_run94(records: list[GuidanceMetricRecord]) -> list[GuidanceMetricRecord]:
    cleaned, _ = _sanitize_after_run90(records)
    return cleaned


def extract_guidance_facts_run94(
    document: SourceDocument, *, rules_hash: str
) -> GuidanceExtractionResult:
    result = extract_guidance_facts_run90(document, rules_hash=rules_hash)
    records, rejected = _sanitize_after_run90(result.records)
    policy = result.policy_evidence if not records else None
    return result.model_copy(
        update={
            "records": records,
            "policy_evidence": policy,
            "rejected_candidates": [*result.rejected_candidates, *rejected],
        }
    )


class GuidanceLedgerRun94(GuidanceLedgerRun90):
    """Run-94 acceptance ledger; classification rules remain unchanged."""

    pass
