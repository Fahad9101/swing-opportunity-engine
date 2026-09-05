from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime

from app.domain.soe_v1_1 import (
    ExtractionMethod,
    GuidanceAction,
    GuidanceExtractionResult,
    GuidanceMetric,
    GuidanceMetricRecord,
    SourceDocument,
)
from app.services.fact_extraction_service import html_to_text
from app.services.phase_1_1e_evidence_hygiene_round4_v1_1 import _action_consistent_history
from app.services.phase_1_1e_guidance_scope_guard_round8_v1_1 import extract_guidance_facts_round8

# Architectural evidence-layer normalization for comparative guidance tables.
#
# Primary-source presentations frequently flatten a table into text such as:
#
#   Full Year 2026 Guidance Update ($ in millions)
#   Prior Guide Updated Guide
#   $5,575 to $5,925 $5,800 to $6,000 Net Sales
#   $5,750 Midpoint $5,900 Midpoint
#   $600 to $750 $600 to $700 Net Income
#   ...
#
# Generic prose extraction is unsafe here because:
#   * row values inherit units from a table-level header; and
#   * a metric label may sit after its two ranges, so a generic "range after
#     metric" routine can bind the next row's values to the current metric.
#
# This module first normalizes the table into metric-scoped structured facts.
# Those facts override conflicting generic records from the same document for
# the same metric/fiscal scope before the Guidance Ledger sees them.
#
# No SOE threshold, score, weight, scanner, classifier, technical rule,
# catalyst rule, market-regime rule, SOE-1.0.0 rule, or IEE logic is changed.

_COMPARATIVE_HEADER = re.compile(
    r"\b(?:prior|previous)\s+(?:guide|guidance)\b.{0,140}?"
    r"\b(?:updated|current|revised)\s+(?:guide|guidance)\b",
    re.I | re.S,
)
_TABLE_SCALE = re.compile(
    r"\$\s*(?:values?\s*)?(?:in\s+)?(thousands?|millions?|billions?)\b",
    re.I,
)
_EXACT_DATE = re.compile(
    r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|"
    r"Dec(?:ember)?)\.?\s+\d{1,2},?\s+20\d{2}\b",
    re.I,
)
_QUARTER_SCOPE = re.compile(
    r"\bQ([1-4])\s*(?:FY|fiscal(?:\s+year)?)?\s*'?((?:20)?\d{2})\b",
    re.I,
)
_QUARTER_WORD_SCOPE = re.compile(
    r"\b(first|second|third|fourth)\s+quarter(?:\s+of)?\s+"
    r"(?:(?:FY|fiscal(?:\s+year)?)\s*)?'?((?:20)?\d{2})\b",
    re.I,
)
_ANNUAL_SCOPE = re.compile(
    r"\b(?:full[-\s]?year|fiscal(?:\s+year)?|FY)\s*'?((?:20)?\d{2})\b",
    re.I,
)
_YEAR_ENDING_SCOPE = re.compile(
    r"\byear\s+ending\s+[A-Za-z]+\s+\d{1,2},?\s*(20\d{2})\b",
    re.I,
)
_QUARTER_WORDS = {"first": 1, "second": 2, "third": 3, "fourth": 4}

_SCALE = {
    "thousand": 1_000.0,
    "thousands": 1_000.0,
    "million": 1_000_000.0,
    "millions": 1_000_000.0,
    "billion": 1_000_000_000.0,
    "billions": 1_000_000_000.0,
    "k": 1_000.0,
    "m": 1_000_000.0,
    "mm": 1_000_000.0,
    "b": 1_000_000_000.0,
    "bn": 1_000_000_000.0,
}

_METRIC_ALIASES: list[tuple[GuidanceMetric, tuple[str, ...]]] = [
    (GuidanceMetric.FCF, ("adjusted free cash flow", "free cash flow", "fcf")),
    (GuidanceMetric.OPERATING_MARGIN, ("adjusted operating margin", "operating margin")),
    (GuidanceMetric.GROSS_MARGIN, ("adjusted gross margin", "gross margin")),
    (GuidanceMetric.EBITDA, ("adjusted ebitda", "ebitda")),
    (
        GuidanceMetric.EPS,
        (
            "adjusted diluted earnings per share",
            "adjusted earnings per share",
            "diluted earnings per share",
            "adjusted diluted eps",
            "adjusted eps",
            "diluted eps",
            "eps",
        ),
    ),
    (GuidanceMetric.REVENUE, ("consolidated net sales", "total net sales", "net sales", "total revenue", "revenue")),
]

