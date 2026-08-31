from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from app.domain.schemas import EstimateSnapshot, FieldProvenance
from app.providers.errors import ProviderError
from app.providers.http_client import ResilientJsonClient
from app.services.cache_service import JsonFileCache


NASDAQ_API_BASE = "https://api.nasdaq.com/api"


def _number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text or text.upper() in {"N/A", "NA", "--", "-"}:
        return None
    negative = text.startswith("(") and text.endswith(")")
    text = text.strip("()$,% ").replace(",", "")
    try:
        result = float(text)
    except ValueError:
        return None
    return -result if negative else result


def _integer(value: Any) -> int | None:
    parsed = _number(value)
    return None if parsed is None else int(parsed)


def _forecast_rows(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Return annual forecast rows without guessing unavailable fields.

    Nasdaq's public analyst endpoint has historically exposed
    ``data.yearlyForecast.rows``.  A small set of alternate container names is
    accepted defensively because the public endpoint is not a contractual API.
    """
    for key in ("yearlyForecast", "annualForecast", "annual"):
        container = data.get(key)
        if isinstance(container, dict) and isinstance(container.get("rows"), list):
            return [row for row in container["rows"] if isinstance(row, dict)]
    return []


def normalize_analyst_forecast(
    ticker: str,
    payload: dict[str, Any],
    *,
    fetched_at: datetime,
    max_age_hours: int = 48,
) -> EstimateSnapshot | None:
    """Normalize Nasdaq public annual EPS forecasts into SOE estimates.

    Only fields explicitly present in the public response are populated.  In
    particular, this adapter does not invent 30/90-day revision histories,
    revenue forecasts, EBITDA forecasts, or up/down revision counts.

    Forward EPS growth is calculated from the first two usable annual
    consensus EPS forecasts.  If the nearer forecast is zero/negative, growth
    is left unavailable because a percentage growth rate would be unstable or
    economically misleading.
    """
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    if not isinstance(data, dict):
        return None
    rows = _forecast_rows(data)
    parsed: list[tuple[float, int | None, str | None]] = []
    for row in rows:
        eps = _number(row.get("consensusEPSForecast"))
        if eps is None:
            continue
        parsed.append((eps, _integer(row.get("numOfEstimates")), row.get("fiscalEnd")))
    if not parsed:
        return None

    forward_eps_growth: float | None = None
    if len(parsed) >= 2 and parsed[0][0] > 0:
        forward_eps_growth = parsed[1][0] / parsed[0][0] - 1

    analyst_count = parsed[0][1]
    as_of = fetched_at
    stale = datetime.now(UTC) - fetched_at > timedelta(hours=max_age_hours)
    source = "Nasdaq public analyst forecast endpoint (prototype-only)"
    provenance = {
        "forward_eps_growth": FieldProvenance(
            source=source,
            as_of=as_of,
            fetched_at=fetched_at,
            stale=stale,
            raw_field="yearlyForecast.rows[].consensusEPSForecast",
        ),
        "analyst_count": FieldProvenance(
            source=source,
            as_of=as_of,
            fetched_at=fetched_at,
            stale=stale,
            raw_field="yearlyForecast.rows[0].numOfEstimates",
        ),
    }
    return EstimateSnapshot(
        ticker=ticker,
        forward_eps_growth=forward_eps_growth,
        analyst_count=analyst_count,
        source=source,
        as_of=as_of,
        fetched_at=fetched_at,
        stale=stale,
        field_provenance=provenance,
    )


class NasdaqAnalystEstimateProvider:
    """Key-free prototype adapter for Nasdaq's public analyst forecast page API.

    Nasdaq does not provide a contractual SLA or redistribution grant for this
    endpoint.  It is therefore isolated behind the SOE provider interface and
    is suitable for prototype validation only, not commercial production.
    """

    name = "nasdaq_public_analyst"

    def __init__(
        self,
        *,
        cache: JsonFileCache,
        rules: dict[str, Any],
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        provider = rules["data_quality"]["provider"]
        self.rules = rules
        self.client = ResilientJsonClient(
            provider=self.name,
            base_url=NASDAQ_API_BASE,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": "https://www.nasdaq.com/",
            },
            timeout_seconds=provider["timeout_seconds"],
            max_retries=provider["max_retries"],
            initial_backoff_seconds=provider["initial_backoff_seconds"],
            max_concurrency=max(1, min(4, provider["max_concurrency"])),
            cache=cache,
            transport=transport,
        )

    async def get_estimates(self, ticker: str) -> EstimateSnapshot | None:
        ttl = self.rules["data_quality"]["cache_ttl_seconds"]["estimates"]
        result = await self.client.request_json_with_metadata(
            "GET",
            f"/analyst/{ticker}/forecast",
            cache_key=f"forecast:{ticker}",
            ttl_seconds=ttl,
            ticker=ticker,
        )
        if not isinstance(result.data, dict):
            raise ProviderError(
                self.name,
                "PROVIDER_BAD_RESPONSE",
                "Nasdaq analyst forecast response was not an object.",
                retryable=False,
                ticker=ticker,
                endpoint=f"{NASDAQ_API_BASE}/analyst/{ticker}/forecast",
            )
        return normalize_analyst_forecast(
            ticker,
            result.data,
            fetched_at=result.fetched_at,
            max_age_hours=self.rules["data_quality"]["staleness_hours"]["estimates"],
        )
