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
    GuidanceValueKind,
    TypedGuidanceFact,
)
from app.domain.soe_v1_1 import ExtractionMethod, GuidanceAction, GuidanceMetric, SourceDocument
from app.services.guidance_evidence_binder_v4 import GuidanceEvidenceBinder
from app.services.guidance_semantic_ownership_service import normalize_typed_guidance_fact


def _doc(text: str) -> SourceDocument:
    ts = datetime(2026, 9, 15, tzinfo=UTC)
    digest = hashlib.sha256(text.encode()).hexdigest()
    return SourceDocument(
        document_id=f"audit-{digest[:12]}", rules_hash="audit-regression", ticker="TEST",
        cik="0000000001", accession="0000000001-26-999998", form="8-K",
        filing_date=ts.date(), source_url="https://www.sec.gov/Archives/edgar/data/1/audit.htm",
        source_timestamp=ts, fetched_at=ts, content_hash=digest, content_type="text/plain", content=text,
    )


def _fact(document: SourceDocument, *, metric: GuidanceMetric, period: str, metric_text: str,
          value_text: str, low: float, high: float, unit: GuidanceUnit = GuidanceUnit.USD_MILLION,
          role: GuidanceFactRole = GuidanceFactRole.CURRENT,
          action: GuidanceAction = GuidanceAction.NONE, basis: str = "UNSPECIFIED",
          period_text: str | None = None) -> TypedGuidanceFact:
    text = document.content or ""
    metric_start = text.index(metric_text)
    value_start = text.index(value_text)
    ptext = period_text or period
    period_start = text.index(ptext)
    evidence = EvidenceBinding(
        full_text=text, metric_text=metric_text, value_text=value_text, period_text=ptext,
        action_text=None, metric_start=metric_start, metric_end=metric_start + len(metric_text),
        value_start=value_start, value_end=value_start + len(value_text),
        period_start=period_start, period_end=period_start + len(ptext),
    )
    provenance = GuidanceProvenance(
        document_id=document.document_id, source=document.source, source_url=document.source_url,
        source_accession=document.accession, source_timestamp=document.source_timestamp,
        source_document_hash=document.content_hash, evidence=evidence,
    )
    return TypedGuidanceFact(
        ticker="TEST", metric=metric, raw_metric_label=metric.value, fiscal_period=period,
        authoritative_period=period,
        period_kind=GuidancePeriodKind.QUARTER if period.startswith("Q") else GuidancePeriodKind.FULL_YEAR,
        accounting_basis=basis, scope_kind=GuidanceScopeKind.COMPANY, scope_label=None,
        value_kind=GuidanceValueKind.ABSOLUTE_LEVEL, role=role, low=low, high=high, unit=unit,
        explicit_action=action, extraction_method=ExtractionMethod.DETERMINISTIC_TEXT,
        provenance=[provenance],
    )


def _norm(fact, document):
    return normalize_typed_guidance_fact(fact, document)


def test_flattened_named_business_owner_is_segment_without_colon():
    document = _doc("2026 guidance Ketjen adjusted EBITDA $120 million to $150 million.")
    fact = _fact(document, metric=GuidanceMetric.EBITDA, period="FY2026",
                 metric_text="adjusted EBITDA", value_text="$120 million", low=120, high=150,
                 period_text="2026 guidance")
    normalized = _norm(fact, document)
    assert normalized.scope_kind is GuidanceScopeKind.SEGMENT
    assert normalized.scope_label == "Ketjen"
    assert not GuidanceEvidenceBinder().bind(normalized, document).accepted


def test_long_term_phrase_after_selected_value_is_not_annual_guidance():
    text = "FY2026 filing context. We remain committed to achieve our $4 billion long-term revenue objective."
    document = _doc(text)
    fact = _fact(document, metric=GuidanceMetric.REVENUE, period="FY2026", metric_text="revenue",
                 value_text="$4 billion", low=4, high=4, unit=GuidanceUnit.USD_BILLION,
                 period_text="FY2026")
    normalized = _norm(fact, document)
    assert normalized.role is GuidanceFactRole.LONG_TERM_TARGET
    assert normalized.period_kind is GuidancePeriodKind.LONG_TERM


def test_preliminary_result_is_actual_even_if_guidance_appears_later():
    document = _doc("Preliminary unaudited results: revenue of $803 million for Q4 2024. Full-year 2025 guidance follows.")
    fact = _fact(document, metric=GuidanceMetric.REVENUE, period="Q4FY2024", metric_text="revenue",
                 value_text="$803 million", low=803, high=803, period_text="Q4 2024")
    assert _norm(fact, document).role is GuidanceFactRole.ACTUAL


def test_nearest_period_owner_beats_later_comparator_period():
    document = _doc("Q4 2024 revenue guidance is $900 million, compared to Q4 2023 revenue of $800 million.")
    fact = _fact(document, metric=GuidanceMetric.REVENUE, period="Q4FY2023", metric_text="revenue",
                 value_text="$900 million", low=900, high=900, period_text="Q4 2023")
    normalized = _norm(fact, document)
    assert any(item.startswith("period:") for item in normalized.metadata["semantic_ownership_issues"])
    assert not GuidanceEvidenceBinder().bind(normalized, document).accepted