_DOLLAR_RANGE = re.compile(
    r"(?P<d1>\$)?\s*(?P<low>\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<s1>billions?|millions?|thousands?|bn|mm|[bmk])?\s*"
    r"(?:to|through|and|-|–|—)\s*"
    r"(?P<d2>\$)?\s*(?P<high>\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<s2>billions?|millions?|thousands?|bn|mm|[bmk])?",
    re.I,
)
_PERCENT_RANGE = re.compile(
    r"(?P<low>\d{1,3}(?:\.\d+)?)\s*%\s*(?:to|through|and|-|–|—)\s*"
    r"(?P<high>\d{1,3}(?:\.\d+)?)\s*%",
    re.I,
)

_FINANCIAL_ROW_BOUNDARY = re.compile(
    r"\b(?:gross\s+bookings|bookings|operating\s+profit|net\s+(?:income|loss)|"
    r"cash(?:\s+and\s+cash\s+equivalents)?\s+(?:provided\s+by|from)\s+operating\s+activities|"
    r"capital\s+expenditures?|adjusted\s+ebitda|ebitda|free\s+cash\s+flow|fcf|"
    r"total\s+revenue|revenue|net\s+sales|sales|adjusted\s+eps|diluted\s+eps|eps|"
    r"gross\s+margin|operating\s+margin)\b",
    re.I,
)
_TABLE_SECTION_END = re.compile(
    r"\b(?:reconciliations?(?:\s+and\s+other)?|quarterly\s+revenue|"
    r"GAAP\s+to\s+non[-\s]?GAAP|non[-\s]?GAAP\s+reconciliations?|"
    r"forward[-\s]?looking\s+statements?|conference\s+call|quarterly\s+dividend|appendix)\b",
    re.I,
)


@dataclass(frozen=True)
class _Mention:
    metric: GuidanceMetric
    alias: str
    start: int
    end: int


@dataclass(frozen=True)
class _Range:
    low: float
    high: float
    unit: str
    start: int
    end: int


def _normalize_year(token: str) -> int:
    year = int(token)
    return year + 2000 if year < 100 else year


def _scopes(context: str) -> set[str]:
    """Return every explicit quarter/annual fiscal scope in a table header."""
    result: set[str] = set()
    quarter_spans: list[tuple[int, int]] = []
    for match in _QUARTER_SCOPE.finditer(context):
        result.add(f"Q{match.group(1)}FY{_normalize_year(match.group(2))}")
        quarter_spans.append(match.span())
    for match in _QUARTER_WORD_SCOPE.finditer(context):
        result.add(f"Q{_QUARTER_WORDS[match.group(1).lower()]}FY{_normalize_year(match.group(2))}")
        quarter_spans.append(match.span())
    for match in _ANNUAL_SCOPE.finditer(context):
        if any(match.start() < end and match.end() > start for start, end in quarter_spans):
            continue
        result.add(f"FY{_normalize_year(match.group(1))}")
    for match in _YEAR_ENDING_SCOPE.finditer(context):
        result.add(f"FY{int(match.group(1))}")
    return result


def _table_scale(context: str) -> float | None:
    matches = list(_TABLE_SCALE.finditer(context))
    if not matches:
        return None
    return _SCALE.get(matches[-1].group(1).lower())


def _parse_exact_date(token: str, *, tzinfo) -> datetime | None:
    cleaned = token.replace(".", "").replace(",", "")
    for pattern in ("%B %d %Y", "%b %d %Y"):
        try:
            parsed = datetime.strptime(cleaned, pattern)
            return parsed.replace(tzinfo=tzinfo or UTC)
        except ValueError:
            continue
    return None


