"""
rate_limiter.py
===============
Deterministic sliding-window rate limiter (per identity: IP or API token).

The window is a deque of monotonic timestamps; a request is admitted when
fewer than `max_requests` timestamps fall inside the trailing
`window_seconds`. The clock is injected, making the limiter fully
deterministic under test — no sleeps required.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from typing import Callable, Deque, Dict, List


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    remaining: int
    retry_after_s: float
    limit: int


class SlidingWindowRateLimiter:
    """Sliding-window counter keyed by arbitrary identity strings."""

    def __init__(
        self,
        max_requests: int,
        window_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_requests < 1:
            raise ValueError("max_requests must be >= 1")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be > 0")

        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._clock = clock
        self._hits: Dict[str, Deque[float]] = {}

    def _prune(self, key: str, now: float) -> Deque[float]:
        window = self._hits.setdefault(key, deque())
        cutoff = now - self.window_seconds

        while window and window[0] <= cutoff:
            window.popleft()

        return window

    def hit(self, key: str) -> RateLimitDecision:
        """Record one hit for `key` and decide admission."""
        now = self._clock()
        window = self._prune(key, now)

        if len(window) >= self.max_requests:
            retry_after = max(0.0, (window[0] + self.window_seconds) - now)
            return RateLimitDecision(
                allowed=False,
                remaining=0,
                retry_after_s=round(retry_after, 3),
                limit=self.max_requests,
            )

        window.append(now)
        remaining = self.max_requests - len(window)

        return RateLimitDecision(
            allowed=True,
            remaining=remaining,
            retry_after_s=0.0,
            limit=self.max_requests,
        )

    def peek(self, key: str) -> int:
        """Current in-window usage without recording a hit."""
        now = self._clock()
        return len(self._prune(key, now))

    def reset(self) -> None:
        self._hits.clear()

    def tracked_identities(self) -> List[str]:
        return list(self._hits.keys())
