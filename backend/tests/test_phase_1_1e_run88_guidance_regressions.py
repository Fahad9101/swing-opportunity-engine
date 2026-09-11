from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.domain.soe_v1_1 import ExtractionMethod, GuidanceMetric, GuidanceMetricRecord
from app.services.phase_1_1e_run88_guidance_repairs_v1_1 import (
    _apply_inherited_scale,
    _excluded_eps_adjustment,
    _historical_actual,
    _margin_value_is_local,
    _rebind_explicit_period,
    _rebind_run85_margin_period,
)


NOW = datetime(2026, 9, 11, tzinfo=UTC)


def record(
    *,
    metric: GuidanceMetric,
    period: str,
    low: float,
    high: float,
    unit: str,
    evidence: str,
    basis: str = "UNSPECIFIED",
) -> GuidanceMetricRecord:
    return GuidanceMetricRecord(
        rules_hash="run88-test",
        ticker="TEST",
        fiscal_period=period,
        metric=metric,
        accounting_basis=basis,
        low=low,
        high=high,
        unit=unit,
        source="SEC EDGAR",
        source_url="https://www.sec.gov/example.htm",
        source_timestamp=NOW,
        as_of=NOW,
        fetched_at=NOW,
        verified=True,
        extraction_method=ExtractionMethod.STRUCTURED,
        evidence_span=evidence,
    )


def test_combined_quarter_and_full_year_header_rebinds_each_value_to_local_scope():
    text = (
        "Raising Third-Quarter and Full-Year 2026 Guidance. "
        "For the third quarter, Chime now expects adjusted EBITDA of $117 to $120 million. "
        "For the full year, Chime now expects adjusted EBITDA of $481 to $489 million."
    )
    q3 = record(
        metric=GuidanceMetric.EBITDA,
        period="FY2026",
        low=117_000_000,
        high=120_000_000,
        unit="USD",
        basis="ADJUSTED",
        evidence=(
            "normalized_explicit_guidance_scope;FY2026 guidance; "
            "adjusted EBITDA of $117 to $120 million"
        ),
    )
    fy = record(
        metric=GuidanceMetric.EBITDA,
        period="FY2026",
        low=481_000_000,
        high=489_000_000,
        unit="USD",
        basis="ADJUSTED",
        evidence=(
            "normalized_explicit_guidance_scope;FY2026 guidance; "
            "adjusted EBITDA of $481 to $489 million"
        ),
    )
    assert _rebind_explicit_period(text, q3).fiscal_period == "Q3FY2026"
    assert _rebind_explicit_period(text, fy).fiscal_period == "FY2026"


def test_second_quarter_value_does_not_bleed_into_full_year_scope():
    text = (
        "Second Quarter and Full Year 2026 Outlook. "
        "For the full year, adjusted diluted earnings per share are expected to be "
        "in the range of $7.90 to $8.30. "
        "For the second quarter, adjusted diluted earnings per share are expected to be "
        "in the range of $2.10 to $2.20."
    )
    row = record(
        metric=GuidanceMetric.EPS,
        period="FY2026",
        low=2.10,
        high=2.20,
        unit="USD/share",
        basis="ADJUSTED",
        evidence=(
            "normalized_explicit_guidance_scope;FY2026 guidance; "
            "adjusted diluted earnings per share are expected to be in the range of $2.10 to $2.20"
        ),
    )
    assert _rebind_explicit_period(text, row).fiscal_period == "Q2FY2026"


def test_long_term_margin_uses_its_own_full_year_period():
    row = record(
        metric=GuidanceMetric.GROSS_MARGIN,
        period="FY2025",
        low=0.48,
        high=0.48,
        unit="fraction",
        basis="ADJUSTED",
        evidence=(
            "normalized_explicit_guidance_scope; phase_1_1e_run85; "
            "The Company is also updating its long-term guidance. For full year 2027, "
            "the Company now expects Adjusted Gross Margin of 48%"
        ),
    )
    assert _rebind_run85_margin_period(row).fiscal_period == "FY2027"


