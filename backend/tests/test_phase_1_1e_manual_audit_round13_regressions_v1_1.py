from datetime import UTC, datetime, timedelta

import pytest

from app.core.config import SOE_1_1_RULES_PATH, load_rules_for_version, rules_hash
from app.domain.soe_v1_1 import GuidanceMetric, SourceDocument
from app.services.guidance_ledger_service import GuidanceLedger
from app.services.phase_1_1e_guidance_table_normalizer_v1_1 import (
    extract_guidance_facts_table_normalized,
    normalize_comparative_guidance_tables,
    normalize_value_before_guidance_rows,
)


NOW = datetime(2026, 9, 7, tzinfo=UTC)
RULES = load_rules_for_version(SOE_1_1_RULES_PATH, "SOE-1.1.0")
RULES_HASH = rules_hash(RULES)


@pytest.mark.parametrize("content", [
    "Full Year 2026 Guidance Updated Guidance Prior Guidance Low High Low High "
    "Net revenues $100 $110 $90 $100",
    "Full Year 2026 Guidance Updated Guidance Prior Guidance "
    "Net revenues $100 million $110 million $90 million $100 million",
])
def test_scalar_table_needs_explicit_columns_and_economic_scale(content):
    doc = SourceDocument(
        document_id="ambiguous", rules_hash=RULES_HASH, ticker="TEST", cik="1",
        accession="1", form="8-K", source_url="https://www.sec.gov/Archives/test.htm",
        source_timestamp=NOW, fetched_at=NOW, content_hash="0" * 64, content=content,
    )
    assert normalize_comparative_guidance_tables(doc, rules_hash=RULES_HASH) == []


def test_value_first_revenue_requires_explicit_economic_scale():
    doc = SourceDocument(
        document_id="unscaled", rules_hash=RULES_HASH, ticker="TEST", cik="1",
        accession="1", form="8-K", source_url="https://www.sec.gov/Archives/test.htm",
        source_timestamp=NOW, fetched_at=NOW, content_hash="0" * 64,
        content="$100-$110 2026 NET REVENUE GUIDANCE",
    )
    assert normalize_value_before_guidance_rows(doc, rules_hash=RULES_HASH) == []


def _extract(ticker: str, content: str, *, when: datetime, suffix: str):
    document = SourceDocument(
        document_id=f"{ticker}-{suffix}",
        rules_hash=RULES_HASH,
        ticker=ticker,
        cik="0000000001",
        accession=f"0000000001-26-00{suffix}",
        form="8-K",
        source_url=f"https://www.sec.gov/Archives/edgar/data/1/{ticker.lower()}-{suffix}.htm",
        source_timestamp=when,
        fetched_at=when,
        content_hash=(ticker.lower() + suffix + "0" * 64)[:64],
        content=content,
    )
    return extract_guidance_facts_table_normalized(document, rules_hash=RULES_HASH)


def test_dgx_updated_first_comparative_table_preserves_column_direction_and_basis():
    extraction = _extract(
        "DGX",
        "Updated Guidance for Full Year 2026. The company updates its full year 2026 "
        "guidance as follows: Updated Guidance Prior Guidance Low High Low High "
        "Net revenues $11.78 billion $11.90 billion $11.70 billion $11.82 billion "
        "Reported diluted EPS $9.58 $9.78 $9.45 $9.65 "
        "Adjusted diluted EPS $10.63 $10.83 $10.50 $10.70.",
        when=NOW,
        suffix="001",
    )

    revenue = next(record for record in extraction.records if record.metric is GuidanceMetric.REVENUE)
    assert revenue.low == pytest.approx(11_780_000_000)
    assert revenue.high == pytest.approx(11_900_000_000)

    eps = [record for record in extraction.records if record.metric is GuidanceMetric.EPS]
    gaap = next(record for record in eps if record.accounting_basis == "UNSPECIFIED")
    adjusted = next(record for record in eps if record.accounting_basis == "ADJUSTED")
    assert (gaap.low, gaap.high) == pytest.approx((9.58, 9.78))
    assert (adjusted.low, adjusted.high) == pytest.approx((10.63, 10.83))


def test_dgx_successive_updated_first_tables_are_not_deteriorated():
    prior = _extract(
        "DGX",
        "Updated Guidance for Full Year 2026. Updated Guidance Prior Guidance Low High Low High "
        "Net revenues $11.78 billion $11.90 billion $11.70 billion $11.82 billion "
        "Reported diluted EPS $9.58 $9.78 $9.45 $9.65 "
        "Adjusted diluted EPS $10.63 $10.83 $10.50 $10.70.",
        when=NOW - timedelta(days=90),
        suffix="001",
    )
    current = _extract(
        "DGX",
        "Updated Guidance for Full Year 2026. Updated Guidance Prior Guidance Low High Low High "
        "Net revenues $11.95 billion $12.05 billion $11.78 billion $11.90 billion "
        "Reported diluted EPS $9.97 $10.17 $9.58 $9.78 "
        "Adjusted diluted EPS $11.05 $11.25 $10.63 $10.83.",
        when=NOW,
        suffix="002",
    )

    assessment = GuidanceLedger([*prior.records, *current.records]).assess(
        "DGX", RULES, rules_hash=RULES_HASH, as_of=NOW
    )
    assert assessment.classification.value == "NOT_DETERIORATED"
    assert assessment.rule_path == "guidance_v1_1.comparable_set_within_tolerance"
    assert set(assessment.comparable_metrics) == {GuidanceMetric.REVENUE, GuidanceMetric.EPS}


def test_hrmy_action_year_beats_preceding_quarter_actual_and_value_first_row_compares():
    prior = _extract(
        "HRMY",
        "WAKIX net revenue grew 30% year over year to approximately $261 million for Q2 2026. "
        "Harmony reaffirms 2026 net revenue guidance of $1.0 billion to $1.04 billion.",
        when=NOW - timedelta(days=19),
        suffix="001",
    )
    current = _extract(
        "HRMY",
        "Reiterating 2026 Net Revenue Guidance. $1.00B-$1.04B 2026 NET REVENUE GUIDANCE.",
        when=NOW,
        suffix="002",
    )

    prior_revenue = next(record for record in prior.records if record.metric is GuidanceMetric.REVENUE)
    current_revenue = next(record for record in current.records if record.metric is GuidanceMetric.REVENUE)
    assert prior_revenue.fiscal_period == "FY2026"
    assert current_revenue.fiscal_period == "FY2026"
    assert current_revenue.low == pytest.approx(1_000_000_000)
    assert current_revenue.high == pytest.approx(1_040_000_000)

    assessment = GuidanceLedger([*prior.records, *current.records]).assess(
        "HRMY", RULES, rules_hash=RULES_HASH, as_of=NOW
    )
    assert assessment.classification.value == "NOT_DETERIORATED"
    assert assessment.rule_path == "guidance_v1_1.comparable_set_within_tolerance"
