from datetime import UTC, datetime

from app.domain.soe_v1_1 import GuidanceAction, GuidanceMetric, GuidanceMetricRecord
from app.services.guidance_ledger_service import GuidanceLedger


RULES_HASH = "1" * 64
NOW = datetime(2026, 6, 11, tzinfo=UTC)


def record(*, period: str, metric: GuidanceMetric, low: float, high: float, basis: str, evidence: str) -> GuidanceMetricRecord:
    return GuidanceMetricRecord(
        rules_hash=RULES_HASH,
        ticker="ADBE",
        fiscal_period=period,
        metric=metric,
        accounting_basis=basis,
        low=low,
        high=high,
        unit="USD/share" if metric is GuidanceMetric.EPS else "USD",
        source="SEC EDGAR",
        source_url="https://www.sec.gov/example",
        source_timestamp=NOW,
        explicit_action=GuidanceAction.NONE,
        verified=True,
        evidence_span=evidence,
        as_of=NOW,
        fetched_at=NOW,
    )


def test_quarter_guidance_header_cannot_participate_under_full_year_key():
    mislabeled = record(
        period="FY2026",
        metric=GuidanceMetric.REVENUE,
        low=6_670_000_000,
        high=6_720_000_000,
        basis="UNSPECIFIED",
        evidence="The following table summarizes Adobe's third quarter FY2026 targets: Total revenue $6.67 billion to $6.72 billion",
    )
    ledger = GuidanceLedger([mislabeled])
    current, prior = ledger.current_and_prior("ADBE")
    assert current == []
    assert prior == []


def test_matching_quarter_guidance_header_remains_eligible():
    quarter = record(
        period="Q3FY2026",
        metric=GuidanceMetric.REVENUE,
        low=6_670_000_000,
        high=6_720_000_000,
        basis="UNSPECIFIED",
        evidence="The following table summarizes Adobe's third quarter FY2026 targets: Total revenue $6.67 billion to $6.72 billion",
    )
    ledger = GuidanceLedger([quarter])
    current, prior = ledger.current_and_prior("ADBE")
    assert len(current) == 1
    assert current[0].fiscal_period == "Q3FY2026"
    assert current[0].explicit_action is GuidanceAction.INITIATE
    assert prior == []


def test_full_year_header_is_not_rejected_by_nearby_quarter_context():
    full_year = record(
        period="FY2026",
        metric=GuidanceMetric.REVENUE,
        low=26_500_000_000,
        high=26_600_000_000,
        basis="UNSPECIFIED",
        evidence="Diluted share count of approximately 395 million for third quarter FY2026. The following table summarizes Adobe's updated FY2026 targets: Total revenue $26.50 billion to $26.60 billion",
    )
    ledger = GuidanceLedger([full_year])
    current, prior = ledger.current_and_prior("ADBE")
    assert len(current) == 1
    assert current[0].fiscal_period == "FY2026"
    assert prior == []


def test_mixed_gaap_non_gaap_eps_table_is_excluded_when_range_binding_is_ambiguous():
    ambiguous = record(
        period="FY2026",
        metric=GuidanceMetric.EPS,
        low=17.90,
        high=18.00,
        basis="ADJUSTED",
        evidence="Earnings per share GAAP: $17.90 to $18.00 Non-GAAP: $24.35 to $24.45 FY2026 targets",
    )
    ledger = GuidanceLedger([ambiguous])
    current, prior = ledger.current_and_prior("ADBE")
    assert current == []
    assert prior == []
