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
        document_id=f"v2-{ticker}-{digest[:12]}",
        rules_hash="binder-v2-test",
        ticker=ticker,
        cik="0000000001",
        accession="0000000001-26-999999",
        form="8-K",
        filing_date=ts.date(),
        source_url=f"https://www.sec.gov/Archives/edgar/data/1/{ticker.lower()}-v2.htm",
        source_timestamp=ts,
        fetched_at=ts,
        content_hash=digest,
        content_type="text/plain",
        content=text,
    )


def _fact(
    document,
    *,
    metric,
    period,
    kind,
    metric_text,
    value_text=None,
    period_text,
    low=None,
    high=None,
    unit=GuidanceUnit.USD,
    basis="UNSPECIFIED",
    action=GuidanceAction.NONE,
):
    text = document.content
    ms = text.index(metric_text)
    ps = text.index(period_text)
    vs = text.index(value_text) if value_text else None
    ev = EvidenceBinding(
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
    prov = GuidanceProvenance(
        document_id=document.document_id,
        source=document.source,
        source_url=document.source_url,
        source_accession=document.accession,
        source_timestamp=document.source_timestamp,
        source_document_hash=document.content_hash,
        evidence=ev,
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
        provenance=[prov],
    )


def test_anet_generic_quarter_context_cannot_become_fy():
    d = _doc("ANET", "Financial Outlook For the third quarter of 2026, we expect: Revenue of approximately $3.3 billion")
    f = _fact(
        d,
        metric=GuidanceMetric.REVENUE,
        period="FY2026",
        kind=GuidancePeriodKind.FULL_YEAR,
        metric_text="Revenue",
        value_text="$3.3 billion",
        period_text="2026",
        low=3.3e9,
        high=3.3e9,
    )
    r = GuidanceEvidenceBinder().bind(f, d)
    assert not r.accepted
    assert not r.dimensions["period"]


def test_quarter_fact_requires_quarter_identifier():
    d = _doc("CBRE", "The company raised its 2026 core EPS outlook to $7.60 to $7.80.")
    f = _fact(
        d,
        metric=GuidanceMetric.EPS,
        period="Q1FY2026",
        kind=GuidancePeriodKind.QUARTER,
        metric_text="EPS",
        value_text="$7.60 to $7.80",
        period_text="2026",
        low=7.6,
        high=7.8,
        unit=GuidanceUnit.USD_PER_SHARE,
        action=GuidanceAction.RAISE,
    )
    r = GuidanceEvidenceBinder().bind(f, d)
    assert not r.accepted
    assert not r.dimensions["period"]


def test_asth_actual_column_rejected():
    d = _doc("ASTH", "FY 2026 Guidance Range Actual FY 2025 Results $3,800 - $4,100 $3,181.8 Total Revenue $250 - $280 $205.4 Adjusted EBITDA")
    f = _fact(
        d,
        metric=GuidanceMetric.REVENUE,
        period="FY2025",
        kind=GuidancePeriodKind.FULL_YEAR,
        metric_text="Revenue",
        value_text="$250 - $280",
        period_text="FY 2025",
        low=250,
        high=280,
    )
    assert not GuidanceEvidenceBinder().bind(f, d).accepted


def test_accounting_standard_guidance_is_not_company_guidance():
    d = _doc("TEM", "The Company is evaluating the impact of the guidance on disclosures. FASB issued ASU No. 2025-07 Revenue from Contracts with Customers, which amends existing guidance and reduces disclosure requirements. Revenue 2025.")
    f = _fact(
        d,
        metric=GuidanceMetric.REVENUE,
        period="FY2025",
        kind=GuidancePeriodKind.FULL_YEAR,
        metric_text="Revenue",
        value_text=None,
        period_text="2025",
        action=GuidanceAction.LOWER,
    )
    r = GuidanceEvidenceBinder().bind(f, d)
    assert not r.accepted
    assert not r.dimensions["action"]


def test_rpo_schedule_not_guidance():
    d = _doc("VOYG", "The Company expects to recognize net sales relating to existing performance obligations of approximately $111.8 million for fiscal year 2026.")
    f = _fact(
        d,
        metric=GuidanceMetric.REVENUE,
        period="FY2026",
        kind=GuidancePeriodKind.FULL_YEAR,
        metric_text="net sales",
        value_text="$111.8 million",
        period_text="fiscal year 2026",
        low=111.8e6,
        high=111.8e6,
        action=GuidanceAction.INITIATE,
    )
    r = GuidanceEvidenceBinder().bind(f, d)
    assert not r.accepted
    assert not r.dimensions["action"]


def test_wfrd_historical_lower_activity_not_cut():
    d = _doc("WFRD", "Second quarter 2026 Latin America revenue of $197 million decreased by $26 million, or 12% sequentially, primarily from lower Drilling-related Services activity.")
    f = _fact(
        d,
        metric=GuidanceMetric.REVENUE,
        period="Q2FY2026",
        kind=GuidancePeriodKind.QUARTER,
        metric_text="revenue",
        value_text="$197 million",
        period_text="Second quarter 2026",
        low=197e6,
        high=197e6,
        action=GuidanceAction.LOWER,
    )
    r = GuidanceEvidenceBinder().bind(f, d)
    assert not r.accepted
    assert not r.dimensions["action"]


def test_kntk_lower_fuel_costs_not_guidance_cut():
    d = _doc("KNTK", "First quarter 2026 gross margin grew year-over-year on lower fuel costs and higher fee gross margin. 2026 Guidance Affirmed.")
    f = _fact(
        d,
        metric=GuidanceMetric.GROSS_MARGIN,
        period="Q1FY2026",
        kind=GuidancePeriodKind.QUARTER,
        metric_text="gross margin",
        value_text=None,
        period_text="First quarter 2026",
        action=GuidanceAction.LOWER,
        unit=GuidanceUnit.UNKNOWN,
    )
    r = GuidanceEvidenceBinder().bind(f, d)
    assert not r.accepted
    assert not r.dimensions["action"]


def test_gva_realized_q2_revenue_not_fy_guidance():
    d = _doc("GVA", "Granite Reports Second Quarter 2026 Results. Raised 2026 revenue guidance by $100 million. Q2 revenue increased 29% year-over-year to $1.5 billion.")
    f = _fact(
        d,
        metric=GuidanceMetric.REVENUE,
        period="FY2026",
        kind=GuidancePeriodKind.FULL_YEAR,
        metric_text="revenue",
        value_text="$1.5 billion",
        period_text="2026",
        low=1.5e9,
        high=1.5e9,
    )
    assert not GuidanceEvidenceBinder().bind(f, d).accepted


def test_chrd_commodity_assumption_not_fcf_value():
    d = _doc("CHRD", "In 2026, Chord expects to generate Adjusted Free Cash Flow of approximately $700MM ($64/Bbl WTI).")
    f = _fact(
        d,
        metric=GuidanceMetric.FCF,
        period="FY2026",
        kind=GuidancePeriodKind.FULL_YEAR,
        metric_text="Adjusted Free Cash Flow",
        value_text="$64",
        period_text="2026",
        low=64,
        high=64,
        basis="ADJUSTED",
    )
    r = GuidanceEvidenceBinder().bind(f, d)
    assert not r.accepted
    assert not r.dimensions["row"]


def test_chrd_value_owned_by_following_fcf_not_ebitda():
    d = _doc("CHRD", "In 2026, Chord expects Adjusted EBITDA of $2.3B and $700MM of Adjusted Free Cash Flow.")
    f = _fact(
        d,
        metric=GuidanceMetric.EBITDA,
        period="FY2026",
        kind=GuidancePeriodKind.FULL_YEAR,
        metric_text="Adjusted EBITDA",
        value_text="$700MM",
        period_text="2026",
        low=700e6,
        high=700e6,
        basis="ADJUSTED",
    )
    r = GuidanceEvidenceBinder().bind(f, d)
    assert not r.accepted
    assert not r.dimensions["row"]


def test_shak_flattened_q_and_fy_guidance_fails_closed():
    d = _doc("SHAK", "Q2 2026 Guidance FY 2026 Guidance Revenue $424m $428m $1.6b $1.7b Adjusted EBITDA $57m $59m $230m $245m")
    f = _fact(
        d,
        metric=GuidanceMetric.REVENUE,
        period="FY2026",
        kind=GuidancePeriodKind.FULL_YEAR,
        metric_text="Revenue",
        value_text="$424m",
        period_text="FY 2026",
        low=424e6,
        high=424e6,
    )
    r = GuidanceEvidenceBinder().bind(f, d)
    assert not r.accepted
    assert not r.dimensions["column"]


def test_rate_case_amount_not_revenue_guidance():
    d = _doc("SWX", "NV regulatory strategy: filed a general rate case requesting to increase revenues by approximately $71.3 million with rates anticipated to become effective October 2026.")
    f = _fact(
        d,
        metric=GuidanceMetric.REVENUE,
        period="FY2026",
        kind=GuidancePeriodKind.FULL_YEAR,
        metric_text="revenues",
        value_text="$71.3 million",
        period_text="2026",
        low=71.3e6,
        high=71.3e6,
    )
    r = GuidanceEvidenceBinder().bind(f, d)
    assert not r.accepted
    assert not r.dimensions["action"]


def test_third_party_market_forecast_not_issuer_guidance():
    d = _doc("BWMN", "The market for engineering services has expected total revenue of $312 billion in 2026, according to IBISWorld.")
    f = _fact(
        d,
        metric=GuidanceMetric.REVENUE,
        period="FY2026",
        kind=GuidancePeriodKind.FULL_YEAR,
        metric_text="revenue",
        value_text="$312 billion",
        period_text="2026",
        low=312e9,
        high=312e9,
    )
    r = GuidanceEvidenceBinder().bind(f, d)
    assert not r.accepted
    assert not r.dimensions["issuer"]


def test_remote_reserve_horizon_not_near_term_guidance():
    d = _doc("ALB", "The reserve estimate assumes the plant can produce until the end of 2058, with revenue of $3,790 million expected over the reserve life.")
    f = _fact(
        d,
        metric=GuidanceMetric.REVENUE,
        period="FY2058",
        kind=GuidancePeriodKind.FULL_YEAR,
        metric_text="revenue",
        value_text="$3,790 million",
        period_text="2058",
        low=3.79e9,
        high=3.79e9,
    )
    r = GuidanceEvidenceBinder().bind(f, d)
    assert not r.accepted
    assert not r.dimensions["period"]


def test_valid_ee_full_year_ebitda_revision_survives_v2():
    d = _doc("EE", "Revised 2026 Financial Outlook. Adjusted EBITDA for the full year 2026 is now expected to range between $480 million and $510 million.")
    f = _fact(
        d,
        metric=GuidanceMetric.EBITDA,
        period="FY2026",
        kind=GuidancePeriodKind.FULL_YEAR,
        metric_text="Adjusted EBITDA",
        value_text="$480 million and $510 million",
        period_text="full year 2026",
        low=480e6,
        high=510e6,
        basis="ADJUSTED",
    )
    assert GuidanceEvidenceBinder().bind(f, d).accepted
