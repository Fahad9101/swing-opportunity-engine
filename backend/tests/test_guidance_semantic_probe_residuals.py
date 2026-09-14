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
from app.services.guidance_evidence_binder_v4 import GuidanceEvidenceBinder


def _doc(ticker: str, text: str, year: int = 2026) -> SourceDocument:
    ts = datetime(year, 9, 14, tzinfo=UTC)
    digest = hashlib.sha256(text.encode()).hexdigest()
    return SourceDocument(
        document_id=f"probe-{ticker}-{digest[:12]}",
        rules_hash="semantic-probe",
        ticker=ticker,
        cik="0000000001",
        accession="0000000001-26-999998",
        form="8-K",
        filing_date=ts.date(),
        source_url=f"https://www.sec.gov/Archives/edgar/data/1/{ticker.lower()}-probe.htm",
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
    value_text: str,
    period_text: str,
    low: float,
    high: float,
    action: GuidanceAction = GuidanceAction.NONE,
) -> TypedGuidanceFact:
    text = document.content
    ms = text.index(metric_text)
    vs = text.index(value_text)
    ps = text.index(period_text)
    action_text = None
    if action is not GuidanceAction.NONE:
        needles = {
            GuidanceAction.RAISE: ("raised", "raising", "increase", "increasing"),
            GuidanceAction.LOWER: ("lower", "lowered", "reduced", "decline", "down"),
            GuidanceAction.REAFFIRM: ("maintain", "reaffirm"),
            GuidanceAction.INITIATE: ("expects", "expected", "providing"),
        }.get(action, ())
        for needle in needles:
            if needle.lower() in text.lower():
                start = text.lower().index(needle.lower())
                action_text = text[start:start + len(needle)]
                break
    evidence = EvidenceBinding(
        full_text=text,
        metric_text=metric_text,
        value_text=value_text,
        period_text=period_text,
        action_text=action_text,
        metric_start=ms,
        metric_end=ms + len(metric_text),
        value_start=vs,
        value_end=vs + len(value_text),
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
        accounting_basis="ADJUSTED" if metric in {GuidanceMetric.EPS, GuidanceMetric.EBITDA, GuidanceMetric.FCF} and "Adjusted" in metric_text else "UNSPECIFIED",
        scope_kind=GuidanceScopeKind.COMPANY,
        scope_label=None,
        role=GuidanceFactRole.CURRENT,
        low=low,
        high=high,
        unit=GuidanceUnit.USD_PER_SHARE if metric is GuidanceMetric.EPS else GuidanceUnit.USD,
        explicit_action=action,
        extraction_method=ExtractionMethod.DETERMINISTIC_TEXT,
        provenance=[provenance],
    )


def test_full_year_guidance_value_cannot_be_serialized_as_quarter_guidance():
    text = "Crane NXT reports second quarter 2026 results. The Company is raising its full year Adjusted EPS guidance to a range of $4.22 to $4.42 from $4.10 to $4.40."
    d = _doc("CXT", text)
    f = _fact(d, metric=GuidanceMetric.EPS, period="Q2FY2026", kind=GuidancePeriodKind.QUARTER, metric_text="Adjusted EPS", value_text="$4.22 to $4.42", period_text="second quarter 2026", low=4.22, high=4.42, action=GuidanceAction.RAISE)
    assert not GuidanceEvidenceBinder().bind(f, d).accepted


def test_acquired_business_run_rate_ebitda_is_not_company_period_guidance():
    text = 'Commonwealth Financial Network: On track to complete the conversion in the fourth quarter of 2026. Continue to expect asset retention of approximately 90% and run-rate EBITDA of approximately $425 million.'
    d = _doc("LPLA", text)
    f = _fact(d, metric=GuidanceMetric.EBITDA, period="Q4FY2026", kind=GuidancePeriodKind.QUARTER, metric_text="EBITDA", value_text="$425 million", period_text="fourth quarter of 2026", low=425e6, high=425e6, action=GuidanceAction.INITIATE)
    assert not GuidanceEvidenceBinder().bind(f, d).accepted