def _comparative_dates(context: str, document_timestamp: datetime) -> tuple[datetime, datetime] | None:
    """Return verified prior/current table dates without inventing precision.

    Comparative presentations often print two exact dates immediately around
    the Prior Guide / Updated Guide headers.  The first date is accepted as the
    prior effective date only when the second date agrees with the primary
    document timestamp (allowing a short SEC filing delay).  Month-only or
    otherwise ambiguous headers remain unpaired and therefore fail closed.
    """
    dates = [
        parsed
        for match in _EXACT_DATE.finditer(context)
        if (parsed := _parse_exact_date(match.group(0), tzinfo=document_timestamp.tzinfo)) is not None
    ]
    if len(dates) < 2:
        return None
    prior, updated = dates[-2], dates[-1]
    if prior >= updated:
        return None
    if abs((updated.date() - document_timestamp.date()).days) > 7:
        return None
    return prior, updated


def _metric_mentions(text: str) -> list[_Mention]:
    raw: list[_Mention] = []
    for metric, aliases in _METRIC_ALIASES:
        for alias in sorted(aliases, key=len, reverse=True):
            for match in re.finditer(rf"\b{re.escape(alias)}\b", text, re.I):
                # Comparative table normalization intentionally ignores obvious
                # segment/product revenue rows. The SOE guidance gate is company-level.
                if metric is GuidanceMetric.REVENUE:
                    local = text[max(0, match.start() - 55) : min(len(text), match.end() + 55)]
                    if re.search(r"\b(?:segment|product|service)\b", local, re.I):
                        continue
                raw.append(_Mention(metric, alias, match.start(), match.end()))
    raw.sort(key=lambda item: (item.start, -(item.end - item.start)))
    result: list[_Mention] = []
    for item in raw:
        if any(not (item.end <= old.start or item.start >= old.end) for old in result):
            continue
        result.append(item)
    return sorted(result, key=lambda item: item.start)


def _amount(token: str, scale_token: str | None, table_scale: float | None) -> float:
    value = float(token.replace(",", ""))
    if scale_token:
        value *= _SCALE.get(scale_token.lower(), 1.0)
    elif table_scale is not None:
        value *= table_scale
    return value


def _ranges(text: str, metric: GuidanceMetric, table_scale: float | None) -> list[_Range]:
    result: list[_Range] = []
    if metric in {GuidanceMetric.GROSS_MARGIN, GuidanceMetric.OPERATING_MARGIN}:
        for match in _PERCENT_RANGE.finditer(text):
            low = float(match.group("low")) / 100.0
            high = float(match.group("high")) / 100.0
            if low <= high:
                result.append(_Range(low, high, "fraction", match.start(), match.end()))
        return result

    for match in _DOLLAR_RANGE.finditer(text):
        # Require a dollar sign or an explicit scale. This avoids treating dates,
        # year labels, and midpoint-to-midpoint prose as monetary ranges.
        if not (match.group("d1") or match.group("d2") or match.group("s1") or match.group("s2")):
            continue
        if metric is GuidanceMetric.EPS:
            low = float(match.group("low").replace(",", ""))
            high = float(match.group("high").replace(",", ""))
            if low <= high:
                result.append(_Range(low, high, "USD/share", match.start(), match.end()))
            continue

        row_scale = table_scale
        if match.group("s1") or match.group("s2"):
            row_scale = None
        low = _amount(match.group("low"), match.group("s1") or match.group("s2"), row_scale)
        high = _amount(match.group("high"), match.group("s2") or match.group("s1"), row_scale)
        # For company-level money metrics, an unscaled bare range is ambiguous.
        if table_scale is None and not (match.group("s1") or match.group("s2")):
            continue
        if low <= high:
            result.append(_Range(low, high, "USD", match.start(), match.end()))
    return result