@pytest.mark.parametrize(
    "evidence",
    [
        (
            "normalized_explicit_guidance_scope; phase_1_1e_run85; "
            "Full Year 2024 Financial Highlights Compared to Prior Year. "
            "Adjusted Gross Margin of 46.5%"
        ),
        (
            "normalized_explicit_guidance_scope; phase_1_1e_run85; "
            "FOURTH QUARTER 2025 HIGHLIGHTS GAAP Operating Margin 11.5%"
        ),
        (
            "normalized_explicit_guidance_scope; phase_1_1e_run85; "
            "FISCAL YEAR 2025 HIGHLIGHTS GAAP Operating Margin 11.3%"
        ),
    ],
)
def test_historical_highlight_margins_are_not_guidance(evidence):
    row = record(
        metric=GuidanceMetric.GROSS_MARGIN if "Gross" in evidence else GuidanceMetric.OPERATING_MARGIN,
        period="FY2025",
        low=0.465 if "46.5" in evidence else 0.115,
        high=0.465 if "46.5" in evidence else 0.115,
        unit="fraction",
        evidence=evidence,
    )
    assert _historical_actual(row) is True


def test_flattened_margin_table_requires_percentage_local_to_margin_label():
    row = record(
        metric=GuidanceMetric.GROSS_MARGIN,
        period="FY2025",
        low=0.13,
        high=0.13,
        unit="fraction",
        basis="ADJUSTED",
        evidence=(
            "normalized_explicit_guidance_scope; phase_1_1e_run85; "
            "Q3 2025 Earnings Presentation FY 2025 Guidance. "
            "Adjusted Gross Margin: Now expect to be flat for the year. "
            "Advertising Investment: greater than 2024. Cash: ~$265M. "
            "Updated Previous ~13% 13-16% Net Sales Growth YoY."
        ),
    )
    assert _margin_value_is_local(row) is False


def test_true_forward_margin_value_remains_local():
    row = record(
        metric=GuidanceMetric.GROSS_MARGIN,
        period="FY2026",
        low=0.597,
        high=0.597,
        unit="fraction",
        evidence=(
            "normalized_explicit_guidance_scope; phase_1_1e_run85; "
            "Fiscal Year 2026 Guidance based on gross margin of 59.7%, operating margin of 27.0%."
        ),
    )
    assert _margin_value_is_local(row) is True


def test_table_level_millions_scale_is_inherited():
    row = record(
        metric=GuidanceMetric.REVENUE,
        period="FY2026",
        low=2990.0,
        high=3040.0,
        unit="USD",
        evidence=(
            "Updated Fiscal Year 2026 Guidance Key Metric FY 2026 "
            "Net Sales (in Millions) $2,990 - $3,040"
        ),
    )
    fixed = _apply_inherited_scale(row)
    assert fixed.low == 2_990_000_000
    assert fixed.high == 3_040_000_000
    assert fixed.midpoint == 3_015_000_000


def test_reported_quarter_revenue_scalar_is_historical_actual():
    row = record(
        metric=GuidanceMetric.REVENUE,
        period="Q4FY2025",
        low=242_000_000,
        high=242_000_000,
        unit="USD",
        evidence=(
            "DigitalOcean Announces Fourth Quarter and Fiscal Year 2025 Financial Results. "
            "Q4 2025 revenue of $242 million. Company raises 2026 and 2027 revenue outlook."
        ),
    )
    assert _historical_actual(row) is True


def test_eps_exclusion_amount_is_not_guided_eps():
    row = record(
        metric=GuidanceMetric.EPS,
        period="FY2026",
        low=1.63,
        high=1.63,
        unit="USD/share",
        basis="ADJUSTED",
        evidence=(
            "HPE expects fiscal year 2026 non-GAAP diluted net EPS to be in the range of "
            "$2.20 to $2.40. The non-GAAP diluted net EPS excludes after-tax costs of "
            "approximately $1.63 per diluted share."
        ),
    )
    assert _excluded_eps_adjustment(row) is True
