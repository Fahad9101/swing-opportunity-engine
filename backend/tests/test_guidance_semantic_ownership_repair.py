from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from types import SimpleNamespace

from app.core.config import SOE_1_1_RULES_PATH, load_rules_for_version, rules_hash
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
from app.services import canonical_shadow_guidance_service as shadow
from app.services import guidance_raw_replay_differential_service as replay
from app.services.guidance_evidence_binder_v4 import GuidanceEvidenceBinder
from app.services.guidance_semantic_ownership_service import normalize_typed_guidance_fact


def _doc(ticker: str, text: str) -> SourceDocument:
    ts = datetime(2026, 9, 14, tzinfo=UTC)
    digest = hashlib.sha256(text.encode()).hexdigest()
    return SourceDocument(
        document_id=f"semantic-{ticker}-{digest[:12]}",
        rules_hash="semantic-ownership-test",
        ticker=ticker,
        cik="0000000001",
        accession="0000000001-26-999997",
        form="8-K",
        filing_date=ts.date(),
        source_url=f"https://www.sec.gov/Archives/edgar/data/1/{ticker.lower()}-semantic.htm",
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
    role: GuidanceFactRole = GuidanceFactRole.CURRENT,
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
        action_text=None,
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
    unit = GuidanceUnit.USD_PER_SHARE if metric is GuidanceMetric.EPS else GuidanceUnit.USD
    basis = "ADJUSTED" if metric in {GuidanceMetric.EBITDA, GuidanceMetric.FCF, GuidanceMetric.EPS} and (
        "adjusted" in metric_text.lower() or "non-gaap" in metric_text.lower()
    ) else "UNSPECIFIED"
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
        value_kind=GuidanceValueKind.ABSOLUTE_LEVEL,
        role=role,
        low=low,
        high=high,
        unit=unit,
        explicit_action=action,
        extraction_method=ExtractionMethod.DETERMINISTIC_TEXT,
        provenance=[provenance],
    )


def _normalized(fact, document):
    return normalize_typed_guidance_fact(fact, document)


def test_named_business_owner_is_not_company_scope_for_revenue_or_ebitda():
    text = (
        "2026 guidance. Ketjen: Revenue $1.1 billion to $1.2 billion; "
        "Ketjen: Adjusted EBITDA $250 million to $270 million."
    )
    document = _doc("TEST", text)
    revenue = _fact(
        document, metric=GuidanceMetric.REVENUE, period="FY2026",
        kind=GuidancePeriodKind.FULL_YEAR, metric_text="Revenue",
        value_text="$1.1 billion", period_text="2026 guidance",
        low=1.1e9, high=1.2e9,
    )
    ebitda = _fact(
        document, metric=GuidanceMetric.EBITDA, period="FY2026",
        kind=GuidancePeriodKind.FULL_YEAR, metric_text="Adjusted EBITDA",
        value_text="$250 million", period_text="2026 guidance",
        low=250e6, high=270e6,
    )
    assert _normalized(revenue, document).scope_kind is GuidanceScopeKind.SEGMENT
    assert _normalized(ebitda, document).scope_kind is GuidanceScopeKind.SEGMENT


def test_long_term_target_is_not_promoted_to_fiscal_guidance():
    text = "The company has a long-term revenue target of $4 billion. FY2025 results follow."
    document = _doc("TEST", text)
    fact = _fact(
        document, metric=GuidanceMetric.REVENUE, period="FY2025",
        kind=GuidancePeriodKind.FULL_YEAR, metric_text="revenue",
        value_text="$4 billion", period_text="FY2025",
        low=4e9, high=4e9,
    )
    normalized = _normalized(fact, document)
    assert normalized.role is GuidanceFactRole.LONG_TERM_TARGET
    assert normalized.period_kind is GuidancePeriodKind.LONG_TERM


def test_historical_result_is_marked_actual():
    text = "Broadcast revenue was $155 million for the quarter. Full-year 2026 guidance will be discussed later."
    document = _doc("TEST", text)
    fact = _fact(
        document, metric=GuidanceMetric.REVENUE, period="FY2026",
        kind=GuidancePeriodKind.FULL_YEAR, metric_text="revenue",
        value_text="$155 million", period_text="2026",
        low=155e6, high=155e6,
    )
    assert _normalized(fact, document).role is GuidanceFactRole.ACTUAL


