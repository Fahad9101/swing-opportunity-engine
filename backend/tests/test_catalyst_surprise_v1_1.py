from datetime import UTC, datetime

import pytest

from app.core.config import SOE_1_1_RULES_PATH, load_rules_for_version, rules_hash
from app.domain.catalyst_surprise_v1_1 import (
    AnalystConsensusContext,
    CatalystSurpriseInput,
    ClinicalExpectationState,
    SurpriseExpectationMetric,
    TransactionContingencyState,
)
from app.domain.catalyst_v1_1 import CatalystEventFamily
from app.services.catalyst_surprise_service import assess_surprise_potential, score_surprise_potential


NOW = datetime(2026, 9, 3, tzinfo=UTC)
RULES = load_rules_for_version(SOE_1_1_RULES_PATH, "SOE-1.1.0")
RULES_HASH = rules_hash(RULES)


def consensus(
    metric: SurpriseExpectationMetric = SurpriseExpectationMetric.EPS,
    *,
    average: float | None = 2.0,
    high: float | None = 2.4,
    low: float | None = 1.8,
    current: float | None = 2.0,
    old_90d: float | None = 1.8,
) -> AnalystConsensusContext:
    return AnalystConsensusContext(
        ticker="TEST",
        period="0q",
        metric=metric,
        average=average,
        high=high,
        low=low,
        current_estimate=current,
        estimate_90d_ago=old_90d,
        analyst_count=20,
        source="consensus-test",
        source_timestamp=NOW,
        field_provenance={"average": "test.avg"},
    )


def event(**updates) -> CatalystSurpriseInput:
    payload = {
        "ticker": "TEST",
        "event_id": "event-1",
        "event_family": CatalystEventFamily.EARNINGS_GUIDANCE,
        "event_type": "quarterly_earnings",
        "economic_exposure_score": 3,
        "catalyst_candidate": True,
        "verified": True,
        "eps_consensus": consensus(),
        "source": "SEC EDGAR",
        "source_url": "https://www.sec.gov/Archives/edgar/data/1/example.htm",
        "source_timestamp": NOW,
        "evidence_spans": ["Quarterly results filed on Form 8-K."],
    }
    payload.update(updates)
    return CatalystSurpriseInput(**payload)


def assess(**updates):
    return assess_surprise_potential(event(**updates), RULES, rules_hash=RULES_HASH)


def test_score_surprise_is_pure_sum_capped_at_five():
    assert score_surprise_potential(2, 2, 1) == 5
    assert score_surprise_potential(1, 1, 0) == 2
    assert score_surprise_potential(2, 2, 1, maximum=4) == 4


@pytest.mark.parametrize(
    ("outcome", "uncertainty", "valuation"),
    [(-1, 1, 1), (3, 1, 1), (1, -1, 1), (1, 3, 1), (1, 1, -1), (1, 1, 2)],
)
def test_score_surprise_rejects_out_of_range_components(outcome, uncertainty, valuation):
    with pytest.raises(ValueError):
        score_surprise_potential(outcome, uncertainty, valuation)


@pytest.mark.parametrize(
    ("high", "low", "expected"),
    [(2.2, 1.8, 2), (2.1, 1.9, 1), (2.09, 1.91, 0)],
)
def test_earnings_dispersion_thresholds(high, low, expected):
    result = assess(eps_consensus=consensus(average=2.0, high=high, low=low))
    assert result.expectation_uncertainty == expected
    assert result.expectation_uncertainty_basis == "eps_consensus_dispersion"


@pytest.mark.parametrize(
    ("current", "old", "expected"),
    [(1.10, 1.0, 2), (1.05, 1.0, 1), (1.049, 1.0, 0)],
)
def test_earnings_falls_back_to_90d_instability_when_range_is_missing(current, old, expected):
    result = assess(
        eps_consensus=consensus(average=1.0, high=None, low=None, current=current, old_90d=old)
    )
    assert result.expectation_uncertainty == expected
    assert result.expectation_uncertainty_basis == "eps_90d_consensus_instability"


def test_sign_changing_eps_range_uses_revenue_dispersion():
    eps = consensus(average=0.05, high=0.50, low=-0.40, current=0.05, old_90d=0.04)
    revenue = consensus(
        SurpriseExpectationMetric.REVENUE,
        average=100.0,
        high=112.0,
        low=88.0,
        current=100.0,
        old_90d=None,
    )
    result = assess(eps_consensus=eps, revenue_consensus=revenue)
    assert result.expectation_metric == SurpriseExpectationMetric.REVENUE
    assert result.expectation_uncertainty == 2
    assert result.expectation_uncertainty_basis == "revenue_consensus_dispersion"


