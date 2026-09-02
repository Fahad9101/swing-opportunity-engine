from __future__ import annotations

from typing import Any

from app.domain.distress_v1_1 import (
    DistressAssessment,
    DistressClassification,
    DistressInputs,
    DistressSectorAdapter,
)


def _distress_rules(rules: dict[str, Any]) -> dict[str, Any]:
    config = rules.get("balance_sheet_distress_v1_1")
    if not isinstance(config, dict):
        raise ValueError("SOE-1.1 balance-sheet distress rules are missing")
    return config


def _sector_metrics(metrics: DistressInputs) -> dict[str, Any]:
    return {
        "net_cash": metrics.net_cash,
        "debt_outstanding": metrics.debt_outstanding,
        "trailing_fcf": metrics.trailing_fcf,
        "debt_to_ebitdare": metrics.debt_to_ebitdare,
        "fixed_charge_coverage": metrics.fixed_charge_coverage,
        "regulatory_capital_breach": metrics.regulatory_capital_breach,
        "prompt_corrective_action_unresolved": metrics.prompt_corrective_action_unresolved,
        "cet1_ratio": metrics.cet1_ratio,
        "cet1_requirement_plus_buffer": metrics.cet1_requirement_plus_buffer,
        "insurer_solvency_ratio": metrics.insurer_solvency_ratio,
        "insurer_regulatory_action_threshold": metrics.insurer_regulatory_action_threshold,
    }


def _result(
    metrics: DistressInputs,
    *,
    rules_hash: str,
    classification: DistressClassification,
    rule_path: str,
    reason: str,
) -> DistressAssessment:
    value = {
        DistressClassification.DISTRESSED: True,
        DistressClassification.NOT_DISTRESSED: False,
        DistressClassification.UNKNOWN: None,
    }[classification]
    return DistressAssessment(
        rules_hash=rules_hash,
        ticker=metrics.ticker,
        sector_adapter=metrics.sector_adapter,
        as_of=metrics.as_of,
        hard_distress_flags=metrics.hard_distress_flags,
        hard_flag_screen_complete=metrics.hard_flag_screen_complete,
        net_debt_to_ebitda=metrics.net_debt_to_ebitda,
        interest_coverage=metrics.interest_coverage,
        liquidity_coverage=metrics.liquidity_coverage,
        cash_runway_months=metrics.cash_runway_months,
        financing_secured=metrics.financing_secured,
        debt_maturities_12m=metrics.debt_maturities_12m,
        committed_liquidity=metrics.committed_liquidity,
        sector_specific_metrics=_sector_metrics(metrics),
        classification=classification,
        balance_sheet_distressed=value,
        rule_path=rule_path,
        reasons=[reason],
        sources=sorted(set(metrics.sources)),
        audit=dict(metrics.audit),
    )


def _unknown(metrics: DistressInputs, rules_hash: str, path: str, reason: str) -> DistressAssessment:
    return _result(
        metrics,
        rules_hash=rules_hash,
        classification=DistressClassification.UNKNOWN,
        rule_path=path,
        reason=reason,
    )


def _safe_result(metrics: DistressInputs, rules_hash: str, path: str, reason: str) -> DistressAssessment:
    if not metrics.hard_flag_screen_complete:
        return _unknown(
            metrics,
            rules_hash,
            "balance_sheet_distress_v1_1.hard_flag_screen_incomplete",
            "A numerically safe path was present, but the required recent primary-source hard-distress screen was not completed.",
        )
    return _result(
        metrics,
        rules_hash=rules_hash,
        classification=DistressClassification.NOT_DISTRESSED,
        rule_path=path,
        reason=reason,
    )


