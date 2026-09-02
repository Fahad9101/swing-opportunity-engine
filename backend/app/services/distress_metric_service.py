from __future__ import annotations

from app.domain.distress_v1_1 import DistressInputs, DistressRawFacts


def derive_distress_inputs(facts: DistressRawFacts) -> DistressInputs:
    """Derive only normalized SOE-1.1 distress metrics.

    Missing inputs remain null. Incomplete liquid-asset disclosure is never
    converted to zero: cash alone may prove net cash when cash >= debt, but
    leverage, liquidity, and burn-runway arithmetic require a complete liquid-
    asset input.
    """

    if facts.liquid_assets_total is not None:
        liquid_assets = facts.liquid_assets_total
        liquid_assets_complete = True
    elif facts.cash is not None and facts.marketable_securities is not None:
        liquid_assets = facts.cash + facts.marketable_securities
        liquid_assets_complete = facts.liquid_assets_complete
    else:
        liquid_assets = facts.cash
        liquid_assets_complete = False

    net_cash = None
    net_debt_to_ebitda = None
    if facts.debt is not None and liquid_assets is not None:
        if liquid_assets >= facts.debt:
            # Cash alone can prove net cash even if unreported securities exist.
            net_cash = True
        elif liquid_assets_complete:
            net_cash = False
        if liquid_assets_complete and facts.ebitda is not None and facts.ebitda > 0:
            net_debt_to_ebitda = max(facts.debt - liquid_assets, 0.0) / facts.ebitda

    interest_coverage = None
    if facts.ebit is not None and facts.cash_interest_expense is not None and facts.cash_interest_expense > 0:
        interest_coverage = facts.ebit / facts.cash_interest_expense

    committed_liquidity = None
    if liquid_assets_complete and liquid_assets is not None and facts.committed_undrawn_revolver is not None:
        committed_liquidity = liquid_assets + facts.committed_undrawn_revolver + max(facts.trailing_fcf or 0.0, 0.0)

    liquidity_coverage = None
    if committed_liquidity is not None and facts.debt_maturities_12m is not None and facts.debt_maturities_12m > 0:
        liquidity_coverage = committed_liquidity / facts.debt_maturities_12m

    cash_runway_months = facts.cash_runway_months
    if (
        cash_runway_months is None
        and facts.trailing_fcf is not None
        and facts.trailing_fcf < 0
        and liquid_assets_complete
        and liquid_assets is not None
    ):
        annual_burn = abs(facts.trailing_fcf)
        if annual_burn > 0:
            cash_runway_months = 12.0 * liquid_assets / annual_burn

    audit = dict(facts.audit)
    audit.update(
        {
            "metric_derivation": "SOE-1.1 deterministic distress derivations",
            "liquid_assets": liquid_assets,
            "liquid_assets_complete": liquid_assets_complete,
            "leverage_suppressed_nonpositive_ebitda": facts.ebitda is not None and facts.ebitda <= 0,
            "leverage_suppressed_incomplete_liquid_assets": not liquid_assets_complete,
            "liquidity_suppressed_without_positive_12m_maturities": facts.debt_maturities_12m is None
            or facts.debt_maturities_12m <= 0,
        }
    )

    return DistressInputs(
        ticker=facts.ticker,
        sector_adapter=facts.sector_adapter,
        as_of=facts.as_of,
        hard_distress_flags=facts.hard_distress_flags,
        net_cash=net_cash,
        debt_outstanding=facts.debt,
        net_debt_to_ebitda=net_debt_to_ebitda,
        interest_coverage=interest_coverage,
        liquidity_coverage=liquidity_coverage,
        cash_runway_months=cash_runway_months,
        financing_secured=facts.financing_secured,
        debt_maturities_12m=facts.debt_maturities_12m,
        committed_liquidity=committed_liquidity,
        trailing_fcf=facts.trailing_fcf,
        debt_to_ebitdare=facts.debt_to_ebitdare,
        fixed_charge_coverage=facts.fixed_charge_coverage,
        regulatory_capital_breach=facts.regulatory_capital_breach,
        prompt_corrective_action_unresolved=facts.prompt_corrective_action_unresolved,
        cet1_ratio=facts.cet1_ratio,
        cet1_requirement_plus_buffer=facts.cet1_requirement_plus_buffer,
        insurer_solvency_ratio=facts.insurer_solvency_ratio,
        insurer_regulatory_action_threshold=facts.insurer_regulatory_action_threshold,
        sources=sorted(set(facts.sources)),
        audit=audit,
    )
