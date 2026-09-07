from datetime import UTC, datetime, timedelta

from app.cli_shadow_validation_guarded import install_guards
from app.core.config import SOE_1_1_RULES_PATH, load_rules_for_version, rules_hash
from app.domain.soe_v1_1 import GuidanceMetric, SourceDocument
from app.services.guidance_ledger_service import GuidanceLedger
from app.services.phase_1_1e_guidance_table_normalizer_v1_1 import (
    extract_guidance_facts_table_normalized,
)


NOW = datetime(2026, 9, 7, tzinfo=UTC)
RULES = load_rules_for_version(SOE_1_1_RULES_PATH, "SOE-1.1.0")
RULES_HASH = rules_hash(RULES)


def _extract(ticker: str, content: str, *, when: datetime, suffix: str):
    install_guards()
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


def test_insm_fy2026_guidance_cannot_borrow_following_fy2025_actual_period():
    prior = _extract(
        "INSM",
        "Insmed is raising its full-year 2025 ARIKAYCE revenue guidance to a range of "
        "$420 million to $430 million.",
        when=NOW - timedelta(days=330),
        suffix="001",
    )
    current = _extract(
        "INSM",
        "Company Expects Full-Year 2026 BRINSUPRI Revenues to Be at Least $1 Billion; "
        "Reiterates Full-Year 2026 ARIKAYCE Revenue Guidance of $450 Million to "
        "$470 Million — Total Company Revenues of $606.4 Million for Full-Year 2025.",
        when=NOW - timedelta(days=190),
        suffix="002",
    )

    assert any(
        record.metric is GuidanceMetric.REVENUE
        and record.low == 450_000_000
        and record.fiscal_period == "FY2026"
        for record in current.records
    )
    assert not any(
        record.metric is GuidanceMetric.REVENUE
        and record.low == 450_000_000
        and record.fiscal_period == "FY2025"
        for record in current.records
    )
    assessment = GuidanceLedger([*prior.records, *current.records]).assess(
        "INSM", RULES, rules_hash=RULES_HASH, as_of=NOW
    )
    assert assessment.guidance_deterioration is None
    assert assessment.rule_path == "guidance_v1_1.no_comparable_prior"


def test_insm_truncated_row_cannot_use_following_actual_period():
    extraction = _extract(
        "INSM",
        "ARIKAYCE Revenue Guidance of $450 Million to $470 Million — Total Company "
        "Revenues of $606.4 Million for Full-Year 2025.",
        when=NOW,
        suffix="003",
    )

    assert not any(
        record.metric is GuidanceMetric.REVENUE
        and record.low == 450_000_000
        and record.fiscal_period == "FY2025"
        for record in extraction.records
    )


def test_bfly_revenue_range_cannot_be_bound_to_following_adjusted_ebitda_row():
    extraction = _extract(
        "BFLY",
        "Reaffirmed revenue guidance and adjusted EBITDA guidance for Fiscal Year 2026: "
        "Revenue of $117 million to $121 million, or 20% to 24% growth. "
        "Adjusted EBITDA loss of $21 million to $25 million.",
        when=NOW,
        suffix="001",
    )

    assert not any(
        record.metric is GuidanceMetric.EBITDA
        and record.low == 117_000_000
        and record.high == 121_000_000
        for record in extraction.records
    )


def test_tex_reconciliation_scalar_cannot_be_bound_to_distant_fcf_label():
    extraction = _extract(
        "TEX",
        "Full-Year 2025 Outlook. Free Cash Flow $300 million to $350 million. "
        "GAAP to Non-GAAP Reconciliation: Net Sales $1,487; Gross Profit $291; "
        "Tax adjustment $14.",
        when=NOW,
        suffix="001",
    )

    assert not any(
        record.metric is GuidanceMetric.FCF and record.low == 14 and record.high == 14
        for record in extraction.records
    )
