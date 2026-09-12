from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from app.domain.catalyst_surprise_v1_1 import AnalystConsensusContext, CatalystSurpriseInput
from app.domain.catalyst_v1_1 import CatalystEventFamily
from app.domain.enums import CatalystGrade
from app.domain.schemas import CorporateEvent, FundamentalSnapshot, Instrument
from app.domain.soe_v1_1 import (
    ExtractionMethod,
    GuidanceAction,
    GuidanceExtractionResult,
    GuidanceMetric,
    GuidanceMetricRecord,
    SourceDocument,
)
from app.providers import sec_distress
from app.services.catalyst_evidence_service import promote_scoring_ready_event as _base_promote_scoring_ready_event
from app.services.catalyst_materiality_service import assess_materiality
from app.services.catalyst_surprise_service import assess_surprise_potential
from app.services.distress_metric_service import derive_distress_inputs
from app.services.fact_extraction_service import html_to_text
from app.services.guidance_ledger_service import GuidanceLedger
from app.services.phase_1_1e_guidance_table_normalizer_v1_1 import extract_guidance_facts_table_normalized
from app.services.shadow_validation_service import CatalystStructuralOverride, catalyst_event_key


# Run-85 audit repair layer. These functions correct evidence normalization and
# audit persistence only; no SOE threshold, score, scanner, weight or classifier
# rule is changed.
_INTEREST_EXPENSE = (
    "InterestExpenseNonoperating",
    "InterestAndDebtExpense",
    "InterestExpenseDebt",
)
_NUM = r"\d+(?:,\d{3})*(?:\.\d+)?"
_SCALE = {
    "thousand": 1_000.0,
    "thousands": 1_000.0,
    "k": 1_000.0,
    "million": 1_000_000.0,
    "millions": 1_000_000.0,
    "m": 1_000_000.0,
    "mm": 1_000_000.0,
    "billion": 1_000_000_000.0,
    "billions": 1_000_000_000.0,
    "b": 1_000_000_000.0,
    "bn": 1_000_000_000.0,
}
_MARGIN_LABEL = re.compile(
    r"(?P<label>(?:(?:non[- ]GAAP|adjusted|GAAP)\s+)?"
    r"(?:gross(?: profit)? margin|operating margin))",
    re.I,
)
_GUIDANCE_YEAR = re.compile(
    r"(?:\b(?:fiscal year|full[- ]year|FY)\s*(20\d{2})\b.{0,80}?\b(?:guidance|outlook)\b|"
    r"\b(20\d{2})\s+(?:annual\s+|full[- ]year\s+)?(?:guidance|outlook)\b|"
    r"\b(?:guidance|outlook)\s+(?:for\s+)?(?:fiscal year|full[- ]year|FY)\s*(20\d{2})\b)",
    re.I | re.S,
)
_SECTION_STOP = re.compile(
    r"\b(?:Conference Call|Forward[- ]Looking Statements?|About [A-Z][A-Za-z]+|"
    r"Financial Results|Condensed Consolidated Statements?)\b"
)


def _amount(value: str, scale: str | None) -> float:
    result = float(value.replace(",", ""))
    if scale:
        result *= _SCALE.get(scale.lower().rstrip("."), 1.0)
    return result


def _basis(label: str) -> str:
    text = label.lower()
    if "non-gaap" in text or "non gaap" in text or "adjusted" in text:
        return "ADJUSTED"
    if "gaap" in text:
        return "GAAP"
    return "UNSPECIFIED"


def _guidance_record(
    document: SourceDocument,
    *,
    rules_hash: str,
    period: str,
    metric: GuidanceMetric,
    accounting_basis: str,
    low: float,
    high: float,
    unit: str,
    evidence: str,
    action: GuidanceAction = GuidanceAction.NONE,
) -> GuidanceMetricRecord:
    return GuidanceMetricRecord(
        rules_hash=rules_hash,
        ticker=document.ticker,
        fiscal_period=period,
        metric=metric,
        accounting_basis=accounting_basis,
        low=low,
        high=high,
        unit=unit,
        source=document.source,
        source_url=document.source_url,
        source_accession=document.accession,
        source_timestamp=document.source_timestamp,
        explicit_action=action,
        verified=True,
        extraction_method=ExtractionMethod.STRUCTURED,
        evidence_span=("normalized_explicit_guidance_scope; phase_1_1e_run85; " + evidence)[:1000],
        source_document_hash=document.content_hash,
        as_of=document.source_timestamp,
        fetched_at=document.fetched_at,
        stale=document.stale,
    )


