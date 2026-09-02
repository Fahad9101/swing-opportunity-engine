from __future__ import annotations

from typing import Any

from app.domain.catalyst_v1_1 import (
    CatalystConsequenceClass,
    CatalystExposureBasis,
    CatalystMaterialityAssessment,
    CatalystMaterialityInput,
)


_EVENT_TYPE_ALIASES = {
    "earnings": "quarterly_earnings",
    "quarterly_results": "quarterly_earnings",
    "quarterly_earnings": "quarterly_earnings",
    "formal_full_year_guidance": "formal_full_year_guidance_update",
    "full_year_guidance_update": "formal_full_year_guidance_update",
    "formal_full_year_guidance_update": "formal_full_year_guidance_update",
    "fda_decision": "regulatory_decision",
    "pdufa": "regulatory_decision",
    "adcom": "regulatory_decision",
    "regulatory_decision": "regulatory_decision",
    "phase3_readout": "pivotal_phase3_readout",
    "pivotal_phase3_readout": "pivotal_phase3_readout",
    "merger_approval": "merger_approval_or_close",
    "merger_close": "merger_approval_or_close",
    "merger_approval_or_close": "merger_approval_or_close",
    "final_core_legal_regulatory_ruling": "final_core_legal_regulatory_ruling",
    "phase2_poc_readout": "phase2_poc_readout",
    "major_reimbursement_decision": "major_reimbursement_decision",
    "investor_day_new_multiyear_targets": "investor_day_new_multiyear_targets",
    "phase1_2_efficacy_update": "phase1_2_efficacy_update",
    "major_contract_customer_award": "major_contract_customer_award",
    "product_launch_with_disclosed_economics": "product_launch_with_disclosed_economics",
    "material_refinancing_covenant_event": "material_refinancing_covenant_event",
    "strategic_review_outcome": "strategic_review_outcome",
    "non_pivotal_study_update": "non_pivotal_study_update",
    "conference_new_data": "conference_new_data",
    "ordinary_measurable_noncore_update": "ordinary_measurable_noncore_update",
    "routine_presentation_no_new_data_expected": "routine_presentation_no_new_data_expected",
    "administrative_or_unverifiable": "administrative_or_unverifiable",
}

_BINARY_DEFAULT_EVENTS = {
    "regulatory_decision",
    "pivotal_phase3_readout",
    "merger_approval_or_close",
    "final_core_legal_regulatory_ruling",
}

_MATERIAL_CHANGE_DEFAULT_EVENTS = {
    "formal_full_year_guidance_update",
    "phase2_poc_readout",
    "major_reimbursement_decision",
    "investor_day_new_multiyear_targets",
    "phase1_2_efficacy_update",
    "major_contract_customer_award",
    "product_launch_with_disclosed_economics",
    "material_refinancing_covenant_event",
    "strategic_review_outcome",
    "non_pivotal_study_update",
    "conference_new_data",
    "ordinary_measurable_noncore_update",
}


def normalize_event_type(value: str) -> str | None:
    key = value.strip().lower().replace("-", "_").replace("/", "_").replace(" ", "_")
    while "__" in key:
        key = key.replace("__", "_")
    return _EVENT_TYPE_ALIASES.get(key)


def score_materiality(event_class_base: int, exposure: int, consequence: int, *, maximum: int = 10) -> int:
    if not 0 <= event_class_base <= 5:
        raise ValueError("event_class_base must be between 0 and 5")
    if not 0 <= exposure <= 3:
        raise ValueError("exposure must be between 0 and 3")
    if not 0 <= consequence <= 2:
        raise ValueError("consequence must be between 0 and 2")
    if maximum <= 0:
        raise ValueError("maximum must be positive")
    return min(maximum, event_class_base + exposure + consequence)


def _materiality_rules(rules: dict[str, Any]) -> dict[str, Any]:
    config = rules.get("catalyst_v1_1", {}).get("materiality")
    if not isinstance(config, dict):
        raise ValueError("SOE-1.1 catalyst materiality rules are missing")
    return config


