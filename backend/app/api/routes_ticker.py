from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Query

from app.core.errors import SOEError
from app.core.freshness import is_stale
from app.persistence.database import SessionLocal
from app.persistence.repositories import ScanRepository
from app.services.event_presenter import DISCLAIMER, in_window, present_events


router = APIRouter(tags=["due-diligence"])


def _latest_run(repository: ScanRepository):
    run = repository.latest_completed_run()
    if run is None: raise SOEError("NO_COMPLETED_SCAN", "No completed scan is available.", status_code=404)
    return run


def _freshness(run) -> dict:
    return {"scan_run_id": run.id, "data_as_of": run.completed_at.isoformat() if run.completed_at else None, "stale": is_stale(run.completed_at)}


def _snapshot(row) -> dict | None:
    if row is None: return None
    return {"source": row.source, "as_of": row.as_of.isoformat(), "fetched_at": row.fetched_at.isoformat(), "stale": row.stale, "data": row.normalized_data}


@router.get("/ticker/{symbol}")
def ticker_card(symbol: str) -> dict:
    ticker = symbol.strip().upper()
    with SessionLocal() as session:
        repository = ScanRepository(session)
        run = _latest_run(repository)
        rows = repository.ticker_rows(run.id, ticker)
        if rows["market"] is None:
            raise SOEError("TICKER_NOT_IN_SCAN", f"{ticker} was not part of the latest completed scan.", status_code=404)
        instrument, opportunity = rows["instrument"], rows["opportunity"]
        audit = opportunity.audit_json if opportunity else None
        issues = [{"code": row.code, "severity": row.severity, "field": row.field, "message": row.message, "source": row.source} for row in rows["validation_issues"]]
        red_flags = []
        if audit:
            red_flags += [{"kind": "rejection", "code": code, "message": code} for code in audit.get("automatic_rejections", [])]
            red_flags += [{"kind": "penalty", "code": item["code"], "message": item["reason"], "points": item["points"]} for item in audit.get("penalties", [])]
        red_flags += [{"kind": "data_quality", "code": item["code"], "message": item["message"]} for item in issues if item["severity"] in {"WARNING", "ERROR"}]
        card = {
            **_freshness(run),
            "ticker": ticker,
            "disclaimer": DISCLAIMER,
            "company": instrument.company_name if instrument else None,
            "exchange": instrument.exchange if instrument else None,
            "sector": instrument.sector if instrument else None,
            "industry": instrument.industry if instrument else None,
            "market_cap": instrument.market_cap if instrument else None,
            "is_biotech": instrument.is_biotech if instrument else False,
            "on_shortlist": opportunity is not None,
            "opportunity_score": opportunity.opportunity_score if opportunity else None,
            "score_breakdown": audit["scores"] if audit else None,
            "data_completeness": audit["data_completeness"] if audit else None,
            "scanners": [{"scanner": row.scanner, "qualified": row.qualified, "conditions_met": row.conditions_met, "conditions_total": row.conditions_total, "evidence": row.evidence} for row in rows["scanner_matches"]],
            "catalysts": present_events(rows["catalysts"], rows["corporate_events"]),
            "red_flags": red_flags,
            "validation_issues": issues,
            "market": _snapshot(rows["market"]),
            "fundamentals": _snapshot(rows["fundamental"]),
            "estimates": _snapshot(rows["estimates"]),
        }
    return card


@router.get("/catalysts")
def catalyst_calendar(days: int = Query(30, ge=0, le=180), ticker: str | None = None, shortlist_only: bool = False, status: str | None = Query(None, pattern="^(confirmed|estimated|speculative)$"), limit: int = Query(200, ge=1, le=1000), offset: int = Query(0, ge=0)) -> dict:
    today = datetime.now(UTC).date()
    with SessionLocal() as session:
        repository = ScanRepository(session)
        run = _latest_run(repository)
        catalysts, events = repository.run_events(run.id, ticker.strip().upper() if ticker else None)
        shortlist = repository.shortlist_tickers(run.id) if shortlist_only else None
        items = [item for item in present_events(catalysts, events) if in_window(item, today, today + timedelta(days=days))]
    if shortlist is not None:
        items = [item for item in items if item["ticker"] in shortlist]
    if status is not None:
        items = [item for item in items if item["status"] == status]
    return {**_freshness(run), "disclaimer": DISCLAIMER, "from": today.isoformat(), "to": (today + timedelta(days=days)).isoformat(), "count": len(items), "limit": limit, "offset": offset, "data": items[offset: offset + limit]}