def classify_distress(metrics: DistressInputs, rules: dict[str, Any], *, rules_hash: str) -> DistressAssessment:
    """Pure SOE-1.1 sector-aware distress classifier.

    Missing evidence never becomes a favorable value. Positive distress can be
    classified from verified adverse evidence, but NOT_DISTRESSED requires both
    a frozen safety path and a completed recent primary-source hard-flag screen.
    """
    config = _distress_rules(rules)

    if not metrics.sources:
        return _unknown(
            metrics,
            rules_hash,
            "balance_sheet_distress_v1_1.missing_provenance",
            "Primary-source provenance is required for a non-null distress classification.",
        )

    hard_rules = config.get("universal_hard_overrides", {})
    active = [flag for flag in metrics.hard_distress_flags if hard_rules.get(flag.value) is True]
    if active:
        return _result(
            metrics,
            rules_hash=rules_hash,
            classification=DistressClassification.DISTRESSED,
            rule_path="balance_sheet_distress_v1_1.universal_hard_override",
            reason="Verified hard-distress condition: " + ", ".join(flag.value for flag in active),
        )

    dispatch = {
        DistressSectorAdapter.CORPORATE: (_classify_corporate, "corporate"),
        DistressSectorAdapter.UTILITY: (_classify_utility, "utilities"),
        DistressSectorAdapter.REIT: (_classify_reit, "reits"),
        DistressSectorAdapter.BANK: (_classify_bank, "banks"),
        DistressSectorAdapter.INSURER: (_classify_insurer, "insurers"),
    }
    classifier, rule_key = dispatch[metrics.sector_adapter]
    return classifier(metrics, config[rule_key], rules_hash)


def _classify_corporate(metrics: DistressInputs, rules: dict[str, Any], rules_hash: str) -> DistressAssessment:
    bad = rules["distressed"]
    safe = rules["safe"]

    if (
        metrics.net_debt_to_ebitda is not None
        and metrics.interest_coverage is not None
        and metrics.net_debt_to_ebitda > bad["net_debt_to_ebitda_gt"]
        and metrics.interest_coverage < bad["paired_interest_coverage_lt"]
    ):
        return _result(metrics, rules_hash=rules_hash, classification=DistressClassification.DISTRESSED, rule_path="balance_sheet_distress_v1_1.corporate.high_leverage_low_coverage", reason="Net debt/EBITDA and interest coverage satisfy the frozen corporate distress pair.")

    if (
        metrics.debt_outstanding is not None
        and metrics.debt_outstanding > 0
        and metrics.interest_coverage is not None
        and metrics.interest_coverage < bad["interest_coverage_absolute_lt"]
    ):
        return _result(metrics, rules_hash=rules_hash, classification=DistressClassification.DISTRESSED, rule_path="balance_sheet_distress_v1_1.corporate.absolute_interest_coverage", reason="Interest coverage is below the frozen absolute corporate threshold with debt outstanding.")

    if metrics.liquidity_coverage is not None and metrics.liquidity_coverage < bad["liquidity_coverage_lt"] and metrics.financing_secured is not True:
        return _result(metrics, rules_hash=rules_hash, classification=DistressClassification.DISTRESSED, rule_path="balance_sheet_distress_v1_1.corporate.liquidity_shortfall", reason="Verified 12-month liquidity coverage is below 1.0 and refinancing is not verified secured.")

    if (
        metrics.trailing_fcf is not None
        and metrics.trailing_fcf < 0
        and metrics.cash_runway_months is not None
        and metrics.cash_runway_months < bad["negative_fcf_runway_months_lt"]
        and metrics.financing_secured is not True
    ):
        return _result(metrics, rules_hash=rules_hash, classification=DistressClassification.DISTRESSED, rule_path="balance_sheet_distress_v1_1.corporate.negative_fcf_short_runway", reason="Negative-FCF runway is below 12 months without verified secured financing.")

    if safe.get("net_cash") is True and metrics.net_cash is True:
        return _safe_result(metrics, rules_hash, "balance_sheet_distress_v1_1.corporate.net_cash_safe", "Verified net-cash position satisfies the frozen corporate safety path.")

    if (
        metrics.net_debt_to_ebitda is not None
        and metrics.interest_coverage is not None
        and metrics.net_debt_to_ebitda <= safe["net_debt_to_ebitda_lte"]
        and metrics.interest_coverage >= safe["paired_interest_coverage_gte"]
    ):
        return _safe_result(metrics, rules_hash, "balance_sheet_distress_v1_1.corporate.leverage_coverage_safe", "Net debt/EBITDA and interest coverage satisfy the frozen corporate safety pair.")

    if (
        metrics.liquidity_coverage is not None
        and metrics.liquidity_coverage >= safe["liquidity_coverage_gte"]
        and metrics.trailing_fcf is not None
        and metrics.trailing_fcf > 0
    ):
        return _safe_result(metrics, rules_hash, "balance_sheet_distress_v1_1.corporate.liquidity_fcf_safe", "Verified liquidity coverage is at least 1.5x and trailing FCF is positive.")

    if (
        metrics.trailing_fcf is not None
        and metrics.trailing_fcf < 0
        and metrics.cash_runway_months is not None
        and metrics.cash_runway_months >= safe["negative_fcf_runway_months_gte"]
    ):
        return _safe_result(metrics, rules_hash, "balance_sheet_distress_v1_1.corporate.negative_fcf_runway_safe", "Negative-FCF runway meets the frozen 18-month safety threshold.")

    return _unknown(metrics, rules_hash, "balance_sheet_distress_v1_1.corporate.unknown", "Corporate evidence is insufficient for a frozen distress or safety path.")


