from __future__ import annotations

from typing import Any

from app.domain.catalyst_surprise_v1_1 import (
    AnalystConsensusContext,
    CatalystSurpriseAssessment,
    CatalystSurpriseInput,
    ClinicalExpectationState,
    SurpriseExpectationMetric,
    TransactionContingencyState,
)
from app.domain.catalyst_v1_1 import CatalystEventFamily
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
    "phase2_poc_readout",
    "major_reimbursement_decision",
    "investor_day_new_multiyear_targets",
}

_INFORMATIONAL_EVENTS = {
    "non_pivotal_study_update",
    "conference_new_data",
    "ordinary_measurable_noncore_update",
    "routine_presentation_no_new_data_expected",
    "administrative_or_unverifiable",
}


def score_surprise_potential(
    outcome_binaryity: int,
    expectation_uncertainty: int,
    valuation_concentration: int,
    *,
    maximum: int = 5,
) -> int:
    if not 0 <= outcome_binaryity <= 2:
        raise ValueError("outcome_binaryity must be between 0 and 2")
    if not 0 <= expectation_uncertainty <= 2:
        raise ValueError("expectation_uncertainty must be between 0 and 2")
    if not 0 <= valuation_concentration <= 1:
        raise ValueError("valuation_concentration must be between 0 and 1")
    if maximum <= 0:
        raise ValueError("maximum must be positive")
    return min(maximum, outcome_binaryity + expectation_uncertainty + valuation_concentration)


def _surprise_rules(rules: dict[str, Any]) -> dict[str, Any]:
    config = rules.get("catalyst_v1_1", {}).get("surprise_re_rating")
    if not isinstance(config, dict):
        raise ValueError("SOE-1.1 catalyst surprise/re-rating rules are missing")
    return config


def _outcome_binaryity(
    inputs: CatalystSurpriseInput,
    canonical_type: str,
    config: dict[str, Any],
) -> tuple[int | None, str]:
    rules = config["outcome_binaryity"]

    if canonical_type in _HARD_BINARY_EVENTS:
        return int(rules["hard_binary"]), "hard_binary_event"

    if inputs.event_family == CatalystEventFamily.TRANSACTION_LEGAL_FINANCING:
        state = inputs.transaction_contingency_state
        if state == TransactionContingencyState.UNRESOLVED_MATERIAL_BINARY_CONTINGENCY:
            return int(rules["hard_binary"]), "transaction_hard_binary_contingency"
        if state == TransactionContingencyState.MULTIPLE_PLAUSIBLE_ECONOMIC_OUTCOMES:
            return int(rules["estimate_reset_event"]), "transaction_multiple_outcomes"
        if state == TransactionContingencyState.ADMINISTRATIVE:
            return int(rules["informational"]), "transaction_administrative"
        return None, "missing_transaction_contingency_for_binaryity"

    if canonical_type in _ESTIMATE_RESET_EVENTS:
        return int(rules["estimate_reset_event"]), "estimate_reset_event"
    if canonical_type in _INFORMATIONAL_EVENTS:
        return int(rules["informational"]), "informational_event"
    return None, "unsupported_outcome_binaryity_event"


def _dispersion(context: AnalystConsensusContext) -> float | None:
    if context.average is None or context.high is None or context.low is None:
        return None
    if context.average == 0:
        return None
    if context.high < context.low:
        return None
    return (context.high - context.low) / abs(context.average)


def _instability(context: AnalystConsensusContext) -> float | None:
    current = context.current_estimate
    old = context.estimate_90d_ago
    if current is None or old is None or old == 0:
        return None
    return abs(current / old - 1)


def _eps_range_is_sign_changing(context: AnalystConsensusContext | None) -> bool:
    if context is None or context.low is None or context.high is None:
        return False
    return context.low <= 0 <= context.high


def _threshold_score(value: float, *, score_2_min: float, score_1_min: float) -> int:
    if value >= score_2_min:
        return 2
    if value >= score_1_min:
        return 1
    return 0


def _earnings_expectation_uncertainty(
    inputs: CatalystSurpriseInput,
    config: dict[str, Any],
) -> tuple[int | None, str | None, SurpriseExpectationMetric | None, float | None, dict[str, Any], str]:
    rules = config["earnings_expectation_uncertainty"]
    eps = inputs.eps_consensus
    revenue = inputs.revenue_consensus

    # The locked specification only defines revenue substitution when EPS is
    # unusable because the consensus average is zero/sign-changing. It does not
    # define a numeric "near-zero" threshold, so none is invented here.
    eps_unusable = eps is not None and (eps.average == 0 or _eps_range_is_sign_changing(eps))
    primary = revenue if eps_unusable else eps
    metric = SurpriseExpectationMetric.REVENUE if eps_unusable else SurpriseExpectationMetric.EPS

    if primary is None:
        # If no EPS context exists at all, revenue can still be the documented
        # primary metric rather than converting missing evidence to zero.
        if eps is None and revenue is not None:
            primary = revenue
            metric = SurpriseExpectationMetric.REVENUE
        else:
            return None, None, None, None, {}, "missing_analyst_consensus_context"

    dispersion = _dispersion(primary)
    if dispersion is not None:
        score = _threshold_score(
            dispersion,
            score_2_min=float(rules["dispersion_score_2_min"]),
            score_1_min=float(rules["dispersion_score_1_min"]),
        )
        basis = f"{metric.value}_consensus_dispersion"
        return score, basis, metric, dispersion, primary.field_provenance, basis

    instability = _instability(primary)
    if instability is not None:
        score = _threshold_score(
            instability,
            score_2_min=float(rules["consensus_instability_score_2_min"]),
            score_1_min=float(rules["consensus_instability_score_1_min"]),
        )
        basis = f"{metric.value}_90d_consensus_instability"
        return score, basis, metric, instability, primary.field_provenance, basis

    return None, None, metric, None, primary.field_provenance, f"missing_{metric.value}_range_and_90d_instability"


