from __future__ import annotations

import asyncio
import csv
from datetime import UTC, datetime, time, timedelta
from io import StringIO

import httpx

from app.providers.errors import ProviderError
from app.services.cache_service import JsonFileCache
from app.services.trading_calendar_service import is_eod_stale


VIX_HISTORY_URL = "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"


class CboeVixProvider:
    name = "cboe_vix"

    def __init__(self, *, cache: JsonFileCache, timeout_seconds: float = 20, max_retries: int = 3, transport: httpx.AsyncBaseTransport | None = None):
        self.cache, self.timeout_seconds, self.max_retries, self.transport = cache, timeout_seconds, max_retries, transport

    async def get_vix_data(self, ttl_seconds: int = 900) -> dict:
        key = "cboe-vix-history"
        cached = self.cache.get_entry(key)
        if cached:
            text, fetched_at = str(cached.data), cached.created_at
        else:
            text = ""
            for attempt in range(self.max_retries + 1):
                try:
                    async with httpx.AsyncClient(timeout=self.timeout_seconds, transport=self.transport) as client:
                        response = await client.get(VIX_HISTORY_URL)
                    response.raise_for_status()
                    text, fetched_at = response.text, datetime.now(UTC)
                    self.cache.set(key, text, ttl_seconds)
                    break
                except (httpx.HTTPError, httpx.TimeoutException) as exc:
                    if attempt < self.max_retries:
                        await asyncio.sleep(0.5 * (2**attempt))
                        continue
                    raise ProviderError(self.name, "VIX_UNAVAILABLE", "Unable to fetch the official Cboe VIX close.", retryable=True, endpoint=VIX_HISTORY_URL) from exc
        rows = list(csv.DictReader(StringIO(text)))
        if not rows:
            raise ProviderError(self.name, "VIX_INVALID_RESPONSE", "Cboe VIX history was empty.", retryable=False, endpoint=VIX_HISTORY_URL)
        latest = rows[-1]
        as_of = datetime.combine(datetime.strptime(latest["DATE"], "%m/%d/%Y").date(), time.min, tzinfo=UTC)
        return {"value": float(latest["CLOSE"]), "source": "Cboe Global Indices", "as_of": as_of.isoformat(), "fetched_at": fetched_at.isoformat(), "stale": is_eod_stale(as_of)}
