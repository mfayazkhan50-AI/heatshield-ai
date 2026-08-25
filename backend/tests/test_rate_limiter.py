"""
test_rate_limiter.py
====================
Deterministic sliding-window rate limiter tests — fake clock, zero sleeps.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.services.rate_limiter import SlidingWindowRateLimiter


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def limiter(clock):
    return SlidingWindowRateLimiter(max_requests=3, window_seconds=10.0, clock=clock)


class TestSlidingWindowUnit:
    def test_admits_up_to_limit(self, limiter):
        assert limiter.hit("ip").allowed is True
        assert limiter.hit("ip").allowed is True
        assert limiter.hit("ip").allowed is True

    def test_blocks_beyond_limit(self, limiter):
        for _ in range(3):
            limiter.hit("ip")

        decision = limiter.hit("ip")
        assert decision.allowed is False
        assert decision.remaining == 0

    def test_retry_after_counts_down(self, limiter, clock):
        for _ in range(3):
            limiter.hit("ip")

        clock.advance(4)
        decision = limiter.hit("ip")
        assert decision.allowed is False
        assert decision.retry_after_s == pytest.approx(6.0)

    def test_window_slides_open_again(self, limiter, clock):
        for _ in range(3):
            limiter.hit("ip")

        assert limiter.hit("ip").allowed is False

        clock.advance(11)
        decision = limiter.hit("ip")
        assert decision.allowed is True
        assert decision.remaining == 2

    def test_partial_expiry_restores_partial_capacity(self, limiter, clock):
        t0 = clock.now
        for _ in range(3):
            limiter.hit("ip")

        clock.advance(5)  # first hit at t0 is now outside the 10s window? No: 5 < 10
        assert limiter.hit("ip").allowed is False

        clock.advance(6)  # total 11s since t0 → earliest hit expired
        decision = limiter.hit("ip")
        assert decision.allowed is True

    def test_keys_are_isolated(self, limiter):
        for _ in range(3):
            limiter.hit("client-a")

        assert limiter.hit("client-b").allowed is True
        assert limiter.hit("client-a").allowed is False

    def test_invalid_configuration_rejected(self):
        with pytest.raises(ValueError):
            SlidingWindowRateLimiter(0, 10)

        with pytest.raises(ValueError):
            SlidingWindowRateLimiter(5, 0)

    def test_peek_does_not_consume(self, limiter):
        limiter.hit("ip")
        assert limiter.peek("ip") == 1
        assert limiter.peek("ip") == 1
        assert limiter.hit("ip").remaining == 1


class TestRateLimitHTTPIntegration:
    @pytest.fixture
    def limited_client(self, monkeypatch):
        from app.api import deps as api_deps
        from app.main import app

        monkeypatch.setattr(
            api_deps,
            "rate_limiter",
            SlidingWindowRateLimiter(max_requests=2, window_seconds=60),
        )

        return TestClient(app)

    def test_health_not_rate_limited(self, limited_client):
        """Health stays open (no dependency)."""
        for _ in range(5):
            assert limited_client.get("/api/health").status_code == 200

    def test_429_after_limit_with_headers(self, limited_client):
        for _ in range(2):
            resp = limited_client.post("/api/heatmap", json={})
            assert resp.status_code == 200

        blocked = limited_client.post("/api/heatmap", json={})
        assert blocked.status_code == 429
        body = blocked.json()
        assert body["detail"]["error"] == "rate_limited"
        assert "Retry-After" in blocked.headers

    def test_retry_after_is_positive_int(self, limited_client):
        limited_client.post("/api/heatmap", json={})
        limited_client.post("/api/heatmap", json={})
        blocked = limited_client.post("/api/heatmap", json={})

        assert int(blocked.headers["Retry-After"]) >= 1

    def test_streaming_mode_also_gated(self, limited_client):
        limited_client.post("/api/heatmap?stream=1", json={})
        limited_client.post("/api/heatmap?stream=1", json={})

        blocked = limited_client.post("/api/heatmap?stream=1", json={})
        assert blocked.status_code == 429
