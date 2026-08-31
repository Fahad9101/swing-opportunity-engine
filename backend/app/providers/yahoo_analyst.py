from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from app.domain.schemas import EstimateSnapshot, FieldProvenance
from app.providers.errors import ProviderError
from app.services.cache_service import JsonFileCache


YAHOO_QUOTE_SUMMARY = "https://query2.finance.yahoo.com/v10/finance/quoteSummary/{symbol}"
YAHOO_COOKIE_BOOTSTRAP = "https://fc.yahoo.com"
YAHOO_CRUMB = "https://query2.finance.yahoo.com/v1/test/getcrumb"


def _raw(value: Any) -> Any:
    if isinstance(value, dict) and "raw" in value:
        return value.get("raw")
    return value


def _float(value: Any) -> float | None:
    value = _raw(value)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    value = _raw(value)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _change(current: float | None, old: float | None) -> float | None:
    if current is None or old is None or old == 0:
        return None
    return current / old - 1


def _period(trend: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    return next((row for row in trend if row.get("period") == name), None)


def normalize_yahoo_earnings_trend(
    ticker: str,
    payload: dict[str, Any],
    *,
    fetched_at: datetime,
    max_age_hours: int = 48,
) -> EstimateSnapshot | None:
    quote_summary = payload.get("quoteSummary")
    if not isinstance(quote_summary, dict):
        return None
    results = quote_summary.get("result")
    if not isinstance(results, list) or not results or not isinstance(results[0], dict):
        return None
    earnings_trend = results[0].get("earningsTrend")
    if not isinstance(earnings_trend, dict):
        return None
    trend = earnings_trend.get("trend")
    if not isinstance(trend, list):
        return None
    trend = [row for row in trend if isinstance(row, dict)]
    current_year = _period(trend, "0y")
    next_year = _period(trend, "+1y")
    if current_year is None and next_year is None:
        return None

    current_eps_estimate = (current_year or {}).get("earningsEstimate") or {}
    next_eps_estimate = (next_year or {}).get("earningsEstimate") or {}
    current_eps = _float(current_eps_estimate.get("avg"))
    next_eps = _float(next_eps_estimate.get("avg"))
    forward_eps_growth = _change(next_eps, current_eps) if current_eps is not None and current_eps > 0 else None

    revisions = (current_year or {}).get("epsRevisions") or {}
    eps_up = _int(revisions.get("upLast30days"))
    eps_down = _int(revisions.get("downLast30days"))

    eps_trend = (current_year or {}).get("epsTrend") or {}
    eps_current = _float(eps_trend.get("current"))
    eps_30d = _float(eps_trend.get("30daysAgo"))
    eps_90d = _float(eps_trend.get("90daysAgo"))
    eps_revision_30d = _change(eps_current, eps_30d)
    eps_revision_90d = _change(eps_current, eps_90d)

    next_revenue_estimate = (next_year or {}).get("revenueEstimate") or {}
    forward_revenue = _float(next_revenue_estimate.get("avg"))
    analyst_count = _int(current_eps_estimate.get("numberOfAnalysts"))
    if analyst_count is None:
        analyst_count = _int(next_eps_estimate.get("numberOfAnalysts"))

    stale = datetime.now(UTC) - fetched_at > timedelta(hours=max_age_hours)
    source = "Yahoo Finance quoteSummary earningsTrend (prototype-only)"
    provenance: dict[str, FieldProvenance] = {}

    def add_provenance(field: str, raw_field: str, value: Any) -> None:
        if value is None:
            return
        provenance[field] = FieldProvenance(
            source=source,
            as_of=fetched_at,
            fetched_at=fetched_at,
            stale=stale,
            raw_field=raw_field,
        )

    add_provenance("forward_eps_growth", "earningsTrend.trend[0y,+1y].earningsEstimate.avg", forward_eps_growth)
    add_provenance("eps_up_revisions", "earningsTrend.trend[0y].epsRevisions.upLast30days", eps_up)
    add_provenance("eps_down_revisions", "earningsTrend.trend[0y].epsRevisions.downLast30days", eps_down)
    add_provenance("eps_revision_30d", "earningsTrend.trend[0y].epsTrend.current/30daysAgo", eps_revision_30d)
    add_provenance("eps_revision_90d", "earningsTrend.trend[0y].epsTrend.current/90daysAgo", eps_revision_90d)
    add_provenance("forward_revenue", "earningsTrend.trend[+1y].revenueEstimate.avg", forward_revenue)
    add_provenance("analyst_count", "earningsTrend.trend[0y].earningsEstimate.numberOfAnalysts", analyst_count)

    if all(value is None for value in (forward_eps_growth, eps_up, eps_down, eps_revision_30d, eps_revision_90d, forward_revenue, analyst_count)):
        return None

    return EstimateSnapshot(
        ticker=ticker,
        forward_eps_growth=forward_eps_growth,
        eps_up_revisions=eps_up,
        eps_down_revisions=eps_down,
        eps_revision_magnitude=eps_revision_30d,
        eps_revision_30d=eps_revision_30d,
        eps_revision_90d=eps_revision_90d,
        forward_revenue=forward_revenue,
        analyst_count=analyst_count,
        source=source,
        as_of=fetched_at,
        fetched_at=fetched_at,
        stale=stale,
        field_provenance=provenance,
    )


class YahooAnalystEstimateProvider:
    """Key-free prototype adapter for Yahoo Finance analyst estimate data.

    Yahoo's public web endpoints are undocumented and provide no production SLA
    or redistribution grant to this project.  The adapter is isolated and is
    intended only for SOE prototype validation.  Commercial production must
    replace or separately license this source.
    """

    name = "yahoo_analyst_prototype"

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
                # Yahoo commonly returns a 404 from fc.yahoo.com while setting
                # the session cookie; the body/status are intentionally ignored.
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
                "modules": "earningsTrend",
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
                    raise ProviderError(self.name, "PROVIDER_SYMBOL_NOT_FOUND", "Yahoo Finance did not return analyst data for symbol.", retryable=False, ticker=ticker, endpoint=endpoint, status_code=404)
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, dict):
                    raise ValueError("Yahoo quoteSummary payload was not an object")
                return data, datetime.now(UTC)
            except ProviderError:
                raise
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                if attempt < self.retries:
                    await asyncio.sleep(self.backoff * (2**attempt))
                    continue
                raise ProviderError(self.name, "PROVIDER_TIMEOUT", "Yahoo analyst request timed out.", retryable=True, ticker=ticker, endpoint=endpoint) from exc
            except (httpx.HTTPError, ValueError) as exc:
                if attempt < self.retries:
                    await asyncio.sleep(self.backoff * (2**attempt))
                    continue
                raise ProviderError(self.name, "PUBLIC_ESTIMATE_DATA_UNAVAILABLE", "Yahoo analyst estimate request failed.", retryable=True, ticker=ticker, endpoint=endpoint) from exc
        raise AssertionError("unreachable")

    async def get_estimates(self, ticker: str) -> EstimateSnapshot | None:
        ttl = self.rules["data_quality"]["cache_ttl_seconds"]["estimates"]
        cache_key = f"yahoo-analyst:{ticker}"
        cached = self.cache.get_entry(cache_key)
        if cached is not None:
            payload, fetched_at = cached.data, cached.created_at
        else:
            payload, fetched_at = await self._request(ticker)
            self.cache.set(cache_key, payload, ttl, created_at=fetched_at)
        return normalize_yahoo_earnings_trend(
            ticker,
            payload,
            fetched_at=fetched_at,
            max_age_hours=self.rules["data_quality"]["staleness_hours"]["estimates"],
        )
