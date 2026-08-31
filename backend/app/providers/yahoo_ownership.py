from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from pydantic import BaseModel, Field

from app.domain.schemas import FieldProvenance
from app.providers.errors import ProviderError
from app.services.cache_service import JsonFileCache


YAHOO_QUOTE_SUMMARY = "https://query2.finance.yahoo.com/v10/finance/quoteSummary/{symbol}"
YAHOO_COOKIE_BOOTSTRAP = "https://fc.yahoo.com"
YAHOO_CRUMB = "https://query2.finance.yahoo.com/v1/test/getcrumb"


class OwnershipSnapshot(BaseModel):
    ticker: str
    institutional_ownership: float | None = None
    short_float: float | None = None
    source: str
    as_of: datetime
    fetched_at: datetime
    stale: bool = False
    field_provenance: dict[str, FieldProvenance] = Field(default_factory=dict)


def _raw(value: Any) -> Any:
    if isinstance(value, dict) and "raw" in value:
        return value.get("raw")
    return value


def _fraction(value: Any, *, field: str) -> float | None:
    value = _raw(value)
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    # These Yahoo fields are documented by their payload shape as fractions,
    # not percentage points. Values outside a broad but economically plausible
    # range are rejected rather than clipped or silently re-scaled.
    upper = 1.50 if field == "institutional_ownership" else 1.00
    if parsed < 0 or parsed > upper:
        return None
    return parsed


def normalize_yahoo_ownership(
    ticker: str,
    payload: dict[str, Any],
    *,
    fetched_at: datetime,
    max_age_hours: int = 48,
) -> OwnershipSnapshot | None:
    quote_summary = payload.get("quoteSummary")
    if not isinstance(quote_summary, dict):
        return None
    results = quote_summary.get("result")
    if not isinstance(results, list) or not results or not isinstance(results[0], dict):
        return None
    result = results[0]
    holders = result.get("majorHoldersBreakdown") or {}
    statistics = result.get("defaultKeyStatistics") or {}

    institutional_ownership = _fraction(
        holders.get("institutionsPercentHeld"), field="institutional_ownership"
    )
    short_float = _fraction(statistics.get("shortPercentOfFloat"), field="short_float")
    if institutional_ownership is None and short_float is None:
        return None

    stale = datetime.now(UTC) - fetched_at > timedelta(hours=max_age_hours)
    source = "Yahoo Finance quoteSummary ownership statistics (prototype-only)"
    provenance: dict[str, FieldProvenance] = {}
    if institutional_ownership is not None:
        provenance["institutional_ownership"] = FieldProvenance(
            source=source,
            as_of=fetched_at,
            fetched_at=fetched_at,
            stale=stale,
            raw_field="majorHoldersBreakdown.institutionsPercentHeld",
        )
    if short_float is not None:
        provenance["short_float"] = FieldProvenance(
            source=source,
            as_of=fetched_at,
            fetched_at=fetched_at,
            stale=stale,
            raw_field="defaultKeyStatistics.shortPercentOfFloat",
        )
    return OwnershipSnapshot(
        ticker=ticker,
        institutional_ownership=institutional_ownership,
        short_float=short_float,
        source=source,
        as_of=fetched_at,
        fetched_at=fetched_at,
        stale=stale,
        field_provenance=provenance,
    )


