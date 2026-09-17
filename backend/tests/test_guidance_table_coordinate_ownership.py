from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from app.domain.guidance_canonical_v1 import (
    EvidenceBinding,
    GuidanceFactRole,
    GuidancePeriodKind,
    GuidanceProvenance,
    GuidanceScopeKind,
    GuidanceUnit,
    TypedGuidanceFact,
)
from app.domain.soe_v1_1 import ExtractionMethod, GuidanceAction, GuidanceMetric, SourceDocument
from app.services.guidance_evidence_binder_v2 import GuidanceEvidenceBinder


def _doc(ticker: str, text: str, year: int = 2026) -> SourceDocument:
    ts = datetime(year, 9, 14, tzinfo=UTC)
    digest = hashlib.sha256(text.encode()).hexdigest()
    return SourceDocument(
        document_id=f"table-{ticker}-{digest[:12]}",
        rules_hash="table-coordinate-test",
        ticker=ticker,
        cik="0000000001",
        accession="0000000001-26-999999",
        form="8-K",
        filing_date=ts.date(),
        source_url=f"https://www.sec.gov/Archives/edgar/data/1/{ticker.lower()}-table.htm",
        source_timestamp=ts,
        fetched_at=ts,
        content_hash=digest,
        content_type="text/plain",
        content=text,
    )


def _fact(
    document: SourceDocument,
    *,
    metric: GuidanceMetric,
    period: str,
    kind: GuidancePeriodKind,
    metric_text: str,
    value_text: str | None,
    period_text: str,
    low: float | None,
    high: float | None,
    unit: GuidanceUnit = GuidanceUnit.USD,
    basis: str = "UNSPECIFIED",
    action: GuidanceAction = GuidanceAction.NONE,
) -> TypedGuidanceFact:
    text = document.content
    ms = text.index(metric_text)
    ps = text.index(period_text)
    vs = text.index(value_text) if value_text else None
    evidence = EvidenceBinding(
        full_text=text,
        metric_text=metric_text,
        value_text=value_text,
        period_text=period_text,
        action_text=action.value if action is not GuidanceAction.NONE else None,
        metric_start=ms,
        metric_end=ms + len(metric_text),
        value_start=vs,
        value_end=(vs + len(value_text)) if value_text else None,
        period_start=ps,
        period_end=ps + len(period_text),
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
    return TypedGuidanceFact(
        ticker=document.ticker,
        metric=metric,
        raw_metric_label=metric.value,
        fiscal_period=period,
        authoritative_period=period,
        period_kind=kind,
        accounting_basis=basis,
        scope_kind=GuidanceScopeKind.COMPANY,
        scope_label=None,
        role=GuidanceFactRole.CURRENT,
        low=low,
        high=high,
        unit=unit,
        explicit_action=action,
        extraction_method=ExtractionMethod.DETERMINISTIC_TEXT,
        provenance=[provenance],
    )


def test_exact_shak_reversed_flattened_table_rejects_intervening_value():
    text = (
        "amortization expense Pre-opening costs Net income Adjusted EBITDA Adjusted Pro Forma Tax Rate "
        "60 – 65 40 – 45 $1.6b – 1.7b $57.0m - $59.0m + LSD % 22.0% - 23.0% "
        "12.0% to 13.0% of Total revenue $28m $124m - $128m $26m – $28m "
        "$45m - $55m $225m - $235m 25% - 27% FY 2026 Guidance"
    )
    document = _doc("SHAK", text)
    fact = _fact(
        document,
        metric=GuidanceMetric.REVENUE,
        period="FY2026",
        kind=GuidancePeriodKind.FULL_YEAR,
        metric_text="Total revenue",
        value_text="$124m - $128m",
        period_text="FY 2026",
        low=124e6,
        high=128e6,
        action=GuidanceAction.LOWER,
    )
    result = GuidanceEvidenceBinder().bind(fact, document)
    assert not result.accepted
    assert not result.dimensions["row"]
    assert any("intervening numeric table value" in reason for reason in result.reasons)


def test_percentage_of_revenue_reference_is_not_revenue_row_owner():
    text = "Adjusted occupancy expense 12.0% to 13.0% of Total revenue $28m FY 2026 Guidance"
    document = _doc("TABL", text)
    fact = _fact(
        document,
        metric=GuidanceMetric.REVENUE,
        period="FY2026",
        kind=GuidancePeriodKind.FULL_YEAR,
        metric_text="Total revenue",
        value_text="$28m",
        period_text="FY 2026",
        low=28e6,
        high=28e6,
    )
    result = GuidanceEvidenceBinder().bind(fact, document)
    assert not result.accepted
    assert not result.dimensions["row"]
    assert any("percentage denominator/reference" in reason for reason in result.reasons)


def test_valid_simple_single_period_table_values_before_header_survives():
    text = "Total revenue $1.6 billion - $1.7 billion Adjusted EBITDA $225 million - $235 million FY 2026 Guidance"
    document = _doc("GOOD", text)
    fact = _fact(
        document,
        metric=GuidanceMetric.REVENUE,
        period="FY2026",
        kind=GuidancePeriodKind.FULL_YEAR,
        metric_text="Total revenue",
        value_text="$1.6 billion - $1.7 billion",
        period_text="FY 2026",
        low=1.6e9,
        high=1.7e9,
    )
    assert GuidanceEvidenceBinder().bind(fact, document).accepted


def test_valid_simple_single_period_table_header_before_values_survives():
    text = "FY 2026 Guidance Total revenue $1.6 billion - $1.7 billion Adjusted EBITDA $225 million - $235 million"
    document = _doc("GOOD", text)
    fact = _fact(
        document,
        metric=GuidanceMetric.REVENUE,
        period="FY2026",
        kind=GuidancePeriodKind.FULL_YEAR,
        metric_text="Total revenue",
        value_text="$1.6 billion - $1.7 billion",
        period_text="FY 2026",
        low=1.6e9,
        high=1.7e9,
    )
    assert GuidanceEvidenceBinder().bind(fact, document).accepted


def test_valid_quarter_and_fy_narrative_sections_survive():
    text = (
        "Q2 2026 Guidance: Revenue $424m - $428m. "
        "FY 2026 Guidance: Consolidated revenue $1.6 billion - $1.7 billion."
    )
    document = _doc("GOOD", text)
    fact = _fact(
        document,
        metric=GuidanceMetric.REVENUE,
        period="FY2026",
        kind=GuidancePeriodKind.FULL_YEAR,
        metric_text="Consolidated revenue",
        value_text="$1.6 billion - $1.7 billion",
        period_text="FY 2026",
        low=1.6e9,
        high=1.7e9,
    )
    assert GuidanceEvidenceBinder().bind(fact, document).accepted


def test_valid_explicit_raise_survives_row_coordinate_guard():
    text = "The company raised FY 2026 guidance for Total revenue to $1.6 billion - $1.7 billion."
    document = _doc("GOOD", text)
    fact = _fact(
        document,
        metric=GuidanceMetric.REVENUE,
        period="FY2026",
        kind=GuidancePeriodKind.FULL_YEAR,
        metric_text="Total revenue",
        value_text="$1.6 billion - $1.7 billion",
        period_text="FY 2026",
        low=1.6e9,
        high=1.7e9,
        action=GuidanceAction.RAISE,
    )
    assert GuidanceEvidenceBinder().bind(fact, document).accepted