def test_local_period_owner_conflict_fails_closed_at_strict_v4():
    text = "Full year 2026 guidance: Revenue $100 million. Third quarter 2026 revenue guidance is $25 million."
    document = _doc("TEST", text)
    wrong = _fact(
        document, metric=GuidanceMetric.REVENUE, period="Q3FY2026",
        kind=GuidancePeriodKind.QUARTER, metric_text="Revenue",
        value_text="$100 million", period_text="Third quarter 2026",
        low=100e6, high=100e6,
    )
    normalized = _normalized(wrong, document)
    assert any(item.startswith("period:") for item in normalized.metadata["semantic_ownership_issues"])
    assert not GuidanceEvidenceBinder().bind(normalized, document).accepted


def test_revenue_subcomponent_fails_closed():
    text = "FY2026 outlook. We expect to recognize $90 million of remaining performance obligations as revenue."
    document = _doc("TEST", text)
    fact = _fact(
        document, metric=GuidanceMetric.REVENUE, period="FY2026",
        kind=GuidancePeriodKind.FULL_YEAR, metric_text="revenue",
        value_text="$90 million", period_text="FY2026",
        low=90e6, high=90e6,
    )
    normalized = _normalized(fact, document)
    assert normalized.scope_kind is GuidanceScopeKind.UNKNOWN
    assert not GuidanceEvidenceBinder().bind(normalized, document).accepted


def test_explicit_ebitda_loss_range_gets_economic_negative_sign():
    text = "Full year 2026 guidance: Adjusted EBITDA loss of $19 million to $23 million."
    document = _doc("TEST", text)
    fact = _fact(
        document, metric=GuidanceMetric.EBITDA, period="FY2026",
        kind=GuidancePeriodKind.FULL_YEAR, metric_text="Adjusted EBITDA",
        value_text="$19 million to $23 million", period_text="Full year 2026",
        low=19e6, high=23e6,
    )
    normalized = _normalized(fact, document)
    assert normalized.low == -23e6
    assert normalized.high == -19e6
    assert normalized.metadata["semantic_sign_normalized"] is True


def test_breakeven_to_loss_gets_negative_to_zero_interval():
    text = "FY2026 guidance: Adjusted EBITDA guidance is between breakeven and a loss of $6 million."
    document = _doc("TEST", text)
    fact = _fact(
        document, metric=GuidanceMetric.EBITDA, period="FY2026",
        kind=GuidancePeriodKind.FULL_YEAR, metric_text="Adjusted EBITDA",
        value_text="$6 million", period_text="FY2026",
        low=0.0, high=6e6,
    )
    normalized = _normalized(fact, document)
    assert normalized.low == -6e6
    assert normalized.high == 0.0


def test_unowned_quoted_prior_role_fails_closed():
    text = "FY2026 guidance: Adjusted EBITDA is expected to be $250 million to $270 million."
    document = _doc("TEST", text)
    fact = _fact(
        document, metric=GuidanceMetric.EBITDA, period="FY2026",
        kind=GuidancePeriodKind.FULL_YEAR, metric_text="Adjusted EBITDA",
        value_text="$250 million", period_text="FY2026",
        low=250e6, high=270e6, role=GuidanceFactRole.QUOTED_PRIOR,
    )
    normalized = _normalized(fact, document)
    assert any(item.startswith("role:") for item in normalized.metadata["semantic_ownership_issues"])
    assert not GuidanceEvidenceBinder().bind(normalized, document).accepted


def test_portfolio_pruning_effect_is_not_revenue_level():
    text = "FY2026 outlook includes business exits reducing revenue by $40 million."
    document = _doc("TEST", text)
    fact = _fact(
        document, metric=GuidanceMetric.REVENUE, period="FY2026",
        kind=GuidancePeriodKind.FULL_YEAR, metric_text="revenue",
        value_text="$40 million", period_text="FY2026",
        low=40e6, high=40e6,
    )
    normalized = _normalized(fact, document)
    assert normalized.value_kind is GuidanceValueKind.DELTA
    assert not GuidanceEvidenceBinder().bind(normalized, document).accepted


def test_transaction_synergy_is_not_company_ebitda_guidance():
    text = "FY2026 transaction update: expected annual EBITDA synergies of $75 million."
    document = _doc("TEST", text)
    fact = _fact(
        document, metric=GuidanceMetric.EBITDA, period="FY2026",
        kind=GuidancePeriodKind.FULL_YEAR, metric_text="EBITDA",
        value_text="$75 million", period_text="FY2026",
        low=75e6, high=75e6,
    )
    normalized = _normalized(fact, document)
    assert normalized.scope_kind is GuidanceScopeKind.UNKNOWN
    assert not GuidanceEvidenceBinder().bind(normalized, document).accepted


