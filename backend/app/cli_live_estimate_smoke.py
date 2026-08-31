from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

from app.core.config import load_rules
from app.providers.errors import ProviderError
from app.providers.yahoo_analyst import YahooAnalystEstimateProvider
from app.services.cache_service import JsonFileCache


DEFAULT_TICKERS = ("DELL", "AVGO", "FAST", "LUV", "ARWR")


async def run_smoke(tickers: tuple[str, ...] = DEFAULT_TICKERS) -> list[dict]:
    with tempfile.TemporaryDirectory(prefix="soe-yahoo-estimate-smoke-") as cache_dir:
        provider = YahooAnalystEstimateProvider(cache=JsonFileCache(Path(cache_dir)), rules=load_rules())
        results: list[dict] = []
        for ticker in tickers:
            try:
                estimate = await provider.get_estimates(ticker)
            except ProviderError as exc:
                results.append({"ticker": ticker, "status": "ERROR", "code": exc.code})
                continue
            if estimate is None:
                results.append({"ticker": ticker, "status": "NO_ESTIMATE"})
                continue
            results.append(
                {
                    "ticker": ticker,
                    "status": "OK",
                    "forward_eps_growth": estimate.forward_eps_growth,
                    "eps_up_revisions_30d": estimate.eps_up_revisions,
                    "eps_down_revisions_30d": estimate.eps_down_revisions,
                    "eps_revision_30d": estimate.eps_revision_30d,
                    "eps_revision_90d": estimate.eps_revision_90d,
                    "forward_revenue": estimate.forward_revenue,
                    "analyst_count": estimate.analyst_count,
                    "source": estimate.source,
                }
            )
        return results


def main() -> None:
    results = asyncio.run(run_smoke())
    print(json.dumps(results, indent=2, sort_keys=True))
    successful = [item for item in results if item["status"] == "OK"]
    if len(successful) < 2:
        raise SystemExit("Live Yahoo estimate smoke failed: fewer than two sample tickers returned usable estimates.")
    with_revision_counts = [
        item for item in successful
        if item["eps_up_revisions_30d"] is not None and item["eps_down_revisions_30d"] is not None
    ]
    if not with_revision_counts:
        raise SystemExit("Live Yahoo estimate smoke failed: no sample ticker exposed 30-day EPS revision counts.")


if __name__ == "__main__":
    main()
