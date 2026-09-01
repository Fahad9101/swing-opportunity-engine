from datetime import UTC, datetime, timedelta

import pytest

from app.core.config import SOE_1_1_RULES_PATH, load_rules_for_version, rules_hash
from app.domain.soe_v1_1 import (
    GuidanceAction,
    GuidanceClassification,
    GuidanceMetric,
    GuidanceMetricRecord,
    GuidancePolicyEvidence,
)
from app.services.guidance_classifier import classify_guidance
from app.services.guidance_ledger_service import GuidanceLedger


RULES = load_rules_for_version(SOE_1_1_RULES_PATH, "SOE-1.1.0")
RULES_HASH = rules_hash(RULES)
NOW = datetime(2026, 9, 1, tzinfo=UTC)


def record(
    metric: GuidanceMetric,
    midpoint: float | None,
    *,
    when: datetime,
    period: str = "FY2027",
    basis: str = "ADJUSTED",
    action: GuidanceAction = GuidanceAction.NONE,
    verified: bool = True,
) -> GuidanceMetricRecord:
    unit = "fraction" if metric in {GuidanceMetric.GROSS_MARGIN, GuidanceMetric.OPERATING_MARGIN} else "USD"
    if metric == GuidanceMetric.EPS:
        unit = "USD/share"
    return GuidanceMetricRecord(
        rules_hash=RULES_HASH,
        ticker="TEST",
        fiscal_period=period,
        metric=metric,
        accounting_basis=basis,
        midpoint=midpoint,
        unit=unit,
        source="SEC EDGAR",
        source_url=f"https://www.sec.gov/test/{when.timestamp()}/{metric.value}",
        source_timestamp=when,
        explicit_action=action,
        verified=verified,
        as_of=when,
        fetched_at=when,
    )


def assess(current, prior, policy=None):
    return classify_guidance(current, prior, RULES, rules_hash=RULES_HASH, policy=policy, as_of=NOW)


@pytest.mark.parametrize(
    "metric,prior_value,current_value,expected",
    [
        (GuidanceMetric.REVENUE, 100.0, 98.0, True),
        (GuidanceMetric.REVENUE, 100.0, 98.01, False),
        (GuidanceMetric.EPS, 10.0, 9.5, True),
        (GuidanceMetric.EPS, 10.0, 9.501, False),
        (GuidanceMetric.EBITDA, 100.0, 95.0, True),
        (GuidanceMetric.EBITDA, 100.0, 95.01, False),
        (GuidanceMetric.FCF, 100.0, 95.0, True),
        (GuidanceMetric.FCF, 100.0, 95.01, False),
        (GuidanceMetric.GROSS_MARGIN, 0.30, 0.29, True),
        (GuidanceMetric.GROSS_MARGIN, 0.30, 0.2901, False),
        (GuidanceMetric.OPERATING_MARGIN, 0.20, 0.19, True),
        (GuidanceMetric.OPERATING_MARGIN, 0.20, 0.1901, False),
    ],
)
def test_exact_material_cut_boundaries(metric, prior_value, current_value, expected):
    result = assess(
        [record(metric, current_value, when=NOW)],
        [record(metric, prior_value, when=NOW - timedelta(days=90))],
    )
    assert result.guidance_deterioration is expected
    assert result.classification is (
        GuidanceClassification.DETERIORATED if expected else GuidanceClassification.NOT_DETERIORATED
    )


def test_explicit_lower_is_deteriorated_without_numeric_values():
    result = assess(
        [record(GuidanceMetric.REVENUE, None, when=NOW, action=GuidanceAction.LOWER)],
        [],
    )
    assert result.guidance_deterioration is True
    assert result.rule_path.endswith("explicit_lower_or_withdrawal")


def test_explicit_withdrawal_is_deteriorated_without_prior_record():
    result = assess(
        [record(GuidanceMetric.EPS, None, when=NOW, action=GuidanceAction.WITHDRAW)],
        [],
    )
    assert result.guidance_deterioration is True
    assert result.explicit_cut_or_withdrawal is True


def test_two_small_one_percent_cuts_are_deteriorated():
    current = [
        record(GuidanceMetric.REVENUE, 99.0, when=NOW),
        record(GuidanceMetric.EPS, 9.9, when=NOW),
    ]
    prior = [
        record(GuidanceMetric.REVENUE, 100.0, when=NOW - timedelta(days=90)),
        record(GuidanceMetric.EPS, 10.0, when=NOW - timedelta(days=90)),
    ]
    result = assess(current, prior)
    assert result.guidance_deterioration is True
    assert result.rule_path.endswith("multi_metric_small_cut")


def test_one_small_cut_is_not_deteriorated():
    current = [
        record(GuidanceMetric.REVENUE, 99.0, when=NOW),
        record(GuidanceMetric.EPS, 10.0, when=NOW),
    ]
    prior = [
        record(GuidanceMetric.REVENUE, 100.0, when=NOW - timedelta(days=90)),
        record(GuidanceMetric.EPS, 10.0, when=NOW - timedelta(days=90)),
    ]
    result = assess(current, prior)
    assert result.guidance_deterioration is False


