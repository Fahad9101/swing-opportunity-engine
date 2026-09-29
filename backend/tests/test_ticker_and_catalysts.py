import asyncio
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.main import app
from app.orchestration.scan_pipeline import run_full_scan, scan_manager
from app.persistence.database import init_database
from app.services.event_presenter import DISCLAIMER, in_window, present_catalyst, present_corporate_event, present_events


def _scan() -> None:
    init_database()
    state = scan_manager.create()
    asyncio.run(run_full_scan(state.scan_run_id, "fixture"))


def test_ticker_card_shows_score_breakdown_catalyst_provenance_and_disclaimer():
    _scan()
    with TestClient(app) as client:
        response = client.get("/api/v1/ticker/rerate")
    assert response.status_code == 200
    card = response.json()
    assert card["ticker"] == "RERATE"
    assert card["disclaimer"] == DISCLAIMER
    assert card["stale"] is False and card["data_as_of"] and card["scan_run_id"]
    assert card["on_shortlist"] is True
    breakdown = card["score_breakdown"]
    assert set(breakdown) >= {"catalyst", "fundamental", "valuation", "technical", "revisions", "balance_sheet", "liquidity", "opportunity_score"}
    assert breakdown["opportunity_score"] == card["opportunity_score"]
    assert card["scanners"] and card["market"]["source"] == "fixture"
    earnings = card["catalysts"][0]
    assert earnings["type"] == "EARNINGS"
    assert earnings["status"] == "confirmed"
    assert earnings["source"] == "synthetic_fixture"
    assert earnings["last_checked"]
    assert earnings["event_date"] == (date.today() + timedelta(days=18)).isoformat()


def test_ticker_card_404_for_ticker_outside_latest_scan():
    _scan()
    with TestClient(app) as client:
        response = client.get("/api/v1/ticker/NOPE")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "TICKER_NOT_IN_SCAN"


def test_catalyst_calendar_filters_by_window_ticker_and_status():
    _scan()
    with TestClient(app) as client:
        near = client.get("/api/v1/catalysts?days=20").json()
        wide = client.get("/api/v1/catalysts?days=40").json()
        growth = client.get("/api/v1/catalysts?days=40&ticker=growth").json()
        speculative = client.get("/api/v1/catalysts?days=40&status=speculative").json()
        shortlist = client.get("/api/v1/catalysts?days=40&shortlist_only=true").json()
        bad = client.get("/api/v1/catalysts?status=maybe")
    near_tickers = {item["ticker"] for item in near["data"]}
    assert "RERATE" in near_tickers and "GROWTH" not in near_tickers
    assert {"RERATE", "GROWTH"} <= {item["ticker"] for item in wide["data"]}
    assert {item["ticker"] for item in growth["data"]} == {"GROWTH"}
    assert speculative["count"] == 0
    assert shortlist["count"] <= wide["count"]
    assert wide["disclaimer"] == DISCLAIMER and wide["stale"] is False
    dates = [item["event_date"] or item["window_start"] for item in wide["data"]]
    assert dates == sorted(dates)
    assert bad.status_code == 422


def _catalyst(**overrides):
    now = datetime(2026, 9, 29, tzinfo=UTC)
    values = dict(ticker="ABC", type="EARNINGS", title="Q3 earnings", event_date="2026-10-20", grade="A", verified=True, source="nasdaq", source_timestamp=now, summary="s", normalized_data={"fetched_at": "2026-09-29T21:00:00Z", "window_start": None, "window_end": None})
    values.update(overrides)
    return SimpleNamespace(**values)


def _event(**overrides):
    now = datetime(2026, 9, 29, tzinfo=UTC)
    values = dict(ticker="ABC", type="EARNINGS", title="Q3 earnings", event_date="2026-10-20", timing="TIME_NOT_SUPPLIED", verified=True, source="nasdaq", fetched_at=now, stale=False, normalized_data={"date_confidence": "B"})
    values.update(overrides)
    return SimpleNamespace(**values)


def test_presenter_labels_confirmed_estimated_and_speculative():
    assert present_catalyst(_catalyst())["status"] == "confirmed"
    assert present_catalyst(_catalyst(grade="B"))["status"] == "estimated"
    assert present_catalyst(_catalyst(verified=False))["status"] == "speculative"
    assert present_corporate_event(_event())["status"] == "estimated"
    assert present_corporate_event(_event(normalized_data={}))["status"] == "confirmed"
    assert present_corporate_event(_event(verified=False))["status"] == "speculative"
    assert present_corporate_event(_event())["last_checked"] == "2026-09-29T00:00:00+00:00"


def test_presenter_dedupes_and_windows_events():
    merged = present_events([_catalyst()], [_event(), _event(ticker="XYZ", event_date="2026-10-01")])
    assert [item["ticker"] for item in merged] == ["XYZ", "ABC"]
    windowed = present_catalyst(_catalyst(event_date=None, normalized_data={"window_start": "2026-10-25", "window_end": "2026-11-15"}))
    assert in_window(windowed, date(2026, 11, 1), date(2026, 11, 5))
    assert not in_window(windowed, date(2026, 10, 1), date(2026, 10, 10))
    assert not in_window(present_catalyst(_catalyst(event_date=None)), date(2026, 1, 1), date(2027, 1, 1))
