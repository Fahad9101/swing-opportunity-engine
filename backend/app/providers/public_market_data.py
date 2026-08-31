from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import httpx

from app.domain.schemas import OHLCVBar
from app.providers.errors import ProviderError
from app.services.cache_service import JsonFileCache
from app.services.trading_calendar_service import latest_expected_completed_session


YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
NASDAQ_SCREENER_URL = "https://api.nasdaq.com/api/screener/stocks"


def normalize_yahoo_chart(payload: dict[str, Any], requested_symbol: str, fetched_at: datetime) -> list[OHLCVBar]:
    rows = ((payload.get("chart") or {}).get("result")) or []
    if not rows:
        return []
    response = rows[0]
    provider_symbol = str((response.get("meta") or {}).get("symbol") or "").upper().replace(".", "-")
    if provider_symbol != requested_symbol.upper().replace(".", "-"):
        raise ProviderError("public_market_data_prototype", "PROVIDER_SYMBOL_MISMATCH", "Yahoo chart symbol did not match requested symbol.", retryable=False, ticker=requested_symbol, endpoint=YAHOO_CHART_URL)
    timestamps = response.get("timestamp") or []
    quotes = ((response.get("indicators") or {}).get("quote")) or []
    quote = quotes[0] if quotes else {}
    bars: list[OHLCVBar] = []
    for index, stamp in enumerate(timestamps):
        values = {field: (quote.get(field) or []) for field in ("open", "high", "low", "close", "volume")}
        if any(index >= len(items) or items[index] is None for items in values.values()):
            continue
        bars.append(OHLCVBar(
            date=datetime.fromtimestamp(int(stamp), UTC).date(), open=float(values["open"][index]),
            high=float(values["high"][index]), low=float(values["low"][index]), close=float(values["close"][index]),
            volume=float(values["volume"][index]), source="Yahoo Finance chart API (prototype-only)",
            as_of=datetime.fromtimestamp(int(stamp), UTC), fetched_at=fetched_at,
        ))
    return bars


def normalize_yahoo_spark(payload: dict[str, Any], requested: set[str], fetched_at: datetime) -> dict[str, list[OHLCVBar]]:
    """Compatibility normalizer retained for older cached/test spark payloads."""
    normalized: dict[str, list[OHLCVBar]] = {}
    for row in ((payload.get("spark") or {}).get("result")) or []:
        symbol = str(row.get("symbol") or "").upper().replace(".", "-")
        if symbol not in requested:
            continue
        responses = row.get("response") or []
        if not responses:
            continue
        response = responses[0]
        timestamps = response.get("timestamp") or []
        quotes = ((response.get("indicators") or {}).get("quote")) or []
        quote = quotes[0] if quotes else {}
        bars: list[OHLCVBar] = []
        for index, stamp in enumerate(timestamps):
            values = {field: (quote.get(field) or []) for field in ("open", "high", "low", "close", "volume")}
            if any(index >= len(items) or items[index] is None for items in values.values()):
                continue
            bars.append(OHLCVBar(
                date=datetime.fromtimestamp(int(stamp), UTC).date(), open=float(values["open"][index]),
                high=float(values["high"][index]), low=float(values["low"][index]), close=float(values["close"][index]),
                volume=float(values["volume"][index]), source="Yahoo Finance chart API (prototype-only)",
                as_of=datetime.fromtimestamp(int(stamp), UTC), fetched_at=fetched_at,
            ))
        if bars:
            normalized[symbol] = bars
    return normalized


