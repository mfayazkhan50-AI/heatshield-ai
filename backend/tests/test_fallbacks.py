"""
test_fallbacks.py
=================
Resilience-ladder regression tests: the product must NEVER freeze or blank
out, whatever the provider layer does.
"""

from __future__ import annotations

import httpx
import pytest

from app.services import fortyguard
from app.services.climate_normals import (
    CITY_CLIMATE_NORMALS,
    build_micro_grid,
    classify_cell_temp,
    consecutive_hours_estimate,
    get_city_normal,
    synthesize_simulated_field,
)
from app.services.llm_router import (
    STATIC_THRESHOLDS,
    deterministic_plan,
    parse_llm_json,
)
from app.services.observation_cache import ObservationCache


# ---------------------------------------------------------------------------
# FortyGuard client guards
# ---------------------------------------------------------------------------

class TestPayloadNormalization:
    def test_valid_payload_normalized(self):
        frame = fortyguard.normalize_payload(
            {"temperature_f": 108.2, "relative_humidity_pct": 15.0}
        )
        assert frame is not None
        assert frame["temperature_f"] == 108.2
        assert frame["source"] == "live"

    def test_zero_cells_payload_rejected(self):
        assert fortyguard.normalize_payload({"temperature_f": None}) is None
        assert fortyguard.normalize_payload({}) is None
        assert fortyguard.normalize_payload("garbage") is None

    def test_cells_array_peak_extracted(self):
        payload = {
            "cells": [
                {"temp_f": 100.0},
                {"temp_f": 112.4},
                {"temp_f": 98.0},
            ]
        }
        frame = fortyguard.normalize_payload(payload)
        assert frame is not None
        assert frame["temperature_f"] == 112.4

    @pytest.mark.asyncio
    async def test_no_key_short_circuits_to_fallback(self, monkeypatch):
        monkeypatch.delenv("FORTYGUARD_API_KEY", raising=False)

        events = []
        results = []

        async for frame, meta in fortyguard.poll_live_frame(33.0, -112.0, on_progress=events.append):
            results.append((frame, meta))

        frame, meta = results[-1]
        assert frame is None
        assert meta["reason"] == "no_key"
        assert events == []  # never polled

    @pytest.mark.asyncio
    async def test_timeout_yields_progress_then_timeout(self, monkeypatch):
        """Every poll attempt must be visible to the progress stream."""

        monkeypatch.setenv("FORTYGUARD_API_KEY", "test-key-123")

        attempts_seen = []

        class FlakyClient:
            def __init__(self, *a, **kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def get(self, *a, **kw):
                raise httpx.TimeoutException("simulated hang")

        monkeypatch.setattr(fortyguard.httpx, "AsyncClient", FlakyClient)

        final = None
        async for frame, meta in fortyguard.poll_live_frame(
            33.0,
            -112.0,
            max_attempts=3,
            interval_s=0.0,
            attempt_timeout_s=0.1,
            total_deadline_s=5.0,
            on_progress=lambda e: attempts_seen.append(e),
        ):
            final = (frame, meta)

        frame, meta = final
        assert frame is None
        assert meta["reason"] in ("timeout", "error", "attempt_timeout:error")
        assert len(attempts_seen) == 3

        first_event = attempts_seen[0]
        assert first_event["status"] == "polling"
        assert first_event["attempt"] == 1
        assert first_event["max"] == 3

    @pytest.mark.asyncio
    async def test_success_on_retry(self, monkeypatch):
        """Attempt #1 fails, attempt #2 returns a valid payload → success."""

        monkeypatch.setenv("FORTYGUARD_API_KEY", "test-key-123")

        call_count = {"n": 0}

        class RecoveringClient:
            def __init__(self, *a, **kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def get(self, *a, **kw):
                call_count["n"] += 1
                if call_count["n"] == 1:
                    raise httpx.ConnectError("simulated outage")
                response = type("Resp", (), {})()
                response.raise_for_status = lambda: None
                response.json = lambda: {"temperature_f": 109.5}
                return response

        monkeypatch.setattr(fortyguard.httpx, "AsyncClient", RecoveringClient)

        frames = []
        metas = []
        async for frame, meta in fortyguard.poll_live_frame(
            33.0, -112.0, max_attempts=5, interval_s=0.0
        ):
            frames.append(frame)
            metas.append(meta)
            if frame is not None:
                break

        assert frames[-1]["temperature_f"] == 109.5
        assert metas[-1]["reason"] == "ok"
        assert metas[-1]["attempts"] == 2


# ---------------------------------------------------------------------------
# Climate-normal fallback synthesizer
# ---------------------------------------------------------------------------

class TestClimateNormals:
    def test_all_cities_have_required_profile_fields(self):
        for city, profile in CITY_CLIMATE_NORMALS.items():
            for field in (
                "normal_high_f",
                "normal_rh_pct",
                "svi",
                "population_density_per_km2",
                "cooling_center_buffer_km",
                "shade_coverage_pct",
                "provenance",
            ):
                assert field in profile, f"{city} missing {field}"

    def test_unknown_city_falls_back_to_default(self):
        profile = get_city_normal("Nowhere, ZZ")
        assert profile == get_city_normal("Phoenix, AZ")

    def test_grid_is_deterministic_across_calls(self):
        a = build_micro_grid(33.5, -112.0, 107.0, seed="x")
        b = build_micro_grid(33.5, -112.0, 107.0, seed="x")

        assert a["cells"] == b["cells"]

    def test_grid_tile_count_matches_side_squared(self):
        grid = build_micro_grid(33.5, -112.0, 107.0, cells_per_side=12)
        assert grid["tile_count"] == 144

    def test_grid_produces_spatial_gradient(self):
        """
        A usable heat map needs variety: not every cell may share one class.
        (Regression guard for the all-critical-grid defect.)
        """
        grid = build_micro_grid(33.5, -112.0, 107.0, seed="gradient")
        classes = {c["class"] for c in grid["cells"]}
        assert len(classes) >= 2

    def test_classify_thresholds(self):
        assert classify_cell_temp(104.0) == "CRITICAL"  # exactly 40°C
        assert classify_cell_temp(103.9) == "HOT"
        assert classify_cell_temp(95.0) == "WARM"
        assert classify_cell_temp(94.9) == "SAFE"

    def test_synthesized_field_labeled_simulated(self):
        package = synthesize_simulated_field(
            location_name="Thermal, CA",
            lat=33.6,
            lon=-116.1,
            fallback_reason="timeout",
        )

        frame = package["frame"]
        assert frame["source"] == "simulated"
        assert "SIMULATED" in str(frame["observed_at"]).upper() or frame[
            "observed_at"
        ].startswith("simulated:")
        assert package["grid"]["tile_count"] > 0

    def test_sustained_hours_estimate_bounded(self):
        assert consecutive_hours_estimate(150.0, 100.0) <= 10.0
        assert consecutive_hours_estimate(90.0, 100.0) == 0.0


# ---------------------------------------------------------------------------
# LLM output parsing robustness (Tier 1-4 surface)
# ---------------------------------------------------------------------------

class TestLLMJsonParsing:
    def test_plain_json(self):
        assert parse_llm_json('{"a": 1}') == {"a": 1}

    def test_markdown_fenced_json(self):
        text = '```json\n{"work_rest_cycle": "rest"}\n```'
        assert parse_llm_json(text) == {"work_rest_cycle": "rest"}

    def test_prose_wrapped_json(self):
        text = 'Here you go:\n{"hydration": "1L/h"} — thanks!'
        assert parse_llm_json(text) == {"hydration": "1L/h"}

    def test_garbage_raises_valueerror(self):
        with pytest.raises(ValueError):
            parse_llm_json("no json here at all")


# ---------------------------------------------------------------------------
# Tier 5 deterministic plan integrity
# ---------------------------------------------------------------------------

class TestDeterministicPlan:
    def test_every_osha_bin_has_plan(self):
        for tier in ("Low", "Caution", "Warning", "Danger", "Extreme Danger"):
            plan = deterministic_plan(tier)
            assert plan["work_rest_cycle"]
            assert plan["hydration_benchmark"]
            assert plan["escalation_protocol"]
            assert plan["generated_by_tier"].startswith("Tier 5")

    def test_unknown_bin_safe_default(self):
        plan = deterministic_plan("Bogus")
        assert plan["work_rest_cycle"]

    def test_plans_are_copies_not_shared_state(self):
        a = deterministic_plan("Danger")
        a["monitoring_indicators"].append("MUTATED")

        b = deterministic_plan("Danger")
        assert "MUTATED" not in b["monitoring_indicators"]


# ---------------------------------------------------------------------------
# Real live FortyGuard tOS Enterprise API (task-based env_params client)
# ---------------------------------------------------------------------------

class TestLiveEnvParamsClient:
    """The current FortyGuard API is task-based: POST /v1/env_params then poll
    GET /v1/status/{id}. Verify the submit → poll → normalize flow with a fake
    httpx.AsyncClient so no credits/network are needed."""

    def test_extract_live_temperatures_anchors_on_apparent_peak(self):
        # Real observed response shape: per-location parameter arrays in °C,
        # heat index pegged high but apparent temp is the physical hot-hour.
        result = {
            "metadata": {
                "timezone": "GMT-8",
                "time_range": {"count": 1},
                "timestamps": ["2026-08-26T15:00:00-08:00"],
            },
            "locations": [
                {
                    "lat": 33.635,
                    "lon": -116.135,
                    "temperature": 40.0,
                    "parameters": {
                        "heat_index_celsius": [37.1],
                        "apparent_temperature_celsius": [45.6],
                        "relative_humidity_percent": [10.9],
                    },
                }
            ],
        }

        frame = fortyguard._extract_live_temperatures(result)

        assert frame is not None
        assert frame["source"] == "live"
        # Therma1, CA ~15:00 apparent 45.6°C → 114.08°F
        assert abs(frame["temperature_f"] - 114.08) < 0.01
        assert abs(frame["heat_index_f"] - (37.1 * 9 / 5 + 32)) < 0.01
        assert frame["relative_humidity_pct"] == 10.9

    def test_extract_returns_none_when_no_signal(self):
        assert fortyguard._extract_live_temperatures({"locations": []}) is None
        assert fortyguard._extract_live_temperatures({"locations": [{"parameters": {}}]}) is None

    @pytest.mark.asyncio
    async def test_fetch_live_no_key_returns_none(self, monkeypatch):
        monkeypatch.delenv("FORTYGUARD_API_KEY", raising=False)
        frame, err = await fortyguard.fetch_live_env_params(33.6, -116.1)
        assert frame is None
        assert err is None

    @pytest.mark.asyncio
    async def test_fetch_live_submit_poll_success(self, monkeypatch):
        monkeypatch.setenv("FORTYGUARD_API_KEY", "test-key")
        monkeypatch.setattr(fortyguard, "ENV_TASK_DEADLINE_S", 30.0)

        status_calls = {"n": 0}

        class FakeClient:
            def __init__(self, *a, **kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def post(self, *a, **kw):
                resp = type("R", (), {})()
                resp.raise_for_status = lambda: None
                resp.json = lambda: {
                    "data": {"activity_id": "act-123"}
                }
                return resp

            async def get(self, *a, **kw):
                status_calls["n"] += 1
                resp = type("R", (), {})()
                resp.status_code = 200
                resp.raise_for_status = lambda: None
                if status_calls["n"] == 1:
                    resp.json = lambda: {"data": {"status": "Processing"}}
                else:
                    resp.json = lambda: {
                        "data": {
                            "status": "Completed",
                            "result": {
                                "locations": [
                                    {
                                        "parameters": {
                                            "apparent_temperature_celsius": [45.6],
                                            "heat_index_celsius": [37.1],
                                            "relative_humidity_percent": [10.9],
                                        }
                                    }
                                ]
                            },
                        }
                    }
                return resp

        monkeypatch.setattr(fortyguard.httpx, "AsyncClient", lambda *a, **kw: FakeClient())

        frame, err = await fortyguard.fetch_live_env_params(33.6, -116.1)

        assert err is None
        assert frame is not None
        assert frame["source"] == "live"
        assert frame["activity_id"] == "act-123"
        assert status_calls["n"] == 2  # one Processing + one Completed

    @pytest.mark.asyncio
    async def test_fetch_live_deadline_falls_back(self, monkeypatch):
        monkeypatch.setenv("FORTYGUARD_API_KEY", "test-key")
        monkeypatch.setattr(fortyguard, "ENV_TASK_DEADLINE_S", 0.0)

        class PendingClient:
            def __init__(self, *a, **kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def post(self, *a, **kw):
                resp = type("R", (), {})()
                resp.raise_for_status = lambda: None
                resp.json = lambda: {"data": {"activity_id": "act-x"}}
                return resp

            async def get(self, *a, **kw):
                resp = type("R", (), {})()
                resp.status_code = 200
                resp.raise_for_status = lambda: None
                resp.json = lambda: {"data": {"status": "Processing"}}
                return resp

        monkeypatch.setattr(fortyguard.httpx, "AsyncClient", lambda *a, **kw: PendingClient())

        frame, err = await fortyguard.fetch_live_env_params(33.6, -116.1)

        # Never raises; returns the fallback-safe (None, error) pair.
        assert frame is None
        assert err is not None