def _classify_utility(metrics: DistressInputs, rules: dict[str, Any], rules_hash: str) -> DistressAssessment:
    bad = rules["distressed"]
    safe = rules["safe"]
    if (
        metrics.net_debt_to_ebitda is not None
        and metrics.interest_coverage is not None
        and metrics.net_debt_to_ebitda > bad["net_debt_to_ebitda_gt"]
        and metrics.interest_coverage < bad["paired_interest_coverage_lt"]
    ):
        return _result(metrics, rules_hash=rules_hash, classification=DistressClassification.DISTRESSED, rule_path="balance_sheet_distress_v1_1.utilities.high_leverage_low_coverage", reason="Utility leverage and coverage satisfy the frozen distress pair.")
    if metrics.liquidity_coverage is not None and metrics.liquidity_coverage < bad["liquidity_coverage_lt"] and metrics.financing_secured is not True:
        return _result(metrics, rules_hash=rules_hash, classification=DistressClassification.DISTRESSED, rule_path="balance_sheet_distress_v1_1.utilities.liquidity_shortfall", reason="Utility liquidity coverage is below 1.0 without verified secured refinancing.")
    if (
        metrics.net_debt_to_ebitda is not None
        and metrics.interest_coverage is not None
        and metrics.net_debt_to_ebitda <= safe["net_debt_to_ebitda_lte"]
        and metrics.interest_coverage >= safe["paired_interest_coverage_gte"]
    ):
        return _safe_result(metrics, rules_hash, "balance_sheet_distress_v1_1.utilities.leverage_coverage_safe", "Utility leverage and coverage satisfy the frozen safety pair.")
    return _unknown(metrics, rules_hash, "balance_sheet_distress_v1_1.utilities.unknown", "Utility evidence is insufficient for a frozen distress or safety path.")


def _classify_reit(metrics: DistressInputs, rules: dict[str, Any], rules_hash: str) -> DistressAssessment:
    bad = rules["distressed"]
    safe = rules["safe"]
    if (
        metrics.debt_to_ebitdare is not None
        and metrics.fixed_charge_coverage is not None
        and metrics.debt_to_ebitdare > bad["debt_to_ebitdare_gt"]
        and metrics.fixed_charge_coverage < bad["paired_fixed_charge_coverage_lt"]
    ):
        return _result(metrics, rules_hash=rules_hash, classification=DistressClassification.DISTRESSED, rule_path="balance_sheet_distress_v1_1.reits.high_leverage_low_fixed_charge_coverage", reason="REIT debt/EBITDAre and fixed-charge coverage satisfy the frozen distress pair.")
    if metrics.liquidity_coverage is not None and metrics.liquidity_coverage < bad["liquidity_coverage_lt"] and metrics.financing_secured is not True:
        return _result(metrics, rules_hash=rules_hash, classification=DistressClassification.DISTRESSED, rule_path="balance_sheet_distress_v1_1.reits.liquidity_shortfall", reason="REIT liquidity coverage is below 1.0 without verified secured refinancing.")
    if (
        metrics.debt_to_ebitdare is not None
        and metrics.fixed_charge_coverage is not None
        and metrics.debt_to_ebitdare <= safe["debt_to_ebitdare_lte"]
        and metrics.fixed_charge_coverage >= safe["paired_fixed_charge_coverage_gte"]
    ):
        return _safe_result(metrics, rules_hash, "balance_sheet_distress_v1_1.reits.leverage_coverage_safe", "REIT debt/EBITDAre and fixed-charge coverage satisfy the frozen safety pair.")
    return _unknown(metrics, rules_hash, "balance_sheet_distress_v1_1.reits.unknown", "REIT evidence is insufficient for a frozen distress or safety path.")


