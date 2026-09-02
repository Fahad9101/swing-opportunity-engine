from datetime import UTC, datetime

from app.core.config import SOE_1_1_RULES_PATH, load_rules_for_version, rules_hash
from app.domain.soe_v1_1 import GuidanceClassification, GuidanceMetric, GuidanceMetricRecord
from app.services.guidance_ledger_service import GuidanceLedger


NOW = datetime(2026, 9, 2, tzinfo=UTC)
RULES = load_rules_for_version(SOE_1_1_RULES_PATH, "SOE-1.1.0")
RULES_HASH = rules_hash(RULES)


def test_all_extracted_records_filtered_from_assessment_return_unknown_not_error():
    # This resembles a reported historical actual captured near guidance prose:
    # extraction produced a record, but the assessment eligibility layer should
    # reject it because it is not genuine forward guidance.
    record = GuidanceMetricRecord(
        rules_hash=RULES_HASH,
        ticker="TEST",
        fiscal_period="Q2FY2026",
        metric=GuidanceMetric.REVENUE,
        accounting_basis="UNSPECIFIED",
        low=47_900_000_000.0,
        high=47_900_000_000.0,
        unit="USD",
        source="SEC EDGAR",
        source_url="https://www.sec.gov/test/reported-actual",
        source_timestamp=NOW,
        evidence_span="The company reported revenue of $47.9 billion for Q2 FY2026 results.",
        as_of=NOW,
        fetched_at=NOW,
    )

    assessment = GuidanceLedger([record]).assess(
        "TEST",
        RULES,
        rules_hash=RULES_HASH,
        as_of=NOW,
    )

    assert assessment.classification is GuidanceClassification.UNKNOWN
    assert assessment.guidance_deterioration is None
    assert assessment.ticker == "TEST"
    assert assessment.rule_path.endswith("no_assessment_eligible_primary_guidance")
    assert assessment.sources == ["https://www.sec.gov/test/reported-actual"]


def test_empty_ledger_returns_unknown_not_error_when_ticker_is_known():
    assessment = GuidanceLedger().assess(
        "TEST",
        RULES,
        rules_hash=RULES_HASH,
        as_of=NOW,
    )

    assert assessment.classification is GuidanceClassification.UNKNOWN
    assert assessment.guidance_deterioration is None
    assert assessment.ticker == "TEST"
    assert assessment.rule_path.endswith("no_assessment_eligible_primary_guidance")