def _exposure_score(inputs: CatalystMaterialityInput, config: dict[str, Any], canonical_type: str) -> tuple[int | None, CatalystExposureBasis | None, float | None, str]:
    exposure_rules = config["economic_exposure"]

    if canonical_type == "quarterly_earnings":
        return int(exposure_rules["company_wide_earnings_default"]), CatalystExposureBasis.COMPANY_WIDE, 1.0, "company_wide_earnings_default"
    if canonical_type == "formal_full_year_guidance_update":
        return int(exposure_rules["company_wide_guidance_default"]), CatalystExposureBasis.COMPANY_WIDE, 1.0, "company_wide_guidance_default"
    if inputs.company_wide is True:
        return 3, CatalystExposureBasis.COMPANY_WIDE, 1.0, "verified_company_wide_event"

    if inputs.is_biotech:
        if inputs.dominant_single_asset is True:
            return 3, CatalystExposureBasis.DOMINANT_SINGLE_ASSET, 1.0, "verified_dominant_single_asset"
        fraction = inputs.biotech_pipeline_value_fraction
        if fraction is None:
            return None, inputs.economic_exposure_basis, None, "missing_biotech_pipeline_value_fraction"
        if fraction >= float(exposure_rules["biotech_score_3_min_pipeline_value_fraction"]):
            score = 3
        elif fraction >= float(exposure_rules["biotech_score_2_min_pipeline_value_fraction"]):
            score = 2
        elif fraction >= float(exposure_rules["biotech_score_1_min_pipeline_value_fraction"]):
            score = 1
        else:
            score = 0
        return score, CatalystExposureBasis.BIOTECH_PIPELINE_VALUE, fraction, "biotech_pipeline_value_fraction"

    fraction = inputs.economic_exposure_fraction
    if fraction is None:
        return None, inputs.economic_exposure_basis, None, "missing_verified_economic_exposure_fraction"
    if fraction >= float(exposure_rules["score_3_min_fraction"]):
        score = 3
    elif fraction >= float(exposure_rules["score_2_min_fraction"]):
        score = 2
    elif fraction >= float(exposure_rules["score_1_min_fraction"]):
        score = 1
    else:
        score = 0
    return score, inputs.economic_exposure_basis, fraction, "verified_economic_exposure_fraction"


def _consequence_score(inputs: CatalystMaterialityInput, config: dict[str, Any], canonical_type: str) -> tuple[int | None, str]:
    consequence_rules = config["consequence_severity"]

    if canonical_type == "quarterly_earnings":
        if inputs.formal_guidance_action is True:
            return int(consequence_rules["earnings_with_formal_guidance_action"]), "earnings_with_formal_guidance_action"
        return int(consequence_rules["quarterly_earnings_default"]), "quarterly_earnings_default"

    if inputs.consequence_class is not None:
        return int(consequence_rules[inputs.consequence_class.value]), f"explicit_{inputs.consequence_class.value}"

    if canonical_type in _BINARY_DEFAULT_EVENTS:
        return int(consequence_rules["binary_permission_viability"]), "event_family_binary_default"
    if canonical_type in _MATERIAL_CHANGE_DEFAULT_EVENTS:
        return int(consequence_rules["material_estimate_or_execution_change"]), "event_family_material_change_default"
    if canonical_type in {"routine_presentation_no_new_data_expected", "administrative_or_unverifiable"}:
        return int(consequence_rules["informational"]), "event_family_informational_default"
    return None, "missing_consequence_class"


def assess_materiality(
    inputs: CatalystMaterialityInput,
    rules: dict[str, Any],
    *,
    rules_hash: str,
) -> CatalystMaterialityAssessment:
    config = _materiality_rules(rules)
    canonical_type = normalize_event_type(inputs.event_type)
    missing: list[str] = []
    reasons: list[str] = []

    if not inputs.verified:
        missing.append("verified_primary_evidence")
    if not inputs.source.strip():
        missing.append("source")
    if not inputs.source_url.strip():
        missing.append("source_url")

    base: int | None = None
    if canonical_type is None:
        missing.append("normalized_event_type")
    else:
        raw_base = config["event_class_base"].get(canonical_type)
        if raw_base is None:
            missing.append("event_class_base")
        else:
            base = int(raw_base)
            reasons.append(f"event_class_base:{canonical_type}={base}")

    exposure: int | None = None
    exposure_basis = inputs.economic_exposure_basis
    exposure_value: float | None = None
    consequence: int | None = None

    if canonical_type is not None:
        exposure, exposure_basis, exposure_value, exposure_reason = _exposure_score(inputs, config, canonical_type)
        if exposure is None:
            missing.append("economic_exposure")
        else:
            reasons.append(f"economic_exposure:{exposure_reason}={exposure}")

        consequence, consequence_reason = _consequence_score(inputs, config, canonical_type)
        if consequence is None:
            missing.append("consequence_severity")
        else:
            reasons.append(f"consequence_severity:{consequence_reason}={consequence}")

    candidate = bool(inputs.verified and base is not None and base > 0)
    if base == 0:
        reasons.append("base_zero_event_is_not_a_catalyst_candidate")

    materiality: int | None = None
    ready = bool(candidate and not missing and exposure is not None and consequence is not None)
    if ready and base is not None and exposure is not None and consequence is not None:
        materiality = score_materiality(base, exposure, consequence, maximum=int(config["maximum"]))
        reasons.append(f"materiality={base}+{exposure}+{consequence}->{materiality}")

    rule_path = "catalyst_v1_1.materiality.scored" if ready else "catalyst_v1_1.materiality.not_ready"
    if base == 0:
        rule_path = "catalyst_v1_1.materiality.administrative_reject"

    return CatalystMaterialityAssessment(
        model_version="SOE-1.1.0",
        rules_hash=rules_hash,
        ticker=inputs.ticker,
        event_id=inputs.event_id,
        event_family=inputs.event_family,
        event_type=canonical_type or inputs.event_type,
        event_class_base=base,
        economic_exposure_score=exposure,
        economic_exposure_basis=exposure_basis,
        economic_exposure_value=exposure_value,
        consequence_severity=consequence,
        materiality=materiality,
        materiality_ready=ready,
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
    )
