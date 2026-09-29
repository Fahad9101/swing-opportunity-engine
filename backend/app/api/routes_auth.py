"""Email one-time-code sign-in, relayed to Supabase Auth.

The iOS app never holds a Supabase key: it calls these endpoints, and the
server adds the publishable key when it forwards the request. Supabase issues
and rate-limits the codes and tokens; this API stores nothing.
"""
from __future__ import annotations

import httpx
from fastapi import APIRouter, Response
from pydantic import BaseModel, EmailStr, Field

from app.core.config import get_settings
from app.core.errors import SOEError


router = APIRouter(prefix="/auth", tags=["auth"])

TIMEOUT = httpx.Timeout(15.0)
# Tests swap in an httpx.MockTransport; production uses the default network transport.
TRANSPORT: httpx.AsyncBaseTransport | None = None


class EmailCodeRequest(BaseModel):
    email: EmailStr


class VerifyRequest(BaseModel):
    email: EmailStr
    code: str = Field(pattern=r"^\d{6,10}$")


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1, max_length=4096)


def _session(payload: dict) -> dict:
    user = payload.get("user") or {}
    return {"access_token": payload["access_token"], "refresh_token": payload["refresh_token"], "expires_in": payload.get("expires_in"), "token_type": payload.get("token_type", "bearer"), "user": {"id": user.get("id"), "email": user.get("email")}}


async def _supabase(path: str, body: dict, *, params: dict | None = None) -> dict:
    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_anon_key:
        raise SOEError("AUTH_NOT_CONFIGURED", "Sign-in is not configured on this server.", status_code=503)
    url = f"{settings.supabase_url.rstrip('/')}/auth/v1/{path}"
    headers = {"apikey": settings.supabase_anon_key, "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, transport=TRANSPORT) as client:
            response = await client.post(url, json=body, params=params, headers=headers)
    except httpx.HTTPError as exc:
        raise SOEError("AUTH_UPSTREAM_UNAVAILABLE", "The sign-in service is unreachable. Try again shortly.", retryable=True, status_code=502) from exc
    if response.status_code == 429:
        raise SOEError("AUTH_RATE_LIMITED", "Too many sign-in attempts. Wait a minute and try again.", retryable=True, status_code=429)
    if response.status_code >= 500:
        raise SOEError("AUTH_UPSTREAM_UNAVAILABLE", "The sign-in service had a problem. Try again shortly.", retryable=True, status_code=502)
    if response.status_code >= 400:
        raise SOEError("AUTH_REJECTED", "That code is invalid or has expired. Request a new one.", status_code=401)
    return response.json() if response.content else {}


@router.post("/email-code", status_code=204)
async def send_email_code(payload: EmailCodeRequest) -> Response:
    await _supabase("otp", {"email": payload.email, "create_user": True})
    return Response(status_code=204)


@router.post("/verify")
async def verify_email_code(payload: VerifyRequest) -> dict:
    return _session(await _supabase("verify", {"type": "email", "email": payload.email, "token": payload.code}))


@router.post("/refresh")
async def refresh_session(payload: RefreshRequest) -> dict:
    return _session(await _supabase("token", {"refresh_token": payload.refresh_token}, params={"grant_type": "refresh_token"}))
