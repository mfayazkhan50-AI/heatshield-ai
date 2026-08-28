"""
test_ndjson_stream.py
=====================
End-to-end tests for POST /api/heatmap?stream=1 — the NDJSON progress
contract the frontend consumes:

    meta → cache → progress* → fallback? → cells* → result
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient


def parse_ndjson(text: str):
    lines = [ln for ln in text.split("\n") if ln.strip()]
    return [json.loads(ln) for ln in lines]


class TestNDJSONStream:
    def test_stream_returns_ndjson_content_type(self, client_no_lifespan):
        resp = client_no_lifespan.post("/api/heatmap?stream=1", json={})
        assert resp.status_code == 200
        assert "ndjson" in resp.headers["content-type"]
        assert "x-activity-id" in {k.lower() for k in resp.headers}

    def test_every_line_is_valid_json(self, client_no_lifespan):
        resp = client_no_lifespan.post("/api/heatmap?stream=1", json={})
        events = parse_ndjson(resp.text)
        assert len(events) >= 3

    def test_event_order_contract(self, client_no_lifespan):
        """
        With no FortyGuard key configured the ladder is:
            meta → cache(miss) → fallback → cells* → result
        """
        resp = client_no_lifespan.post("/api/heatmap?stream=1", json={})
        events = parse_ndjson(resp.text)

        types = [e["type"] for e in events]

        assert types[0] == "meta"
        assert "cache" in types
        assert "fallback" in types
        assert types[-1] == "result"

        cache_idx = types.index("cache")
        fallback_idx = types.index("fallback")
        result_idx = len(types) - 1

        assert cache_idx < fallback_idx < result_idx

    def test_result_payload_completeness(self, client_no_lifespan):
        resp = client_no_lifespan.post(
            "/api/heatmap?stream=1",
            json={"location_name": "Thermal, CA"},
        )
        events = parse_ndjson(resp.text)

        result = next(e for e in events if e["type"] == "result")
        payload = result["payload"]

        for key in (
            "activity_id",
            "location_name",
            "source",
            "peak_temp_f",
            "tile_count",
            "risk_breakdown",
            "osha_bin",
            "generated_at",
        ):
            assert key in payload, f"result payload missing {key}"

    def test_risk_breakdown_is_embedded_and_deterministic(self, client_no_lifespan):
        """The stream must carry the transparent scoring artifact."""
        resp = client_no_lifespan.post(
            "/api/heatmap?stream=1",
            json={"location_name": "Thermal, CA", "force_refresh": True},
        )
        payload = parse_ndjson(resp.text)[-1]["payload"]

        breakdown = payload["risk_breakdown"]
        assert 0.0 <= breakdown["response_gap"] <= 10.0
        assert breakdown["formula_expression"] == (
            "R = 0.40·Heat_Exposure + 0.35·Vulnerability_Index "
            "+ 0.25·Resource_Deficit"
        )
        assert len(breakdown["components"]) == 3

    def test_cells_chunks_cover_full_grid(self, client_no_lifespan):
        resp = client_no_lifespan.post(
            "/api/heatmap?stream=1",
            json={"cells_per_side": 12},
        )
        events = parse_ndjson(resp.text)

        cell_events = [e for e in events if e["type"] == "cells"]
        total_cells = sum(len(e["cells"]) for e in cell_events)
        result_payload = events[-1]["payload"]

        assert total_cells == result_payload["tile_count"] == 144

        # Chunk bookkeeping must be coherent.
        assert cell_events[0]["chunk"] == 0
        assert cell_events[-1]["of"] == len(cell_events)

    def test_cell_shape(self, client_no_lifespan):
        resp = client_no_lifespan.post("/api/heatmap?stream=1", json={})
        events = parse_ndjson(resp.text)

        first_cells = next(e for e in events if e["type"] == "cells")["cells"]
        cell = first_cells[0]

        for key in ("lat", "lon", "temp_f", "temp_c", "intensity", "class"):
            assert key in cell

        assert cell["class"] in ("SAFE", "WARM", "HOT", "CRITICAL")
        assert 0.0 <= cell["intensity"] <= 1.0


class TestFallbackEvent:
    def test_fallback_reason_and_banner_message(self, client_no_lifespan, monkeypatch):
        monkeypatch.delenv("FORTYGUARD_API_KEY", raising=False)

        resp = client_no_lifespan.post("/api/heatmap?stream=1", json={})
        events = parse_ndjson(resp.text)

        fallback = next(e for e in events if e["type"] == "fallback")
        assert fallback["reason"] == "no_key"
        assert "SIMULATED FIELD / DATA ACTIVE" in fallback["message"]

        result = events[-1]
        assert result["payload"]["source"] == "simulated"
        assert result["payload"]["fallback_reason"] == "no_key"


class TestCacheBehavior:
    def test_second_request_hits_cache(self, client_no_lifespan):
        body = {"latitude": 40.71, "longitude": -74.00}  # unique coords

        first = client_no_lifespan.post("/api/heatmap?stream=1", json=body)
        events1 = parse_ndjson(first.text)
        assert any(e["type"] == "cache" and e["hit"] is False for e in events1)

        second = client_no_lifespan.post("/api/heatmap?stream=1", json=body)
        events2 = parse_ndjson(second.text)

        cache_events = [e for e in events2 if e["type"] == "cache"]
        assert len(cache_events) == 1
        assert cache_events[0]["hit"] is True

        # Cached replay returns immediately with a result AND re-streams the
        # persisted grid (cells live in their own NDJSON frames, so a cache
        # hit that skips the live path must still hand the canvas its tiles).
        assert events2[-1]["type"] == "result"
        cells_events = [e for e in events2 if e["type"] == "cells"]
        assert len(cells_events) >= 1
        assert cells_events[0]["chunk"] == 0
        assert len(cells_events[0]["cells"]) > 0

    def test_force_refresh_bypasses_cache(self, client_no_lifespan):
        body = {
            "latitude": 40.72,
            "longitude": -74.01,
            "force_refresh": True,
        }

        for _ in range(2):
            resp = client_no_lifespan.post("/api/heatmap?stream=1", json=body)
            events = parse_ndjson(resp.text)
            assert any(e["type"] == "cache" and e["hit"] is False for e in events)


class TestNonStreamingMode:
    def test_plain_json_mode(self, client_no_lifespan):
        resp = client_no_lifespan.post(
            "/api/heatmap",
            json={"latitude": 41.88, "longitude": -87.63, "force_refresh": True},
        )
        assert resp.status_code == 200

        payload = resp.json()
        assert payload["tile_count"] > 0
        assert len(payload["cells"]) == payload["tile_count"]
        assert "risk_breakdown" in payload
