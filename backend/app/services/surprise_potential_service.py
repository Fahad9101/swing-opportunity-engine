from __future__ import annotations

from typing import Any

from app.domain.catalyst_v1_1 import CatalystEventFamily
from app.domain.surprise_v1_1 import (
    ClinicalExpectationClass,
    SurpriseOutcomeClass,
    SurprisePotentialAssessment,
    SurprisePotentialInput,
    TransactionExpectationClass,
)
from app.services.catalyst_materiality_service import normalize_event_type


_HARD_BINARY_EVENTS = {
    "regulatory_decision",
    "pivotal_phase3_readout",
    "merger_approval_or_close",
    "final_core_legal_regulatory_ruling",
}
_ESTIMATE_RESET_EVENTS = {
    "quarterly_earnings",
    "formal_full_year_guidance_update",
}
_INFORMATIONAL_EVENTS = {
    "routine_presentation_no_new_data_expected",
    "administrative_or_unverifiable",
}


def _surprise_rules(rules: dict[str, Any]) -> dict[str, Any]:
    config = rules.get("catalyst_v1_1", {}).get("surprise_re_rating")
    if not isinstance(config, dict):
        raise ValueError("SOE-1.1 surprise/re-rating rules are missing")
    return config


def score_surprise(outcome_binaryity: int, expectation_uncertainty: int, valuation_concentration: int, *, maximum: int = 5) -> int:
    if not 0 <= outcome_binaryity <= 2:
        raise ValueError("outcome_binaryity must be between 0 and 2")
    if not 0 <= expectation_uncertainty <= 2:
        raise ValueError("expectation_uncertainty must be between 0 and 2")
    if not 0 <= valuation_concentration <= 1:
        raise ValueError("valuation_concentration must be between 0 and 1")
    if maximum <= 0:
        raise ValueError("maximum must be positive")
    return min(maximum, outcome_binaryity + expectation_uncertainty + valuation_concentration)


def analyst_dispersion_fraction(consensus: float | None, low: float | None, high: float | None) -> float | None:
    """Return analyst range width as a magnitude ratio, never a direction signal."""
    if consensus is None or low is None or high is None:
        return None
    if high < low:
        return None
    denominator = abs(consensus)
    if denominator <= 1e-12:
        return None
    return abs(high - low) / denominator


def consensus_instability_fraction(current: float | None, prior: float | None) -> float | None:
    """Return absolute consensus movement; sign/direction is deliberately discarded."""
    if current is None or prior is None:
        return None
    denominator = abs(prior)
    if denominator <= 1e-12:
        return None
    return abs(current - prior) / denominator


def _tier(value: float, *, score_2_min: float, score_1_min: float) -> int:
    if value >= score_2_min:
        return 2
    if value >= score_1_min:
        return 1
    return 0


def _outcome_binaryity(event_type: str, config: dict[str, Any]) -> tuple[int | None, str]:
    canonical = normalize_event_type(event_type)
    rules = config["outcome_binaryity"]
    if canonical in _HARD_BINARY_EVENTS:
        return int(rules[SurpriseOutcomeClass.HARD_BINARY.value]), "hard_binary_event"
    if canonical in _ESTIMATE_RESET_EVENTS:
        return int(rules[SurpriseOutcomeClass.ESTIMATE_RESET.value]), "estimate_reset_event"
    if canonical in _INFORMATIONAL_EVENTS:
        return int(rules[SurpriseOutcomeClass.INFORMATIONAL.value]), "informational_event"
    return None, "outcome_class_not_determinable"


def _earnings_uncertainty(inputs: SurprisePotentialInput, config: dict[str, Any]) -> tuple[int | None, float | None, float | None, str]:
    rules = config["earnings_expectation_uncertainty"]
    dispersion = analyst_dispersion_fraction(inputs.analyst_consensus, inputs.analyst_low, inputs.analyst_high)
    if dispersion is None:
        # The implementation plan explicitly requires missing analyst ranges to
        # remain null rather than becoming a favorable/neutral zero.
        return None, None, consensus_instability_fraction(inputs.analyst_consensus, inputs.prior_consensus), "missing_valid_analyst_range"

    dispersion_score = _tier(
        dispersion,
        score_2_min=float(rules["dispersion_score_2_min"]),
        score_1_min=float(rules["dispersion_score_1_min"]),
    )
    instability = consensus_instability_fraction(inputs.analyst_consensus, inputs.prior_consensus)
    if instability is None:
        return dispersion_score, dispersion, None, "dispersion_only"
    instability_score = _tier(
        instability,
        score_2_min=float(rules["consensus_instability_score_2_min"]),
        score_1_min=float(rules["consensus_instability_score_1_min"]),
    )
    return max(dispersion_score, instability_score), dispersion, instability, "max_dispersion_instability"


def _clinical_uncertainty(inputs: SurprisePotentialInput, config: dict[str, Any]) -> tuple[int | None, str]:
    rules = config["clinical_regulatory_expectation_uncertainty"]
    if inputs.prior_clinical_evidence_available is not True:
        return None, "missing_prior_clinical_evidence"
    if inputs.clinical_expectation_class is None:
        return None, "missing_clinical_expectation_class"
    return int(rules[inputs.clinical_expectation_class.value]), inputs.clinical_expectation_class.value