def test_named_acquisition_revenue_contribution_is_not_consolidated_guidance():
    text = "Marvell expects meaningful revenue contributions from Celestial AI to begin in the second half of fiscal 2028, reaching a $500 million annualized run-rate."
    d = _doc("MRVL", text, year=2025)
    f = _fact(d, metric=GuidanceMetric.REVENUE, period="FY2028", kind=GuidancePeriodKind.FULL_YEAR, metric_text="revenue", value_text="$500 million", period_text="fiscal 2028", low=500e6, high=500e6, action=GuidanceAction.INITIATE)
    assert not GuidanceEvidenceBinder().bind(f, d).accepted


def test_realized_revenue_edged_down_is_not_lower_guidance():
    text = "Investment Management Q4FY2024: Revenue edged down 1% to $155 million. The decline was driven by lower incentive fees."
    d = _doc("CBRE", text)
    f = _fact(d, metric=GuidanceMetric.REVENUE, period="Q4FY2024", kind=GuidancePeriodKind.QUARTER, metric_text="Revenue", value_text="$155 million", period_text="Q4FY2024", low=155e6, high=155e6, action=GuidanceAction.LOWER)
    assert not GuidanceEvidenceBinder().bind(f, d).accepted


def test_results_year_column_cannot_own_quarter_guidance_value():
    text = "(Dollars in millions) Q3 2026 Guidance Q3 2025 Results Q3 2025 Results ex CP Y/Y Change Revenue $300 - $320 $250 $245."
    d = _doc("CGNX", text)
    f = _fact(d, metric=GuidanceMetric.REVENUE, period="Q3FY2025", kind=GuidancePeriodKind.QUARTER, metric_text="Revenue", value_text="$300 - $320", period_text="Q3 2025", low=300e6, high=320e6)
    assert not GuidanceEvidenceBinder().bind(f, d).accepted


def test_fx_headwind_amount_is_not_company_revenue_guidance():
    text = "Financial Outlook – First Quarter of 2025. Cognex expects revenue to be between $200 million and $220 million. At the midpoint, this represents a similar revenue level year-on-year, offset by a $5 million FX headwind."
    d = _doc("CGNX", text, year=2025)
    f = _fact(d, metric=GuidanceMetric.REVENUE, period="Q1FY2025", kind=GuidancePeriodKind.QUARTER, metric_text="revenue", value_text="$5 million", period_text="First Quarter of 2025", low=5e6, high=5e6, action=GuidanceAction.INITIATE)
    assert not GuidanceEvidenceBinder().bind(f, d).accepted


def test_valid_quarter_guidance_in_combined_quarter_and_full_year_section_survives():
    text = "Financial Outlook: Netskope is providing the following guidance for the third quarter and full year fiscal 2027. For the third quarter of fiscal 2027, we expect Revenue of $227 million to $229 million."
    d = _doc("NTSK", text)
    f = _fact(d, metric=GuidanceMetric.REVENUE, period="Q3FY2027", kind=GuidancePeriodKind.QUARTER, metric_text="Revenue", value_text="$227 million to $229 million", period_text="third quarter of fiscal 2027", low=227e6, high=229e6, action=GuidanceAction.INITIATE)
    assert GuidanceEvidenceBinder().bind(f, d).accepted


def test_valid_company_full_year_guidance_with_acquisition_assumption_survives():
    text = "2026 Guidance includes the acquisition. Wabtec continues to expect total revenue between $12.30 billion and $12.60 billion for full year 2026."
    d = _doc("WAB", text)
    f = _fact(d, metric=GuidanceMetric.REVENUE, period="FY2026", kind=GuidancePeriodKind.FULL_YEAR, metric_text="total revenue", value_text="$12.30 billion", period_text="full year 2026", low=12.3e9, high=12.6e9, action=GuidanceAction.NONE)
    assert GuidanceEvidenceBinder().bind(f, d).accepted
