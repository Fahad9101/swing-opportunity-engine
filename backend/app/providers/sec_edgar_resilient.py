from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from typing import Any

import httpx

from app.domain.schemas import FundamentalSnapshot
from app.providers.errors import ProviderError
from app.providers.sec_edgar import (
    COMPANYFACTS_URL,
    TICKER_MAP_URL,
    SecEdgarProvider,
    normalize_companyfacts,
)


class ResilientSecEdgarProvider(SecEdgarProvider):
    """SEC companyfacts provider with a conservative network fallback.

    The preferred full-market path remains the official nightly companyfacts ZIP.
    GitHub-hosted egress is occasionally denied access to the large SEC archive;
    when that happens this adapter can use the official data.sec.gov companyfacts
    endpoint for universal-gate survivors. Requests are serialized, throttled
    below SEC fair-access limits, cached, and retried with bounded backoff.

    This is a data-transport change only. It does not alter any SOE-1.0.0 field
    definition, scanner condition, threshold, score weight, or missing-data rule.
    """

    name = "sec_edgar"

    def __init__(self, *args, min_interval_seconds: float = 0.20, **kwargs):
        super().__init__(*args, **kwargs)
        self.min_interval_seconds = max(0.0, float(min_interval_seconds))
        self._request_lock = asyncio.Lock()
        self._last_request_at = 0.0
        self._client: httpx.AsyncClient | None = None
        self._ticker_map_error: ProviderError | None = None

    def _client_instance(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=45,
                transport=self.transport,
                headers={
                    "User-Agent": self.user_agent,
                    "Accept": "application/json",
                    "Accept-Encoding": "gzip, deflate",
                },
                follow_redirects=True,
            )
        return self._client

    async def _network_json(self, url: str, *, ticker: str | None = None) -> tuple[dict[str, Any], datetime]:
        last_response: httpx.Response | None = None
        last_error: Exception | None = None
        for attempt in range(5):
            try:
                async with self._request_lock:
                    wait = self.min_interval_seconds - (time.monotonic() - self._last_request_at)
                    if wait > 0:
                        await asyncio.sleep(wait)
                    try:
                        response = await self._client_instance().get(url)
                    finally:
                        self._last_request_at = time.monotonic()
                last_response = response
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt < 4:
                        retry_after = response.headers.get("Retry-After")
                        try:
                            delay = float(retry_after) if retry_after else 0.5 * (2**attempt)
                        except ValueError:
                            delay = 0.5 * (2**attempt)
                        await asyncio.sleep(max(self.min_interval_seconds, delay))
                        continue
                if response.status_code == 403:
                    # A 403 from SEC edge infrastructure is not evidence about a
                    # security. Surface it as a provider-access failure.
                    raise ProviderError(
                        self.name,
                        "SEC_ACCESS_FORBIDDEN",
                        "SEC EDGAR denied this hosted runner request.",
                        retryable=True,
                        ticker=ticker,
                        endpoint=url,
                        status_code=403,
                    )
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ValueError("SEC JSON payload was not an object")
                return payload, datetime.now(UTC)
            except ProviderError:
                raise
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
                if attempt < 4:
                    await asyncio.sleep(max(self.min_interval_seconds, 0.5 * (2**attempt)))
                    continue
        raise ProviderError(
            self.name,
            "SEC_DATA_UNAVAILABLE",
            "SEC EDGAR network fallback failed.",
            retryable=True,
            ticker=ticker,
            endpoint=url,
            status_code=last_response.status_code if last_response is not None else None,
        ) from last_error

    async def ticker_map(self) -> dict[str, str]:
        if self._ticker_to_cik is not None:
            return self._ticker_to_cik
        if self._ticker_map_error is not None:
            raise self._ticker_map_error

        cached = self.cache.get_entry("sec-company-ticker-exchange-map")
        if cached:
            payload = cached.data
        else:
            try:
                payload, fetched_at = await self._network_json(TICKER_MAP_URL)
            except ProviderError as exc:
                self._ticker_map_error = exc
                raise
            self.cache.set("sec-company-ticker-exchange-map", payload, 86400, created_at=fetched_at)

        fields = payload.get("fields") or []
        mapping: dict[str, str] = {}
        for values in payload.get("data") or []:
            row = dict(zip(fields, values, strict=False))
            ticker = str(row.get("ticker") or "").upper().replace(".", "-")
            if ticker and row.get("cik") is not None:
                mapping[ticker] = f"{int(row['cik']):010d}"
        self._ticker_to_cik = mapping
        return mapping

    async def get_fundamentals(self, ticker: str) -> FundamentalSnapshot | None:
        # Preserve the validated bulk path whenever it is available.
        if self.zip_path.exists():
            return await super().get_fundamentals(ticker)

        cik = (await self.ticker_map()).get(ticker.upper().replace(".", "-"))
        if not cik:
            return None

        cache_key = f"sec-companyfacts-network-v1:{cik}"
        cached = self.cache.get_entry(cache_key)
        if cached:
            payload, fetched_at = cached.data, cached.created_at
        else:
            payload, fetched_at = await self._network_json(COMPANYFACTS_URL.format(cik=cik), ticker=ticker)
            ttl = int(self.rules["data_quality"]["cache_ttl_seconds"]["fundamentals"])
            self.cache.set(cache_key, payload, ttl, created_at=fetched_at)

        return normalize_companyfacts(
            ticker,
            payload,
            fetched_at=fetched_at,
            max_age_hours=self.rules["data_quality"]["staleness_hours"]["fundamentals"],
        )

    async def network_smoke_test(self) -> dict[str, Any]:
        """Check official SEC mapping + one companyfacts record without mutating rules."""
        mapping = await self.ticker_map()
        cik = mapping.get("AAPL")
        if cik is None:
            raise ProviderError(self.name, "SEC_MAPPING_INVALID", "SEC ticker map did not contain AAPL.", retryable=False)
        payload, fetched_at = await self._network_json(COMPANYFACTS_URL.format(cik=cik), ticker="AAPL")
        return {
            "ticker_map_count": len(mapping),
            "aapl_cik": cik,
            "companyfacts_entity": payload.get("entityName"),
            "fetched_at": fetched_at.isoformat(),
        }

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
