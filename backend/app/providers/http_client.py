from __future__ import annotations

import asyncio
import json
import random
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

from app.providers.errors import ProviderError
from app.services.cache_service import JsonFileCache


@dataclass(frozen=True)
class FetchedJson:
    data: dict[str, Any] | list[Any]
    fetched_at: datetime
    from_cache: bool


class ResilientJsonClient:
    def __init__(self, *, provider: str, base_url: str, headers: dict[str, str], timeout_seconds: float, max_retries: int, initial_backoff_seconds: float, max_concurrency: int, cache: JsonFileCache, transport: httpx.AsyncBaseTransport | None = None):
        self.provider = provider
        self.base_url = base_url.rstrip("/")
        self.headers = headers
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.initial_backoff_seconds = initial_backoff_seconds
        self.cache = cache
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._transport = transport

    async def request_json(self, method: str, path: str, *, params: dict[str, Any] | None = None, payload: dict[str, Any] | None = None, cache_key: str | None = None, ttl_seconds: int = 0, ticker: str | None = None) -> dict[str, Any] | list[Any]:
        result = await self.request_json_with_metadata(method, path, params=params, payload=payload, cache_key=cache_key, ttl_seconds=ttl_seconds, ticker=ticker)
        return result.data

    async def request_json_with_metadata(self, method: str, path: str, *, params: dict[str, Any] | None = None, payload: dict[str, Any] | None = None, cache_key: str | None = None, ttl_seconds: int = 0, ticker: str | None = None) -> FetchedJson:
        if cache_key and ttl_seconds:
            cached = self.cache.get_entry(f"{self.provider}:{cache_key}")
            if cached is not None: return FetchedJson(data=cached.data, fetched_at=cached.created_at, from_cache=True)
        url = path if path.startswith("http") else f"{self.base_url}/{path.lstrip('/')}"
        safe_endpoint = url.split("?", 1)[0]
        last_error: ProviderError | None = None
        for attempt in range(self.max_retries + 1):
            try:
                async with self._semaphore:
                    async with httpx.AsyncClient(headers=self.headers, timeout=self.timeout_seconds, transport=self._transport) as client:
                        response = await client.request(method, url, params=params, json=payload)
                if response.status_code == 429:
                    retry_after = min(float(response.headers.get("Retry-After", 0) or 0), 30)
                    last_error = ProviderError(self.provider, "PROVIDER_RATE_LIMIT", "Provider rate limit reached.", retryable=True, ticker=ticker, endpoint=safe_endpoint, status_code=429)
                    if attempt < self.max_retries:
                        await asyncio.sleep(max(retry_after, self.initial_backoff_seconds * (2 ** attempt)) + random.uniform(0, 0.1))
                        continue
                    raise last_error
                if response.status_code in {408, 425, 500, 502, 503, 504}:
                    last_error = ProviderError(self.provider, "PROVIDER_TRANSIENT_ERROR", f"Provider returned HTTP {response.status_code}.", retryable=True, ticker=ticker, endpoint=safe_endpoint, status_code=response.status_code)
                    if attempt < self.max_retries:
                        await asyncio.sleep(self.initial_backoff_seconds * (2 ** attempt) + random.uniform(0, 0.1))
                        continue
                    raise last_error
                if response.status_code in {401, 403}:
                    raise ProviderError(self.provider, "PROVIDER_AUTH_ERROR", "Provider authentication failed.", retryable=False, ticker=ticker, endpoint=safe_endpoint, status_code=response.status_code)
                if response.status_code == 402:
                    raise ProviderError(self.provider, "PROVIDER_SUBSCRIPTION_REQUIRED", "Provider subscription does not cover this endpoint.", retryable=False, ticker=ticker, endpoint=safe_endpoint, status_code=402)
                if response.status_code == 404:
                    raise ProviderError(self.provider, "PROVIDER_SYMBOL_NOT_FOUND", "Provider did not recognize the symbol.", retryable=False, ticker=ticker, endpoint=safe_endpoint, status_code=404)
                if response.status_code >= 400:
                    raise ProviderError(self.provider, "PROVIDER_BAD_RESPONSE", f"Provider returned HTTP {response.status_code}.", retryable=False, ticker=ticker, endpoint=safe_endpoint, status_code=response.status_code)
                try:
                    data = response.json()
                except (json.JSONDecodeError, ValueError) as exc:
                    raise ProviderError(self.provider, "PROVIDER_INVALID_JSON", "Provider returned invalid JSON.", retryable=False, ticker=ticker, endpoint=safe_endpoint, status_code=response.status_code) from exc
                fetched_at = datetime.now(UTC)
                if cache_key and ttl_seconds: self.cache.set(f"{self.provider}:{cache_key}", data, ttl_seconds, created_at=fetched_at)
                return FetchedJson(data=data, fetched_at=fetched_at, from_cache=False)
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_error = ProviderError(self.provider, "PROVIDER_TIMEOUT", "Provider request timed out or failed to connect.", retryable=True, ticker=ticker, endpoint=safe_endpoint)
                if attempt < self.max_retries:
                    await asyncio.sleep(self.initial_backoff_seconds * (2 ** attempt) + random.uniform(0, 0.1))
                    continue
                raise last_error from exc
        raise last_error or ProviderError(self.provider, "PROVIDER_UNKNOWN_ERROR", "Unknown provider failure.", retryable=False, ticker=ticker, endpoint=safe_endpoint)
