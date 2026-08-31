from __future__ import annotations

import asyncio
import json
from typing import Any

from app.core.config import load_rules
from app.providers.errors import ProviderError
from app.providers.provider_registry import get_provider
from app.scoring.balance_sheet_score import score_balance_sheet
from app.scoring.biotech_fundamental_score import score_biotech_fundamentals
from app.scoring.catalyst_score import score_catalyst
from app.scoring.fundamental_score import score_fundamentals
from app.scoring.liquidity_score import score_liquidity
from app.scoring.opportunity_score import calculate_opportunity_score
from app.scoring.penalties import build_penalties
from app.scoring.revision_score import score_revisions
from app.scoring.technical_score import score_technical
from app.scoring.valuation_score import score_valuation
from app.screeners.biotech_catalyst import BiotechCatalystScreener
from app.screeners.growth_pullback import GrowthPullbackScreener
from app.screeners.rerating import ReratingScreener
from app.services.technical_service import build_market_snapshot
from app.services.universe_service import passes_universal_gate


DEFAULT_TICKERS = ("DELL", "AVGO", "FAST", "LUV", "ARWR")


def _score_dump(component) -> dict[str, Any]:
    return {
        "score": component.score,
        "maximum": component.maximum,
        "available": component.available,
        "available_points": component.available_points,
        "components": component.components,
    }


async def audit(tickers: tuple[str, ...] = DEFAULT_TICKERS) -> list[dict[str, Any]]:
    rules = load_rules()
    provider = get_provider("free_public")
    instruments = await provider.list_instruments()
    by_ticker = {item.ticker: item for item in instruments}
    screeners = (ReratingScreener(), GrowthPullbackScreener(), BiotechCatalystScreener())
    output: list[dict[str, Any]] = []

    for ticker in tickers:
        instrument = by_ticker.get(ticker)
        if instrument is None:
            output.append({"ticker": ticker, "status": "NOT_IN_UNIVERSE"})
            continue
        try:
            bars = await provider.get_ohlcv(ticker)
            market = build_market_snapshot(ticker, bars, provider.name, rules)
            gate = passes_universal_gate(instrument, market, rules)
            fundamental = await provider.get_fundamentals(ticker) if gate.passed else None
            estimates = await provider.get_estimates(ticker) if gate.passed else None
            catalysts = await provider.get_catalysts(ticker) if gate.passed else None
            matches = [
                screener.evaluate(instrument, market, fundamental, estimates, catalysts, rules)
                for screener in screeners
            ] if gate.passed else []
            qualified = [match for match in matches if match.qualified]

            penalties = build_penalties(fundamental.raw.get("penalty_flags", []), rules) if fundamental else []
            penalty_points = sum(item.points for item in penalties)
            scores: dict[str, Any] | None = None
            if qualified:
                fundamental_component = (
                    score_biotech_fundamentals(fundamental)
                    if instrument.is_biotech
                    else score_fundamentals(fundamental)
                )
                components = {
                    "catalyst": score_catalyst(catalysts or []),
                    "fundamental": fundamental_component,
                    "valuation": score_valuation(fundamental),
                    "technical": score_technical(market, rules),
                    "revisions": score_revisions(estimates),
                    "balance_sheet": score_balance_sheet(instrument, fundamental),
                    "liquidity": score_liquidity(market, fundamental),
                }
                total = calculate_opportunity_score(components, penalty_points, len(qualified))
                scores = {
                    "components": {name: _score_dump(component) for name, component in components.items()},
                    "penalty_points": penalty_points,
                    "penalties": [penalty.model_dump(mode="json") for penalty in penalties],
                    "base_opportunity_score": total.base_opportunity_score,
                    "multi_scanner_bonus": total.multi_scanner_bonus,
                    "opportunity_score": total.opportunity_score,
                }

            output.append(
                {
                    "ticker": ticker,
                    "status": "OK",
                    "company": instrument.company_name,
                    "market_cap": instrument.market_cap,
                    "is_biotech": instrument.is_biotech,
                    "gate": {"passed": gate.passed, "rejection_codes": gate.rejection_codes},
                    "market": {
                        "price": market.price,
                        "sma50": market.sma50,
                        "sma200": market.sma200,
                        "rsi14": market.rsi14,
                        "pullback_from_50d_high_pct": market.pullback_from_50d_high_pct,
                        "avg_dollar_volume_20d": market.avg_dollar_volume_20d,
                    },
                    "fundamental": None if fundamental is None else {
                        "revenue_growth": fundamental.revenue_growth,
                        "revenue_growth_qoq": fundamental.revenue_growth_qoq,
                        "operating_margin": fundamental.operating_margin,
                        "operating_margin_prior": fundamental.operating_margin_prior,
                        "operating_margin_expansion_bps": fundamental.operating_margin_expansion_bps,
                        "fcf_growth": fundamental.fcf_growth,
                        "cash_runway_months": fundamental.cash_runway_months,
                        "institutional_ownership": fundamental.institutional_ownership,
                        "short_float": fundamental.short_float,
                        "penalty_flags": fundamental.raw.get("penalty_flags", []),
                    },
                    "estimates": None if estimates is None else {
                        "forward_eps_growth": estimates.forward_eps_growth,
                        "eps_up_revisions": estimates.eps_up_revisions,
                        "eps_down_revisions": estimates.eps_down_revisions,
                        "eps_revision_30d": estimates.eps_revision_30d,
                        "eps_revision_90d": estimates.eps_revision_90d,
                        "forward_revenue": estimates.forward_revenue,
                        "analyst_count": estimates.analyst_count,
                    },
                    "scanner_matches": [match.model_dump(mode="json") for match in matches],
                    "qualified_scanners": [match.scanner.value for match in qualified],
                    "scores": scores,
                }
            )
        except ProviderError as exc:
            output.append({"ticker": ticker, "status": "PROVIDER_ERROR", "error": exc.as_dict()})
        except Exception as exc:  # diagnostic CLI: preserve per-ticker isolation
            output.append({"ticker": ticker, "status": "ERROR", "error": str(exc)})
    return output


def main() -> None:
    results = asyncio.run(audit())
    print(json.dumps(results, indent=2, sort_keys=True))
    usable = [row for row in results if row.get("status") == "OK" and row.get("gate", {}).get("passed")]
    if len(usable) < 3:
        raise SystemExit("Targeted live scanner audit failed: fewer than three sample tickers passed the universal gate with usable real data.")
    if not all(row.get("fundamental", {}).get("institutional_ownership") is not None for row in usable):
        raise SystemExit("Targeted live scanner audit failed: ownership enrichment did not reach every usable sample fundamental record.")


if __name__ == "__main__":
    main()