def _transaction_uncertainty(inputs: SurprisePotentialInput, config: dict[str, Any]) -> tuple[int | None, str]:
    rules = config["transaction_legal_financing_expectation_uncertainty"]
    if inputs.transaction_expectation_class is None:
        return None, "missing_transaction_contingency_class"
    return int(rules[inputs.transaction_expectation_class.value]), inputs.transaction_expectation_class.value


def _expectation_uncertainty(
    inputs: SurprisePotentialInput,
    config: dict[str, Any],
) -> tuple[int | None, float | None, float | None, str]:
    canonical = normalize_event_type(inputs.event_type)
    if canonical in _ESTIMATE_RESET_EVENTS:
        return _earnings_uncertainty(inputs, config)
    if inputs.event_family == CatalystEventFamily.CLINICAL_REGULATORY:
        score, reason = _clinical_uncertainty(inputs, config)
        return score, None, None, reason
    if inputs.event_family == CatalystEventFamily.TRANSACTION_LEGAL_FINANCING:
        score, reason = _transaction_uncertainty(inputs, config)
        return score, None, None, reason
    if canonical in _INFORMATIONAL_EVENTS:
        return 0, None, None, "informational_event"
    return None, None, None, "expectation_framework_not_determinable"


def _valuation_concentration(inputs: SurprisePotentialInput, config: dict[str, Any]) -> tuple[int | None, str]:
    exposure = inputs.economic_exposure_score
    if exposure is None:
        return None, "missing_materiality_exposure_score"
    threshold = int(config["valuation_concentration"]["score_1_when_exposure_score"])
    return (1 if exposure >= threshold else 0), f"exposure_score={exposure}"


def assess_surprise_potential(
    inputs: SurprisePotentialInput,
    rules: dict[str, Any],
    *,
    rules_hash: str,
) -> SurprisePotentialAssessment:
    config = _surprise_rules(rules)
    canonical = normalize_event_type(inputs.event_type) or inputs.event_type
    missing: list[str] = []
    reasons: list[str] = []

    if not inputs.verified:
        missing.append("verified_primary_evidence")
    if not inputs.catalyst_candidate:
        missing.append("catalyst_candidate")
    if not inputs.source.strip():
        missing.append("source")
    if not inputs.source_url.strip():
        missing.append("source_url")

    outcome, outcome_reason = _outcome_binaryity(inputs.event_type, config)
    if outcome is None:
        missing.append("outcome_binaryity")
    else:
        reasons.append(f"outcome_binaryity:{outcome_reason}={outcome}")

    uncertainty, dispersion, instability, uncertainty_reason = _expectation_uncertainty(inputs, config)
    if uncertainty is None:
        missing.append("expectation_uncertainty")
    else:
        reasons.append(f"expectation_uncertainty:{uncertainty_reason}={uncertainty}")
    if dispersion is not None:
        reasons.append(f"analyst_dispersion_fraction={dispersion:.6f}")
    if instability is not None:
        reasons.append(f"consensus_instability_fraction={instability:.6f}")

    concentration, concentration_reason = _valuation_concentration(inputs, config)
    if concentration is None:
        missing.append("valuation_concentration")
    else:
        reasons.append(f"valuation_concentration:{concentration_reason}->{concentration}")

    score: int | None = None
    ready = bool(
        inputs.verified
        and inputs.catalyst_candidate
        and not missing
        and outcome is not None
        and uncertainty is not None
        and concentration is not None
    )
    if ready and outcome is not None and uncertainty is not None and concentration is not None:
        score = score_surprise(outcome, uncertainty, concentration, maximum=int(config["maximum"]))
        reasons.append(f"surprise_score={outcome}+{uncertainty}+{concentration}->{score}")

    if not inputs.catalyst_candidate or canonical == "administrative_or_unverifiable":
        rule_path = "catalyst_v1_1.surprise_re_rating.administrative_reject"
        ready = False
        score = None
    else:
        rule_path = "catalyst_v1_1.surprise_re_rating.scored" if ready else "catalyst_v1_1.surprise_re_rating.not_ready"

    return SurprisePotentialAssessment(
        model_version="SOE-1.1.0",
        rules_hash=rules_hash,
        ticker=inputs.ticker,
        event_id=inputs.event_id,
        event_family=inputs.event_family,
        event_type=canonical,
        outcome_binaryity=outcome,
        expectation_uncertainty=uncertainty,
        analyst_dispersion_fraction=dispersion,
        consensus_instability_fraction=instability,
        valuation_concentration=concentration,
        surprise_score=score,
        surprise_ready=ready,
        directional_prediction=False,
        missing_fields=sorted(set(missing)),
        rule_path=rule_path,
        reasons=reasons,
        source=inputs.source,
        source_url=inputs.source_url,
        source_timestamp=inputs.source_timestamp,
        extraction_method=inputs.extraction_method,
        evidence_spans=inputs.evidence_spans,
        structured_provenance=inputs.structured_provenance,
    )
