from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx

from app.domain.schemas import CorporateEvent, FieldProvenance
from app.providers.errors import ProviderError
from app.services.catalyst_evidence_service import annotate_catalyst_evidence, parse_public_date


API_URL = "https://clinicaltrials.gov/api/v2/studies"


def _canonical_sponsor(value: str | None) -> str:
    text = re.sub(r"[^a-z0-9 ]+", " ", (value or "").lower())
    tokens = [
        token
        for token in text.split()
        if token not in {"inc", "incorporated", "corp", "corporation", "company", "co", "ltd", "limited", "plc", "llc", "holdings", "holding"}
    ]
    return " ".join(tokens)


def _sponsor_matches(requested: str, actual: str | None) -> bool:
    expected = _canonical_sponsor(requested)
    observed = _canonical_sponsor(actual)
    if not expected or not observed:
        return False
    if expected in observed or observed in expected:
        return True
    expected_tokens = set(expected.split())
    observed_tokens = set(observed.split())
    overlap = expected_tokens & observed_tokens
    return len(overlap) >= min(2, len(expected_tokens), len(observed_tokens))


def normalize_trial_events(
    ticker: str,
    payload: dict[str, Any],
    *,
    fetched_at: datetime,
    horizon_days: int,
    sponsor: str | None = None,
) -> list[CorporateEvent]:
    today, horizon = date.today(), date.today() + timedelta(days=horizon_days)
    events: list[CorporateEvent] = []
    for study in payload.get("studies") or []:
        protocol = study.get("protocolSection") or {}
        identification = protocol.get("identificationModule") or {}
        status = protocol.get("statusModule") or {}
        sponsor_module = protocol.get("sponsorCollaboratorsModule") or {}
        lead_sponsor = (sponsor_module.get("leadSponsor") or {}).get("name")
        if sponsor and not _sponsor_matches(sponsor, lead_sponsor):
            continue
        nct_id = identification.get("nctId")
        title = identification.get("briefTitle") or nct_id or "Clinical study"
        for key, event_type in (
            ("primaryCompletionDateStruct", "CLINICAL_TRIAL_PRIMARY_COMPLETION"),
            ("completionDateStruct", "CLINICAL_TRIAL_COMPLETION"),
        ):
            struct = status.get(key) or {}
            value = str(struct.get("date") or "").strip()
            if not value:
                continue
            try:
                anchor, precision, window_start, window_end = parse_public_date(value)
            except (ValueError, TypeError):
                continue
            if window_end < today or window_start > horizon:
                continue
            as_of = datetime.combine(anchor, datetime.min.time(), tzinfo=UTC)
            raw_field = f"protocolSection.statusModule.{key}.date"
            provenance = {
                "event_date": FieldProvenance(
                    source="ClinicalTrials.gov API v2",
                    as_of=as_of,
                    fetched_at=fetched_at,
                    raw_field=raw_field,
                ),
                "window_start": FieldProvenance(
                    source="ClinicalTrials.gov API v2",
                    as_of=as_of,
                    fetched_at=fetched_at,
                    raw_field=raw_field,
                ),
                "window_end": FieldProvenance(
                    source="ClinicalTrials.gov API v2",
                    as_of=as_of,
                    fetched_at=fetched_at,
                    raw_field=raw_field,
                ),
            }
            base = CorporateEvent(
                ticker=ticker,
                type=event_type,
                title=f"{title} ({nct_id})",
                event_date=anchor,
                timing=struct.get("type"),
                verified=True,
                source="ClinicalTrials.gov API v2",
                as_of=as_of,
                fetched_at=fetched_at,
                stale=False,
                field_provenance=provenance,
            )
            events.append(
                annotate_catalyst_evidence(
                    base,
                    date_precision=precision,
                    window_start=window_start,
                    window_end=window_end,
                    catalyst_candidate=False,
                    evidence_status="TRIAL_MILESTONE_ONLY_NOT_A_READOUT",
                    source_url=f"https://clinicaltrials.gov/study/{nct_id}" if nct_id else None,
                )
            )
    events.sort(key=lambda item: (item.window_start or item.event_date, item.type, item.title))
    return events


class ClinicalTrialsProvider:
    name = "clinicaltrials_gov"

    def __init__(self, *, timeout_seconds: float = 20, transport: httpx.AsyncBaseTransport | None = None):
        self.timeout_seconds, self.transport = timeout_seconds, transport
        self._cache: dict[str, list[CorporateEvent]] = {}

    async def get_events(self, ticker: str, sponsor: str, horizon_days: int = 56) -> list[CorporateEvent]:
        cache_key = f"{ticker.upper()}::{_canonical_sponsor(sponsor)}::{horizon_days}"
        if cache_key in self._cache:
            return list(self._cache[cache_key])
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds, transport=self.transport) as client:
                response = await client.get(
                    API_URL,
                    params={
                        "query.spons": sponsor,
                        "filter.overallStatus": "RECRUITING|NOT_YET_RECRUITING|ACTIVE_NOT_RECRUITING|ENROLLING_BY_INVITATION",
                        "pageSize": 100,
                        "format": "json",
                    },
                )
            response.raise_for_status()
            fetched_at = datetime.now(UTC)
            events = normalize_trial_events(
                ticker,
                response.json(),
                fetched_at=fetched_at,
                horizon_days=horizon_days,
                sponsor=sponsor,
            )
            self._cache[cache_key] = events
            return list(events)
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderError(
                self.name,
                "CLINICAL_TRIALS_UNAVAILABLE",
                "ClinicalTrials.gov request failed.",
                retryable=True,
                ticker=ticker,
                endpoint=API_URL,
            ) from exc
