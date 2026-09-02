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


def _assessment(
    metrics: DistressInputs,
    *,
    rules_hash: str,
    classification: DistressClassification,
    rule_path: str,
    reasons: list[str],
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
        reasons=reasons,
        sources=sorted(set(metrics.sources)),
        audit=dict(metrics.audit),
    )


def _unknown(metrics: DistressInputs, rules_hash: str, reason: str, path: str) -> DistressAssessment:
    return _assessment(
        metrics,
        rules_hash=rules_hash,
        classification=DistressClassification.UNKNOWN,
        rule_path=path,
        reasons=[reason],
    )


def classify_distress(metrics: DistressInputs, rules: dict[str, Any], *, rules_hash: str) -> DistressAssessment:
    """Classify balance-sheet distress using only SOE-1.1 deterministic rules.

    The function is intentionally pure: it performs no network access and does
    not infer missing evidence. NOT_DISTRESSED is a positive-evidence state.
    """

    config = _distress_rules(rules)
    if not metrics.sources:
        return _unknown(
            metrics,
            rules_hash,
            "Primary-source provenance is required for a non-null distress classification.",
            "balance_sheet_distress_v1_1.missing_provenance",
        )

    hard_rules = config.get("universal_hard_overrides", {})
    active_hard_flags = [
        flag for flag in metrics.hard_distress_flags if hard_rules.get(flag.value) is True
    ]
    if active_hard_flags:
        return _assessment(
            metrics,
            rules_hash=rules_hash,
            classification=DistressClassification.DISTRESSED,
            rule_path="balance_sheet_distress_v1_1.universal_hard_override",
            reasons=["Verified hard-distress condition: " + ", ".join(flag.value for flag in active_hard_flags)],
        )

    if metrics.sector_adapter is DistressSectorAdapter.CORPORATE:
        return _classify_corporate(metrics, config["corporate"], rules_hash)
    if metrics.sector_adapter is DistressSectorAdapter.UTILITY:
        return _classify_utility(metrics, config["utilities"], rules_hash)
    if metrics.sector_adapter is DistressSectorAdapter.REIT:
        return _classify_reit(metrics, config["reits"], rules_hash)
    if metrics.sector_adapter is DistressSectorAdapter.BANK:
        return _classify_bank(metrics, config["banks"], rules_hash)
    if metrics.sector_adapter is DistressSectorAdapter.INSURER:
        return _classify_insurer(metrics, config["insurers"], rules_hash)

    return _unknown(
        metrics,
        rules_hash,
        "No deterministic sector adapter is available.",
        "balance_sheet_distress_v1_1.unsupported_adapter",
    )


