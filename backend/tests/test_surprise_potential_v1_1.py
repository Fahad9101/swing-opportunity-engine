from datetime import UTC, datetime

import pytest

from app.domain.catalyst_v1_1 import CatalystEventFamily
from app.domain.surprise_v1_1 import (
    ClinicalExpectationClass,
    SurprisePotentialInput,
    TransactionExpectationClass,
)
from app.services.surprise_potential_service import (
    analyst_dispersion_fraction,
    assess_surprise_potential,
    consensus_instability_fraction,
    score_surprise,
)


RULES = {
    "catalyst_v1_1": {
        "surprise_re_rating": {
            "outcome_binaryity": {
                "hard_binary": 2,
                "estimate_reset_event": 1,
                "informational": 0,
            },
            "earnings_expectation_uncertainty": {
                "dispersion_score_2_min": 0.20,
                "dispersion_score_1_min": 0.10,
                "consensus_instability_score_2_min": 0.10,
                "consensus_instability_score_1_min": 0.05,
            },
            "clinical_regulatory_expectation_uncertainty": {
                "unresolved_pivotal_or_regulatory": 2,
                "phase2_or_derisked_label_expansion": 1,
                "confirmatory_administrative": 0,
            },
            "transaction_legal_financing_expectation_uncertainty": {
                "unresolved_material_binary_contingency": 2,
                "multiple_plausible_economic_outcomes": 1,
                "administrative": 0,
            },
            "valuation_concentration": {"score_1_when_exposure_score": 3},
            "maximum": 5,
        }
    }
}


def _base(**kwargs) -> SurprisePotentialInput:
    payload = {
        "ticker": "TEST",
        "event_id": "event-1",
        "event_family": CatalystEventFamily.EARNINGS_GUIDANCE,
        "event_type": "quarterly_earnings",
        "source": "SEC EDGAR",
        "source_url": "https://www.sec.gov/Archives/edgar/data/1/test.htm",
        "source_timestamp": datetime(2026, 9, 1, tzinfo=UTC),
        "verified": True,
        "catalyst_candidate": True,
        "economic_exposure_score": 3,
        "analyst_consensus": 100.0,
        "analyst_low": 90.0,
        "analyst_high": 110.0,
        "evidence_spans": ["verified evidence"],
    }
    payload.update(kwargs)
    return SurprisePotentialInput(**payload)


def test_score_surprise_caps_at_five():
    assert score_surprise(2, 2, 1, maximum=5) == 5


def test_score_surprise_validates_component_bounds():
    with pytest.raises(ValueError):
        score_surprise(3, 2, 1)


def test_dispersion_is_range_width_over_absolute_consensus():
    assert analyst_dispersion_fraction(100.0, 90.0, 110.0) == pytest.approx(0.20)
    assert analyst_dispersion_fraction(-2.0, -2.2, -1.8) == pytest.approx(0.20)


def test_invalid_or_missing_analyst_range_stays_null():
    assert analyst_dispersion_fraction(None, 90.0, 110.0) is None
    assert analyst_dispersion_fraction(100.0, 110.0, 90.0) is None
    assert analyst_dispersion_fraction(0.0, -1.0, 1.0) is None


def test_consensus_instability_discards_direction():
    assert consensus_instability_fraction(110.0, 100.0) == pytest.approx(0.10)
    assert consensus_instability_fraction(90.0, 100.0) == pytest.approx(0.10)


def test_earnings_high_dispersion_scores_uncertainty_two_and_total_four():
    result = assess_surprise_potential(_base(), RULES, rules_hash="rules")
    assert result.outcome_binaryity == 1
    assert result.expectation_uncertainty == 2
    assert result.valuation_concentration == 1
    assert result.surprise_score == 4
    assert result.directional_prediction is False


def test_earnings_mid_dispersion_scores_one():
    result = assess_surprise_potential(
        _base(analyst_low=95.0, analyst_high=105.0), RULES, rules_hash="rules"
    )
    assert result.analyst_dispersion_fraction == pytest.approx(0.10)
    assert result.expectation_uncertainty == 1
    assert result.surprise_score == 3


