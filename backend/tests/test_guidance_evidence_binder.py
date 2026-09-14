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
from app.services.guidance_evidence_binder import GuidanceEvidenceBinder
from app.services.guidance_raw_canonical_extractor import extract_canonical_typed_guidance_facts


def _doc(ticker: str, text: str) -> SourceDocument:
    ts = datetime(2026, 9, 14, tzinfo=UTC)
    digest = hashlib.sha256(text.encode()).hexdigest()
    return SourceDocument(
        document_id=f"binder-{ticker}-{digest[:12]}",
        rules_hash="binder-test",
        ticker=ticker,
        cik="0000000001",
        accession="0000000001-26-888888",
        form="8-K",
        filing_date=ts.date(),
        source_url=f"https://www.sec.gov/Archives/edgar/data/1/{ticker.lower()}-binder.htm",
        source_timestamp=ts,
        fetched_at=ts,
        content_hash=digest,
        content_type="text/plain",
        content=text,
    )


def _manual_fact(
    document: SourceDocument,
    *,
    metric: GuidanceMetric,
    fiscal_period: str,
    period_kind: GuidancePeriodKind,
    metric_text: str,
    value_text: str,
    period_text: str,
    low: float,
    high: float,
    unit: GuidanceUnit = GuidanceUnit.USD_MILLION,
    accounting_basis: str = "UNSPECIFIED",
    action: GuidanceAction = GuidanceAction.NONE,
) -> TypedGuidanceFact:
    text = document.content
    metric_start = text.index(metric_text)
    value_start = text.index(value_text)
    period_start = text.index(period_text)
    provenance = GuidanceProvenance(
        document_id=document.document_id,
        source=document.source,
        source_url=document.source_url,
        source_accession=document.accession,
        source_timestamp=document.source_timestamp,
        source_document_hash=document.content_hash,
        evidence=EvidenceBinding(
            full_text=text,
            metric_text=metric_text,
            value_text=value_text,
            period_text=period_text,
            action_text=action.value if action is not GuidanceAction.NONE else None,
            metric_start=metric_start,
            metric_end=metric_start + len(metric_text),
            value_start=value_start,
            value_end=value_start + len(value_text),
            period_start=period_start,
            period_end=period_start + len(period_text),
        ),
    )
    return TypedGuidanceFact(
        ticker=document.ticker,
        metric=metric,
        raw_metric_label=metric.value,
        fiscal_period=fiscal_period,
        authoritative_period=fiscal_period,
        period_kind=period_kind,
        accounting_basis=accounting_basis,
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


def test_fn_quarter_guidance_cannot_enter_as_full_year_guidance():
    text = (
        "Based on information available as of February 3, 2025, Fabrinet is issuing guidance for its "
        "third fiscal quarter ending March 28, 2025, as follows: Fabrinet expects third quarter revenue "
        "to be in the range of $850 million to $870 million."
    )
    document = _doc("FN", text)
    facts = list(extract_canonical_typed_guidance_facts(document).facts)
    assert any(f.metric is GuidanceMetric.REVENUE for f in facts)
    decisions = [GuidanceEvidenceBinder().bind(fact, document) for fact in facts if fact.metric is GuidanceMetric.REVENUE]
    assert decisions
    assert not any(decision.accepted for decision in decisions)
    assert any("quarter evidence cannot be admitted as full-year guidance" in " ".join(decision.reasons) for decision in decisions)


def test_myrg_historical_project_change_is_not_forward_guidance():
    text = (
        "During the year ended December 31, 2025, changes in estimates pertaining to certain projects "
        "decreased consolidated gross margin by 1.4% compared with the prior year."
    )
    document = _doc("MYRG", text)
    fact = _manual_fact(
        document,
        metric=GuidanceMetric.GROSS_MARGIN,
        fiscal_period="FY2025",
        period_kind=GuidancePeriodKind.FULL_YEAR,
        metric_text="gross margin",
        value_text="1.4%",
        period_text="2025",
        low=0.014,
        high=0.014,
        unit=GuidanceUnit.FRACTION,
    )
    result = GuidanceEvidenceBinder().bind(fact, document)
    assert result.accepted is False
    assert result.dimensions["action"] is False
    assert any("historical/realized result" in reason for reason in result.reasons)


def test_rblx_flattened_quarter_and_full_year_columns_fail_closed():
    text = (
        "Guidance Updated Guidance Q2 2026 Full Year 2026 ($ in millions) Low High Low High "
        "Revenue $1,390 $1,450 $5,865 $6,135 YoY % 29% 34% 20% 25%."
    )
    document = _doc("RBLX", text)
    fact = _manual_fact(
        document,
        metric=GuidanceMetric.REVENUE,
        fiscal_period="FY2026",
        period_kind=GuidancePeriodKind.FULL_YEAR,
        metric_text="Revenue",
        value_text="$1,390",
        period_text="Full Year 2026",
        low=1390.0,
        high=1390.0,
    )
    result = GuidanceEvidenceBinder().bind(fact, document)
    assert result.accepted is False
    assert result.dimensions["column"] is False
    assert any("row×column coordinate" in reason for reason in result.reasons)


def test_tln_respectively_binding_rejects_ebitda_range_as_fcf():
    text = (
        "Reaffirming 2026 Adjusted EBITDA and Adjusted Free Cash Flow guidance ranges of "
        "$1,750 million - $2,050 million and $980 million - $1,180 million, respectively."
    )
    document = _doc("TLN", text)
    wrong = _manual_fact(
        document,
        metric=GuidanceMetric.FCF,
        fiscal_period="FY2026",
        period_kind=GuidancePeriodKind.FULL_YEAR,
        metric_text="Adjusted Free Cash Flow",
        value_text="$1,750 million - $2,050 million",
        period_text="2026",
        low=1750.0,
        high=2050.0,
        accounting_basis="ADJUSTED",
        action=GuidanceAction.REAFFIRM,
    )
    result = GuidanceEvidenceBinder().bind(wrong, document)
    assert result.accepted is False
    assert result.dimensions["column"] is False
    assert any("respectively-linked" in reason for reason in result.reasons)


def test_tln_respectively_binding_accepts_fcf_owned_range():
    text = (
        "Reaffirming 2026 Adjusted EBITDA and Adjusted Free Cash Flow guidance ranges of "
        "$1,750 million - $2,050 million and $980 million - $1,180 million, respectively."
    )
    document = _doc("TLN", text)
    correct = _manual_fact(
        document,
        metric=GuidanceMetric.FCF,
        fiscal_period="FY2026",
        period_kind=GuidancePeriodKind.FULL_YEAR,
        metric_text="Adjusted Free Cash Flow",
        value_text="$980 million - $1,180 million",
        period_text="2026",
        low=980.0,
        high=1180.0,
        accounting_basis="ADJUSTED",
        action=GuidanceAction.REAFFIRM,
    )
    result = GuidanceEvidenceBinder().bind(correct, document)
    assert result.accepted is True, result.reasons


def test_valid_full_year_eps_cut_survives_strict_binding():
    text = "The Company reduced its full year 2026 GAAP diluted earnings per share outlook range to $2.54 to $2.84."
    document = _doc("TFX", text)
    facts = list(extract_canonical_typed_guidance_facts(document).facts)
    candidates = [
        fact for fact in facts
        if fact.metric is GuidanceMetric.EPS and fact.explicit_action is GuidanceAction.LOWER
    ]
    assert candidates
    accepted = [GuidanceEvidenceBinder().bind(fact, document) for fact in candidates]
    assert any(result.accepted for result in accepted), [result.reasons for result in accepted]


def test_valid_annual_adjusted_ebitda_range_survives_strict_binding():
    text = "The Company now expects full year 2026 adjusted EBITDA to be in the range of $690 million to $710 million."
    document = _doc("ESI", text)
    facts = list(extract_canonical_typed_guidance_facts(document).facts)
    candidates = [fact for fact in facts if fact.metric is GuidanceMetric.EBITDA]
    assert candidates
    accepted = [GuidanceEvidenceBinder().bind(fact, document) for fact in candidates]
    assert any(result.accepted for result in accepted), [result.reasons for result in accepted]


def test_issuer_provenance_mismatch_fails_closed():
    text = "The Company expects full year 2026 revenue of $900 million to $920 million."
    document = _doc("GOOD", text)
    fact = _manual_fact(
        document,
        metric=GuidanceMetric.REVENUE,
        fiscal_period="FY2026",
        period_kind=GuidancePeriodKind.FULL_YEAR,
        metric_text="revenue",
        value_text="$900 million to $920 million",
        period_text="full year 2026",
        low=900.0,
        high=920.0,
    )
    foreign = document.model_copy(update={"ticker": "OTHER"})
    result = GuidanceEvidenceBinder().bind(fact, foreign)
    assert result.accepted is False
    assert result.dimensions["issuer"] is False
