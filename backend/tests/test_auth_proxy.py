import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api import routes_auth
from app.core.config import get_settings
from app.main import app


SUPABASE_URL = "https://example-project.supabase.co"
SESSION = {"access_token": "access.jwt", "refresh_token": "refresh-1", "expires_in": 3600, "token_type": "bearer", "user": {"id": "user-1", "email": "fahad@example.com", "role": "authenticated"}}


@pytest.fixture
def supabase(monkeypatch):
    calls = []
    responses = {}

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        status, body = responses.get(request.url.path, (200, {}))
        return httpx.Response(status, json=body)

    monkeypatch.setenv("SUPABASE_URL", SUPABASE_URL)
    monkeypatch.setenv("SUPABASE_ANON_KEY", "publishable-key")
    monkeypatch.setattr(routes_auth, "TRANSPORT", httpx.MockTransport(handler))
    get_settings.cache_clear()
    yield calls, responses
    get_settings.cache_clear()


def test_email_code_is_relayed_with_server_side_key(supabase):
    calls, _ = supabase
    with TestClient(app) as client:
        response = client.post("/api/v1/auth/email-code", json={"email": "fahad@example.com"})
    assert response.status_code == 204
    request = calls[-1]
    assert f"{request.url.scheme}://{request.url.host}{request.url.path}" == f"{SUPABASE_URL}/auth/v1/otp"
    assert request.url.params["redirect_to"] == "swingscreener://auth-callback"
    assert request.headers["apikey"] == "publishable-key"
    assert json.loads(request.content) == {"email": "fahad@example.com", "create_user": True}


def test_verify_returns_a_trimmed_session(supabase):
    calls, responses = supabase
    responses["/auth/v1/verify"] = (200, SESSION)
    with TestClient(app) as client:
        response = client.post("/api/v1/auth/verify", json={"email": "fahad@example.com", "code": "123456"})
    assert response.status_code == 200
    assert response.json() == {"access_token": "access.jwt", "refresh_token": "refresh-1", "expires_in": 3600, "token_type": "bearer", "user": {"id": "user-1", "email": "fahad@example.com"}}
    assert json.loads(calls[-1].content) == {"type": "email", "email": "fahad@example.com", "token": "123456"}


def test_refresh_uses_refresh_grant(supabase):
    calls, responses = supabase
    responses["/auth/v1/token"] = (200, SESSION)
    with TestClient(app) as client:
        response = client.post("/api/v1/auth/refresh", json={"refresh_token": "refresh-0"})
    assert response.status_code == 200 and response.json()["access_token"] == "access.jwt"
    assert calls[-1].url.params["grant_type"] == "refresh_token"


@pytest.mark.parametrize(("status", "code", "http"), [(400, "AUTH_REJECTED", 401), (403, "AUTH_REJECTED", 401), (429, "AUTH_RATE_LIMITED", 429), (500, "AUTH_UPSTREAM_UNAVAILABLE", 502)])
def test_upstream_errors_map_to_clear_codes(supabase, status, code, http):
    _, responses = supabase
    responses["/auth/v1/verify"] = (status, {"msg": "upstream detail"})
    with TestClient(app) as client:
        response = client.post("/api/v1/auth/verify", json={"email": "fahad@example.com", "code": "123456"})
    assert response.status_code == http
    assert response.json()["error"]["code"] == code
    assert "upstream detail" not in response.text


def test_input_is_validated_before_calling_supabase(supabase):
    calls, _ = supabase
    with TestClient(app) as client:
        assert client.post("/api/v1/auth/email-code", json={"email": "not-an-email"}).status_code == 422
        assert client.post("/api/v1/auth/verify", json={"email": "fahad@example.com", "code": "12ab"}).status_code == 422
    assert calls == []


def test_sign_in_unconfigured_returns_503(monkeypatch):
    monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)
    get_settings.cache_clear()
    try:
        with TestClient(app) as client:
            response = client.post("/api/v1/auth/email-code", json={"email": "fahad@example.com"})
        assert response.status_code == 503 and response.json()["error"]["code"] == "AUTH_NOT_CONFIGURED"
    finally:
        get_settings.cache_clear()
