import asyncio

from fastapi.testclient import TestClient

from app.core.constants import MODEL_VERSION
from app.domain.enums import ScanStatus
from app.main import app
from app.orchestration.scan_pipeline import run_full_scan, scan_manager
from app.persistence.database import init_database


def test_fixture_trial_scan_completes_and_deduplicates():
    init_database()
    state = scan_manager.create()
    result = asyncio.run(run_full_scan(state.scan_run_id, "fixture"))
    assert result.status == ScanStatus.COMPLETED
    assert result.universe_count == 4
    assert result.error_count == 0
    assert len(result.opportunities) >= 3
    assert len({item.ticker for item in result.opportunities}) == len(result.opportunities)
    assert result.market_regime is not None
    assert all(item.scores.base_opportunity_score == sum(float(component.score or 0) for component in [item.scores.catalyst, item.scores.fundamental, item.scores.valuation, item.scores.technical, item.scores.revisions, item.scores.balance_sheet, item.scores.liquidity]) for item in result.opportunities)


def test_health_and_json_error_contract():
    with TestClient(app) as client:
        health = client.get("/api/v1/health")
        assert health.status_code == 200
        assert health.json()["model_version"] == MODEL_VERSION
        missing = client.get("/api/v1/scans/00000000-0000-0000-0000-000000000000")
        assert missing.status_code == 404
        payload = missing.json()["error"]
        assert payload["code"] == "SCAN_NOT_FOUND"
        assert "request_id" in payload


def test_persisted_opportunity_filters_and_market_regime():
    init_database()
    state = scan_manager.create()
    asyncio.run(run_full_scan(state.scan_run_id, "fixture"))
    with TestClient(app) as client:
        biotech = client.get("/api/v1/opportunities?biotech=true")
        assert biotech.status_code == 200
        assert biotech.json()["count"] == 1
        assert biotech.json()["data"][0]["ticker"] == "BIOCAT"
        body = biotech.json()
        assert body["scan_run_id"] is not None
        assert body["data_as_of"] is not None
        assert body["stale"] is False
        regime = client.get("/api/v1/market-regime")
        assert regime.status_code == 200
        assert regime.json()["regime"] == "GREEN"


def test_scan_api_can_be_disabled_for_hosted_deployments(monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setenv("SCAN_API_ENABLED", "false")
    get_settings.cache_clear()
    try:
        with TestClient(app) as client:
            response = client.post("/api/v1/scans")
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "SCAN_API_DISABLED"
    finally:
        monkeypatch.delenv("SCAN_API_ENABLED")
        get_settings.cache_clear()
