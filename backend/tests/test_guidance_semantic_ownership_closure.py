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
from app.services.guidance_evidence_binder_v3 import GuidanceEvidenceBinder


def _doc(ticker: str, text: str, year: int = 2026) -> SourceDocument:
    ts = datetime(year, 9, 14, tzinfo=UTC)
    digest = hashlib.sha256(text.encode()).hexdigest()
    return SourceDocument(
        document_id=f"closure-{ticker}-{digest[:12]}",
        rules_hash="semantic-closure-test",
        ticker=ticker,
        cik="0000000001",
        accession="0000000001-26-999999",
        form="8-K",
        filing_date=ts.date(),
        source_url=f"https://www.sec.gov/Archives/edgar/data/1/{ticker.lower()}-closure.htm",
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
    evidence = EvidenceBinding(
        full_text=text,
        metric_text=metric_text,
        value_text=value_text,
        period_text=period_text,
        action_text=action.value if action is not GuidanceAction.NONE else None,
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
        accounting_basis="UNSPECIFIED",
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


def test_spxc_comparison_base_year_cannot_own_2026_guidance_value():
    text = "Raising 2026 Guidance (all comparisons against the full year 2025) Revenue range of $2.575 to $2.645 billion."
    d = _doc("SPXC", text)
    f = _fact(d, metric=GuidanceMetric.REVENUE, period="FY2025", kind=GuidancePeriodKind.FULL_YEAR,
              metric_text="Revenue", value_text="$2.575 to $2.645 billion", period_text="full year 2025",
              low=2.575e9, high=2.645e9, action=GuidanceAction.RAISE)
    r = GuidanceEvidenceBinder().bind(f, d)
    assert not r.accepted
    assert any("comparison/base year" in x for x in r.reasons)


def test_spxc_target_year_guidance_value_survives():
    text = "Raising 2026 Guidance: Revenue range of $2.575 to $2.645 billion for full year 2026."
    d = _doc("SPXC", text)
    f = _fact(d, metric=GuidanceMetric.REVENUE, period="FY2026", kind=GuidancePeriodKind.FULL_YEAR,
              metric_text="Revenue", value_text="$2.575 to $2.645 billion", period_text="full year 2026",
              low=2.575e9, high=2.645e9, action=GuidanceAction.RAISE)
    assert GuidanceEvidenceBinder().bind(f, d).accepted


def test_lrcx_quarter_ended_value_cannot_be_full_year_guidance():
    text = "Outlook For the quarter ended September 27, 2026, Lam is providing the following guidance: Revenue $8.10 Billion."
    d = _doc("LRCX", text)
    f = _fact(d, metric=GuidanceMetric.REVENUE, period="FY2026", kind=GuidancePeriodKind.FULL_YEAR,
              metric_text="Revenue", value_text="$8.10 Billion", period_text="2026",
              low=8.10e9, high=8.10e9)
    r = GuidanceEvidenceBinder().bind(f, d)
    assert not r.accepted
    assert any("quarter-ended outlook" in x for x in r.reasons)


def test_wms_realized_quarter_performance_is_not_guidance():
    text = "Performance for the first quarter of fiscal 2027 unfolded largely as we anticipated, with net sales increasing 21% to $1.0 billion and Adjusted EBITDA increasing 29% to $358.3 million."
    d = _doc("WMS", text)
    f = _fact(d, metric=GuidanceMetric.REVENUE, period="Q1FY2027", kind=GuidancePeriodKind.QUARTER,
              metric_text="net sales", value_text="$1.0 billion", period_text="first quarter of fiscal 2027",
              low=1e9, high=1e9)
    r = GuidanceEvidenceBinder().bind(f, d)
    assert not r.accepted
    assert any("realized/preliminary" in x for x in r.reasons)


def test_ptrn_year_ended_actual_table_is_not_guidance():
    text = "(in thousands) Year Ended December 31, 2023 2024 2025 Revenues $ 1,366,417"
    d = _doc("PTRN", text)
    f = _fact(d, metric=GuidanceMetric.REVENUE, period="FY2025", kind=GuidancePeriodKind.FULL_YEAR,
              metric_text="Revenues", value_text="$ 1,366,417", period_text="2025",
              low=1.366417e9, high=1.366417e9)
    r = GuidanceEvidenceBinder().bind(f, d)
    assert not r.accepted
    assert any("realized/preliminary" in x for x in r.reasons)


def test_transaction_eps_accretion_is_not_eps_guidance():
    text = "The Company expects the transaction to be accretive to EPS in subsequent years, with anticipated EPS accretion of between $0.40 and $0.45 in 2028."
    d = _doc("FSS", text)
    f = _fact(d, metric=GuidanceMetric.EPS, period="FY2028", kind=GuidancePeriodKind.FULL_YEAR,
              metric_text="EPS accretion", value_text="$0.40", period_text="2028",
              low=0.40, high=0.40)
    r = GuidanceEvidenceBinder().bind(f, d)
    assert not r.accepted
    assert any("transaction EPS accretion" in x for x in r.reasons)


def test_transaction_synergy_is_not_issuer_ebitda_guidance():
    text = "Represents 12.0x projected 2025 EBITDA multiple when adjusting for estimated tax benefits of ~$95 million and expected run-rate cost synergies of $25 million."
    d = _doc("WAB", text)
    f = _fact(d, metric=GuidanceMetric.EBITDA, period="FY2025", kind=GuidancePeriodKind.FULL_YEAR,
              metric_text="EBITDA", value_text="$25 million", period_text="2025",
              low=25e6, high=25e6)
    r = GuidanceEvidenceBinder().bind(f, d)
    assert not r.accepted
    assert any("transaction multiple/synergy" in x for x in r.reasons)


def test_tam_is_not_revenue_guidance():
    text = "Management estimate: the broader safety and security systems market yields a ~$2.5bn annual TAM."
    d = _doc("FSS", text)
    f = _fact(d, metric=GuidanceMetric.REVENUE, period="FY2026", kind=GuidancePeriodKind.FULL_YEAR,
              metric_text="market", value_text="$2.5bn", period_text="2026" if "2026" in text else "annual",
              low=2.5e9, high=2.5e9)
    r = GuidanceEvidenceBinder().bind(f, d)
    assert not r.accepted


def test_contract_contribution_is_not_consolidated_revenue_guidance():
    text = "We signed a large cloud services agreement that is expected to contribute more than $30 billion in annual revenue."
    d = _doc("ORCL", text)
    f = _fact(d, metric=GuidanceMetric.REVENUE, period="FY2026", kind=GuidancePeriodKind.FULL_YEAR,
              metric_text="revenue", value_text="$30 billion", period_text="annual",
              low=30e9, high=30e9)
    r = GuidanceEvidenceBinder().bind(f, d)
    assert not r.accepted
    assert any("contract/agreement contribution" in x for x in r.reasons)


def test_valid_divestiture_adjusted_outlook_survives():
    text = "Full Year 2026 Outlook: Revenue is expected to be between $347 million and $357 million, representing expected year-over-year growth of 24% excluding the impact of the Maximum Effort divestiture."
    d = _doc("MNTN", text)
    f = _fact(d, metric=GuidanceMetric.REVENUE, period="FY2026", kind=GuidancePeriodKind.FULL_YEAR,
              metric_text="Revenue", value_text="$347 million", period_text="Full Year 2026",
              low=347e6, high=357e6)
    assert GuidanceEvidenceBinder().bind(f, d).accepted


def test_valid_consolidated_guidance_with_acquisition_assumption_survives():
    text = "2026 Guidance includes the acquisition. Wabtec continues to expect total revenue between $12.30 billion and $12.60 billion for full year 2026."
    d = _doc("WAB", text)
    f = _fact(d, metric=GuidanceMetric.REVENUE, period="FY2026", kind=GuidancePeriodKind.FULL_YEAR,
              metric_text="total revenue", value_text="$12.30 billion", period_text="full year 2026",
              low=12.3e9, high=12.6e9)
    assert GuidanceEvidenceBinder().bind(f, d).accepted
