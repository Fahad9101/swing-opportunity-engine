"""Verify Supabase Auth access tokens for per-user endpoints.

The iOS app signs in with Supabase Auth and sends the access token as
`Authorization: Bearer <jwt>`. The API only verifies it and reads the user id
(`sub`); it never issues tokens and holds no Supabase service key.
"""
from __future__ import annotations

from functools import lru_cache

import jwt
from fastapi import Header

from app.core.config import get_settings
from app.core.errors import SOEError


ASYMMETRIC_ALGORITHMS = ["ES256", "RS256", "EdDSA"]


@lru_cache
def _jwks_client(supabase_url: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(f"{supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json", cache_keys=True, lifespan=3600)


def _unauthorized(message: str) -> SOEError:
    return SOEError("AUTH_INVALID", message, status_code=401)


def verify_token(token: str) -> str:
    settings = get_settings()
    if not settings.supabase_url and not settings.supabase_jwt_secret:
        raise SOEError("AUTH_NOT_CONFIGURED", "Sign-in is not configured on this server.", status_code=503)
    try:
        algorithm = jwt.get_unverified_header(token).get("alg")
    except jwt.PyJWTError as exc:
        raise _unauthorized("The access token is malformed.") from exc
    options = {"require": ["exp", "sub"]}
    issuer = f"{settings.supabase_url.rstrip('/')}/auth/v1" if settings.supabase_url else None
    try:
        if algorithm == "HS256":
            if not settings.supabase_jwt_secret:
                raise _unauthorized("HS256 tokens are not accepted by this server.")
            claims = jwt.decode(token, settings.supabase_jwt_secret, algorithms=["HS256"], audience=settings.supabase_jwt_audience, issuer=issuer, options=options)
        elif algorithm in ASYMMETRIC_ALGORITHMS and settings.supabase_url:
            key = _jwks_client(settings.supabase_url).get_signing_key_from_jwt(token)
            claims = jwt.decode(token, key.key, algorithms=ASYMMETRIC_ALGORITHMS, audience=settings.supabase_jwt_audience, issuer=issuer, options=options)
        else:
            raise _unauthorized("The access token uses an unsupported signing algorithm.")
    except jwt.ExpiredSignatureError as exc:
        raise SOEError("AUTH_EXPIRED", "The access token has expired. Sign in again.", status_code=401) from exc
    except jwt.PyJWTError as exc:
        raise _unauthorized("The access token could not be verified.") from exc
    return str(claims["sub"])


def current_user_id(authorization: str | None = Header(default=None)) -> str:
    """FastAPI dependency: the Supabase user id from a valid bearer token."""
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise SOEError("AUTH_REQUIRED", "Sign in to use the watchlist.", status_code=401)
    return verify_token(token.strip())