def _classify_bank(metrics: DistressInputs, rules: dict[str, Any], rules_hash: str) -> DistressAssessment:
    if rules.get("distressed_if_regulatory_capital_breach") is True and (
        metrics.regulatory_capital_breach is True or metrics.prompt_corrective_action_unresolved is True
    ):
        return _result(metrics, rules_hash=rules_hash, classification=DistressClassification.DISTRESSED, rule_path="balance_sheet_distress_v1_1.banks.regulatory_capital_breach", reason="Primary regulatory evidence shows a capital breach or unresolved prompt-corrective-action condition.")

    ratio = metrics.cet1_ratio
    requirement = metrics.cet1_requirement_plus_buffer
    if ratio is not None and requirement is not None:
        if ratio < requirement:
            return _result(metrics, rules_hash=rules_hash, classification=DistressClassification.DISTRESSED, rule_path="balance_sheet_distress_v1_1.banks.cet1_below_requirement", reason="CET1 is below the institution-specific requirement plus buffer.")
        required_safe_ratio = requirement + rules["safe_cet1_excess_over_requirement_and_buffer_bps_gte"] / 10_000.0
        if ratio >= required_safe_ratio:
            assessment = _safe_result(metrics, rules_hash, "balance_sheet_distress_v1_1.banks.cet1_excess_safe", "CET1 exceeds the applicable requirement plus buffer by at least the frozen 250 bps margin.")
            if assessment.classification is DistressClassification.NOT_DISTRESSED:
                assessment.audit["cet1_excess_bps"] = (ratio - requirement) * 10_000.0
            return assessment

    return _unknown(metrics, rules_hash, "balance_sheet_distress_v1_1.banks.unknown", "Bank regulatory-capital evidence is insufficient for a frozen distress or safety path.")


def _classify_insurer(metrics: DistressInputs, rules: dict[str, Any], rules_hash: str) -> DistressAssessment:
    ratio = metrics.insurer_solvency_ratio
    threshold = metrics.insurer_regulatory_action_threshold
    if ratio is not None and threshold is not None and threshold > 0:
        if rules.get("distressed_below_regulatory_action_threshold") is True and ratio < threshold:
            return _result(metrics, rules_hash=rules_hash, classification=DistressClassification.DISTRESSED, rule_path="balance_sheet_distress_v1_1.insurers.below_regulatory_action_threshold", reason="Insurer solvency/RBC ratio is below the applicable regulatory action threshold.")
        ratio_to_threshold = ratio / threshold
        if ratio_to_threshold >= rules["safe_ratio_to_regulatory_action_threshold_gte"]:
            assessment = _safe_result(metrics, rules_hash, "balance_sheet_distress_v1_1.insurers.solvency_margin_safe", "Insurer solvency/RBC ratio is at least 1.5x the applicable regulatory action threshold.")
            if assessment.classification is DistressClassification.NOT_DISTRESSED:
                assessment.audit["ratio_to_regulatory_action_threshold"] = ratio_to_threshold
            return assessment

    return _unknown(metrics, rules_hash, "balance_sheet_distress_v1_1.insurers.unknown", "Insurer regulatory-solvency evidence is insufficient for a frozen distress or safety path.")
