from datetime import UTC, datetime, timedelta

from app.core.config import SOE_1_1_RULES_PATH, load_rules_for_version, rules_hash
from app.domain.soe_v1_1 import (
    ExtractionMethod,
    GuidanceAction,
    GuidanceMetric,
    GuidanceMetricRecord,
)
from app.services.guidance_ledger_service import GuidanceLedger
from app.services.phase_1_1e_guidance_period_guard_round7_v1_1 import (
    dedupe_guidance_records_round7,
    tighten_guidance_record_round7,
)

NOW = datetime(2026, 9, 5, tzinfo=UTC)
RULES = load_rules_for_version(SOE_1_1_RULES_PATH, "SOE-1.1.0")
RULES_HASH = rules_hash(RULES)


def _record(
    value: float,
    *,
    when: datetime,
    evidence: str,
    period: str = "FY2026",
    action: GuidanceAction = GuidanceAction.NONE,
) -> GuidanceMetricRecord:
    return GuidanceMetricRecord(
        rules_hash=RULES_HASH,
        ticker="INSM",
        fiscal_period=period,
        metric=GuidanceMetric.REVENUE,
        accounting_basis="UNSPECIFIED",
        low=value,
        high=value,
        unit="USD",
        source="SEC EDGAR",
        source_url="https://www.sec.gov/Archives/edgar/data/1104506/example-ex99.htm",
        source_accession="0001140361-26-000001",
        source_timestamp=when,
        explicit_action=action,
        verified=True,
        extraction_method=ExtractionMethod.DETERMINISTIC_TEXT,
        evidence_span=evidence,
        source_document_hash="d" * 64,
        as_of=when,
        fetched_at=when,
    )


def test_insm_full_year_2025_product_descriptor_corrects_wrong_period_label():
    row = _record(
        425_000_000,
        when=NOW - timedelta(days=300),
        # Deliberately start from the bad FY2026 label seen in the live audit.
        period="FY2026",
        action=GuidanceAction.RAISE,
        evidence=(
            "Insmed is raising its full-year 2025 global ARIKAYCE revenue guidance "
            "to a range of $420 million to $430 million, from a range of "
            "$405 million to $425 million previously."
        ),
    )
    fixed = tighten_guidance_record_round7(row)
    assert fixed is not None
    assert fixed.fiscal_period == "FY2025"


def test_insm_full_year_2026_arikayce_guidance_binds_to_fy2026():
    row = _record(
        460_000_000,
        when=NOW,
        period="FY2025",  # deliberately wrong input to prove evidence wins
        evidence=(
            "Company Expects Full-Year 2026 BRINSUPRI Revenues to Be at Least $1 Billion; "
            "Reiterates Full-Year 2026 ARIKAYCE Revenue Guidance of $450 Million to $470 Million."
        ),
        action=GuidanceAction.REAFFIRM,
    )
    fixed = tighten_guidance_record_round7(row)
    assert fixed is not None
    assert fixed.fiscal_period == "FY2026"


def test_insm_fy2025_and_fy2026_guidance_cannot_form_comparable_pair():
    old = _record(
        425_000_000,
        when=NOW - timedelta(days=300),
        period="FY2026",  # emulate bad extraction before Round 7
        action=GuidanceAction.RAISE,
        evidence=(
            "Insmed is raising its full-year 2025 global ARIKAYCE revenue guidance "
            "to a range of $420 million to $430 million, from $405 million to "
            "$425 million previously."
        ),
    )
    new = _record(
        460_000_000,
        when=NOW,
        period="FY2026",
        action=GuidanceAction.REAFFIRM,
        evidence=(
            "Reiterates Full-Year 2026 ARIKAYCE Revenue Guidance of "
            "$450 million to $470 million."
        ),
    )

    records = dedupe_guidance_records_round7([old, new])
    ledger = GuidanceLedger(records)
    current, prior = ledger.current_and_prior("INSM", as_of=NOW)

    assert {row.fiscal_period for row in records} == {"FY2025", "FY2026"}
    assert len(current) == 1
    assert current[0].fiscal_period == "FY2026"
    assert prior == []

    assessment = ledger.assess("INSM", RULES, rules_hash=RULES_HASH, as_of=NOW)
    assert assessment.guidance_deterioration is None


def test_same_fiscal_year_guidance_updates_remain_comparable():
    prior = _record(
        460_000_000,
        when=NOW - timedelta(days=90),
        period="FY2026",
        evidence="Full-year 2026 ARIKAYCE revenue guidance is $450 million to $470 million.",
    )
    current = _record(
        470_000_000,
        when=NOW,
        period="FY2026",
        action=GuidanceAction.RAISE,
        evidence="Insmed raises full-year 2026 ARIKAYCE revenue guidance to $460 million to $480 million.",
    )

    ledger = GuidanceLedger(dedupe_guidance_records_round7([prior, current]))
    current_rows, prior_rows = ledger.current_and_prior("INSM", as_of=NOW)
    assert len(current_rows) == 1
    assert len(prior_rows) == 1
    assert current_rows[0].fiscal_period == prior_rows[0].fiscal_period == "FY2026"