def _pair_for_metric(
    text: str,
    mentions: list[_Mention],
    index: int,
    table_scale: float | None,
) -> tuple[_Range, _Range, str] | None:
    mention = mentions[index]
    previous_end = mentions[index - 1].end if index > 0 else 0
    next_start = mentions[index + 1].start if index + 1 < len(mentions) else len(text)

    prefix = text[previous_end : mention.start]
    suffix = text[mention.end : next_start]
    prefix_ranges = _ranges(prefix, mention.metric, table_scale)
    suffix_ranges = _ranges(suffix, mention.metric, table_scale)

    candidates: list[tuple[int, _Range, _Range, str]] = []
    if len(prefix_ranges) >= 2:
        prior, current = prefix_ranges[-2], prefix_ranges[-1]
        distance = len(prefix) - current.end
        candidates.append((distance, prior, current, "values_before_metric"))
    if len(suffix_ranges) >= 2:
        prior, current = suffix_ranges[0], suffix_ranges[1]
        distance = prior.start
        candidates.append((distance, prior, current, "values_after_metric"))

    if not candidates:
        return None
    distance, prior, current, layout = min(candidates, key=lambda item: item[0])
    # Fail closed when the pair is not locally attached to the metric row.
    if distance > 120:
        return None
    return prior, current, layout


def _range_matches_record(candidate: _Range, record: GuidanceMetricRecord) -> bool:
    if record.low is None or record.high is None:
        return False
    scale = max(abs(record.low), abs(record.high), abs(candidate.low), abs(candidate.high), 1.0)
    tolerance = scale * 1e-9
    return abs(candidate.low - record.low) <= tolerance and abs(candidate.high - record.high) <= tolerance


def _unscaled_dollar_ranges(text: str) -> list[_Range]:
    """Return explicit dollar ranges without guessing their economic scale.

    These candidates are used only to validate whether a pre-existing prose
    record crossed a metric-row boundary.  They are never emitted as guidance
    facts, so matching raw values does not manufacture a unit or scale.
    """
    result: list[_Range] = []
    for match in _DOLLAR_RANGE.finditer(text):
        if not (match.group("d1") or match.group("d2")):
            continue
        if match.group("s1") or match.group("s2"):
            continue
        low = float(match.group("low").replace(",", ""))
        high = float(match.group("high").replace(",", ""))
        if low <= high:
            result.append(_Range(low, high, "UNSCALED_USD", match.start(), match.end()))
    return result


def _metric_spans(text: str, metric: GuidanceMetric) -> list[tuple[int, int]]:
    aliases = next(aliases for item, aliases in _METRIC_ALIASES if item is metric)
    spans: list[tuple[int, int]] = []
    for alias in sorted(aliases, key=len, reverse=True):
        spans.extend(
            (match.start(), match.end())
            for match in re.finditer(rf"\b{re.escape(alias)}\b", text, re.I)
        )
    return sorted(spans)


def _record_has_metric_local_range(record: GuidanceMetricRecord) -> bool:
    """Require a numeric record to stay inside its financial-metric row.

    The prose extractor operates on bounded sliding windows so that flattened
    SEC tables remain readable.  A window can still contain several rows.  A
    range is admissible only when at least one occurrence of the claimed metric
    reaches that exact range without crossing another financial row label.

    Structured comparative-table records already have explicit row binding and
    are validated separately by ``_pair_for_metric``.
    """
    if record.extraction_method is ExtractionMethod.STRUCTURED or record.low is None or record.high is None:
        return True
    text = (record.evidence_span or "").strip()
    if not text:
        return True

    candidates = [*_ranges(text, record.metric, table_scale=None), *_unscaled_dollar_ranges(text)]
    matching_ranges = [
        candidate
        for candidate in candidates
        if _range_matches_record(candidate, record)
    ]
    if not matching_ranges:
        # This guard only adjudicates explicit ranges.  Scalar and qualitative
        # records continue through the existing evidence-hygiene pipeline.
        return True

    spans = _metric_spans(text, record.metric)
    for candidate in matching_ranges:
        for start, end in spans:
            if candidate.start >= end:
                distance = candidate.start - end
                bridge = text[end:candidate.start]
            elif start >= candidate.end:
                distance = start - candidate.end
                bridge = text[candidate.end:start]
            else:
                distance = 0
                bridge = ""
            if distance <= 260 and not _FINANCIAL_ROW_BOUNDARY.search(bridge):
                return True
    return False