def _classify_corporate(metrics: DistressInputs, rules: dict[str, Any], rules_hash: str) -> DistressAssessment:
    distressed = rules["distressed"]
    safe = rules["safe"]

    if (
        metrics.net_debt_to_ebitda is not None
        and metrics.interest_coverage is not None
        and metrics.net_debt_to_ebitda > distressed["net_debt_to_ebitda_gt"]
        and metrics.interest_coverage < distressed["paired_interest_coverage_lt"]
    ):
        return _assessment(
            metrics,
            rules_hash=rules_hash,
            classification=DistressClassification.DISTRESSED,
            rule_path="balance_sheet_distress_v1_1.corporate.high_leverage_low_coverage",
            reasons=["Net debt/EBITDA and interest coverage satisfy the frozen corporate distress pair."],
        )

    if (
        metrics.debt_outstanding is not None
        and metrics.debt_outstanding > 0
        and metrics.interest_coverage is not None
        and metrics.interest_coverage < distressed["interest_coverage_absolute_lt"]
    ):
        return _assessment(
            metrics,
            rules_hash=rules_hash,
            classification=DistressClassification.DISTRESSED,
            rule_path="balance_sheet_distress_v1_1.corporate.absolute_interest_coverage",
            reasons=["Interest coverage is below the frozen absolute corporate distress threshold with debt outstanding."],
        )

    if metrics.liquidity_coverage is not None and metrics.liquidity_coverage < distressed["liquidity_coverage_lt"] and metrics.financing_secured is not True:
        return _assessment(
            metrics,
            rules_hash=rules_hash,
            classification=DistressClassification.DISTRESSED,
            rule_path="balance_sheet_distress_v1_1.corporate.liquidity_shortfall",
            reasons=["Verified 12-month liquidity coverage is below 1.0 and refinancing is not verified secured."],
        )

    if (
        metrics.trailing_fcf is not None
        and metrics.trailing_fcf < 0
        and metrics.cash_runway_months is not None
        and metrics.cash_runway_months < distressed["negative_fcf_runway_months_lt"]
        and metrics.financing_secured is not True
    ):
        return _assessment(
            metrics,
            rules_hash=rules_hash,
            classification=DistressClassification.DISTRESSED,
            rule_path="balance_sheet_distress_v1_1.corporate.negative_fcf_short_runway",
            reasons=["Negative-FCF cash runway is below the frozen 12-month distress threshold without verified secured financing."],
        )

    if safe.get("net_cash") is True and metrics.net_cash is True:
        return _assessment(
            metrics,
            rules_hash=rules_hash,
            classification=DistressClassification.NOT_DISTRESSED,
            rule_path="balance_sheet_distress_v1_1.corporate.net_cash_safe",
            reasons=["Verified net-cash position satisfies the frozen corporate safety path."],
        )

    if (
        metrics.net_debt_to_ebitda is not None
        and metrics.interest_coverage is not None
        and metrics.net_debt_to_ebitda <= safe["net_debt_to_ebitda_lte"]
        and metrics.interest_coverage >= safe["paired_interest_coverage_gte"]
    ):
        return _assessment(
            metrics,
            rules_hash=rules_hash,
            classification=DistressClassification.NOT_DISTRESSED,
            rule_path="balance_sheet_distress_v1_1.corporate.leverage_coverage_safe",
            reasons=["Net debt/EBITDA and interest coverage satisfy the frozen corporate safety pair."],
        )

    if (
        metrics.liquidity_coverage is not None
        and metrics.liquidity_coverage >= safe["liquidity_coverage_gte"]
        and metrics.trailing_fcf is not None
        and metrics.trailing_fcf > 0
    ):
        return _assessment(
            metrics,
            rules_hash=rules_hash,
            classification=DistressClassification.NOT_DISTRESSED,
            rule_path="balance_sheet_distress_v1_1.corporate.liquidity_fcf_safe",
            reasons=["Verified liquidity coverage is at least 1.5x and trailing FCF is positive."],
        )

    if (
        metrics.trailing_fcf is not None
        and metrics.trailing_fcf < 0
        and metrics.cash_runway_months is not None
        and metrics.cash_runway_months >= safe["negative_fcf_runway_months_gte"]
    ):
        return _assessment(
            metrics,
            rules_hash=rules_hash,
            classification=DistressClassification.NOT_DISTRESSED,
            rule_path="balance_sheet_distress_v1_1.corporate.negative_fcf_runway_safe",
            reasons=["Negative-FCF cash runway meets the frozen 18-month safety threshold."],
        )

    return _unknown(
        metrics,
        rules_hash,
        "Corporate distress evidence is insufficient for either a frozen distress or safety path.",
        "balance_sheet_distress_v1_1.corporate.unknown",
    )


def _classify_utility(metrics: DistressInputs, rules: dict[str, Any], rules_hash: str) -> DistressAssessment:
    distressed = rules["distressed"]
    safe = rules["safe"]
    if (
        metrics.net_debt_to_ebitda is not None
        and metrics.interest_coverage is not None
        and metrics.net_debt_to_ebitda > distressed["net_debt_to_ebitda_gt"]
        and metrics.interest_coverage < distressed["paired_interest_coverage_lt"]
    ):
        return _assessment(metrics, rules_hash=rules_hash, classification=DistressClassification.DISTRESSED, rule_path="balance_sheet_distress_v1_1.utilities.high_leverage_low_coverage", reasons=["Utility leverage and coverage satisfy the frozen distress pair."])
    if metrics.liquidity_coverage is not None and metrics.liquidity_coverage < distressed["liquidity_coverage_lt"] and metrics.financing_secured is not True:
        return _assessment(metrics, rules_hash=rules_hash, classification=DistressClassification.DISTRESSED, rule_path="balance_sheet_distress_v1_1.utilities.liquidity_shortfall", reasons=["Utility liquidity coverage is below 1.0 without verified secured refinancing."])
    if (
        metrics.net_debt_to_ebitda is not None
        and metrics.interest_coverage is not None
        and metrics.net_debt_to_ebitda <= safe["net_debt_to_ebitda_lte"]
        and metrics.interest_coverage >= safe["paired_interest_coverage_gte"]
    ):
        return _assessment(metrics, rules_hash=rules_hash, classification=DistressClassification.NOT_DISTRESSED, rule_path="balance_sheet_distress_v1_1.utilities.leverage_coverage_safe", reasons=["Utility leverage and coverage satisfy the frozen safety pair."])
    return _unknown(metrics, rules_hash, "Utility distress evidence is insufficient for a frozen distress or safety path.", "balance_sheet_distress_v1_1.utilities.unknown")


