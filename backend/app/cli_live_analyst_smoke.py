from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

from app.core.config import load_rules
from app.providers.errors import ProviderError
from app.providers.nasdaq_analyst import NasdaqAnalystEstimateProvider
from app.services.cache_service import JsonFileCache


DEFAULT_TICKERS = ("DELL", "AVGO", "FAST", "LUV", "ARWR")


async def run_smoke(tickers: tuple[str, ...] = DEFAULT_TICKERS) -> list[dict]:
    rules = load_rules()
    with tempfile.TemporaryDirectory(prefix="soe-nasdaq-smoke-") as cache_dir:
        provider = NasdaqAnalystEstimateProvider(cache=JsonFileCache(Path(cache_dir)), rules=rules)
        results: list[dict] = []
        for ticker in tickers:
            try:
                estimate = await provider.get_estimates(ticker)
            except ProviderError as exc:
                results.append({"ticker": ticker, "status": "ERROR", "code": exc.code})
                continue
            if estimate is None:
                results.append({"ticker": ticker, "status": "NO_FORECAST"})
                continue
            results.append(
                {
                    "ticker": ticker,
                    "status": "OK",
                    "forward_eps_growth": estimate.forward_eps_growth,
                    "analyst_count": estimate.analyst_count,
                    "eps_up_revisions": estimate.eps_up_revisions,
                    "eps_down_revisions": estimate.eps_down_revisions,
                    "source": estimate.source,
                }
            )
        return results


def main() -> None:
    results = asyncio.run(run_smoke())
    print(json.dumps(results, indent=2, sort_keys=True))
    successful = [item for item in results if item["status"] == "OK"]
    if len(successful) < 2:
        raise SystemExit("Live Nasdaq analyst smoke failed: fewer than two sample tickers returned usable forecasts.")
    # Revision history is not supplied by this adapter; protect the missing-data contract.
    if any(item["eps_up_revisions"] is not None or item["eps_down_revisions"] is not None for item in successful):
        raise SystemExit("Live Nasdaq analyst smoke failed: revision counts were unexpectedly synthesized.")


if __name__ == "__main__":
    main()
