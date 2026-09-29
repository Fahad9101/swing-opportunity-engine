import asyncio
import time
import uuid
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from app.core import auth
from app.core.config import get_settings
from app.main import app
from app.orchestration.scan_pipeline import run_full_scan, scan_manager
from app.persistence.database import init_database


SUPABASE_URL = "https://example-project.supabase.co"
SECRET = "test-secret-with-at-least-32-bytes-of-length"


def _token(sub: str, *, key=SECRET, algorithm="HS256", audience="authenticated", issuer=f"{SUPABASE_URL}/auth/v1", expires_in=3600) -> str:
    claims = {"sub": sub, "aud": audience, "iss": issuer, "exp": int(time.time()) + expires_in}
    return jwt.encode(claims, key, algorithm=algorithm)


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _user(name: str) -> dict:
    # The test database persists between runs, so every run gets fresh users.
    return _auth(_token(f"{name}-{uuid.uuid4()}"))


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", SUPABASE_URL)
    monkeypatch.setenv("SUPABASE_JWT_SECRET", SECRET)
    get_settings.cache_clear()
    init_database()
    yield
    get_settings.cache_clear()


@pytest.fixture
def client(configured):
    with TestClient(app) as test_client:
        yield test_client


def test_watchlist_requires_a_valid_token(client):
    assert client.get("/api/v1/watchlist").json()["error"]["code"] == "AUTH_REQUIRED"
    assert client.get("/api/v1/watchlist", headers={"Authorization": "Basic abc"}).status_code == 401
    assert client.get("/api/v1/watchlist", headers=_auth("not-a-jwt")).json()["error"]["code"] == "AUTH_INVALID"
    assert client.get("/api/v1/watchlist", headers=_auth(_token("u1", expires_in=-60))).json()["error"]["code"] == "AUTH_EXPIRED"
    assert client.get("/api/v1/watchlist", headers=_auth(_token("u1", audience="anon"))).status_code == 401
    assert client.get("/api/v1/watchlist", headers=_auth(_token("u1", issuer="https://evil.example/auth/v1"))).status_code == 401
    assert client.get("/api/v1/watchlist", headers=_auth(_token("u1", key="wrong-secret-that-is-also-32-bytes-long"))).status_code == 401


def test_watchlist_returns_503_when_sign_in_is_not_configured(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_JWT_SECRET", raising=False)
    get_settings.cache_clear()
    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/watchlist", headers=_auth(_token("u1")))
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "AUTH_NOT_CONFIGURED"
    finally:
        get_settings.cache_clear()


def test_watchlist_add_update_remove_is_scoped_per_user(client):
    alice, bob = _user("alice"), _user("bob")
    created = client.put("/api/v1/watchlist/aapl", headers=alice, json={"note": "breakout watch"})
    assert created.status_code == 201 and created.json()["ticker"] == "AAPL"
    updated = client.put("/api/v1/watchlist/AAPL", headers=alice, json={"note": "earnings play"})
    assert updated.status_code == 200 and updated.json()["note"] == "earnings play"
    assert client.put("/api/v1/watchlist/MSFT", headers=alice).status_code == 201
    assert [item["ticker"] for item in client.get("/api/v1/watchlist", headers=alice).json()["data"]] == ["AAPL", "MSFT"]
    assert client.get("/api/v1/watchlist", headers=bob).json()["count"] == 0
    assert client.delete("/api/v1/watchlist/AAPL", headers=bob).status_code == 404
    assert client.delete("/api/v1/watchlist/AAPL", headers=alice).status_code == 204
    assert [item["ticker"] for item in client.get("/api/v1/watchlist", headers=alice).json()["data"]] == ["MSFT"]
    assert client.put("/api/v1/watchlist/not a ticker!", headers=alice).status_code == 422
    assert client.put("/api/v1/watchlist/AAPL", headers=alice, json={"note": "x" * 501}).status_code == 422


def test_watchlist_caps_items(client, monkeypatch):
    monkeypatch.setattr("app.api.routes_watchlist.MAX_ITEMS", 2)
    user = _user("cap")
    assert client.put("/api/v1/watchlist/AAA", headers=user).status_code == 201
    assert client.put("/api/v1/watchlist/BBB", headers=user).status_code == 201
    assert client.put("/api/v1/watchlist/BBB", headers=user, json={"note": "edit is fine"}).status_code == 200
    assert client.put("/api/v1/watchlist/CCC", headers=user).json()["error"]["code"] == "WATCHLIST_FULL"


def test_watchlist_items_show_latest_score_and_next_catalyst(client):
    state = scan_manager.create()
    asyncio.run(run_full_scan(state.scan_run_id, "fixture"))
    user = _user("enrich")
    client.put("/api/v1/watchlist/RERATE", headers=user)
    client.put("/api/v1/watchlist/ZZZZ", headers=user)
    body = client.get("/api/v1/watchlist", headers=user).json()
    assert body["stale"] is False and body["disclaimer"] and body["scan_run_id"]
    rerate, unknown = body["data"]
    assert rerate["on_shortlist"] is True and rerate["opportunity_score"] is not None
    assert rerate["next_catalyst"]["type"] == "EARNINGS" and rerate["next_catalyst"]["status"] == "confirmed"
    assert unknown == {**unknown, "on_shortlist": False, "opportunity_score": None, "next_catalyst": None}


def test_asymmetric_supabase_tokens_verify_through_jwks(client, monkeypatch):
    private_key = ec.generate_private_key(ec.SECP256R1())
    other_key = ec.generate_private_key(ec.SECP256R1())
    monkeypatch.setattr(auth, "_jwks_client", lambda url: SimpleNamespace(get_signing_key_from_jwt=lambda token: SimpleNamespace(key=private_key.public_key())))
    good = _token("es-user", key=private_key, algorithm="ES256")
    forged = _token("es-user", key=other_key, algorithm="ES256")
    assert client.get("/api/v1/watchlist", headers=_auth(good)).status_code == 200
    assert client.get("/api/v1/watchlist", headers=_auth(forged)).status_code == 401


def test_hs256_tokens_rejected_without_secret(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", SUPABASE_URL)
    monkeypatch.delenv("SUPABASE_JWT_SECRET", raising=False)
    get_settings.cache_clear()
    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/watchlist", headers=_auth(_token("u1")))
        assert response.status_code == 401
    finally:
        get_settings.cache_clear()