def normalize_nasdaq_screener(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = (((payload.get("data") or {}).get("rows")) or [])
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        ticker = str(row.get("symbol") or "").upper().replace(".", "-")
        if not ticker:
            continue
        cap = row.get("marketCap")
        try:
            market_cap = float(str(cap).replace(",", "")) if cap not in (None, "", "N/A") else None
        except (TypeError, ValueError):
            market_cap = None
        result[ticker] = {
            "name": row.get("name"), "market_cap": market_cap, "country": row.get("country") or None,
            "sector": row.get("sector") or None, "industry": row.get("industry") or None,
        }
    return result


class PublicMarketDataProvider:
    """Replaceable prototype adapter for public Nasdaq metadata and Yahoo EOD bars.

    Yahoo's chart endpoint is undocumented and has no production SLA. It is intentionally
    isolated here and must be replaced or separately licensed before commercial use.
    """

    name = "public_market_data_prototype"

    def __init__(self, *, cache: JsonFileCache, rules: dict[str, Any], transport: httpx.AsyncBaseTransport | None = None):
        provider = rules["data_quality"]["provider"]
        self.cache, self.rules, self.transport = cache, rules, transport
        self.timeout = provider["timeout_seconds"]
        self.retries = provider["max_retries"]
        self.concurrency = provider["max_concurrency"]
        self._bars: dict[str, list[OHLCVBar]] = {}
        self.errors: list[dict[str, Any]] = []

    async def _json(self, url: str, *, params: dict[str, Any], ticker: str | None = None) -> tuple[dict[str, Any], datetime]:
        for attempt in range(self.retries + 1):
            try:
                headers = {"User-Agent": "Mozilla/5.0 SOE-Free-Public-Validation/1.0", "Accept": "application/json"}
                async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport, headers=headers) as client:
                    response = await client.get(url, params=params)
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt < self.retries:
                        await asyncio.sleep(0.5 * (2**attempt))
                        continue
                response.raise_for_status()
                return response.json(), datetime.now(UTC)
            except (httpx.HTTPError, ValueError) as exc:
                if attempt < self.retries:
                    await asyncio.sleep(0.5 * (2**attempt))
                    continue
                code = "PROVIDER_TIMEOUT" if isinstance(exc, httpx.TimeoutException) else "PUBLIC_MARKET_DATA_UNAVAILABLE"
                raise ProviderError(self.name, code, "Public market-data request failed.", retryable=True, ticker=ticker, endpoint=url) from exc
        raise AssertionError("unreachable")

    async def get_metadata(self) -> tuple[dict[str, dict[str, Any]], datetime]:
        key = "nasdaq-public-screener-metadata"
        cached = self.cache.get_entry(key)
        if cached:
            return normalize_nasdaq_screener(cached.data), cached.created_at
        payload, fetched_at = await self._json(NASDAQ_SCREENER_URL, params={"tableonly": "true", "limit": 25, "offset": 0, "download": "true"})
        self.cache.set(key, payload, self.rules["data_quality"]["cache_ttl_seconds"]["universe"])
        return normalize_nasdaq_screener(payload), fetched_at

    async def prefetch(self, tickers: list[str], sessions: int = 260, *, retain: bool = False) -> None:
        ttl = self.rules["data_quality"]["cache_ttl_seconds"]["ohlcv"]
        missing: list[str] = []
        for ticker in tickers:
            cached = self.cache.get_entry(f"public-ohlcv:{ticker}:{sessions}")
            if cached:
                if retain:
                    self._bars[ticker] = [OHLCVBar.model_validate(item) for item in cached.data]
            else:
                missing.append(ticker)

        concurrency = max(16, min(100, self.concurrency * 16))
        semaphore = asyncio.Semaphore(concurrency)
        headers = {"User-Agent": "Mozilla/5.0 SOE-Free-Public-Validation/1.0", "Accept": "application/json"}

        async def fetch(client: httpx.AsyncClient, ticker: str) -> None:
            async with semaphore:
                try:
                    endpoint = YAHOO_CHART_URL.format(symbol=ticker)
                    response = None
                    for attempt in range(self.retries + 1):
                        response = await client.get(endpoint, params={"range": "2y", "interval": "1d", "events": "splits"})
                        if response.status_code not in {429, 500, 502, 503, 504} or attempt == self.retries:
                            break
                        await asyncio.sleep(0.5 * (2**attempt))
                    if response is None or response.status_code != 200:
                        raise ProviderError(self.name, "PUBLIC_MARKET_DATA_UNAVAILABLE", "Yahoo chart request failed.", retryable=True, ticker=ticker, endpoint=endpoint, status_code=response.status_code if response else None)
                    bars = normalize_yahoo_chart(response.json(), ticker, datetime.now(UTC))[-sessions:]
                    if not bars:
                        raise ProviderError(self.name, "TICKER_DATA_UNAVAILABLE", "No usable OHLCV returned for ticker.", retryable=False, ticker=ticker, endpoint=endpoint)
                    if retain:
                        self._bars[ticker] = bars
                    self.cache.set(f"public-ohlcv:{ticker}:{sessions}", [item.model_dump(mode="json") for item in bars], ttl)
                except (httpx.HTTPError, ValueError, ProviderError) as exc:
                    error = exc if isinstance(exc, ProviderError) else ProviderError(self.name, "PUBLIC_MARKET_DATA_UNAVAILABLE", "Yahoo chart request failed.", retryable=True, ticker=ticker, endpoint=YAHOO_CHART_URL.format(symbol=ticker))
                    self.errors.append(error.as_dict())

        limits = httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency)
        async with httpx.AsyncClient(timeout=max(30, self.timeout), headers=headers, limits=limits, transport=self.transport) as client:
            await asyncio.gather(*(fetch(client, ticker) for ticker in missing))

    def _load_cached_bars(self, ticker: str, sessions: int) -> bool:
        cached = self.cache.get_entry(f"public-ohlcv:{ticker}:{sessions}")
        if not cached:
            return False
        self._bars[ticker] = [OHLCVBar.model_validate(item) for item in cached.data]
        return bool(self._bars[ticker])

    async def get_ohlcv(self, ticker: str, sessions: int = 260) -> list[OHLCVBar]:
        bars = self._bars.get(ticker)
        if bars is None or len(bars) < sessions:
            loaded = self._load_cached_bars(ticker, sessions)
            if not loaded:
                # Full scans prefetch 520 sessions once for both technical and
                # Milestone-2.5G historical valuation work. A 260-session
                # technical request can therefore reuse the larger cache.
                for cached_sessions in (520, 756, 1260):
                    if cached_sessions >= sessions and self._load_cached_bars(ticker, cached_sessions):
                        loaded = True
                        break
            if not loaded:
                await self.prefetch([ticker], sessions, retain=True)
        bars = self._bars.get(ticker)
        if not bars:
            raise ProviderError(self.name, "TICKER_DATA_UNAVAILABLE", "No usable OHLCV returned for ticker.", retryable=False, ticker=ticker, endpoint=YAHOO_CHART_URL.format(symbol=ticker))
        completed_through = latest_expected_completed_session()
        return [bar for bar in bars if bar.date <= completed_through][-sessions:]
