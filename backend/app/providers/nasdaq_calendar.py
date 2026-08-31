from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import httpx

from app.domain.schemas import CorporateEvent, FieldProvenance
from app.providers.errors import ProviderError
from app.providers.http_client import ResilientJsonClient
from app.services.cache_service import JsonFileCache
from app.services.catalyst_evidence_service import annotate_catalyst_evidence


class NasdaqEarningsCalendar:
    name = "nasdaq_earnings_calendar"

    def __init__(self, *, cache: JsonFileCache, rules: dict[str, Any], transport: httpx.AsyncBaseTransport | None = None):
        quality = rules["data_quality"]
        provider = quality["provider"]
        self.rules = rules
        self.client = ResilientJsonClient(
            provider=self.name, base_url="https://api.nasdaq.com", headers={"User-Agent": "Mozilla/5.0 SOE/1.0"},
            timeout_seconds=provider["timeout_seconds"], max_retries=provider["max_retries"],
            initial_backoff_seconds=provider["initial_backoff_seconds"], max_concurrency=provider["max_concurrency"],
            cache=cache, transport=transport,
        )
        self._events: dict[str, list[CorporateEvent]] | None = None
        self.errors: list[dict[str, Any]] = []

    async def prefetch(self) -> None:
        if self._events is not None:
            return
        today = date.today()
        horizon = self.rules["catalyst"]["max_horizon_days"]
        ttl = self.rules["data_quality"]["cache_ttl_seconds"]["calendar"]
        max_age = self.rules["data_quality"]["staleness_hours"]["calendar"]
        mapping: dict[str, list[CorporateEvent]] = {}

        async def fetch(day: date):
            try:
                result = await self.client.request_json_with_metadata("GET", "/api/calendar/earnings", params={"date": day.isoformat()}, cache_key=f"earnings:{day}", ttl_seconds=ttl)
                return day, result, None
            except ProviderError as exc:
                return day, None, exc

        for offset in range(0, horizon + 1, 8):
            results = await asyncio.gather(*(fetch(today + timedelta(days=value)) for value in range(offset, min(offset + 8, horizon + 1))))
            for day, result, error in results:
                if error:
                    item = error.as_dict()
                    item["occurred_at"] = datetime.now(UTC).isoformat()
                    self.errors.append(item)
                    continue
                data = result.data if result and isinstance(result.data, dict) else {}
                rows = (((data.get("data") or {}).get("rows")) or [])
                as_of = datetime.combine(day, time.min, tzinfo=UTC)
                stale = datetime.now(UTC) - result.fetched_at > timedelta(hours=max_age)
                for row in rows:
                    ticker = str(row.get("symbol") or "").upper().replace(".", "-")
                    if not ticker:
                        continue
                    timing = {"time-pre-market": "PRE_MARKET", "time-after-hours": "AFTER_HOURS"}.get(row.get("time"), row.get("time"))
                    provenance = {field: FieldProvenance(source="Nasdaq Earnings Calendar", as_of=as_of, fetched_at=result.fetched_at, stale=stale, raw_field=raw) for field, raw in {"event_date": "query.date", "timing": "data.rows[].time", "title": "data.rows[].name"}.items()}
                    base = CorporateEvent(
                        ticker=ticker,
                        type="EARNINGS",
                        title=f"{row.get('name') or ticker} earnings",
                        event_date=day,
                        timing=timing,
                        verified=True,
                        source="Nasdaq Earnings Calendar",
                        as_of=as_of,
                        fetched_at=result.fetched_at,
                        stale=stale,
                        field_provenance=provenance,
                    )
                    event = annotate_catalyst_evidence(
                        base,
                        date_precision="DAY",
                        window_start=day,
                        window_end=day,
                        catalyst_candidate=True,
                        evidence_status="VERIFIED_EARNINGS_DATE_SCORE_INPUTS_INCOMPLETE",
                        source_url="https://www.nasdaq.com/market-activity/earnings",
                    )
                    mapping.setdefault(ticker, []).append(event)
        self._events = mapping

    async def get_events(self, ticker: str) -> list[CorporateEvent]:
        await self.prefetch()
        return list((self._events or {}).get(ticker.upper().replace(".", "-"), []))