def _basis(metric: GuidanceMetric, alias: str) -> str:
    if metric is GuidanceMetric.REVENUE:
        return "UNSPECIFIED"
    if "adjusted" in alias.lower():
        return "ADJUSTED"
    return "UNSPECIFIED"


def _direction(prior: _Range, current: _Range) -> GuidanceAction:
    prior_mid = (prior.low + prior.high) / 2.0
    current_mid = (current.low + current.high) / 2.0
    tolerance = max(abs(prior_mid), abs(current_mid), 1.0) * 1e-12
    if current_mid > prior_mid + tolerance:
        return GuidanceAction.RAISE
    if current_mid < prior_mid - tolerance:
        return GuidanceAction.LOWER
    return GuidanceAction.REAFFIRM


def normalize_comparative_guidance_tables(
    document: SourceDocument,
    *,
    rules_hash: str,
) -> list[GuidanceMetricRecord]:
    """Normalize primary-source prior-vs-updated guidance tables.

    When the table supplies two verified exact dates, emit both the quoted prior
    range and the updated range at the primary document's availability timestamp,
    linking the updated record to the quoted prior through ``supersedes_record_id``.
    The prior effective date remains explicit in evidence without back-dating a
    fact to before the source document was available. If exact dates cannot be
    verified, emit only the updated row and let the ledger fail closed unless an
    independently dated prior primary-source record exists.
    """
    text = re.sub(r"\s+", " ", html_to_text(document.content or "")).strip()
    if not text:
        return []

    normalized: list[GuidanceMetricRecord] = []
    seen: set[tuple[str, str, str, datetime, float, float]] = set()

    for header in _COMPARATIVE_HEADER.finditer(text):
        context_start = max(0, header.start() - 360)
        context = text[context_start : header.end()]
        fiscal_scopes = _scopes(context)
        # A single comparative header can include FY prior/current columns and
        # a next-quarter column.  There is no deterministic two-column mapping
        # in that shape, so do not normalize any row under an ambiguous scope.
        if len(fiscal_scopes) != 1:
            continue
        fiscal_scope = next(iter(fiscal_scopes))
        scale = _table_scale(context)

        # Bound the table window. Stop at the next comparative header when one
        # exists; otherwise use a conservative 2,400-character window.
        next_header = _COMPARATIVE_HEADER.search(text, header.end())
        table_end = min(len(text), header.end() + 2400)
        if next_header is not None:
            table_end = min(table_end, next_header.start())
        section_end = _TABLE_SECTION_END.search(text, header.end(), table_end)
        if section_end is not None:
            table_end = section_end.start()
        table = text[header.end() : table_end]
        comparative_dates = _comparative_dates(
            text[header.start() : min(table_end, header.end() + 260)],
            document.source_timestamp,
        )
        mentions = _metric_mentions(table)
        if not mentions:
            continue

        for index, mention in enumerate(mentions):
            pair = _pair_for_metric(table, mentions, index, scale)
            if pair is None:
                continue
            prior, current, layout = pair
            basis = _basis(mention.metric, mention.alias)
            key = (
                mention.metric.value,
                fiscal_scope,
                basis,
                document.source_timestamp,
                current.low,
                current.high,
            )
            if key in seen:
                continue
            seen.add(key)

            row_start = max(0, mention.start - 220)
            row_end = min(len(table), mention.end + 220)
            # Preserve the actual primary-source table header in the evidence
            # span. The unchanged GuidanceLedger requires explicit forward-
            # guidance context for quantitative evidence; a synthetic metadata
            # prefix alone must never be used to bypass that eligibility gate.
            source_header = context[-420:]
            source_row = table[row_start:row_end]
            evidence = (
                f"normalized_comparative_guidance_table; layout={layout}; "
                f"scope={fiscal_scope}; table_scale={scale}; prior={prior.low}:{prior.high}; "
                f"updated={current.low}:{current.high}; source_header={source_header}; "
                f"source_row={source_row}"
            )[:1000]

            common = dict(
                rules_hash=rules_hash,
                ticker=document.ticker,
                fiscal_period=fiscal_scope,
                metric=mention.metric,
                accounting_basis=basis,
                unit=current.unit,
                source=document.source,
                source_url=document.source_url,
                source_accession=document.accession,
                verified=True,
                extraction_method=ExtractionMethod.STRUCTURED,
                source_document_hash=document.content_hash,
                fetched_at=document.fetched_at,
                stale=document.stale,
            )

            quoted_prior: GuidanceMetricRecord | None = None
            if comparative_dates is not None:
                prior_timestamp, updated_timestamp = comparative_dates
                prior_key = (
                    mention.metric.value,
                    fiscal_scope,
                    basis,
                    document.source_timestamp,
                    prior.low,
                    prior.high,
                )
                if prior_key not in seen:
                    seen.add(prior_key)
                    prior_evidence = (
                        f"normalized_comparative_guidance_table; row_version=prior; layout={layout}; "
                        f"scope={fiscal_scope}; table_scale={scale}; prior_date={prior_timestamp.date()}; "
                        f"updated_date={updated_timestamp.date()}; prior={prior.low}:{prior.high}; "
                        f"updated={current.low}:{current.high}; source_header={source_header}; "
                        f"source_row={source_row}"
                    )[:1000]
                    quoted_prior = GuidanceMetricRecord(
                        **common,
                        low=prior.low,
                        high=prior.high,
                        source_timestamp=document.source_timestamp,
                        explicit_action=GuidanceAction.NONE,
                        evidence_span=prior_evidence,
                        as_of=document.source_timestamp,
                    )
                    normalized.append(quoted_prior)

            normalized.append(
                GuidanceMetricRecord(
                    **common,
                    low=current.low,
                    high=current.high,
                    source_timestamp=document.source_timestamp,
                    explicit_action=_direction(prior, current),
                    supersedes_record_id=quoted_prior.record_id if quoted_prior is not None else None,
                    evidence_span=(
                        evidence.replace(
                            "normalized_comparative_guidance_table; ",
                            "normalized_comparative_guidance_table; row_version=updated; ",
                            1,
                        )
                    ),
                    as_of=document.source_timestamp,
                )
            )

    return sorted(
        normalized,
        key=lambda item: (item.source_timestamp, item.metric.value, item.fiscal_period, item.accounting_basis),
    )


