from __future__ import annotations

from datetime import UTC, datetime

import yaml

from app.domain.guidance_canonical_v1 import GuidanceInvariantCode, GuidanceScopeKind
from app.domain.soe_v1_1 import ExtractionMethod, GuidanceAction, GuidanceClassification, GuidanceMetric, GuidanceMetricRecord
from app.services.guidance_canonical_assessment_service import assess_canonicalization_result
from app.services.guidance_canonical_migration_service import canonicalize_legacy_records_for_migration


T1 = datetime(2026, 1, 1, tzinfo=UTC)
T2 = datetime(2026, 4, 1, tzinfo=UTC)
T3 = datetime(2026, 7, 1, tzinfo=UTC)


def rules() -> dict:
    with open("config/soe_v1_1_rules.yaml", "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def record(
    *,
    ticker: str = "TEST",
    metric: GuidanceMetric = GuidanceMetric.REVENUE,
    period: str = "FY2026",
    low: float | None,
    high: float | None,
    unit: str,
    evidence: str,
    ts: datetime,
    action: GuidanceAction = GuidanceAction.NONE,
    basis: str = "UNSPECIFIED",
    supersedes=None,
):
    return GuidanceMetricRecord(
        rules_hash="migration-test",
        ticker=ticker,
        fiscal_period=period,
        metric=metric,
        accounting_basis=basis,
        low=low,
        high=high,
        unit=unit,
        source="SEC EDGAR",
        source_url=f"https://www.sec.gov/{ticker}-{ts.date().isoformat()}.htm",
        source_accession=f"acc-{ticker}-{ts.date().isoformat()}",
        source_timestamp=ts,
        explicit_action=action,
        verified=True,
        extraction_method=ExtractionMethod.STRUCTURED,
        evidence_span=evidence,
        source_document_hash=f"hash-{ticker}-{ts.date().isoformat()}",
        as_of=ts,
        fetched_at=ts,
        stale=False,
        supersedes_record_id=supersedes,
    )


def test_legacy_normalized_money_is_not_scaled_twice():
    rows = [
        record(
            low=138_500_000,
            high=141_500_000,
            unit="USD",
            evidence="FY2026 revenue guidance $138.5 - $141.5 million",
            ts=T1,
        ),
        record(
            low=470_000_000,
            high=471_000_000,
            unit="USD",
            evidence="normalized_explicit_guidance_scope;FY2026 guidance (USD millions); Revenue $470 - $471",
            ts=T2,
        ),
    ]
    result = canonicalize_legacy_records_for_migration(rows)
    assert not result.quarantined
    values = sorted((fact.low, fact.high) for fact in result.accepted)
    assert values == [(138_500_000.0, 141_500_000.0), (470_000_000.0, 471_000_000.0)]
    assessment = assess_canonicalization_result(result, "TEST", rules(), rules_hash="migration-test", as_of=T2)
    assert assessment.classification is GuidanceClassification.NOT_DETERIORATED


def test_product_revenue_is_not_company_level_guidance():
    row = record(
        ticker="KNSA",
        low=980_000_000,
        high=995_000_000,
        unit="USD",
        evidence="Financial Guidance Kiniksa expects 2026 ARCALYST net product revenue of between $980 million and $995 million.",
        ts=T3,
    )
    result = canonicalize_legacy_records_for_migration([row])
    assert not result.accepted
    assert result.quarantined[0].fact.scope_kind is GuidanceScopeKind.PRODUCT
    assert GuidanceInvariantCode.NON_COMPANY_SCOPE in {v.code for v in result.quarantined[0].violations}


def test_margin_level_remains_absolute_despite_adjacent_growth_rows():
    row = record(
        ticker="RGEN",
        metric=GuidanceMetric.GROSS_MARGIN,
        low=0.537,
        high=0.542,
        unit="fraction",
        evidence="FY2026 Adjusted guidance Reported Growth 10% - 13% Gross Margin 53.7% - 54.2%",
        ts=T3,
    )
    result = canonicalize_legacy_records_for_migration([row])
    assert not result.quarantined
    fact = result.accepted[0]
    assert fact.low == 0.537
    assert fact.high == 0.542


def test_quoted_prior_role_is_assigned_before_deduplication():
    prior = record(
        ticker="HUM",
        metric=GuidanceMetric.EPS,
        period="FY2026",
        low=8.89,
        high=8.89,
        unit="USD/share",
        evidence="FY2026 GAAP EPS guidance prior $8.89",
        ts=T2,
        basis="GAAP",
    )
    current = record(
        ticker="HUM",
        metric=GuidanceMetric.EPS,
        period="FY2026",
        low=8.36,
        high=8.36,
        unit="USD/share",
        evidence="FY2026 GAAP EPS guidance lowered to $8.36 from $8.89",
        ts=T2,
        action=GuidanceAction.LOWER,
        basis="GAAP",
        supersedes=prior.record_id,
    )
    result = canonicalize_legacy_records_for_migration([prior, current])
    roles = {fact.role.value for fact in result.accepted}
    assert roles == {"CURRENT", "QUOTED_PRIOR"}
    assessment = assess_canonicalization_result(result, "HUM", rules(), rules_hash="migration-test", as_of=T2)
    assert assessment.classification is GuidanceClassification.DETERIORATED


def test_newer_blocking_quarantine_prevents_stale_fallback():
    old_prior = record(
        ticker="FRPT",
        low=1_180_000_000,
        high=1_210_000_000,
        unit="USD",
        evidence="FY2025 guidance Net sales $1.18 billion to $1.21 billion",
        ts=T1,
        period="FY2025",
    )
    old_current = record(
        ticker="FRPT",
        low=1_120_000_000,
        high=1_150_000_000,
        unit="USD",
        evidence="FY2025 guidance Net sales $1.12 billion to $1.15 billion",
        ts=T2,
        period="FY2025",
    )
    bad_latest = record(
        ticker="FRPT",
        metric=GuidanceMetric.GROSS_MARGIN,
        low=0.13,
        high=0.13,
        unit="fraction",
        evidence="phase_1_1e_run94_explicit_period_authority=FY2025; FY 2025 Guidance Adjusted Gross Margin 13%",
        ts=T3,
        period="Q3FY2025",
        basis="ADJUSTED",
    )
    result = canonicalize_legacy_records_for_migration([old_prior, old_current, bad_latest])
    assessment = assess_canonicalization_result(result, "FRPT", rules(), rules_hash="migration-test", as_of=T3)
    assert assessment.classification is GuidanceClassification.UNKNOWN
    assert assessment.rule_path == "guidance_v1_1.canonical_unresolved_latest_evidence"