class YahooOwnershipProvider:
    """Key-free prototype adapter for ownership and short-float data.

    Yahoo's web endpoints are undocumented and have no production SLA or
    redistribution grant to this project. This adapter is isolated for
    validation only and must be replaced or separately licensed before
    commercial production.
    """

    name = "yahoo_ownership_prototype"

    def __init__(
        self,
        *,
        cache: JsonFileCache,
        rules: dict[str, Any],
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        provider = rules["data_quality"]["provider"]
        self.cache = cache
        self.rules = rules
        self.timeout = provider["timeout_seconds"]
        self.retries = provider["max_retries"]
        self.backoff = provider["initial_backoff_seconds"]
        self.transport = transport
        self._auth_lock = asyncio.Lock()
        self._crumb: str | None = None
        self._cookies: dict[str, str] = {}
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://finance.yahoo.com/",
        }

    async def _refresh_auth(self) -> None:
        async with self._auth_lock:
            async with httpx.AsyncClient(
                headers=self.headers,
                timeout=self.timeout,
                transport=self.transport,
                follow_redirects=True,
            ) as client:
                try:
                    await client.get(YAHOO_COOKIE_BOOTSTRAP)
                except httpx.HTTPError:
                    pass
                response = await client.get(YAHOO_CRUMB)
                if response.status_code != 200 or not response.text.strip():
                    raise ProviderError(
                        self.name,
                        "PROVIDER_AUTH_ERROR",
                        "Yahoo Finance crumb bootstrap failed.",
                        retryable=True,
                        endpoint=YAHOO_CRUMB,
                        status_code=response.status_code,
                    )
                self._crumb = response.text.strip()
                self._cookies = {cookie: value for cookie, value in client.cookies.items()}

    async def _request(self, ticker: str) -> tuple[dict[str, Any], datetime]:
        if self._crumb is None:
            await self._refresh_auth()
        endpoint = YAHOO_QUOTE_SUMMARY.format(symbol=ticker)
        for attempt in range(self.retries + 1):
            params = {
                "modules": "majorHoldersBreakdown,defaultKeyStatistics",
                "formatted": "false",
                "lang": "en-US",
                "region": "US",
                "corsDomain": "finance.yahoo.com",
                "symbol": ticker,
                "crumb": self._crumb or "",
            }
            try:
                async with httpx.AsyncClient(
                    headers=self.headers,
                    cookies=self._cookies,
                    timeout=self.timeout,
                    transport=self.transport,
                    follow_redirects=True,
                ) as client:
                    response = await client.get(endpoint, params=params)
                if response.status_code in {401, 403} and attempt < self.retries:
                    self._crumb = None
                    self._cookies = {}
                    await self._refresh_auth()
                    continue
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt < self.retries:
                        await asyncio.sleep(self.backoff * (2**attempt))
                        continue
                if response.status_code == 404:
                    raise ProviderError(
                        self.name,
                        "PROVIDER_SYMBOL_NOT_FOUND",
                        "Yahoo Finance did not return ownership data for symbol.",
                        retryable=False,
                        ticker=ticker,
                        endpoint=endpoint,
                        status_code=404,
                    )
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, dict):
                    raise ValueError("Yahoo quoteSummary ownership payload was not an object")
                return data, datetime.now(UTC)
            except ProviderError:
                raise
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                if attempt < self.retries:
                    await asyncio.sleep(self.backoff * (2**attempt))
                    continue
                raise ProviderError(
                    self.name,
                    "PROVIDER_TIMEOUT",
                    "Yahoo ownership request timed out.",
                    retryable=True,
                    ticker=ticker,
                    endpoint=endpoint,
                ) from exc
            except (httpx.HTTPError, ValueError) as exc:
                if attempt < self.retries:
                    await asyncio.sleep(self.backoff * (2**attempt))
                    continue
                raise ProviderError(
                    self.name,
                    "PUBLIC_OWNERSHIP_DATA_UNAVAILABLE",
                    "Yahoo ownership request failed.",
                    retryable=True,
                    ticker=ticker,
                    endpoint=endpoint,
                ) from exc
        raise AssertionError("unreachable")

    async def get_ownership(self, ticker: str) -> OwnershipSnapshot | None:
        ttl = self.rules["data_quality"]["cache_ttl_seconds"]["estimates"]
        cache_key = f"yahoo-ownership:{ticker}"
        cached = self.cache.get_entry(cache_key)
        if cached is not None:
            payload, fetched_at = cached.data, cached.created_at
        else:
            payload, fetched_at = await self._request(ticker)
            self.cache.set(cache_key, payload, ttl, created_at=fetched_at)
        return normalize_yahoo_ownership(
            ticker,
            payload,
            fetched_at=fetched_at,
            max_age_hours=self.rules["data_quality"]["staleness_hours"]["estimates"],
        )