def test_flattened_multi_metric_table_fails_closed():
    document = _doc("FY2025 Guidance Date Issued Net Revenue Adjusted EBITDA March 2025 $428 million to $440 million $70 million to $76 million")
    fact = _fact(document, metric=GuidanceMetric.EBITDA, period="FY2025", metric_text="Adjusted EBITDA",
                 value_text="$428 million", low=428, high=440, period_text="FY2025")
    normalized = _norm(fact, document)
    assert any(item.startswith("column:") for item in normalized.metadata["semantic_ownership_issues"])
    assert not GuidanceEvidenceBinder().bind(normalized, document).accepted


def test_mixed_scale_range_with_collapsed_endpoint_fails_closed():
    document = _doc("FY2026 guidance: total revenue $980 million to $1 billion.")
    fact = _fact(document, metric=GuidanceMetric.REVENUE, period="FY2026", metric_text="total revenue",
                 value_text="$980 million", low=980, high=980, unit=GuidanceUnit.USD_MILLION,
                 period_text="FY2026")
    normalized = _norm(fact, document)
    assert any(item.startswith("value:") for item in normalized.metadata["semantic_ownership_issues"])
    assert not GuidanceEvidenceBinder().bind(normalized, document).accepted


def test_revenue_subcomponents_and_product_sales_are_not_company_revenue():
    document = _doc("FY2026 guidance includes inorganic revenue of $33 million. INGREZZA Net Sales Guidance is $2.7 billion to $2.8 billion.")
    inorganic = _fact(document, metric=GuidanceMetric.REVENUE, period="FY2026", metric_text="revenue",
                      value_text="$33 million", low=33, high=33, period_text="FY2026")
    product = _fact(document, metric=GuidanceMetric.REVENUE, period="FY2026", metric_text="Net Sales Guidance",
                    value_text="$2.7 billion", low=2.7, high=2.8, unit=GuidanceUnit.USD_BILLION,
                    period_text="FY2026")
    assert not GuidanceEvidenceBinder().bind(_norm(inorganic, document), document).accepted
    normalized_product = _norm(product, document)
    assert normalized_product.scope_kind is GuidanceScopeKind.PRODUCT
    assert not GuidanceEvidenceBinder().bind(normalized_product, document).accepted


def test_divestiture_effect_is_not_total_ebitda_guidance():
    document = _doc("FY2026 outlook includes a reduction of approximately $30 million from the sale of the Graphics business in adjusted EBITDA.")
    fact = _fact(document, metric=GuidanceMetric.EBITDA, period="FY2026", metric_text="adjusted EBITDA",
                 value_text="$30 million", low=30, high=30, period_text="FY2026")
    normalized = _norm(fact, document)
    assert normalized.value_kind is GuidanceValueKind.DELTA
    assert not GuidanceEvidenceBinder().bind(normalized, document).accepted


def test_from_to_old_value_becomes_prior_and_current_action_is_removed():
    document = _doc("FY2026 revenue guidance increased from $1.29 billion to $1.33 billion.")
    fact = _fact(document, metric=GuidanceMetric.REVENUE, period="FY2026", metric_text="revenue",
                 value_text="$1.29 billion", low=1.29, high=1.29, unit=GuidanceUnit.USD_BILLION,
                 period_text="FY2026", action=GuidanceAction.RAISE)
    normalized = _norm(fact, document)
    assert normalized.role is GuidanceFactRole.QUOTED_PRIOR
    assert normalized.explicit_action is GuidanceAction.NONE


def test_loss_range_recovers_second_endpoint_in_fact_units():
    document = _doc("FY2025 outlook: adjusted EBITDA loss in range $9 million to $5 million.")
    fact = _fact(document, metric=GuidanceMetric.EBITDA, period="FY2025", metric_text="adjusted EBITDA",
                 value_text="$9 million", low=9, high=9, unit=GuidanceUnit.USD_MILLION,
                 period_text="FY2025")
    normalized = _norm(fact, document)
    assert normalized.low == -9
    assert normalized.high == -5
    assert normalized.metadata["semantic_sign_normalized"] is True


def test_adjusted_basis_is_normalized_from_owned_metric_phrase():
    document = _doc("FY2026 guidance: adjusted diluted EPS $4.15 to $5.15.")
    fact = _fact(document, metric=GuidanceMetric.EPS, period="FY2026", metric_text="adjusted diluted EPS",
                 value_text="$4.15", low=4.15, high=5.15, unit=GuidanceUnit.USD_PER_SHARE,
                 period_text="FY2026")
    assert _norm(fact, document).accounting_basis == "ADJUSTED"


def test_valid_company_total_range_with_comparator_survives():
    document = _doc("FY2026 guidance: the company expects total revenue $12.3 billion to $12.6 billion, compared to FY2025 revenue of $11.5 billion.")
    fact = _fact(document, metric=GuidanceMetric.REVENUE, period="FY2026", metric_text="total revenue",
                 value_text="$12.3 billion", low=12.3, high=12.6, unit=GuidanceUnit.USD_BILLION,
                 period_text="FY2026")
    normalized = _norm(fact, document)
    assert normalized.metadata.get("semantic_ownership_issues") is None
    assert normalized.scope_kind is GuidanceScopeKind.COMPANY
    assert GuidanceEvidenceBinder().bind(normalized, document).accepted
