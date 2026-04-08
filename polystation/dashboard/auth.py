"""Simple bearer token authentication for the dashboard API."""
from __future__ import annotations

import os

from fastapi import Depends, HTTPException, Request

_API_TOKEN = os.getenv("POLYSTATION_API_TOKEN", "")


def get_api_token() -> str:
    return _API_TOKEN


def require_auth(request: Request, token: str = Depends(get_api_token)) -> None:
    """FastAPI dependency that enforces bearer token auth on write endpoints.

    If POLYSTATION_API_TOKEN is not set, auth is disabled (local dev mode).
    """
    if not token:
        return  # Auth disabled

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(401, "Missing Authorization header")

    provided = auth_header[7:]  # Strip "Bearer "
    if provided != token:
        raise HTTPException(403, "Invalid API token")