def extract_guidance_facts_table_normalized(
    document: SourceDocument,
    *,
    rules_hash: str,
) -> GuidanceExtractionResult:
    base = extract_guidance_facts_round8(document, rules_hash=rules_hash)
    rejected = list(base.rejected_candidates)
    base_records: list[GuidanceMetricRecord] = []
    for record in base.records:
        if _record_has_metric_local_range(record):
            base_records.append(record)
        else:
            rejected.append(
                {
                    "reason": "cross_metric_row_range_binding",
                    "metric": record.metric.value,
                    "fiscal_period": record.fiscal_period,
                    "source_url": record.source_url,
                    "evidence": (record.evidence_span or "")[:400],
                }
            )

    table_records = normalize_comparative_guidance_tables(document, rules_hash=rules_hash)
    if not table_records:
        policy = base.policy_evidence
        if any(item.midpoint is not None for item in base_records):
            policy = None
        return base.model_copy(
            update={"records": base_records, "policy_evidence": policy, "rejected_candidates": rejected}
        )

    # The normalized comparative table is authoritative for the same document,
    # metric and fiscal scope. Remove generic prose/table records that can have
    # lost the table unit or crossed a flattened row boundary.
    authoritative = {(item.metric, item.fiscal_period) for item in table_records}
    records = [
        item
        for item in base_records
        if (item.metric, item.fiscal_period) not in authoritative
    ]
    records.extend(table_records)
    records = _action_consistent_history(records)
    records = sorted(
        records,
        key=lambda item: (
            item.source_timestamp,
            item.metric.value,
            item.fiscal_period,
            item.accounting_basis,
            item.source_url,
        ),
    )

    policy = base.policy_evidence
    if any(item.midpoint is not None for item in records):
        policy = None
    return base.model_copy(
        update={"records": records, "policy_evidence": policy, "rejected_candidates": rejected}
    )
