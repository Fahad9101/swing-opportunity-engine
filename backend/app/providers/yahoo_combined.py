from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from typing import Any

import httpx

from app.domain.schemas import EstimateSnapshot
from app.providers.errors import ProviderError
from app.providers.yahoo_analyst import AnalystValuationReference, normalize_yahoo_earnings_trend, normalize_yahoo_valuation_reference
from app.providers.yahoo_ownership import OwnershipSnapshot, normalize_yahoo_ownership
from app.services.cache_service import JsonFileCache


YAHOO_QUOTE_SUMMARY = "https://query2.finance.yahoo.com/v10/finance/quoteSummary/{symbol}"
YAHOO_COOKIE_BOOTSTRAP = "https://fc.yahoo.com"
YAHOO_CRUMB = "https://query2.finance.yahoo.com/v1/test/getcrumb"
YAHOO_COMBINED_MODULES = "earningsTrend,financialData,majorHoldersBreakdown,defaultKeyStatistics"


class YahooCombinedEnrichmentProvider:
    """One shared Yahoo quoteSummary session for all prototype enrichment fields.

    Milestone 2.5J uses this adapter only to improve transport reliability and
    request efficiency. It does not add an investment input, alter a frozen
    threshold, or convert missing data into favorable evidence.

    One cached payload per ticker supplies analyst estimates/revisions, analyst
    valuation references, institutional ownership, and short float. Requests are
    serialized and rate-limited so a full-market validation does not bootstrap a
    new Yahoo crumb or make two quoteSummary calls for every surviving ticker.
    Yahoo remains an undocumented prototype-validation source and is not approved
    here for commercial redistribution or production use.
    """

    name = "yahoo_combined_prototype"

    def __init__(
        self,
        *,
        cache: JsonFileCache,
        rules: dict[str, Any],
        transport: httpx.AsyncBaseTransport | None = None,
        min_interval_seconds: float = 0.30,
    ) -> None:
        provider = rules["data_quality"]["provider"]
        self.cache = cache
        self.rules = rules
        self.timeout = provider["timeout_seconds"]
        self.retries = provider["max_retries"]
        self.backoff = provider["initial_backoff_seconds"]
        self.transport = transport
        self.min_interval_seconds = max(0.0, float(min_interval_seconds))
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://finance.yahoo.com/",
        }
        self._auth_lock = asyncio.Lock()
        self._request_lock = asyncio.Lock()
        self._client: httpx.AsyncClient | None = None
        self._crumb: str | None = None
        self._last_request_at = 0.0

    def _client_instance(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                headers=self.headers,
                timeout=self.timeout,
                transport=self.transport,
                follow_redirects=True,
            )
        return self._client

    async def _wait_for_slot(self) -> None:
        remaining = self.min_interval_seconds - (time.monotonic() - self._last_request_at)
        if remaining > 0:
            await asyncio.sleep(remaining)

    async def _get(self, url: str, **kwargs) -> httpx.Response:
        # One global request lane is intentional. The scan pipeline itself is
        # sequential, but this also protects future callers from accidental
        # full-market concurrency against an undocumented endpoint.
        async with self._request_lock:
            await self._wait_for_slot()
            try:
                return await self._client_instance().get(url, **kwargs)
            finally:
                self._last_request_at = time.monotonic()

    def _retry_delay(self, response: httpx.Response | None, attempt: int) -> float:
        if response is not None:
            retry_after = response.headers.get("Retry-After")
            if retry_after:
                try:
                    return max(self.min_interval_seconds, float(retry_after))
                except ValueError:
                    pass
        # A rate-limit response gets a deliberately larger deterministic global
        # cooldown than an ordinary transient server error.
        multiplier = 5.0 if response is not None and response.status_code == 429 else 1.0
        return max(self.min_interval_seconds, self.backoff * (2**attempt) * multiplier)

    async def _refresh_auth(self, *, force: bool = False) -> None:
        async with self._auth_lock:
            if self._crumb is not None and not force:
                return
            self._crumb = None
            last_response: httpx.Response | None = None
            for attempt in range(self.retries + 1):
                try:
                    # fc.yahoo.com commonly answers 404 while still establishing
                    # cookies. The status itself is therefore intentionally ignored.
                    try:
                        await self._get(YAHOO_COOKIE_BOOTSTRAP)
                    except httpx.HTTPError:
                        pass
                    response = await self._get(YAHOO_CRUMB)
                    last_response = response
                    crumb = response.text.strip()
                    if response.status_code == 200 and crumb and "Too Many Requests" not in crumb:
                        self._crumb = crumb
                        return
                    if response.status_code == 429 or response.status_code >= 500:
                        if attempt < self.retries:
                            await asyncio.sleep(self._retry_delay(response, attempt))
                            continue
                    break
                except (httpx.TimeoutException, httpx.NetworkError) as exc:
                    if attempt < self.retries:
                        await asyncio.sleep(self._retry_delay(None, attempt))
                        continue
                    raise ProviderError(
                        self.name,
                        "PROVIDER_TIMEOUT",
                        "Yahoo Finance authentication bootstrap timed out.",
                        retryable=True,
                        endpoint=YAHOO_CRUMB,
                    ) from exc
            status = last_response.status_code if last_response is not None else None
            code = "PROVIDER_RATE_LIMITED" if status == 429 else "PROVIDER_AUTH_ERROR"
            raise ProviderError(
                self.name,
                code,
                "Yahoo Finance shared crumb bootstrap failed.",
                retryable=True,
                endpoint=YAHOO_CRUMB,
                status_code=status,
            )

    async def _request(self, ticker: str) -> tuple[dict[str, Any], datetime]:
        await self._refresh_auth()
        endpoint = YAHOO_QUOTE_SUMMARY.format(symbol=ticker)
        last_response: httpx.Response | None = None
        for attempt in range(self.retries + 1):
            params = {
                "modules": YAHOO_COMBINED_MODULES,
                "formatted": "false",
                "lang": "en-US",
                "region": "US",
                "corsDomain": "finance.yahoo.com",
                "symbol": ticker,
                "crumb": self._crumb or "",
            }
            try:
                response = await self._get(endpoint, params=params)
                last_response = response
                if response.status_code in {401, 403}:
                    if attempt < self.retries:
                        await self._refresh_auth(force=True)
                        continue
                    raise ProviderError(
                        self.name,
                        "PROVIDER_AUTH_ERROR",
                        "Yahoo Finance rejected the shared authenticated session.",
                        retryable=True,
                        ticker=ticker,
                        endpoint=endpoint,
                        status_code=response.status_code,
                    )
                if response.status_code == 429:
                    if attempt < self.retries:
                        await asyncio.sleep(self._retry_delay(response, attempt))
                        continue
                    raise ProviderError(
                        self.name,
                        "PROVIDER_RATE_LIMITED",
                        "Yahoo Finance rate-limited the shared enrichment request.",
                        retryable=True,
                        ticker=ticker,
                        endpoint=endpoint,
                        status_code=429,
                    )
                if response.status_code >= 500:
                    if attempt < self.retries:
                        await asyncio.sleep(self._retry_delay(response, attempt))
                        continue
                if response.status_code == 404:
                    raise ProviderError(
                        self.name,
                        "PROVIDER_SYMBOL_NOT_FOUND",
                        "Yahoo Finance did not return quoteSummary data for symbol.",
                        retryable=False,
                        ticker=ticker,
                        endpoint=endpoint,
                        status_code=404,
                    )
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ValueError("Yahoo quoteSummary payload was not an object")
                return payload, datetime.now(UTC)
            except ProviderError:
                raise
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                if attempt < self.retries:
                    await asyncio.sleep(self._retry_delay(None, attempt))
                    continue
                raise ProviderError(
                    self.name,
                    "PROVIDER_TIMEOUT",
                    "Yahoo shared enrichment request timed out.",
                    retryable=True,
                    ticker=ticker,
                    endpoint=endpoint,
                ) from exc
            except (httpx.HTTPError, ValueError) as exc:
                if attempt < self.retries:
                    await asyncio.sleep(self._retry_delay(last_response, attempt))
                    continue
                raise ProviderError(
                    self.name,
                    "PUBLIC_YAHOO_DATA_UNAVAILABLE",
                    "Yahoo shared enrichment request failed.",
                    retryable=True,
                    ticker=ticker,
                    endpoint=endpoint,
                    status_code=last_response.status_code if last_response is not None else None,
                ) from exc
        raise AssertionError("unreachable")

    async def _payload(self, ticker: str) -> tuple[dict[str, Any], datetime]:
        ttl = self.rules["data_quality"]["cache_ttl_seconds"]["estimates"]
        key = ticker.upper().replace(".", "-")
        cache_key = f"yahoo-combined-v1:{key}"
        cached = self.cache.get_entry(cache_key)
        if cached is not None:
            return cached.data, cached.created_at
        payload, fetched_at = await self._request(key)
        self.cache.set(cache_key, payload, ttl, created_at=fetched_at)
        return payload, fetched_at

    async def get_estimates(self, ticker: str) -> EstimateSnapshot | None:
        payload, fetched_at = await self._payload(ticker)
        return normalize_yahoo_earnings_trend(
            ticker,
            payload,
            fetched_at=fetched_at,
            max_age_hours=self.rules["data_quality"]["staleness_hours"]["estimates"],
        )

    async def get_valuation_reference(self, ticker: str) -> AnalystValuationReference | None:
        payload, fetched_at = await self._payload(ticker)
        return normalize_yahoo_valuation_reference(
            ticker,
            payload,
            fetched_at=fetched_at,
            max_age_hours=self.rules["data_quality"]["staleness_hours"]["estimates"],
        )

    async def get_ownership(self, ticker: str) -> OwnershipSnapshot | None:
        payload, fetched_at = await self._payload(ticker)
        return normalize_yahoo_ownership(
            ticker,
            payload,
            fetched_at=fetched_at,
            max_age_hours=self.rules["data_quality"]["staleness_hours"]["estimates"],
        )

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