def _direction(prior_low: float, prior_high: float, current_low: float, current_high: float) -> GuidanceAction:
    prior_mid = (prior_low + prior_high) / 2.0
    current_mid = (current_low + current_high) / 2.0
    tolerance = max(abs(prior_mid), abs(current_mid), 1.0) * 1e-12
    if current_mid < prior_mid - tolerance:
        return GuidanceAction.LOWER
    if current_mid > prior_mid + tolerance:
        return GuidanceAction.RAISE
    return GuidanceAction.REAFFIRM


def normalize_distress_companyfacts_run85(
    ticker: str,
    payload: dict[str, Any],
    *,
    sector_adapter,
    fetched_at: datetime,
):
    """Use EBIT / income-statement interest expense; never cash interest paid.

    `DistressRawFacts.cash_interest_expense` is retained as the legacy transport
    field to avoid changing the frozen domain interface. In this Phase-1.1E
    wrapper it contains true income-statement interest expense, with provenance
    recorded explicitly in `audit`.
    """
    facts = sec_distress.normalize_distress_companyfacts(
        ticker,
        payload,
        sector_adapter=sector_adapter,
        fetched_at=fetched_at,
    )
    operating_income, operating_concept = sec_distress._annual_map(
        payload, sec_distress._OPERATING_INCOME
    )
    interest_expense, interest_concept = sec_distress._annual_map(payload, _INTEREST_EXPENSE)
    coverage_ends = sorted(
        end
        for end in set(operating_income) & set(interest_expense)
        if sec_distress._fresh_end(
            end,
            fetched_at,
            max_age_days=sec_distress._MAX_ANNUAL_AGE_DAYS,
        )
    )
    coverage_end = coverage_ends[-1] if coverage_ends else None
    ebit = operating_income.get(coverage_end) if coverage_end else facts.ebit
    denominator = interest_expense.get(coverage_end) if coverage_end else None

    audit = dict(facts.audit)
    concepts = dict(audit.get("concepts") or {})
    concepts["ebit_for_interest_coverage"] = operating_concept
    concepts["interest_expense"] = interest_concept
    concepts["cash_interest_paid_legacy_unused"] = concepts.pop("cash_interest", None)
    audit["concepts"] = concepts
    audit["interest_coverage_period_end"] = coverage_end
    audit["interest_coverage_definition"] = "EBIT / income-statement interest expense"
    audit["cash_interest_paid_used_for_interest_coverage"] = False
    limitations = list(audit.get("companyfacts_limits") or [])
    limitations.append(
        "interest coverage is UNKNOWN when a same-period true interest-expense concept is unavailable"
    )
    audit["companyfacts_limits"] = sorted(set(limitations))

    return facts.model_copy(
        update={
            "ebit": ebit,
            "cash_interest_expense": abs(denominator) if denominator is not None else None,
            "audit": audit,
        }
    )


def _latest_guidance_year_before(text: str, position: int, *, max_distance: int = 1800) -> tuple[str, int] | None:
    start = max(0, position - max_distance)
    window = text[start:position]
    candidates: list[tuple[int, int]] = []
    for match in _GUIDANCE_YEAR.finditer(window):
        token = match.group(1) or match.group(2) or match.group(3)
        if token:
            candidates.append((start + match.start(), int(token)))
    if not candidates:
        return None
    absolute, year = max(candidates)
    return f"FY{year}", absolute


def _margin_metric(label: str) -> GuidanceMetric:
    return (
        GuidanceMetric.GROSS_MARGIN
        if "gross" in label.lower()
        else GuidanceMetric.OPERATING_MARGIN
    )


