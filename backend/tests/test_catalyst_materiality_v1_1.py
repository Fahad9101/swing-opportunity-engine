from datetime import UTC, datetime

import pytest

from app.core.config import SOE_1_1_RULES_PATH, load_rules_for_version, rules_hash
from app.domain.catalyst_v1_1 import (
    CatalystConsequenceClass,
    CatalystEventFamily,
    CatalystExposureBasis,
    CatalystMaterialityInput,
)
from app.services.catalyst_materiality_service import assess_materiality, normalize_event_type, score_materiality


NOW = datetime(2026, 9, 2, tzinfo=UTC)
RULES = load_rules_for_version(SOE_1_1_RULES_PATH, "SOE-1.1.0")
RULES_HASH = rules_hash(RULES)


def evidence(**updates):
    payload = {
        "ticker": "TEST",
        "event_id": "event-1",
        "event_family": CatalystEventFamily.CORPORATE_STRATEGIC,
        "event_type": "major_contract_customer_award",
        "source": "SEC",
        "source_url": "https://www.sec.gov/Archives/edgar/data/1/example.htm",
        "source_timestamp": NOW,
        "verified": True,
        "economic_exposure_basis": CatalystExposureBasis.REVENUE,
        "economic_exposure_fraction": 0.10,
        "consequence_class": CatalystConsequenceClass.MATERIAL_ESTIMATE_OR_EXECUTION_CHANGE,
        "evidence_spans": ["Contract represents approximately 10% of annual revenue."],
    }
    payload.update(updates)
    return CatalystMaterialityInput(**payload)


def assess(**updates):
    return assess_materiality(evidence(**updates), RULES, rules_hash=RULES_HASH)


def test_score_materiality_is_pure_sum_capped_at_ten():
    assert score_materiality(5, 3, 2) == 10
    assert score_materiality(4, 3, 2) == 9
    assert score_materiality(5, 3, 2, maximum=9) == 9


@pytest.mark.parametrize(
    ("base", "exposure", "consequence"),
    [(-1, 1, 1), (6, 1, 1), (1, -1, 1), (1, 4, 1), (1, 1, -1), (1, 1, 3)],
)
def test_score_materiality_rejects_out_of_range_components(base, exposure, consequence):
    with pytest.raises(ValueError):
        score_materiality(base, exposure, consequence)


def test_event_family_normalization_is_conservative():
    assert normalize_event_type("EARNINGS") == "quarterly_earnings"
    assert normalize_event_type("PDUFA") == "regulatory_decision"
    assert normalize_event_type("TRIAL_PRIMARY_COMPLETION") is None


def test_company_wide_earnings_scores_base4_exposure3_consequence1():
    result = assess(
        event_family=CatalystEventFamily.EARNINGS_GUIDANCE,
        event_type="earnings",
        economic_exposure_basis=None,
        economic_exposure_fraction=None,
        consequence_class=None,
    )
    assert result.event_class_base == 4
    assert result.economic_exposure_score == 3
    assert result.consequence_severity == 1
    assert result.materiality == 8
    assert result.materiality_ready is True


def test_earnings_with_formal_guidance_action_gets_consequence_two():
    result = assess(
        event_family=CatalystEventFamily.EARNINGS_GUIDANCE,
        event_type="quarterly_earnings",
        economic_exposure_basis=None,
        economic_exposure_fraction=None,
        consequence_class=None,
        formal_guidance_action=True,
    )
    assert result.consequence_severity == 2
    assert result.materiality == 9


def test_formal_full_year_guidance_is_company_wide_and_material_change():
    result = assess(
        event_family=CatalystEventFamily.EARNINGS_GUIDANCE,
        event_type="formal_full_year_guidance_update",
        economic_exposure_basis=None,
        economic_exposure_fraction=None,
        consequence_class=None,
    )
    assert result.event_class_base == 4
    assert result.economic_exposure_score == 3
    assert result.consequence_severity == 1
    assert result.materiality == 8


