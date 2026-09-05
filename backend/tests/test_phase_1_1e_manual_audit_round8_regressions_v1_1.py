from datetime import UTC, datetime, timedelta

from app.core.config import SOE_1_1_RULES_PATH, load_rules_for_version, rules_hash
from app.domain.soe_v1_1 import (
    ExtractionMethod,
    GuidanceAction,
    GuidanceMetric,
    GuidanceMetricRecord,
)
from app.services.guidance_ledger_service import GuidanceLedger
from app.services.phase_1_1e_guidance_scope_guard_round8_v1_1 import (
    dedupe_guidance_records_round8,
    tighten_guidance_record_round8,
)

NOW = datetime(2026, 9, 5, tzinfo=UTC)
RULES = load_rules_for_version(SOE_1_1_RULES_PATH, "SOE-1.1.0")
RULES_HASH = rules_hash(RULES)


def _record(
    ticker: str,
    value: float,
    *,
    when: datetime,
    evidence: str,
    period: str = "FY2027",
    action: GuidanceAction = GuidanceAction.NONE,
) -> GuidanceMetricRecord:
    return GuidanceMetricRecord(
        rules_hash=RULES_HASH,
        ticker=ticker,
        fiscal_period=period,
        metric=GuidanceMetric.REVENUE,
        accounting_basis="UNSPECIFIED",
        low=value,
        high=value,
        unit="USD",
        source="SEC EDGAR",
        source_url=f"https://www.sec.gov/Archives/edgar/data/1/{ticker.lower()}-ex99.htm",
        source_accession="0000000001-26-000001",
        source_timestamp=when,
        explicit_action=action,
        verified=True,
        extraction_method=ExtractionMethod.DETERMINISTIC_TEXT,
        evidence_span=evidence,
        source_document_hash="e" * 64,
        as_of=when,
        fetched_at=when,
    )


def test_iot_q2_fy2027_outlook_preserves_quarter_scope():
    row = _record(
        "IOT",
        483_000_000,
        when=NOW - timedelta(days=90),
        period="FY2027",  # emulate Round-7 collapse
        evidence="Q2 FY2027 Outlook Total revenue $482 million - $484 million.",
    )
    fixed = tighten_guidance_record_round8(row)
    assert fixed is not None
    assert fixed.fiscal_period == "Q2FY2027"


def test_iot_q3_fy2027_outlook_preserves_quarter_scope():
    row = _record(
        "IOT",
        515_000_000,
        when=NOW,
        period="FY2027",  # emulate Round-7 collapse
        evidence="Q3 FY2027 Outlook Total revenue $514 million - $516 million.",
    )
    fixed = tighten_guidance_record_round8(row)
    assert fixed is not None
    assert fixed.fiscal_period == "Q3FY2027"


def test_iot_full_year_fy2027_outlook_remains_annual():
    row = _record(
        "IOT",
        2_045_000_000,
        when=NOW,
        period="FY2027",
        evidence="FY2027 Outlook Total revenue $2.043 billion - $2.047 billion.",
    )
    fixed = tighten_guidance_record_round8(row)
    assert fixed is not None
    assert fixed.fiscal_period == "FY2027"


def test_iot_quarterly_and_full_year_ranges_do_not_collapse_or_create_false_cut():
    q1_release = NOW - timedelta(days=90)
    q2_release = NOW
    records = [
        _record(
            "IOT",
            483_000_000,
            when=q1_release,
            period="FY2027",  # deliberately wrong/collapsed input
            evidence="Q2 FY2027 Outlook Total revenue $482 million - $484 million.",
        ),
        _record(
            "IOT",
            2_009_000_000,
            when=q1_release,
            period="FY2027",
            evidence="FY 2027 Outlook Total revenue $2.005 billion - $2.013 billion.",
        ),
        _record(
            "IOT",
            515_000_000,
            when=q2_release,
            period="FY2027",  # deliberately wrong/collapsed input
            evidence="Q3 FY2027 Outlook Total revenue $514 million - $516 million.",
        ),
        _record(
            "IOT",
            2_045_000_000,
            when=q2_release,
            period="FY2027",
            action=GuidanceAction.RAISE,
            evidence="FY2027 Outlook Total revenue $2.043 billion - $2.047 billion.",
        ),
    ]

    corrected = dedupe_guidance_records_round8(records)
    assert {(row.fiscal_period, round(row.midpoint or 0)) for row in corrected} == {
        ("Q2FY2027", 483_000_000),
        ("FY2027", 2_009_000_000),
        ("Q3FY2027", 515_000_000),
        ("FY2027", 2_045_000_000),
    }

    ledger = GuidanceLedger(corrected)
    current, prior = ledger.current_and_prior("IOT", as_of=NOW)
    assert {row.fiscal_period for row in current} == {"Q3FY2027", "FY2027"}
    assert len(prior) == 1
    assert prior[0].fiscal_period == "FY2027"
    assert round(prior[0].midpoint or 0) == 2_009_000_000

    assessment = ledger.assess("IOT", RULES, rules_hash=RULES_HASH, as_of=NOW)
    assert assessment.guidance_deterioration is False


def test_round8_preserves_insm_full_year_2025_product_descriptor_fix():
    row = _record(
        "INSM",
        425_000_000,
        when=NOW - timedelta(days=300),
        period="FY2026",  # deliberately wrong input
        action=GuidanceAction.RAISE,
        evidence=(
            "Insmed is raising its full-year 2025 global ARIKAYCE revenue guidance "
            "to a range of $420 million to $430 million, from a range of "
            "$405 million to $425 million previously."
        ),
    )
    fixed = tighten_guidance_record_round8(row)
    assert fixed is not None
    assert fixed.fiscal_period == "FY2025"