def _normalize_revision_eps(
    document: SourceDocument,
    text: str,
    *,
    rules_hash: str,
) -> list[GuidanceMetricRecord]:
    records: list[GuidanceMetricRecord] = []
    pattern = re.compile(
        rf"\brevis(?:e|es|ed|ing)\s+(?:its\s+)?"
        rf"(?P<basis>GAAP|Adjusted|Non[- ]GAAP)\s+EPS\s+guidance"
        rf"(?P<scope>.{{0,180}}?)"
        rf"\bto\s+[\'\"“”]?\s*(?:at\s+least\s+)?\$(?P<current>{_NUM})[\'\"“”]?"
        rf"\s+from\s+(?:the\s+previous\s+estimate\s+of\s+)?"
        rf"[\'\"“”]?\s*(?:at\s+least\s+)?\$(?P<prior>{_NUM})[\'\"“”]?",
        re.I | re.S,
    )
    for match in pattern.finditer(text):
        year_match = re.search(r"\b(20\d{2})\b", match.group("scope"))
        if year_match is None:
            near = _latest_guidance_year_before(text, match.start(), max_distance=700)
            if near is None:
                continue
            period = near[0]
        else:
            period = f"FY{year_match.group(1)}"
        current = float(match.group("current"))
        prior = float(match.group("prior"))
        basis = "ADJUSTED" if match.group("basis").lower() != "gaap" else "GAAP"
        prior_record = _guidance_record(
            document,
            rules_hash=rules_hash,
            period=period,
            metric=GuidanceMetric.EPS,
            accounting_basis=basis,
            low=prior,
            high=prior,
            unit="USD/share",
            evidence=match.group(),
        )
        current_record = _guidance_record(
            document,
            rules_hash=rules_hash,
            period=period,
            metric=GuidanceMetric.EPS,
            accounting_basis=basis,
            low=current,
            high=current,
            unit="USD/share",
            evidence=match.group(),
            action=_direction(prior, prior, current, current),
        ).model_copy(update={"supersedes_record_id": prior_record.record_id})
        records.extend((prior_record, current_record))

        tail = text[match.end() : match.end() + 260]
        affirmed = re.search(
            rf"\b(?:while\s+)?affirm(?:s|ed|ing)?\s+(?:its\s+)?"
            rf"(?P<basis>Adjusted|Non[- ]GAAP|GAAP)\s+EPS\s+guidance"
            rf"(?:\s+of)?\s+[\'\"“”]?\s*(?:at\s+least\s+)?\$(?P<value>{_NUM})",
            tail,
            re.I,
        )
        if affirmed:
            label = affirmed.group("basis")
            aff_basis = "ADJUSTED" if label.lower() != "gaap" else "GAAP"
            value = float(affirmed.group("value"))
            records.append(
                _guidance_record(
                    document,
                    rules_hash=rules_hash,
                    period=period,
                    metric=GuidanceMetric.EPS,
                    accounting_basis=aff_basis,
                    low=value,
                    high=value,
                    unit="USD/share",
                    evidence=(match.group() + " " + affirmed.group())[:1000],
                    action=GuidanceAction.REAFFIRM,
                )
            )
    return records


def _normalize_long_term_revenue(
    document: SourceDocument,
    text: str,
    *,
    rules_hash: str,
) -> list[GuidanceMetricRecord]:
    records: list[GuidanceMetricRecord] = []
    for header in re.finditer(
        r"\b(?P<year>20\d{2})\s+Long[- ]Term(?:\s+Financial)?\s+Outlook\b",
        text,
        re.I,
    ):
        section = text[header.start() : header.start() + 1400]
        boundary = _SECTION_STOP.search(section)
        if boundary:
            section = section[: boundary.start()]
        revenue = re.search(
            rf"\b(?:Total\s+)?(?:Net\s+)?Revenue(?:s)?\s+"
            rf"(?:Between|of|from|in\s+the\s+range\s+of)?\s*"
            rf"\$?(?P<low>{_NUM})\s*(?P<s1>million|billion|M|B)\b\s*"
            rf"(?:and|to|[-–—])\s*\$?(?P<high>{_NUM})\s*"
            rf"(?P<s2>million|billion|M|B)?\b",
            section,
            re.I,
        )
        if revenue is None:
            continue
        scale1 = revenue.group("s1")
        scale2 = revenue.group("s2") or scale1
        low = _amount(revenue.group("low"), scale1)
        high = _amount(revenue.group("high"), scale2)
        if low > high:
            continue
        records.append(
            _guidance_record(
                document,
                rules_hash=rules_hash,
                period=f"FY{header.group('year')}",
                metric=GuidanceMetric.REVENUE,
                accounting_basis="UNSPECIFIED",
                low=low,
                high=high,
                unit="USD",
                evidence=section[:1000],
                action=GuidanceAction.REAFFIRM
                if re.search(r"\breaffirm", section[: revenue.end()], re.I)
                else GuidanceAction.NONE,
            )
        )
    return records


