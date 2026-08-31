from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx

from app.domain.schemas import CorporateEvent, FieldProvenance
from app.providers.errors import ProviderError


API_URL = "https://clinicaltrials.gov/api/v2/studies"


def normalize_trial_events(ticker: str, payload: dict[str, Any], *, fetched_at: datetime, horizon_days: int) -> list[CorporateEvent]:
    today, horizon = date.today(), date.today() + timedelta(days=horizon_days)
    events: list[CorporateEvent] = []
    for study in payload.get("studies") or []:
        protocol = study.get("protocolSection") or {}
        identification = protocol.get("identificationModule") or {}
        status = protocol.get("statusModule") or {}
        nct_id = identification.get("nctId")
        title = identification.get("briefTitle") or nct_id or "Clinical study"
        for key, event_type in (("primaryCompletionDateStruct", "CLINICAL_TRIAL_PRIMARY_COMPLETION"), ("completionDateStruct", "CLINICAL_TRIAL_COMPLETION")):
            struct = status.get(key) or {}
            value = struct.get("date")
            if not value:
                continue
            try:
                event_date = date.fromisoformat(value if len(value) == 10 else f"{value}-01" if len(value) == 7 else f"{value}-01-01")
            except ValueError:
                continue
            if not today <= event_date <= horizon:
                continue
            as_of = datetime.combine(event_date, datetime.min.time(), tzinfo=UTC)
            raw_field = f"protocolSection.statusModule.{key}.date"
            events.append(CorporateEvent(
                ticker=ticker, type=event_type, title=f"{title} ({nct_id})", event_date=event_date,
                timing=struct.get("type"), verified=True, source="ClinicalTrials.gov API v2",
                as_of=as_of, fetched_at=fetched_at, stale=False,
                field_provenance={"event_date": FieldProvenance(source="ClinicalTrials.gov API v2", as_of=as_of, fetched_at=fetched_at, raw_field=raw_field)},
            ))
    return events


class ClinicalTrialsProvider:
    name = "clinicaltrials_gov"

    def __init__(self, *, timeout_seconds: float = 20, transport: httpx.AsyncBaseTransport | None = None):
        self.timeout_seconds, self.transport = timeout_seconds, transport

    async def get_events(self, ticker: str, sponsor: str, horizon_days: int = 56) -> list[CorporateEvent]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds, transport=self.transport) as client:
                response = await client.get(API_URL, params={"query.spons": sponsor, "filter.overallStatus": "RECRUITING|NOT_YET_RECRUITING|ACTIVE_NOT_RECRUITING", "pageSize": 100, "format": "json"})
            response.raise_for_status()
            fetched_at = datetime.now(UTC)
            return normalize_trial_events(ticker, response.json(), fetched_at=fetched_at, horizon_days=horizon_days)
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderError(self.name, "CLINICAL_TRIALS_UNAVAILABLE", "ClinicalTrials.gov request failed.", retryable=True, ticker=ticker, endpoint=API_URL) from exc
