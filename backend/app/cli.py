from __future__ import annotations

import asyncio
import json

from app.orchestration.scan_pipeline import run_full_scan, scan_manager
from app.persistence.database import init_database


async def main() -> None:
    init_database()
    state = scan_manager.create()
    result = await run_full_scan(state.scan_run_id)
    report = {
        "scan_run_id": str(result.scan_run_id),
        "status": result.status,
        "model_version": result.model_version,
        "rules_hash": result.rules_hash,
        "universe_size": result.universe_count,
        "universal_passes": result.universal_pass_count,
        "technical_survivors": result.technical_survivor_count,
        "scanner_matches": result.scanner_match_counts,
        "scanner_data_incomplete": result.scanner_incomplete_counts,
        "candidate_count": len(result.opportunities),
        "fully_scored_count": result.fully_scored_count,
        "market_regime": result.market_regime.regime if result.market_regime else None,
        "breadth_available": result.market_regime.breadth_available if result.market_regime else False,
        "missing_data_rates": result.missing_data_rates,
        "provider_errors": result.provider_errors,
        "validation_issues": result.validation_issues,
        "errors": result.errors,
        "opportunities": [
            {
                "ticker": item.ticker,
                "primary_scanner": item.primary_scanner,
                "secondary_scanners": item.secondary_scanners,
                "opportunity_score": item.scores.opportunity_score,
                "components": {
                    "catalyst": item.scores.catalyst.score,
                    "fundamental": item.scores.fundamental.score,
                    "valuation": item.scores.valuation.score,
                    "technical": item.scores.technical.score,
                    "revisions": item.scores.revisions.score,
                    "balance_sheet": item.scores.balance_sheet.score,
                    "liquidity": item.scores.liquidity.score,
                },
                "data_completeness": item.data_completeness.model_dump(mode="json"),
            }
            for item in result.opportunities
        ],
    }
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