def _normalize_margin_guidance(
    document: SourceDocument,
    text: str,
    *,
    rules_hash: str,
) -> list[GuidanceMetricRecord]:
    records: list[GuidanceMetricRecord] = []
    seen: set[tuple[str, str, str, float, float]] = set()

    # Comparative rows such as:
    # Updated Guidance / Previous Guidance ... Adjusted Gross Margin 16.0%-16.6% 16.4%-17.0%
    comparative_header = re.compile(
        r"\b(?P<first>Updated|Current|Revised|Previous|Prior)\s+(?:Guidance|Guide)\b"
        r".{0,180}?\b(?P<second>Updated|Current|Revised|Previous|Prior)\s+(?:Guidance|Guide)\b",
        re.I | re.S,
    )
    for label_match in _MARGIN_LABEL.finditer(text):
        period_info = _latest_guidance_year_before(text, label_match.start())
        if period_info is None:
            continue
        period, header_position = period_info
        if label_match.start() - header_position > 1800:
            continue
        label = label_match.group("label")
        metric = _margin_metric(label)
        basis = _basis(label)
        tail = text[label_match.end() : label_match.end() + 360]

        header_window = text[max(header_position, label_match.start() - 600) : label_match.start()]
        headers = list(comparative_header.finditer(header_window))
        row_two = re.match(
            rf"\s*(?:is\s+(?:now\s+)?expected\s+to\s+be\s+|"
            rf"(?:is\s+)?expected\s+to\s+be\s+|estimated\s+|of\s+|:\s*)?"
            rf"(?:approximately\s+)?"
            rf"(?P<c1>{_NUM})\s*%\s*(?:to|and|[-–—])\s*(?P<c2>{_NUM})\s*%"
            rf".{{0,80}}?"
            rf"(?P<p1>{_NUM})\s*%\s*(?:to|and|[-–—])\s*(?P<p2>{_NUM})\s*%",
            tail,
            re.I | re.S,
        )
        if headers and row_two:
            hdr = headers[-1]
            first = hdr.group("first").lower()
            updated_first = first in {"updated", "current", "revised"}
            first_low = float(row_two.group("c1")) / 100.0
            first_high = float(row_two.group("c2")) / 100.0
            second_low = float(row_two.group("p1")) / 100.0
            second_high = float(row_two.group("p2")) / 100.0
            if updated_first:
                current_low, current_high = first_low, first_high
                prior_low, prior_high = second_low, second_high
            else:
                prior_low, prior_high = first_low, first_high
                current_low, current_high = second_low, second_high
            if current_low <= current_high and prior_low <= prior_high:
                prior = _guidance_record(
                    document,
                    rules_hash=rules_hash,
                    period=period,
                    metric=metric,
                    accounting_basis=basis,
                    low=prior_low,
                    high=prior_high,
                    unit="fraction",
                    evidence=(header_window[-500:] + " " + label + tail[:250])[:1000],
                )
                current = _guidance_record(
                    document,
                    rules_hash=rules_hash,
                    period=period,
                    metric=metric,
                    accounting_basis=basis,
                    low=current_low,
                    high=current_high,
                    unit="fraction",
                    evidence=(header_window[-500:] + " " + label + tail[:250])[:1000],
                    action=_direction(prior_low, prior_high, current_low, current_high),
                ).model_copy(update={"supersedes_record_id": prior.record_id})
                records.extend((prior, current))
                seen.add((metric.value, period, basis, current_low, current_high))
                continue

        current_range = re.match(
            rf"\s*(?:is\s+(?:now\s+)?expected\s+to\s+be\s+between\s+|"
            rf"is\s+(?:now\s+)?expected\s+to\s+be\s+(?:in\s+the\s+range\s+of\s+)?|"
            rf"(?:is\s+)?expected\s+to\s+be\s+(?:between\s+|in\s+the\s+range\s+of\s+)?|"
            rf"estimated\s+|of\s+|:\s*)?"
            rf"(?:approximately\s+)?"
            rf"(?P<low>{_NUM})\s*(?:%|percent)\s*"
            rf"(?:to|and|[-–—])\s*(?P<high>{_NUM})\s*(?:%|percent)",
            tail,
            re.I,
        )
        if current_range:
            current_low = float(current_range.group("low")) / 100.0
            current_high = float(current_range.group("high")) / 100.0
            if current_low <= current_high:
                evidence = text[max(header_position, label_match.start() - 350) : label_match.end() + current_range.end()]
                previous_tail = tail[current_range.end() : current_range.end() + 180]
                previous = re.search(
                    rf"\b(?:previously|prior(?:\s+guidance)?|previous(?:\s+guidance)?)\s*"
                    rf"(?P<low>{_NUM})\s*(?:%|percent)\s*"
                    rf"(?:to|and|[-–—])\s*(?P<high>{_NUM})\s*(?:%|percent)",
                    previous_tail,
                    re.I,
                )
                if previous:
                    prior_low = float(previous.group("low")) / 100.0
                    prior_high = float(previous.group("high")) / 100.0
                    prior = _guidance_record(
                        document,
                        rules_hash=rules_hash,
                        period=period,
                        metric=metric,
                        accounting_basis=basis,
                        low=prior_low,
                        high=prior_high,
                        unit="fraction",
                        evidence=(evidence + " " + previous.group())[:1000],
                    )
                    current = _guidance_record(
                        document,
                        rules_hash=rules_hash,
                        period=period,
                        metric=metric,
                        accounting_basis=basis,
                        low=current_low,
                        high=current_high,
                        unit="fraction",
                        evidence=(evidence + " " + previous.group())[:1000],
                        action=_direction(prior_low, prior_high, current_low, current_high),
                    ).model_copy(update={"supersedes_record_id": prior.record_id})
                    records.extend((prior, current))
                else:
                    records.append(
                        _guidance_record(
                            document,
                            rules_hash=rules_hash,
                            period=period,
                            metric=metric,
                            accounting_basis=basis,
                            low=current_low,
                            high=current_high,
                            unit="fraction",
                            evidence=evidence,
                        )
                    )
                seen.add((metric.value, period, basis, current_low, current_high))
                continue

        point = re.match(
            rf"\s*(?:is\s+(?:now\s+)?expected\s+to\s+be\s+|"
            rf"(?:is\s+)?expected\s+to\s+be\s+|estimated\s+|of\s+|:\s*)?"
            rf"(?:approximately\s+)?(?P<value>{_NUM})\s*(?:%|percent)",
            tail,
            re.I,
        )
        if point:
            value = float(point.group("value")) / 100.0
            key = (metric.value, period, basis, value, value)
            if key not in seen:
                records.append(
                    _guidance_record(
                        document,
                        rules_hash=rules_hash,
                        period=period,
                        metric=metric,
                        accounting_basis=basis,
                        low=value,
                        high=value,
                        unit="fraction",
                        evidence=text[max(header_position, label_match.start() - 350) : label_match.end() + point.end()],
                    )
                )
                seen.add(key)

    return records