def test_multi_metric_respectively_statement_fails_closed_without_coordinates():
    text = "FY2026 guidance: revenue and Adjusted EBITDA are $1.0 billion and $200 million, respectively."
    document = _doc("TEST", text)
    fact = _fact(
        document, metric=GuidanceMetric.REVENUE, period="FY2026",
        kind=GuidancePeriodKind.FULL_YEAR, metric_text="revenue",
        value_text="$1.0 billion", period_text="FY2026",
        low=1e9, high=1e9,
    )
    normalized = _normalized(fact, document)
    assert any("respectively" in item for item in normalized.metadata["semantic_ownership_issues"])
    assert not GuidanceEvidenceBinder().bind(normalized, document).accepted


def test_valid_company_total_revenue_survives_semantic_normalization_and_strict_v4():
    text = "2026 Guidance includes the acquisition. The company expects total revenue between $12.30 billion and $12.60 billion for full year 2026."
    document = _doc("TEST", text)
    fact = _fact(
        document, metric=GuidanceMetric.REVENUE, period="FY2026",
        kind=GuidancePeriodKind.FULL_YEAR, metric_text="total revenue",
        value_text="$12.30 billion", period_text="full year 2026",
        low=12.3e9, high=12.6e9,
    )
    normalized = _normalized(fact, document)
    assert normalized.scope_kind is GuidanceScopeKind.COMPANY
    assert normalized.metadata.get("semantic_ownership_issues") is None
    assert GuidanceEvidenceBinder().bind(normalized, document).accepted


def test_raw_replay_cannot_bypass_semantic_scope_normalization(monkeypatch):
    text = "2026 guidance. Ketjen: Adjusted EBITDA $250 million to $270 million."
    source, verified = _single_replay_source("TEST", text)
    document = replay._source_document(source, verified[source.source_url], rules_hash="candidate-hash")
    bad = _fact(
        document, metric=GuidanceMetric.EBITDA, period="FY2026",
        kind=GuidancePeriodKind.FULL_YEAR, metric_text="Adjusted EBITDA",
        value_text="$250 million", period_text="2026 guidance",
        low=250e6, high=270e6,
    )
    monkeypatch.setattr(
        replay,
        "extract_canonical_typed_guidance_facts",
        lambda _document: SimpleNamespace(facts=[bad], rejected_candidates=[]),
    )
    canonical, raw_count, rejected, errors = replay._canonicalize_ticker(
        [source], verified, rules_hash="candidate-hash"
    )
    assert raw_count == 1
    assert rejected == []
    assert errors == []
    assert canonical.accepted == []
    assert len(canonical.quarantined) == 1


def test_persisted_ledger_records_are_exact_accepted_classifier_inputs(monkeypatch):
    text = (
        "2026 guidance. Ketjen: Adjusted EBITDA $250 million to $270 million. "
        "The company expects total revenue between $12.30 billion and $12.60 billion for full year 2026."
    )
    document = _doc("TEST", text)
    segment = _fact(
        document, metric=GuidanceMetric.EBITDA, period="FY2026",
        kind=GuidancePeriodKind.FULL_YEAR, metric_text="Adjusted EBITDA",
        value_text="$250 million", period_text="2026 guidance",
        low=250e6, high=270e6,
    )
    company = _fact(
        document, metric=GuidanceMetric.REVENUE, period="FY2026",
        kind=GuidancePeriodKind.FULL_YEAR, metric_text="total revenue",
        value_text="$12.30 billion", period_text="full year 2026",
        low=12.3e9, high=12.6e9,
    )
    monkeypatch.setattr(
        shadow,
        "extract_canonical_typed_guidance_facts",
        lambda _document: SimpleNamespace(facts=[segment, company], rejected_candidates=[]),
    )
    rules = load_rules_for_version(SOE_1_1_RULES_PATH, "SOE-1.1.0")
    assessment, meta, errors = shadow.assess_canonical_guidance_documents(
        "TEST", [document], rules, rules_hash=rules_hash(rules)
    )
    assert errors == []
    assert assessment is not None
    assert meta["semantic_ownership_version"] == "semantic-ownership-v1"
    assert meta["records"] == len(meta["ledger_records"]) == 1
    assert meta["ledger_records"][0]["metric"] == "revenue"
    assert meta["ledger_records"][0]["low"] == 12.3e9
    assert meta["canonical_quarantined_facts"] >= 1


def _single_replay_source(ticker: str, content: str):
    payload = content.encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    url = f"https://www.sec.gov/Archives/edgar/data/1/{ticker.lower()}-semantic-replay.htm"
    source = replay.RawReplaySource(
        ticker=ticker,
        source_url=url,
        source_document_hash=digest,
        source_accession="0000000001-26-999996",
        source_timestamp=datetime(2026, 9, 14, tzinfo=UTC),
        cik="0000000001",
    )
    verified = {
        url: replay.VerifiedDocumentContent(
            content=content,
            content_hash=digest,
            content_type="text/plain",
        )
    }
    return source, verified
