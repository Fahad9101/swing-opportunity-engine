"""Read-only presentation of stored catalysts and corporate events.

"Show, don't score": these helpers only label events for display (confirmed,
estimated or speculative, with source and last-checked time). They do not feed
any score, scanner, threshold or classification.
"""
from __future__ import annotations

from datetime import date

from app.persistence.orm_models import CatalystORM, CorporateEventORM


DISCLAIMER = "Screening tool, not financial advice."

# SOE's frozen A/B/C date confidence: A = confirmed exact date or narrow window,
# B = guided or estimated window, C = speculative or too coarse.
DATE_STATUS = {"A": "confirmed", "B": "estimated", "C": "speculative"}


def _iso(value) -> str | None:
    return value.isoformat() if value is not None and hasattr(value, "isoformat") else value


def _event_day(row: dict) -> str | None:
    return row["event_date"] or row["window_start"]


def present_catalyst(row: CatalystORM) -> dict:
    data = row.normalized_data or {}
    grade = row.grade if row.verified else "C"
    return {
        "ticker": row.ticker, "kind": "catalyst", "type": row.type, "title": row.title,
        "event_date": row.event_date, "window_start": data.get("window_start"), "window_end": data.get("window_end"),
        "timing": None, "status": DATE_STATUS.get(grade, "speculative"), "date_confidence": grade, "verified": row.verified,
        "source": row.source, "source_url": data.get("source_url"),
        "last_checked": data.get("fetched_at") or _iso(row.source_timestamp), "stale": bool(data.get("stale", False)),
        "summary": row.summary,
    }


def present_corporate_event(row: CorporateEventORM) -> dict:
    data = row.normalized_data or {}
    grade = data.get("date_confidence")
    if not row.verified:
        grade = "C"
    status = DATE_STATUS.get(grade) if grade else ("confirmed" if row.verified else "speculative")
    return {
        "ticker": row.ticker, "kind": "corporate_event", "type": row.type, "title": row.title,
        "event_date": row.event_date, "window_start": data.get("window_start"), "window_end": data.get("window_end"),
        "timing": row.timing, "status": status, "date_confidence": grade, "verified": row.verified,
        "source": row.source, "source_url": data.get("source_url"),
        "last_checked": _iso(row.fetched_at), "stale": row.stale,
        "summary": None,
    }


def present_events(catalysts: list[CatalystORM], events: list[CorporateEventORM]) -> list[dict]:
    """Merge both event tables, drop exact duplicates, and sort by date then ticker."""
    items = [present_catalyst(row) for row in catalysts] + [present_corporate_event(row) for row in events]
    seen: set[tuple] = set()
    unique = []
    for item in items:
        key = (item["ticker"], item["type"], _event_day(item), item["title"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return sorted(unique, key=lambda item: (_event_day(item) or "9999-12-31", item["ticker"]))


def in_window(item: dict, start: date, end: date) -> bool:
    """True when the event date, or any part of its estimated window, falls in [start, end]."""
    first = _event_day(item)
    if first is None:
        return False
    last = item["window_end"] or first
    return first <= end.isoformat() and last >= start.isoformat()
