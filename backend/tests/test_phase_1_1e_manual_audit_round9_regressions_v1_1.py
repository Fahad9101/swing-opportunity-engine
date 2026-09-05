from datetime import UTC, datetime, timedelta

from app.cli_shadow_validation_guarded import install_guards
from app.core.config import SOE_1_1_RULES_PATH, load_rules_for_version, rules_hash
from app.domain.soe_v1_1 import (
    ExtractionMethod,
    GuidanceAction,
    GuidanceMetric,
    GuidanceMetricRecord,
    SourceDocument,
)
from app.services.guidance_ledger_service import GuidanceLedger
from app.services.phase_1_1e_guidance_table_normalizer_v1_1 import (
    _record_has_metric_local_range,
    _scopes,
    extract_guidance_facts_table_normalized,
)


NOW = datetime(2026, 9, 5, tzinfo=UTC)
RULES = load_rules_for_version(SOE_1_1_RULES_PATH, "SOE-1.1.0")
RULES_HASH = rules_hash(RULES)


def _document(ticker: str, content: str, *, when: datetime, suffix: str) -> SourceDocument:
    return SourceDocument(
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


def _extract(ticker: str, content: str, *, when: datetime, suffix: str):
    install_guards()
    return extract_guidance_facts_table_normalized(
        _document(ticker, content, when=when, suffix=suffix),
        rules_hash=RULES_HASH,
    )


def test_rblx_bookings_range_cannot_be_bound_to_revenue():
    prior = _extract(
        "RBLX",
        "For FY 2025, our revenue guidance is $4,290 million - $4,365 million, "
        "or year-over-year growth of 19-21%.",
        when=NOW - timedelta(days=490),
        suffix="001",
    )
    current = _extract(
        "RBLX",
        """Forward Looking Guidance
Roblox provides its third quarter and updated full year 2025 GAAP and non-GAAP guidance:
Third Quarter 2025 Guidance
Revenue between $1,110 million and $1,160 million. Our revenue guidance assumes that there are no material changes in estimates used in our revenue recognition.
Bookings between $1,590 million and $1,640 million.
Updated Full Year 2025 Guidance
Revenue between $4,390 million and $4,490 million. Our revenue guidance assumes that there are no material changes in estimates used in our revenue recognition.
Bookings between $5,870 million and $5,970 million.""",
        when=NOW - timedelta(days=399),
        suffix="002",
    )

    forbidden = {1_615_000_000, 5_920_000_000}
    assert not any(
        row.metric is GuidanceMetric.REVENUE and row.midpoint in forbidden
        for row in current.records
    )
    assert any(item["reason"] == "cross_metric_row_range_binding" for item in current.rejected_candidates)

    records = [*prior.records, *current.records]
    assessment = GuidanceLedger(records).assess("RBLX", RULES, rules_hash=RULES_HASH, as_of=NOW)
    assert assessment.guidance_deterioration is not True
    assert not assessment.rule_path.endswith("material_numeric_cut")


def test_ge_operating_profit_ranges_cannot_be_bound_to_revenue():
    invalid_initial = GuidanceMetricRecord(
        rules_hash=RULES_HASH,
        ticker="GE",
        fiscal_period="FY2025",
        metric=GuidanceMetric.REVENUE,
        accounting_basis="UNSPECIFIED",
        low=7_800_000_000,
        high=8_200_000_000,
        unit="USD",
        source="SEC EDGAR",
        source_url="https://www.sec.gov/Archives/ge-initial.htm",
        source_timestamp=NOW - timedelta(days=590),
        explicit_action=GuidanceAction.INITIATE,
        extraction_method=ExtractionMethod.DETERMINISTIC_TEXT,
        evidence_span=(
            "GE Aerospace Full Year 2025 Guidance For 2025 GE Aerospace is initiating guidance. "
            "Adjusted Revenue Growth Adjusted Revenue +10% $35.1B LDD Operating Profit "
            "$7.3B $7.8 - $8.2B Adjusted EPS $4.60 - $5.45."
        ),
        as_of=NOW - timedelta(days=590),
        fetched_at=NOW,
    )
    invalid_maintained = invalid_initial.model_copy(
        update={
            "low": 1_100_000_000,
            "high": 1_300_000_000,
            "midpoint": 1_200_000_000,
            "source_timestamp": NOW - timedelta(days=501),
            "as_of": NOW - timedelta(days=501),
            "explicit_action": GuidanceAction.REAFFIRM,
            "evidence_span": (
                "Maintaining 2025 guidance. Defense revenue growth remains mid- to high-single "
                "digits and operating profit remains $1.1-$1.3 billion."
            ),
        }
    )

    assert _record_has_metric_local_range(invalid_initial) is False
    assert _record_has_metric_local_range(invalid_maintained) is False


def test_three_column_multi_scope_table_fails_closed_instead_of_creating_lower_action():
    result = _extract(
        "EXPE",
        """Business Outlook
Fiscal Year 2026 Q2 2026
Metric Previous Guidance Current Guidance
Gross bookings $127 - $129B +6 - 8% $127 - $129B +6 - 8% $32.5 - $33.1B +7 - 9%
Revenue $15.6 - $16.0B +6 - 9% $15.6 - $16.0B +6 - 9% $4.11 - $4.19B +9 - 11%
Adjusted EBITDA margin expansion +1 - 1.25pts +1 - 1.25pts 0.5 - 1pt""",
        when=NOW - timedelta(days=121),
        suffix="001",
    )

    assert not any(row.explicit_action is GuidanceAction.LOWER for row in result.records)
    assert not any(row.metric is GuidanceMetric.EBITDA and row.midpoint for row in result.records)


def test_quarter_scope_with_embedded_fiscal_year_is_not_falsely_ambiguous():
    assert _scopes("Q2 fiscal year 2026 Previous Guidance Current Guidance") == {"Q2FY2026"}


def test_metric_local_range_remains_admissible():
    result = _extract(
        "SAFE",
        "Full Year 2026 Guidance. Revenue is expected to be $900 million to $930 million.",
        when=NOW,
        suffix="001",
    )
    revenue = [row for row in result.records if row.metric is GuidanceMetric.REVENUE]
    assert len(revenue) == 1
    assert revenue[0].low == 900_000_000
    assert revenue[0].high == 930_000_000
