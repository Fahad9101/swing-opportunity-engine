from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.domain.soe_v1_1 import (
    ExtractionMethod,
    GuidanceAction,
    GuidanceMetric,
    GuidanceMetricRecord,
)
from app.services.phase_1_1e_run90_population_preflight_v1_1 import (
    GuidanceLedgerRun90,
    dedupe_guidance_records_run90,
)


NOW = datetime(2026, 9, 11, tzinfo=UTC)


def record(
    metric: GuidanceMetric,
    low: float,
    high: float,
    *,
    period: str = "FY2026",
    basis: str = "UNSPECIFIED",
    timestamp: datetime = NOW,
    evidence: str = "Full-year 2026 guidance expects this range.",
    action: GuidanceAction = GuidanceAction.NONE,
    unit: str | None = None,
):
    if unit is None:
        unit = "fraction" if metric in {GuidanceMetric.GROSS_MARGIN, GuidanceMetric.OPERATING_MARGIN} else (
            "USD/share" if metric is GuidanceMetric.EPS else "USD"
        )
    return GuidanceMetricRecord(
        rules_hash="run90-test",
        ticker="TEST",
        fiscal_period=period,
        metric=metric,
        accounting_basis=basis,
        low=low,
        high=high,
        unit=unit,
        source="SEC EDGAR",
        source_url=f"https://www.sec.gov/{timestamp.timestamp()}.htm",
        source_accession="0000000001-26-000001",
        source_timestamp=timestamp,
        explicit_action=action,
        verified=True,
        extraction_method=ExtractionMethod.STRUCTURED,
        evidence_span=evidence,
        source_document_hash="run90-test",
        as_of=timestamp,
        fetched_at=timestamp,
        stale=False,
    )


def test_inherited_scale_marker_is_executed_exactly_once():
    raw = record(
        GuidanceMetric.REVENUE,
        221.0,
        226.0,
        evidence=(
            "phase_1_1e_run88_inherited_table_scale=1e+06; "
            "Full-year 2026 guidance. Net sales (in millions) $221 - $226."
        ),
    )
    first = dedupe_guidance_records_run90([raw])
    assert len(first) == 1
    assert first[0].low == 221_000_000.0
    assert first[0].high == 226_000_000.0

    second = dedupe_guidance_records_run90(first)
    assert second[0].low == 221_000_000.0
    assert second[0].high == 226_000_000.0


def test_run89_ebitda_cannot_steal_revenue_range():
    bad = record(
        GuidanceMetric.EBITDA,
        130_000_000.0,
        150_000_000.0,
        basis="ADJUSTED",
        evidence=(
            "phase_1_1e_run89_authoritative_forward_scope; Full Year 2026 Outlook; "
            "Adjusted EBITDA. Revenue is now expected to be between $130 million and $150 million."
        ),
    )
    assert dedupe_guidance_records_run90([bad]) == []


def test_run89_revenue_cannot_steal_corporate_expense_range():
    bad = record(
        GuidanceMetric.REVENUE,
        205_000_000.0,
        215_000_000.0,
        evidence=(
            "phase_1_1e_run89_authoritative_forward_scope; FY2026 guidance; "
            "Revenue Growth 5.9% to 7.9%. Corporate Unallocated Expense $205 million to $215 million."
        ),
    )
    assert dedupe_guidance_records_run90([bad]) == []


def test_conflicting_same_scope_ranges_fail_closed():
    a = record(GuidanceMetric.REVENUE, 500_000_000, 510_000_000)
    b = record(GuidanceMetric.REVENUE, 120_000_000, 130_000_000)
    assert dedupe_guidance_records_run90([a, b]) == []


def test_same_range_assigned_to_two_metrics_fails_closed():
    revenue = record(GuidanceMetric.REVENUE, 130_000_000, 150_000_000)
    ebitda = record(
        GuidanceMetric.EBITDA,
        130_000_000,
        150_000_000,
        basis="ADJUSTED",
    )
    assert dedupe_guidance_records_run90([revenue, ebitda]) == []


def test_impossible_annual_value_not_allowed_to_equal_quarter_value():
    quarter = record(
        GuidanceMetric.REVENUE,
        370_000_000,
        390_000_000,
        period="Q3FY2026",
    )
    annual = record(
        GuidanceMetric.REVENUE,
        370_000_000,
        390_000_000,
        period="FY2026",
    )
    cleaned = dedupe_guidance_records_run90([quarter, annual])
    assert [(r.fiscal_period, r.low, r.high) for r in cleaned] == [
        ("Q3FY2026", 370_000_000, 390_000_000)
    ]


def test_identical_gaap_and_adjusted_eps_without_linkage_fail_closed():
    gaap = record(GuidanceMetric.EPS, 0.76, 0.85, basis="GAAP")
    adjusted = record(GuidanceMetric.EPS, 0.76, 0.85, basis="ADJUSTED")
    assert dedupe_guidance_records_run90([gaap, adjusted]) == []


def test_explicit_lower_action_survives_basis_collision_guard():
    gaap = record(
        GuidanceMetric.EPS,
        6.52,
        6.52,
        basis="GAAP",
        action=GuidanceAction.LOWER,
        evidence="FY2026 guidance lowered GAAP EPS to at least $6.52.",
    )
    adjusted = record(
        GuidanceMetric.EPS,
        9.00,
        9.00,
        basis="ADJUSTED",
        action=GuidanceAction.REAFFIRM,
        evidence="FY2026 guidance reaffirmed adjusted EPS at least $9.00.",
    )
    cleaned = dedupe_guidance_records_run90([gaap, adjusted])
    assert len(cleaned) == 2
    assert {r.explicit_action for r in cleaned} == {
        GuidanceAction.LOWER,
        GuidanceAction.REAFFIRM,
    }


def test_unscaled_run89_money_without_explicit_scale_fails_closed():
    raw = record(
        GuidanceMetric.REVENUE,
        480.0,
        490.0,
        evidence=(
            "phase_1_1e_run89_authoritative_forward_scope; "
            "Full-year 2026 guidance; Revenue $480 - $490."
        ),
    )
    assert dedupe_guidance_records_run90([raw]) == []


def test_scope_change_sensitive_pair_returns_no_comparison():
    prior = record(
        GuidanceMetric.REVENUE,
        3_400_000_000,
        3_400_000_000,
        timestamp=NOW - timedelta(days=90),
        evidence=(
            "phase_1_1e_run90_scope_change_sensitive; "
            "Full-year 2026 guidance includes expected contribution from discontinued operations."
        ),
    )
    current = record(
        GuidanceMetric.REVENUE,
        2_660_000_000,
        2_710_000_000,
        timestamp=NOW,
        evidence="Full-year 2026 guidance after the separation.",
    )
    ledger = GuidanceLedgerRun90([prior, current])
    current_rows, prior_rows = ledger.current_and_prior("TEST", as_of=NOW)
    assert current_rows == []
    assert prior_rows == []


def test_clean_simple_guidance_survives():
    revenue = record(GuidanceMetric.REVENUE, 600_000_000, 640_000_000)
    ebitda = record(
        GuidanceMetric.EBITDA,
        118_000_000,
        132_000_000,
        basis="ADJUSTED",
    )
    cleaned = dedupe_guidance_records_run90([revenue, ebitda])
    assert {(r.metric, r.low, r.high) for r in cleaned} == {
        (GuidanceMetric.REVENUE, 600_000_000, 640_000_000),
        (GuidanceMetric.EBITDA, 118_000_000, 132_000_000),
    }