def _clinical_expectation_uncertainty(
    inputs: CatalystSurpriseInput,
    config: dict[str, Any],
) -> tuple[int | None, str | None, str]:
    state = inputs.clinical_expectation_state
    if state is None:
        return None, None, "missing_prior_clinical_or_regulatory_evidence_state"
    rules = config["clinical_regulatory_expectation_uncertainty"]
    return int(rules[state.value]), state.value, state.value


def _transaction_expectation_uncertainty(
    inputs: CatalystSurpriseInput,
    config: dict[str, Any],
) -> tuple[int | None, str | None, str]:
    state = inputs.transaction_contingency_state
    if state is None:
        return None, None, "missing_transaction_contingency_state"
    rules = config["transaction_legal_financing_expectation_uncertainty"]
    return int(rules[state.value]), state.value, state.value


def _valuation_concentration(exposure_score: int | None, config: dict[str, Any]) -> tuple[int | None, str]:
    if exposure_score is None:
        return None, "missing_economic_exposure_score"
    concentrated_score = int(config["valuation_concentration"]["score_1_when_exposure_score"])
    if exposure_score == concentrated_score:
        return 1, "economic_exposure_score_3"
    if 0 <= exposure_score < concentrated_score:
        return 0, "economic_exposure_score_below_3"
    return None, "invalid_economic_exposure_score"


def assess_surprise_potential(
    inputs: CatalystSurpriseInput,
    rules: dict[str, Any],
    *,
    rules_hash: str,
) -> CatalystSurpriseAssessment:
    config = _surprise_rules(rules)
    canonical_type = normalize_event_type(inputs.event_type)
    missing: list[str] = []
    reasons: list[str] = ["surprise_potential_is_non_directional"]

    candidate = bool(inputs.catalyst_candidate and inputs.verified)
    if not inputs.verified:
        missing.append("verified_primary_evidence")
    if not inputs.catalyst_candidate:
        missing.append("catalyst_candidate")
    if canonical_type is None:
        missing.append("normalized_event_type")

    outcome: int | None = None
    uncertainty: int | None = None
    uncertainty_basis: str | None = None
    expectation_metric: SurpriseExpectationMetric | None = None
    expectation_value: float | None = None
    expectation_provenance: dict[str, Any] = {}

    if canonical_type is not None:
        outcome, outcome_reason = _outcome_binaryity(inputs, canonical_type, config)
        if outcome is None:
            missing.append("outcome_binaryity")
        else:
            reasons.append(f"outcome_binaryity:{outcome_reason}={outcome}")

        if inputs.event_family == CatalystEventFamily.EARNINGS_GUIDANCE:
            uncertainty, uncertainty_basis, expectation_metric, expectation_value, expectation_provenance, uncertainty_reason = _earnings_expectation_uncertainty(inputs, config)
        elif inputs.event_family == CatalystEventFamily.CLINICAL_REGULATORY:
            uncertainty, uncertainty_basis, uncertainty_reason = _clinical_expectation_uncertainty(inputs, config)
        elif inputs.event_family == CatalystEventFamily.TRANSACTION_LEGAL_FINANCING:
            uncertainty, uncertainty_basis, uncertainty_reason = _transaction_expectation_uncertainty(inputs, config)
        else:
            uncertainty = None
            uncertainty_reason = "unsupported_event_family_for_expectation_uncertainty"

        if uncertainty is None:
            missing.append("expectation_uncertainty")
            reasons.append(f"expectation_uncertainty:{uncertainty_reason}")
        else:
            reasons.append(f"expectation_uncertainty:{uncertainty_reason}={uncertainty}")

    valuation, valuation_reason = _valuation_concentration(inputs.economic_exposure_score, config)
    if valuation is None:
        missing.append("valuation_concentration")
    else:
        reasons.append(f"valuation_concentration:{valuation_reason}={valuation}")

    ready = bool(candidate and canonical_type is not None and not missing and outcome is not None and uncertainty is not None and valuation is not None)
    score: int | None = None
    if ready and outcome is not None and uncertainty is not None and valuation is not None:
        score = score_surprise_potential(outcome, uncertainty, valuation, maximum=int(config["maximum"]))
        reasons.append(f"surprise_potential={outcome}+{uncertainty}+{valuation}->{score}")

    rule_path = "catalyst_v1_1.surprise_re_rating.scored" if ready else "catalyst_v1_1.surprise_re_rating.not_ready"

    return CatalystSurpriseAssessment(
        model_version="SOE-1.1.0",
        rules_hash=rules_hash,
        ticker=inputs.ticker,
        event_id=inputs.event_id,
        event_family=inputs.event_family,
        event_type=canonical_type or inputs.event_type,
        outcome_binaryity=outcome,
        expectation_uncertainty=uncertainty,
        expectation_uncertainty_basis=uncertainty_basis,
        expectation_metric=expectation_metric,
        expectation_value=expectation_value,
        valuation_concentration=valuation,
        surprise_potential=score,
        surprise_ready=ready,
        catalyst_candidate=candidate,
        missing_fields=sorted(set(missing)),
        rule_path=rule_path,
        reasons=reasons,
        source=inputs.source,
        source_url=inputs.source_url,
        source_timestamp=inputs.source_timestamp,
        extraction_method=inputs.extraction_method,
        evidence_spans=inputs.evidence_spans,
        structured_provenance=inputs.structured_provenance,
        expectation_provenance=expectation_provenance,
    )