def test_two_fifty_basis_point_margin_cuts_are_deteriorated():
    current = [
        record(GuidanceMetric.GROSS_MARGIN, 0.295, when=NOW),
        record(GuidanceMetric.OPERATING_MARGIN, 0.195, when=NOW),
    ]
    prior = [
        record(GuidanceMetric.GROSS_MARGIN, 0.30, when=NOW - timedelta(days=90)),
        record(GuidanceMetric.OPERATING_MARGIN, 0.20, when=NOW - timedelta(days=90)),
    ]
    assert assess(current, prior).guidance_deterioration is True


def test_missing_prior_is_unknown_not_safe():
    result = assess([record(GuidanceMetric.REVENUE, 100.0, when=NOW)], [])
    assert result.guidance_deterioration is None
    assert result.classification is GuidanceClassification.UNKNOWN


def test_changed_fiscal_period_is_unknown():
    result = assess(
        [record(GuidanceMetric.REVENUE, 100.0, when=NOW, period="FY2028")],
        [record(GuidanceMetric.REVENUE, 100.0, when=NOW - timedelta(days=90), period="FY2027")],
    )
    assert result.guidance_deterioration is None


def test_changed_accounting_basis_is_unknown():
    result = assess(
        [record(GuidanceMetric.EPS, 10.0, when=NOW, basis="GAAP")],
        [record(GuidanceMetric.EPS, 10.0, when=NOW - timedelta(days=90), basis="ADJUSTED")],
    )
    assert result.guidance_deterioration is None


def test_zero_or_negative_midpoint_is_unknown():
    result = assess(
        [record(GuidanceMetric.EPS, -2.0, when=NOW)],
        [record(GuidanceMetric.EPS, -1.0, when=NOW - timedelta(days=90))],
    )
    assert result.guidance_deterioration is None
    assert any(not delta.comparable for delta in result.metric_deltas)


def test_initiated_new_metric_does_not_block_comparable_existing_metrics():
    result = assess(
        [
            record(GuidanceMetric.REVENUE, 101.0, when=NOW),
            record(GuidanceMetric.FCF, 20.0, when=NOW, action=GuidanceAction.INITIATE),
        ],
        [record(GuidanceMetric.REVENUE, 100.0, when=NOW - timedelta(days=90))],
    )
    assert result.guidance_deterioration is False


def test_positive_action_conflicting_with_numeric_cut_is_unknown():
    result = assess(
        [record(GuidanceMetric.REVENUE, 95.0, when=NOW, action=GuidanceAction.REAFFIRM)],
        [record(GuidanceMetric.REVENUE, 100.0, when=NOW - timedelta(days=90))],
    )
    assert result.guidance_deterioration is None
    assert result.rule_path.endswith("conflicting_primary_evidence")


def test_explicit_standing_no_guidance_policy_is_not_deteriorated():
    policy = GuidancePolicyEvidence(
        ticker="TEST",
        standing_no_guidance_policy=True,
        source="SEC EDGAR",
        source_url="https://www.sec.gov/test/policy",
        source_timestamp=NOW,
        evidence_span="The company does not provide quantitative financial guidance.",
    )
    result = assess([], [], policy=policy)
    assert result.guidance_deterioration is False
    assert result.classification is GuidanceClassification.NOT_DETERIORATED


def test_unverified_records_do_not_create_false_safety():
    result = assess(
        [record(GuidanceMetric.REVENUE, 110.0, when=NOW, verified=False)],
        [record(GuidanceMetric.REVENUE, 100.0, when=NOW - timedelta(days=90), verified=False)],
    )
    assert result.guidance_deterioration is None


def test_non_null_assessment_always_has_source_and_rule_path():
    result = assess(
        [record(GuidanceMetric.REVENUE, 101.0, when=NOW)],
        [record(GuidanceMetric.REVENUE, 100.0, when=NOW - timedelta(days=90))],
    )
    assert result.guidance_deterioration is False
    assert result.sources
    assert result.rule_path.startswith("guidance_v1_1.")


def test_ledger_sets_supersedes_and_selects_latest_two_versions():
    first = record(GuidanceMetric.REVENUE, 100.0, when=NOW - timedelta(days=180))
    second = record(GuidanceMetric.REVENUE, 102.0, when=NOW - timedelta(days=90))
    third = record(GuidanceMetric.REVENUE, 104.0, when=NOW)
    ledger = GuidanceLedger()
    stored = ledger.add_many([first, second, third])
    assert stored[1].supersedes_record_id == stored[0].record_id
    assert stored[2].supersedes_record_id == stored[1].record_id
    current, prior = ledger.current_and_prior("TEST", as_of=NOW)
    assert current[0].midpoint == 104.0
    assert prior[0].midpoint == 102.0
