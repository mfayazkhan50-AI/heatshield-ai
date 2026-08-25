"""
test_api_schemas.py
===================
Route-schema regression tests: malformed payloads must die at the
validation boundary (422) with actionable messages — never reach the graph.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


class TestHealth:
    def test_health_ok(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["service"] == "heatshield-ai-backend"


class TestCacheStatsEndpoint:
    def test_stats_shape(self, client):
        resp = client.get("/api/cache/stats")
        assert resp.status_code == 200

        stats = resp.json()
        for key in ("hits", "misses", "total_lookups", "hit_rate", "hot_entries"):
            assert key in stats


class TestStreamAgentSchema:
    def test_blank_thread_id_rejected(self, client):
        resp = client.post("/api/stream-agent", json={"thread_id": "   "})
        assert resp.status_code == 422

    def test_missing_thread_id_rejected(self, client):
        resp = client.post("/api/stream-agent", json={})
        assert resp.status_code == 422

    def test_latitude_out_of_range(self, client):
        resp = client.post(
            "/api/stream-agent",
            json={
                "thread_id": "t1",
                "latitude": 123.0,
                "longitude": 0.0,
            },
        )
        assert resp.status_code == 422

    def test_longitude_out_of_range(self, client):
        resp = client.post(
            "/api/stream-agent",
            json={
                "thread_id": "t2",
                "latitude": 0.0,
                "longitude": -999.0,
            },
        )
        assert resp.status_code == 422

    def test_invalid_operation_context_rejected(self, client):
        resp = client.post(
            "/api/stream-agent",
            json={
                "thread_id": "t3",
                "operation_context": "underwater_welding",
            },
        )
        assert resp.status_code == 422

    def test_valid_operation_contexts_accepted_at_schema_layer(self):
        """
        Schema-level acceptance check: valid bodies pass validation and are
        routed into the handler (which streams; we assert non-422).
        Uses a short-lived connection aborted after headers arrive.
        """
        with TestClient(app) as c:
            resp = c.post(
                "/api/stream-agent",
                json={
                    "thread_id": "schema-accept-1",
                    "location_name": "Phoenix, AZ",
                    "operation_context": "delivery",
                },
            )
            # SSE stream begins (200) — schema accepted the request.
            assert resp.status_code == 200

    def test_byok_key_max_length_enforced(self, client):
        resp = client.post(
            "/api/stream-agent",
            json={
                "thread_id": "t4",
                "byok_key": "x" * 300,
            },
        )
        assert resp.status_code == 422

    def test_validation_errors_are_actionable(self, client):
        resp = client.post("/api/stream-agent", json={"thread_id": ""})
        detail = resp.json()["detail"]

        msgs = " ".join(d["msg"] for d in detail)
        assert "thread_id" in str(detail).lower() or "blank" in msgs.lower()


class TestHeatmapSchema:
    def test_default_body_accepted(self, client_no_lifespan):
        resp = client_no_lifespan.post("/api/heatmap", json={})
        assert resp.status_code == 200

    def test_latitude_bounds(self, client_no_lifespan):
        resp = client_no_lifespan.post(
            "/api/heatmap",
            json={"latitude": 91.0},
        )
        assert resp.status_code == 422

    def test_cells_per_side_bounded(self, client_no_lifespan):
        resp = client_no_lifespan.post(
            "/api/heatmap",
            json={"cells_per_side": 500},
        )
        assert resp.status_code == 422

        ok = client_no_lifespan.post(
            "/api/heatmap",
            json={"cells_per_side": 12, "force_refresh": True},
        )
        assert ok.status_code == 200
        assert ok.json()["tile_count"] == 144


class TestThreadEndpoint:
    def test_unknown_thread_404(self, client):
        resp = client.get("/api/thread/definitely-not-a-real-thread")
        assert resp.status_code == 404
