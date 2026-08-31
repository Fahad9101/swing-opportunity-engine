from __future__ import annotations

import asyncio
import json

from app.core.config import get_settings, load_rules
from app.providers.errors import ProviderError
from app.providers.yahoo_ownership import YahooOwnershipProvider
from app.services.cache_service import JsonFileCache


DEFAULT_TICKERS = ("DELL", "AVGO", "FAST", "LUV", "ARWR")


async def smoke(tickers: tuple[str, ...] = DEFAULT_TICKERS) -> list[dict]:
    settings = get_settings()
    provider = YahooOwnershipProvider(
        cache=JsonFileCache(settings.cache_dir),
        rules=load_rules(),
    )
    results: list[dict] = []
    for ticker in tickers:
        try:
            snapshot = await provider.get_ownership(ticker)
            if snapshot is None:
                results.append({"ticker": ticker, "status": "NO_DATA"})
                continue
            row = {
                "ticker": ticker,
                "status": "OK",
                "institutional_ownership": snapshot.institutional_ownership,
                "short_float": snapshot.short_float,
                "source": snapshot.source,
                "stale": snapshot.stale,
            }
            if snapshot.institutional_ownership is not None and not 0 <= snapshot.institutional_ownership <= 1.50:
                row["status"] = "INVALID_INSTITUTIONAL_RANGE"
            if snapshot.short_float is not None and not 0 <= snapshot.short_float <= 1.0:
                row["status"] = "INVALID_SHORT_FLOAT_RANGE"
            results.append(row)
        except ProviderError as exc:
            results.append({"ticker": ticker, "status": "PROVIDER_ERROR", "error": exc.as_dict()})
    return results


def main() -> None:
    results = asyncio.run(smoke())
    print(json.dumps(results, indent=2, sort_keys=True))
    usable = [row for row in results if row.get("status") == "OK"]
    if len(usable) < 4:
        raise SystemExit("Live ownership smoke failed: fewer than four sample tickers returned valid ownership/short-float data.")
    if not any(row.get("institutional_ownership") is not None for row in usable):
        raise SystemExit("Live ownership smoke failed: institutional ownership was absent for every sample.")
    if not any(row.get("short_float") is not None for row in usable):
        raise SystemExit("Live ownership smoke failed: short float was absent for every sample.")


if __name__ == "__main__":
    main()