def test_zero_eps_average_does_not_invent_a_near_zero_threshold():
    eps = consensus(average=0.0, high=0.2, low=0.1, current=0.1, old_90d=0.08)
    revenue = consensus(
        SurpriseExpectationMetric.REVENUE,
        average=100.0,
        high=108.0,
        low=92.0,
        current=100.0,
        old_90d=None,
    )
    result = assess(eps_consensus=eps, revenue_consensus=revenue)
    assert result.expectation_metric == SurpriseExpectationMetric.REVENUE
    assert result.expectation_uncertainty == 1


def test_missing_range_and_instability_stays_null_not_zero():
    result = assess(
        eps_consensus=consensus(average=2.0, high=None, low=None, current=None, old_90d=None)
    )
    assert result.expectation_uncertainty is None
    assert result.surprise_potential is None
    assert result.surprise_ready is False
    assert "expectation_uncertainty" in result.missing_fields


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (ClinicalExpectationState.UNRESOLVED_PIVOTAL_OR_REGULATORY, 2),
        (ClinicalExpectationState.PHASE2_OR_DERISKED_LABEL_EXPANSION, 1),
        (ClinicalExpectationState.CONFIRMATORY_ADMINISTRATIVE, 0),
    ],
)
def test_clinical_expectation_states_are_deterministic(state, expected):
    result = assess(
        event_family=CatalystEventFamily.CLINICAL_REGULATORY,
        event_type="pivotal_phase3_readout" if expected == 2 else "phase2_poc_readout",
        eps_consensus=None,
        clinical_expectation_state=state,
    )
    assert result.expectation_uncertainty == expected


def test_missing_prior_clinical_evidence_stays_null():
    result = assess(
        event_family=CatalystEventFamily.CLINICAL_REGULATORY,
        event_type="pivotal_phase3_readout",
        eps_consensus=None,
        clinical_expectation_state=None,
    )
    assert result.expectation_uncertainty is None
    assert result.surprise_potential is None


@pytest.mark.parametrize(
    ("state", "expected_uncertainty", "expected_binaryity"),
    [
        (TransactionContingencyState.UNRESOLVED_MATERIAL_BINARY_CONTINGENCY, 2, 2),
        (TransactionContingencyState.MULTIPLE_PLAUSIBLE_ECONOMIC_OUTCOMES, 1, 1),
        (TransactionContingencyState.ADMINISTRATIVE, 0, 0),
    ],
)
def test_transaction_contingency_controls_uncertainty_and_binaryity(state, expected_uncertainty, expected_binaryity):
    result = assess(
        event_family=CatalystEventFamily.TRANSACTION_LEGAL_FINANCING,
        event_type="material_refinancing_covenant_event",
        eps_consensus=None,
        transaction_contingency_state=state,
    )
    assert result.expectation_uncertainty == expected_uncertainty
    assert result.outcome_binaryity == expected_binaryity


def test_valuation_concentration_is_one_only_at_exposure_three():
    assert assess(economic_exposure_score=3).valuation_concentration == 1
    assert assess(economic_exposure_score=2).valuation_concentration == 0
    missing = assess(economic_exposure_score=None)
    assert missing.valuation_concentration is None
    assert missing.surprise_potential is None


def test_hard_binary_plus_high_uncertainty_plus_concentration_can_score_five():
    result = assess(
        event_family=CatalystEventFamily.CLINICAL_REGULATORY,
        event_type="regulatory_decision",
        eps_consensus=None,
        clinical_expectation_state=ClinicalExpectationState.UNRESOLVED_PIVOTAL_OR_REGULATORY,
    )
    assert result.outcome_binaryity == 2
    assert result.expectation_uncertainty == 2
    assert result.valuation_concentration == 1
    assert result.surprise_potential == 5
    assert result.surprise_ready is True


def test_unverified_or_non_candidate_event_cannot_score():
    unverified = assess(verified=False)
    assert unverified.surprise_potential is None
    assert "verified_primary_evidence" in unverified.missing_fields

    rejected = assess(catalyst_candidate=False)
    assert rejected.surprise_potential is None
    assert "catalyst_candidate" in rejected.missing_fields


def test_scored_assessment_is_explicitly_non_directional_and_auditable():
    result = assess()
    assert result.surprise_potential is not None
    assert result.rules_hash == RULES_HASH
    assert result.rule_path == "catalyst_v1_1.surprise_re_rating.scored"
    assert "surprise_potential_is_non_directional" in result.reasons
    assert result.source == "SEC EDGAR"
    assert result.source_url.startswith("https://www.sec.gov/")