def _classify_reit(metrics: DistressInputs, rules: dict[str, Any], rules_hash: str) -> DistressAssessment:
    distressed = rules["distressed"]
    safe = rules["safe"]
    if (
        metrics.debt_to_ebitdare is not None
        and metrics.fixed_charge_coverage is not None
        and metrics.debt_to_ebitdare > distressed["debt_to_ebitdare_gt"]
        and metrics.fixed_charge_coverage < distressed["paired_fixed_charge_coverage_lt"]
    ):
        return _assessment(metrics, rules_hash=rules_hash, classification=DistressClassification.DISTRESSED, rule_path="balance_sheet_distress_v1_1.reits.high_leverage_low_fixed_charge_coverage", reasons=["REIT debt/EBITDAre and fixed-charge coverage satisfy the frozen distress pair."])
    if metrics.liquidity_coverage is not None and metrics.liquidity_coverage < distressed["liquidity_coverage_lt"] and metrics.financing_secured is not True:
        return _assessment(metrics, rules_hash=rules_hash, classification=DistressClassification.DISTRESSED, rule_path="balance_sheet_distress_v1_1.reits.liquidity_shortfall", reasons=["REIT liquidity coverage is below 1.0 without verified secured refinancing."])
    if (
        metrics.debt_to_ebitdare is not None
        and metrics.fixed_charge_coverage is not None
        and metrics.debt_to_ebitdare <= safe["debt_to_ebitdare_lte"]
        and metrics.fixed_charge_coverage >= safe["paired_fixed_charge_coverage_gte"]
    ):
        return _assessment(metrics, rules_hash=rules_hash, classification=DistressClassification.NOT_DISTRESSED, rule_path="balance_sheet_distress_v1_1.reits.leverage_coverage_safe", reasons=["REIT debt/EBITDAre and fixed-charge coverage satisfy the frozen safety pair."])
    return _unknown(metrics, rules_hash, "REIT distress evidence is insufficient for a frozen distress or safety path.", "balance_sheet_distress_v1_1.reits.unknown")


def _classify_bank(metrics: DistressInputs, rules: dict[str, Any], rules_hash: str) -> DistressAssessment:
    if rules.get("distressed_if_regulatory_capital_breach") is True and (
        metrics.regulatory_capital_breach is True or metrics.prompt_corrective_action_unresolved is True
    ):
        return _assessment(metrics, rules_hash=rules_hash, classification=DistressClassification.DISTRESSED, rule_path="balance_sheet_distress_v1_1.banks.regulatory_capital_breach", reasons=["Primary regulatory evidence shows a capital breach or unresolved prompt-corrective-action condition."])

    if metrics.cet1_ratio is not None and metrics.cet1_requirement_plus_buffer is not None:
        if metrics.cet1_ratio < metrics.cet1_requirement_plus_buffer:
            return _assessment(metrics, rules_hash=rules_hash, classification=DistressClassification.DISTRESSED, rule_path="balance_sheet_distress_v1_1.banks.cet1_below_requirement", reasons=["CET1 is below the institution-specific requirement plus buffer."])
        excess_bps = (metrics.cet1_ratio - metrics.cet1_requirement_plus_buffer) * 10_000
        if excess_bps >= rules["safe_cet1_excess_over_requirement_and_buffer_bps_gte"]:
            assessment = _assessment(metrics, rules_hash=rules_hash, classification=DistressClassification.NOT_DISTRESSED, rule_path="balance_sheet_distress_v1_1.banks.cet1_excess_safe", reasons=["CET1 exceeds the applicable requirement plus buffer by at least the frozen 250 bps margin."])
            assessment.audit["cet1_excess_bps"] = excess_bps
            return assessment

    return _unknown(metrics, rules_hash, "Bank regulatory-capital evidence is insufficient for a frozen distress or safety path.", "balance_sheet_distress_v1_1.banks.unknown")


def _classify_insurer(metrics: DistressInputs, rules: dict[str, Any], rules_hash: str) -> DistressAssessment:
    ratio = metrics.insurer_solvency_ratio
    threshold = metrics.insurer_regulatory_action_threshold
    if ratio is not None and threshold is not None and threshold > 0:
        if rules.get("distressed_below_regulatory_action_threshold") is True and ratio < threshold:
            return _assessment(metrics, rules_hash=rules_hash, classification=DistressClassification.DISTRESSED, rule_path="balance_sheet_distress_v1_1.insurers.below_regulatory_action_threshold", reasons=["Insurer solvency/RBC ratio is below the applicable regulatory action threshold."])
        ratio_to_threshold = ratio / threshold
        if ratio_to_threshold >= rules["safe_ratio_to_regulatory_action_threshold_gte"]:
            assessment = _assessment(metrics, rules_hash=rules_hash, classification=DistressClassification.NOT_DISTRESSED, rule_path="balance_sheet_distress_v1_1.insurers.solvency_margin_safe", reasons=["Insurer solvency/RBC ratio is at least 1.5x the applicable regulatory action threshold."])
            assessment.audit["ratio_to_regulatory_action_threshold"] = ratio_to_threshold
            return assessment

    return _unknown(metrics, rules_hash, "Insurer regulatory-solvency evidence is insufficient for a frozen distress or safety path.", "balance_sheet_distress_v1_1.insurers.unknown")
