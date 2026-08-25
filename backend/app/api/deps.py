"""
deps.py
=======
Shared FastAPI dependencies (rate limiting) used by both the SSE agent
route and the heatmap router. Kept out of main.py to stay import-cycle
free.
"""

from __future__ import annotations

import os

from fastapi import HTTPException, Request

from app.services.rate_limiter import RateLimitDecision, SlidingWindowRateLimiter

RATE_LIMIT_MAX = int(os.getenv("RATE_LIMIT_MAX", "60"))
RATE_LIMIT_WINDOW_S = float(os.getenv("RATE_LIMIT_WINDOW_S", "60"))

rate_limiter = SlidingWindowRateLimiter(
    max_requests=RATE_LIMIT_MAX,
    window_seconds=RATE_LIMIT_WINDOW_S,
)


async def enforce_rate_limit(request: Request) -> None:
    """
    Guard every /api data route with a sliding window keyed by client IP.
    Emits standard 429s with Retry-After so well-behaved clients back off.
    """
    client_ip = request.client.host if request.client else "anonymous"

    decision: RateLimitDecision = rate_limiter.hit(client_ip)

    if not decision.allowed:
        raise HTTPException(
            status_code=429,
            detail={
                "error": "rate_limited",
                "message": (
                    "Too many requests — sliding window "
                    f"({decision.limit}/{int(RATE_LIMIT_WINDOW_S)}s) exhausted."
                ),
                "retry_after_s": decision.retry_after_s,
            },
            headers={
                "Retry-After": str(max(1, int(decision.retry_after_s) or 1))
            },
        )