@pytest.mark.parametrize(
    ("fraction", "expected"),
    [(0.20, 3), (0.199999, 2), (0.10, 2), (0.099999, 1), (0.05, 1), (0.049999, 0)],
)
def test_conventional_exposure_boundaries(fraction, expected):
    result = assess(economic_exposure_fraction=fraction)
    assert result.economic_exposure_score == expected
    assert result.materiality is not None


@pytest.mark.parametrize(
    ("fraction", "expected"),
    [(0.50, 3), (0.499999, 2), (0.25, 2), (0.249999, 1), (0.10, 1), (0.099999, 0)],
)
def test_biotech_pipeline_exposure_boundaries(fraction, expected):
    result = assess(
        event_family=CatalystEventFamily.CLINICAL_REGULATORY,
        event_type="phase2_poc_readout",
        is_biotech=True,
        economic_exposure_basis=CatalystExposureBasis.BIOTECH_PIPELINE_VALUE,
        economic_exposure_fraction=None,
        biotech_pipeline_value_fraction=fraction,
        consequence_class=CatalystConsequenceClass.MATERIAL_ESTIMATE_OR_EXECUTION_CHANGE,
    )
    assert result.economic_exposure_score == expected


def test_documented_dominant_single_asset_defaults_to_exposure_three():
    result = assess(
        event_family=CatalystEventFamily.CLINICAL_REGULATORY,
        event_type="pivotal_phase3_readout",
        is_biotech=True,
        economic_exposure_basis=CatalystExposureBasis.DOMINANT_SINGLE_ASSET,
        economic_exposure_fraction=None,
        dominant_single_asset=True,
        consequence_class=None,
    )
    assert result.economic_exposure_score == 3
    assert result.consequence_severity == 2
    assert result.materiality == 10


def test_regulatory_decision_defaults_to_binary_consequence():
    result = assess(
        event_family=CatalystEventFamily.CLINICAL_REGULATORY,
        event_type="pdufa",
        company_wide=True,
        economic_exposure_fraction=None,
        consequence_class=None,
    )
    assert result.event_class_base == 5
    assert result.consequence_severity == 2
    assert result.materiality == 10


def test_explicit_binary_consequence_can_upgrade_refinancing_event():
    result = assess(
        event_family=CatalystEventFamily.TRANSACTION_LEGAL_FINANCING,
        event_type="material_refinancing_covenant_event",
        company_wide=True,
        economic_exposure_fraction=None,
        consequence_class=CatalystConsequenceClass.BINARY_PERMISSION_VIABILITY,
    )
    assert result.event_class_base == 3
    assert result.economic_exposure_score == 3
    assert result.consequence_severity == 2
    assert result.materiality == 8


def test_missing_exposure_is_null_not_zero():
    result = assess(economic_exposure_fraction=None, economic_exposure_basis=None)
    assert result.economic_exposure_score is None
    assert result.materiality is None
    assert result.materiality_ready is False
    assert "economic_exposure" in result.missing_fields


def test_unknown_event_type_is_null_not_administrative_zero():
    result = assess(event_type="rumor_from_social_media")
    assert result.event_class_base is None
    assert result.materiality is None
    assert result.catalyst_candidate is False
    assert "normalized_event_type" in result.missing_fields


def test_administrative_event_cannot_score_even_with_complete_inputs():
    result = assess(event_type="administrative_or_unverifiable", company_wide=True)
    assert result.event_class_base == 0
    assert result.catalyst_candidate is False
    assert result.materiality is None
    assert result.rule_path.endswith("administrative_reject")


def test_unverified_event_cannot_score():
    result = assess(verified=False)
    assert result.materiality is None
    assert result.materiality_ready is False
    assert result.catalyst_candidate is False
    assert "verified_primary_evidence" in result.missing_fields


def test_non_null_materiality_preserves_primary_provenance_and_rule_path():
    result = assess()
    assert result.materiality is not None
    assert result.source == "SEC"
    assert result.source_url.startswith("https://www.sec.gov/")
    assert result.rules_hash == RULES_HASH
    assert result.rule_path == "catalyst_v1_1.materiality.scored"
    assert result.evidence_spans
