"""
test_agent_graph.py
===================
Integration tests for the full LangGraph run through the SSE endpoint:
deterministic scoring → grounded cascade → conditional dispatch gate.
"""

from __future__ import annotations

import json

from app.engine.scoring import score_response_gap
from app.services.dispatch import (
    compose_sms_text,
    compose_voice_script,
    dispatch_critical_alerts,
)
from app.services.llm_router import build_llm_prompt


class TestPromptGrounding:
    def test_prompt_embeds_deterministic_artifact(self):
        breakdown = score_response_gap(
            peak_temp_f=110.0,
            relative_humidity_pct=18.0,
            heat_index_f=112.0,
            consecutive_hours_above_40c=3.0,
            svi=0.9,
            population_density_per_km2=500,
            cooling_center_buffer_km=6.0,
            shade_coverage_pct=10.0,
            operation="roadwork",
        )

        state = {
            "fortyguard_data": {"temperature_f": 110.0, "relative_humidity_pct": 18.0},
            "heat_index_f": 112.0,
            "risk_level": "Danger",
            "location_name": "Thermal, CA",
            "risk_breakdown": breakdown,
        }

        prompt = build_llm_prompt(state)

        assert "DETERMINISTIC SCORING ARTIFACT" in prompt
        assert f"response_gap_R: {breakdown['response_gap']}" in prompt
        assert "MUST NOT compute" in prompt
        assert "immutable ground truth" in prompt

    def test_prompt_forbids_number_generation(self):
        prompt = build_llm_prompt(
            {"risk_breakdown": {}, "risk_level": "Warning", "heat_index_f": 95}
        )
        assert "MUST NOT compute, estimate, alter or invent ANY number" in prompt


class TestDispatchGate:
    def test_blank_contacts_env_falls_back_to_defaults(self, monkeypatch):
        """
        `HEATSHIELD_SUPERVISOR_CONTACTS=` (present but empty, as in .env)
        must behave like unset: fall back to demo contacts. Regression
        guard for the empty-string-vs-unset getenv bug that yielded zero
        records and a phantom dispatch_mode='live'.
        """
        from app.services.dispatch import supervisor_contacts

        monkeypatch.setenv("HEATSHIELD_SUPERVISOR_CONTACTS", "")
        contacts = supervisor_contacts()

        assert contacts, "blank env must fall back to defaults"
        assert all(c.startswith("+") for c in contacts)

    def test_dispatch_records_dry_run_previews(self):
        """
        Without Twilio credentials the dispatch node must still produce
        complete dry-run records (SMS + voice per contact) with previews —
        the demo-critical guarantee.
        """
        import asyncio

        breakdown = {
            "response_gap": 8.2,
            "risk_tier": "CRITICAL",
            "raw_inputs": {
                "peak_temp_f": 117.4,
                "consecutive_hours_above_40c": 5.5,
            },
        }

        records = asyncio.run(
            dispatch_critical_alerts(
                site_name="Thermal, CA",
                latitude=33.6,
                longitude=-116.1,
                breakdown=breakdown,
                activity_id="test-activity",
            )
        )

        assert len(records) >= 2  # at least one SMS + one voice

        channels = {r["channel"] for r in records}
        assert channels == {"sms", "voice"}

        for record in records:
            assert record["mode"] == "dry_run"
            assert record["status"] == "preview"
            assert record["preview"]
            assert record["activity_id"] == "test-activity"

    def test_sms_message_contains_score_and_directive(self):
        breakdown = {
            "response_gap": 8.2,
            "risk_tier": "CRITICAL",
            "raw_inputs": {
                "peak_temp_f": 117.4,
                "consecutive_hours_above_40c": 5.5,
            },
        }

        text = compose_sms_text("Thermal, CA", breakdown)

        assert "8.2/10" in text
        assert "CRITICAL" in text
        assert "117.4F" in text
        assert "Halt" in text or "halt" in text

    def test_voice_script_spoken_friendly(self):
        breakdown = {
            "response_gap": 7.4,
            "risk_tier": "CRITICAL",
            "raw_inputs": {},
        }
        script = compose_voice_script("Thermal, CA", breakdown)
        assert "7.4 out of 10" in script
        assert "40 degrees" in script


