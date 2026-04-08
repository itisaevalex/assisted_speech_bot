"""Simple in-memory rate limiter."""
from __future__ import annotations

import time
from collections import defaultdict

from fastapi import HTTPException, Request

_BUCKETS: dict[str, list[float]] = defaultdict(list)


def rate_limit(max_requests: int, window_seconds: int):
    """Returns a FastAPI dependency that rate-limits by client IP."""
    def check(request: Request):
        ip = request.client.host if request.client else "unknown"
        key = f"{ip}:{request.url.path}"
        now = time.time()
        # Clean old entries
        _BUCKETS[key] = [t for t in _BUCKETS[key] if t > now - window_seconds]
        if len(_BUCKETS[key]) >= max_requests:
            raise HTTPException(429, "Too many requests")
        _BUCKETS[key].append(now)
    return check
