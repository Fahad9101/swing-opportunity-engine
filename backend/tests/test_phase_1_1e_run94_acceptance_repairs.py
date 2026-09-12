from __future__ import annotations

from datetime import UTC, datetime

from app.domain.soe_v1_1 import ExtractionMethod, GuidanceAction, GuidanceMetric, GuidanceMetricRecord
from app.services.phase_1_1e_run94_acceptance_repairs_v1_1 import dedupe_guidance_records_run94


NOW = datetime(2026, 9, 12, tzinfo=UTC)


def record(
    metric: GuidanceMetric,
    low: float,
    high: float,
    *,
    period: str,
    evidence: str,
    basis: str = "UNSPECIFIED",
    unit: str | None = None,
):
    if unit is None:
        unit = "USD/share" if metric is GuidanceMetric.EPS else "USD"
    return GuidanceMetricRecord(
        rules_hash="run94-test",
        ticker="TEST",
        fiscal_period=period,
        metric=metric,
        accounting_basis=basis,
        low=low,
        high=high,
        unit=unit,
        source="SEC EDGAR",
        source_url="https://www.sec.gov/test.htm",
        source_accession="0000000001-26-000001",
        source_timestamp=NOW,
        explicit_action=GuidanceAction.NONE,
        verified=True,
        extraction_method=ExtractionMethod.STRUCTURED,
        evidence_span=evidence,
        source_document_hash="run94-test",
        as_of=NOW,
        fetched_at=NOW,
        stale=False,
    )


def test_full_year_issuer_language_overrides_wrong_quarter_rebind():
    row = record(
        GuidanceMetric.REVENUE,
        3_000_000_000,
        3_200_000_000,
        period="Q4FY2024",
        evidence=(
            "phase_1_1e_run88_period_rebind; from=FY2025; to=Q4FY2024; "
            "2025 Full-Year Guidance Revenue $3.0 to $3.2 billion"
        ),
    )
    cleaned = dedupe_guidance_records_run94([row])
    assert len(cleaned) == 1
    assert cleaned[0].fiscal_period == "FY2025"


def test_quarter_issuer_language_overrides_wrong_annual_period():
    row = record(
        GuidanceMetric.REVENUE,
        3_325_000_000,
        3_575_000_000,
        period="FY2025",
        evidence="Q4 2025 Guidance Revenue $3.325 to $3.575 billion",
    )
    cleaned = dedupe_guidance_records_run94([row])
    assert len(cleaned) == 1
    assert cleaned[0].fiscal_period == "Q4FY2025"


def test_ambiguous_changed_run88_rebind_fails_closed():
    row = record(
        GuidanceMetric.EPS,
        5.0,
        5.2,
        period="Q4FY2024",
        basis="ADJUSTED",
        unit="USD/share",
        evidence=(
            "phase_1_1e_run88_period_rebind; from=FY2025; to=Q4FY2024; "
            "Adjusted EPS is expected to be $5.00 to $5.20"
        ),
    )
    assert dedupe_guidance_records_run94([row]) == []


def test_celestica_eps_range_cannot_become_scaled_revenue():
    bad = record(
        GuidanceMetric.REVENUE,
        1_650_000_000.0,
        1_810_000_000.0,
        period="Q4FY2025",
        evidence=(
            "phase_1_1e_run90_scale_applied=1e+09; "
            "phase_1_1e_run88_inherited_table_scale=1e+09; "
            "Q4 2025 Guidance Revenue (in billions) $3.655 $3.325 to $3.575 "
            "GAAP EPS $2.31 N/A Adjusted operating margin 7.7% 7.6% "
            "Adjusted EPS (non-GAAP) $1.89 $1.65 to $1.81"
        ),
    )
    cleaned = dedupe_guidance_records_run94([bad])
    assert all(
        not (row.low == 1_650_000_000.0 and row.high == 1_810_000_000.0)
        for row in cleaned
    )
    if cleaned:
        assert len(cleaned) == 1
        assert cleaned[0].low == 3_325_000_000.0
        assert cleaned[0].high == 3_575_000_000.0


def test_celestica_true_scaled_revenue_range_survives():
    good = record(
        GuidanceMetric.REVENUE,
        3_325_000_000.0,
        3_575_000_000.0,
        period="Q4FY2025",
        evidence=(
            "phase_1_1e_run90_scale_applied=1e+09; "
            "phase_1_1e_run88_inherited_table_scale=1e+09; "
            "Q4 2025 Guidance Revenue (in billions) $3.655 $3.325 to $3.575 "
            "Adjusted EPS (non-GAAP) $1.89 $1.65 to $1.81"
        ),
    )
    cleaned = dedupe_guidance_records_run94([good])
    assert len(cleaned) == 1
    assert cleaned[0].low == 3_325_000_000.0
    assert cleaned[0].high == 3_575_000_000.0


def test_clean_non_table_guidance_is_unchanged():
    clean = record(
        GuidanceMetric.REVENUE,
        600_000_000.0,
        640_000_000.0,
        period="FY2026",
        evidence="FY2026 revenue guidance is $600 million to $640 million.",
    )
    rows = dedupe_guidance_records_run94([clean])
    assert len(rows) == 1
    assert rows[0].fiscal_period == "FY2026"
    assert rows[0].low == 600_000_000.0