class TestSSEAgentRun:
    def test_full_stream_produces_result_with_breakdown(self, client):
        """End-to-end SSE run completes regardless of data availability.

        With FORTYGUARD_API_KEY configured the run ingests REAL live
        observations (source='live'); without it the deterministic engine
        produces a labeled simulated field (source='simulated'). Either way a
        valid risk breakdown is always produced and streamed.
        """

        resp = client.post(
            "/api/stream-agent",
            json={
                "thread_id": "test-e2e-1",
                "location_name": "Thermal, CA",
                "latitude": 33.6,
                "longitude": -116.1,
                "operation_context": "roadwork",
            },
        )
        assert resp.status_code == 200

        events = _parse_sse(resp.text)
        event_names = [name for name, _ in events]

        assert event_names[0] == "status"
        assert "result" in event_names
        assert event_names[-1] == "status"

        result_data = next(data for name, data in events if name == "result")

        enterprise = result_data["enterprise_output"]
        assert enterprise is not None
        # Live data is a feature (not a failure) when a key is present.
        assert enterprise["source"] in ("live", "simulated")

        breakdown = enterprise["risk_breakdown"]
        assert breakdown["risk_tier"] in ("NORMAL", "ELEVATED", "HIGH", "CRITICAL")
        assert len(breakdown["components"]) == 3

    def test_critical_run_triggers_dispatch_node(self, client):
        """
        The unfair advantage, pinned as a regression test: a CRITICAL run
        MUST route through the telephony dispatch node and attach records.
        """
        resp = client.post(
            "/api/stream-agent",
            json={
                "thread_id": "test-e2e-critical",
                "location_name": "Thermal, CA",
                "latitude": 33.6,
                "longitude": -116.1,
                "operation_context": "roadwork",
            },
        )

        events = _parse_sse(resp.text)

        node_events = [data for name, data in events if name == "node"]
        visited_nodes = {n["name"] for n in node_events}

        assert "dispatch_critical_alerts" in visited_nodes

        result_data = next(data for name, data in events if name == "result")
        enterprise = result_data["enterprise_output"]

        assert enterprise["dispatch_mode"] == "dry_run"
        assert len(enterprise["dispatch_records"]) >= 2
        assert enterprise["tactical_actions"], "numbered actions required"
        assert enterprise["tactical_actions"][0]["id"] == "01"

    def test_noncritical_run_skips_dispatch(self, client):
        resp = client.post(
            "/api/stream-agent",
            json={
                "thread_id": "test-e2e-miami",
                "location_name": "Miami, FL",
                "latitude": 25.76,
                "longitude": -80.19,
                "operation_context": "construction",
            },
        )

        events = _parse_sse(resp.text)
        result_data = next(data for name, data in events if name == "result")

        assert result_data["enterprise_output"]["dispatch_mode"] == "not_triggered"

    def test_checkpointed_state_persists_per_thread(self, client):
        """Thread state must be retrievable after a completed run."""
        resp = client.post(
            "/api/stream-agent",
            json={
                "thread_id": "test-e2e-persist",
                "location_name": "Phoenix, AZ",
                "latitude": 33.45,
                "longitude": -112.07,
                "operation_context": "construction",
            },
        )
        assert resp.status_code == 200

        thread_resp = client.get("/api/thread/test-e2e-persist")
        assert thread_resp.status_code == 200

        state = thread_resp.json()
        assert state["risk_breakdown"]["risk_tier"]


def _parse_sse(text: str):
    """Parse an SSE body into [(event_name, json_data), ...]."""
    parsed = []

    for frame in text.split("\n\n"):
        if not frame.strip():
            continue

        event_name = None
        data_lines = []

        for line in frame.split("\n"):
            if line.startswith("event:"):
                event_name = line[6:].strip()
            elif line.startswith("data:"):
                data_lines.append(line[5:].lstrip())

        if event_name is None:
            continue

        raw = "\n".join(data_lines)

        try:
            data = json.loads(raw)
        except ValueError:
            data = raw

        parsed.append((event_name, data))

    return parsed
