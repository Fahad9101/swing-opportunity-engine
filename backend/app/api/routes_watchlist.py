from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Body, Depends, Response
from pydantic import BaseModel, Field

from app.core.auth import current_user_id
from app.core.errors import SOEError
from app.core.freshness import is_stale
from app.persistence.database import SessionLocal
from app.persistence.repositories import ScanRepository, WatchlistRepository
from app.services.event_presenter import DISCLAIMER, in_window, present_events


router = APIRouter(tags=["watchlist"])

MAX_ITEMS = 100
UPCOMING_DAYS = 90
TICKER_PATTERN = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")


class WatchlistNote(BaseModel):
    note: str | None = Field(default=None, max_length=500)


def _ticker(symbol: str) -> str:
    ticker = symbol.strip().upper()
    if not TICKER_PATTERN.match(ticker): raise SOEError("INVALID_TICKER", f"{symbol!r} is not a valid ticker.", status_code=422)
    return ticker


def _item(row) -> dict:
    return {"ticker": row.ticker, "note": row.note, "added_at": row.added_at.isoformat()}


@router.get("/watchlist")
def watchlist(user_id: str = Depends(current_user_id)) -> dict:
    today = datetime.now(UTC).date()
    with SessionLocal() as session:
        rows = WatchlistRepository(session, user_id).items()
        items = [_item(row) for row in rows]
        scans = ScanRepository(session)
        run = scans.latest_completed_run()
        tickers = {item["ticker"] for item in items}
        if run is not None and tickers:
            scores = scans.opportunity_scores(run.id, tickers)
            upcoming = [event for event in present_events(*scans.run_events(run.id, tickers=tickers)) if in_window(event, today, today + timedelta(days=UPCOMING_DAYS))]
        else:
            scores, upcoming = {}, []
    for item in items:
        item["on_shortlist"] = item["ticker"] in scores
        item["opportunity_score"] = scores.get(item["ticker"])
        item["next_catalyst"] = next((event for event in upcoming if event["ticker"] == item["ticker"]), None)
    completed_at = run.completed_at if run is not None else None
    return {"scan_run_id": run.id if run else None, "data_as_of": completed_at.isoformat() if completed_at else None, "stale": is_stale(completed_at), "disclaimer": DISCLAIMER, "count": len(items), "data": items}


@router.put("/watchlist/{symbol}")
def add_to_watchlist(symbol: str, response: Response, payload: WatchlistNote | None = Body(default=None), user_id: str = Depends(current_user_id)) -> dict:
    ticker = _ticker(symbol)
    with SessionLocal() as session:
        repository = WatchlistRepository(session, user_id)
        if repository.get(ticker) is None and repository.count() >= MAX_ITEMS:
            raise SOEError("WATCHLIST_FULL", f"A watchlist holds at most {MAX_ITEMS} tickers.", status_code=409)
        row, created = repository.upsert(ticker, payload.note if payload else None)
        item = _item(row)
    response.status_code = 201 if created else 200
    return item


@router.delete("/watchlist/{symbol}", status_code=204)
def remove_from_watchlist(symbol: str, user_id: str = Depends(current_user_id)) -> Response:
    ticker = _ticker(symbol)
    with SessionLocal() as session:
        if not WatchlistRepository(session, user_id).remove(ticker):
            raise SOEError("NOT_ON_WATCHLIST", f"{ticker} is not on your watchlist.", status_code=404)
    return Response(status_code=204)