def extract_guidance_facts_run85(
    document: SourceDocument,
    *,
    rules_hash: str,
) -> GuidanceExtractionResult:
    base = extract_guidance_facts_table_normalized(document, rules_hash=rules_hash)
    text = re.sub(r"\s+", " ", html_to_text(document.content or "")).strip()
    supplemental = [
        *_normalize_revision_eps(document, text, rules_hash=rules_hash),
        *_normalize_long_term_revenue(document, text, rules_hash=rules_hash),
        *_normalize_margin_guidance(document, text, rules_hash=rules_hash),
    ]
    if not supplemental:
        return base

    # A structured Run-85 normalization is authoritative for its own metric /
    # fiscal-period key. For long-term revenue, the exact normalized value also
    # suppresses a generic record that bound that same value to a different FY.
    authoritative_keys = {(r.metric, r.fiscal_period, r.accounting_basis) for r in supplemental}
    long_term_values = {
        (r.metric, r.low, r.high, r.unit, r.source_timestamp)
        for r in supplemental
        if r.metric is GuidanceMetric.REVENUE
        and "Long-Term" in (r.evidence_span or "")
    }
    records = [
        r
        for r in base.records
        if (r.metric, r.fiscal_period, r.accounting_basis) not in authoritative_keys
        and (r.metric, r.low, r.high, r.unit, r.source_timestamp) not in long_term_values
    ]
    records.extend(supplemental)

    unique: dict[tuple[Any, ...], GuidanceMetricRecord] = {}
    for record in records:
        key = (
            record.metric,
            record.fiscal_period,
            record.accounting_basis,
            record.low,
            record.high,
            record.source_timestamp,
            record.supersedes_record_id,
        )
        unique[key] = record
    records = sorted(
        unique.values(),
        key=lambda r: (
            r.source_timestamp,
            r.metric.value,
            r.fiscal_period,
            r.accounting_basis,
            str(r.record_id),
        ),
    )
    rejected = list(base.rejected_candidates)
    rejected.append(
        {
            "reason": "phase_1_1e_run85_structured_repair",
            "supplemental_record_count": len(supplemental),
        }
    )
    policy = base.policy_evidence
    if any(record.midpoint is not None for record in records):
        policy = None
    return base.model_copy(
        update={
            "records": records,
            "policy_evidence": policy,
            "rejected_candidates": rejected,
        }
    )