def test_instability_can_raise_uncertainty_without_using_direction():
    result = assess_surprise_potential(
        _base(analyst_low=97.0, analyst_high=103.0, prior_consensus=90.0),
        RULES,
        rules_hash="rules",
    )
    assert result.analyst_dispersion_fraction == pytest.approx(0.06)
    assert result.consensus_instability_fraction == pytest.approx(10.0 / 90.0)
    assert result.expectation_uncertainty == 2
    assert result.surprise_score == 4
    assert result.directional_prediction is False


def test_missing_analyst_range_keeps_earnings_surprise_null_even_with_prior_consensus():
    result = assess_surprise_potential(
        _base(analyst_low=None, analyst_high=None, prior_consensus=90.0),
        RULES,
        rules_hash="rules",
    )
    assert result.expectation_uncertainty is None
    assert result.surprise_score is None
    assert "expectation_uncertainty" in result.missing_fields


def test_hard_binary_clinical_event_scores_five_when_unresolved_and_concentrated():
    result = assess_surprise_potential(
        _base(
            event_family=CatalystEventFamily.CLINICAL_REGULATORY,
            event_type="pivotal_phase3_readout",
            analyst_consensus=None,
            analyst_low=None,
            analyst_high=None,
            prior_clinical_evidence_available=True,
            clinical_expectation_class=ClinicalExpectationClass.UNRESOLVED_PIVOTAL_OR_REGULATORY,
        ),
        RULES,
        rules_hash="rules",
    )
    assert result.outcome_binaryity == 2
    assert result.expectation_uncertainty == 2
    assert result.valuation_concentration == 1
    assert result.surprise_score == 5


def test_missing_prior_clinical_evidence_stays_null():
    result = assess_surprise_potential(
        _base(
            event_family=CatalystEventFamily.CLINICAL_REGULATORY,
            event_type="regulatory_decision",
            analyst_consensus=None,
            analyst_low=None,
            analyst_high=None,
            prior_clinical_evidence_available=None,
            clinical_expectation_class=ClinicalExpectationClass.UNRESOLVED_PIVOTAL_OR_REGULATORY,
        ),
        RULES,
        rules_hash="rules",
    )
    assert result.expectation_uncertainty is None
    assert result.surprise_score is None


def test_transaction_binary_contingency_scores_five_when_concentrated():
    result = assess_surprise_potential(
        _base(
            event_family=CatalystEventFamily.TRANSACTION_LEGAL_FINANCING,
            event_type="merger_approval_or_close",
            analyst_consensus=None,
            analyst_low=None,
            analyst_high=None,
            transaction_expectation_class=TransactionExpectationClass.UNRESOLVED_MATERIAL_BINARY_CONTINGENCY,
        ),
        RULES,
        rules_hash="rules",
    )
    assert result.outcome_binaryity == 2
    assert result.expectation_uncertainty == 2
    assert result.surprise_score == 5


def test_nonconcentrated_exposure_scores_zero_valuation_concentration():
    result = assess_surprise_potential(_base(economic_exposure_score=2), RULES, rules_hash="rules")
    assert result.valuation_concentration == 0
    assert result.surprise_score == 3


def test_missing_exposure_stays_null_not_zero():
    result = assess_surprise_potential(_base(economic_exposure_score=None), RULES, rules_hash="rules")
    assert result.valuation_concentration is None
    assert result.surprise_score is None


def test_administrative_event_never_gets_surprise_score():
    result = assess_surprise_potential(
        _base(
            event_family=CatalystEventFamily.CORPORATE_STRATEGIC,
            event_type="administrative_or_unverifiable",
            catalyst_candidate=False,
            analyst_consensus=None,
            analyst_low=None,
            analyst_high=None,
            economic_exposure_score=None,
        ),
        RULES,
        rules_hash="rules",
    )
    assert result.outcome_binaryity == 0
    assert result.surprise_score is None
    assert result.rule_path.endswith("administrative_reject")


def test_unmapped_event_type_stays_null_instead_of_guessing_binaryity():
    result = assess_surprise_potential(
        _base(event_type="major_contract_customer_award"), RULES, rules_hash="rules"
    )
    assert result.outcome_binaryity is None
    assert result.surprise_score is None