def analyst_consensus_audit_payload(
    context: AnalystConsensusContext | None,
) -> dict[str, Any] | None:
    if context is None:
        return None
    return context.model_dump(mode="json")


def candidate_calendar_event_run85(event: CorporateEvent) -> CorporateEvent:
    """Fail conservatively on Nasdaq future-date provenance.

    Nasdaq calendar rows provide a public calendar day, but the Phase-1.1E
    evidence available here does not prove issuer confirmation. Keep the day as
    a narrow estimated window and map it to the already-frozen Grade-B
    confidence definition rather than Grade A.
    """
    if (
        event.type.upper() == "EARNINGS"
        and event.source == "Nasdaq Earnings Calendar"
        and (event.date_precision or "DAY").upper() == "DAY"
    ):
        return event.model_copy(
            update={
                "timing": "ESTIMATED",
                "date_confidence": CatalystGrade.B,
                "evidence_status": "PUBLIC_CALENDAR_DAY_UNCONFIRMED_ESTIMATE",
            }
        )
    return event


def promote_scoring_ready_event_run85(event: CorporateEvent):
    return _base_promote_scoring_ready_event(candidate_calendar_event_run85(event))


async def assess_earnings_catalysts_run85(
    self,
    ticker: str,
    events: list[CorporateEvent],
) -> tuple[dict[str, CatalystStructuralOverride], list[dict[str, Any]], list[str]]:
    """Run the existing frozen catalyst math while preserving audit inputs."""
    from app.services import shadow_enrichment_service as runtime

    target_events = [
        event
        for event in events
        if event.catalyst_candidate and event.type.upper() == "EARNINGS"
    ]
    if not target_events:
        return {}, [], []

    documents, errors = self._documents(
        ticker,
        forms=runtime._CATALYST_FORMS,
        lookback_days=500,
        limit=20,
        max_exhibits=4,
    )
    primary = None
    for document in reversed(documents):
        candidates = runtime.extract_sec_catalyst_candidates(document)
        earnings = [
            candidate
            for candidate in candidates
            if candidate.input.event_type == "quarterly_earnings"
        ]
        if earnings:
            primary = earnings[-1]
            break
    if primary is None:
        return (
            {},
            [
                {
                    "event_key": catalyst_event_key(event),
                    "event_type": event.type,
                    "event_date": event.event_date.isoformat(),
                    "future_event_source": event.source,
                    "future_event_date_confidence": (
                        candidate_calendar_event_run85(event).date_confidence.value
                        if candidate_calendar_event_run85(event).date_confidence
                        else None
                    ),
                    "sufficient_primary_evidence": False,
                    "materiality": None,
                    "surprise_potential": None,
                    "missing_reason": "no_recent_primary_sec_earnings_evidence",
                }
                for event in target_events
            ],
            errors,
        )

    overrides: dict[str, CatalystStructuralOverride] = {}
    rows: list[dict[str, Any]] = []
    for original_event in target_events:
        event = candidate_calendar_event_run85(original_event)
        key = catalyst_event_key(original_event)
        future_input = primary.input.model_copy(
            update={
                "event_id": f"shadow:{key}",
                "event_date": event.event_date,
                "formal_guidance_action": False,
            }
        )
        materiality = assess_materiality(
            future_input,
            self.rules,
            rules_hash=self.rules_hash,
        )
        eps = revenue = None
        consensus_error = None
        try:
            eps, revenue = await self.consensus.get_consensus(
                ticker,
                event_type="quarterly_earnings",
            )
        except Exception as exc:  # preserve provider failure as validation evidence
            consensus_error = f"CONSENSUS:{type(exc).__name__}:{exc}"
            errors.append(consensus_error)

        surprise = None
        if materiality.materiality is not None:
            surprise_input = CatalystSurpriseInput(
                ticker=ticker,
                event_id=f"shadow:{key}",
                event_family=CatalystEventFamily.EARNINGS_GUIDANCE,
                event_type="quarterly_earnings",
                economic_exposure_score=materiality.economic_exposure_score,
                catalyst_candidate=materiality.catalyst_candidate,
                verified=True,
                eps_consensus=eps,
                revenue_consensus=revenue,
                source=materiality.source,
                source_url=materiality.source_url,
                source_timestamp=materiality.source_timestamp,
                extraction_method=materiality.extraction_method,
                evidence_spans=materiality.evidence_spans,
                structured_provenance={
                    **materiality.structured_provenance,
                    "future_event_source": event.source,
                    "future_event_source_url": event.source_url,
                    "future_event_date": event.event_date.isoformat(),
                    "future_event_verified": event.verified,
                    "future_event_date_confidence": (
                        event.date_confidence.value if event.date_confidence else None
                    ),
                    "future_event_date_precision": event.date_precision,
                    "future_event_timing": event.timing,
                    "future_event_field_provenance": {
                        key: value.model_dump(mode="json")
                        for key, value in event.field_provenance.items()
                    },
                },
            )
            surprise = assess_surprise_potential(
                surprise_input,
                self.rules,
                rules_hash=self.rules_hash,
            )

        materiality_value = materiality.materiality
        surprise_value = surprise.surprise_potential if surprise else None
        if materiality_value is not None or surprise_value is not None:
            overrides[key] = CatalystStructuralOverride(
                materiality=materiality_value,
                surprise_potential=surprise_value,
                evidence_id=materiality.event_id,
                reasons=tuple(
                    materiality.reasons + (surprise.reasons if surprise else [])
                ),
            )

        rows.append(
            {
                "event_key": key,
                "event_type": event.type,
                "event_date": event.event_date.isoformat(),
                "future_event_source": event.source,
                "future_event_source_url": event.source_url,
                "future_event_verified": event.verified,
                "future_event_date_confidence": (
                    event.date_confidence.value if event.date_confidence else None
                ),
                "future_event_date_precision": event.date_precision,
                "future_event_timing": event.timing,
                "future_event_field_provenance": {
                    key: value.model_dump(mode="json")
                    for key, value in event.field_provenance.items()
                },
                "primary_evidence_source": materiality.source,
                "primary_evidence_url": materiality.source_url,
                "sufficient_primary_evidence": materiality.materiality_ready,
                "materiality": materiality_value,
                "economic_exposure_score": materiality.economic_exposure_score,
                "surprise_potential": surprise_value,
                "expectation_uncertainty": (
                    surprise.expectation_uncertainty if surprise else None
                ),
                "expectation_metric": (
                    surprise.expectation_metric.value
                    if surprise and surprise.expectation_metric
                    else None
                ),
                "expectation_value": (
                    surprise.expectation_value if surprise else None
                ),
                "expectation_provenance": (
                    surprise.expectation_provenance if surprise else {}
                ),
                "eps_consensus": analyst_consensus_audit_payload(eps),
                "revenue_consensus": analyst_consensus_audit_payload(revenue),
                "surprise_ready": surprise.surprise_ready if surprise else False,
                "consensus_error": consensus_error,
                "materiality_rule_path": materiality.rule_path,
                "surprise_rule_path": surprise.rule_path if surprise else None,
            }
        )
    return overrides, rows, errors


def run85_distress_replay_check(facts) -> float | None:
    """Small audit helper used by regression tests; no production call path."""
    return derive_distress_inputs(facts).interest_coverage
