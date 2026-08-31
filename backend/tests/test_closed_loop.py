"""
test_closed_loop.py
===================
Tests for the P0 closed-loop agent: intervention simulation, confidence,
incident/ack/escalation state machine, audit identity, response metrics,
multi-site prioritization, and the end-to-end closed-loop graph outcome.
"""

from __future__ import annotations

import pytest

from app.engine.audit import (
    decision_entry,
    dispatch_id,
    incident_id,
    response_metrics,
)
from app.engine.confidence import (
    assessment_overrides_decision,
    classify_confidence,
)
from app.engine.interventions import (
    select_best_intervention,
    simulate_all_interventions,
    simulate_intervention,
)
from app.engine.scoring import DISPATCH_THRESHOLD, score_response_gap
from app.services.incident import (
    Incident,
    IncidentState,
    open_incident,
)

BASE_INPUTS = dict(
    peak_temp_f=108.0, relative_humidity_pct=12.0, heat_index_f=112.0,
    consecutive_hours_above_40c=4.0, svi=0.97,
    population_density_per_km2=420, cooling_center_buffer_km=6.8,
    shade_coverage_pct=8.0, operation="construction",
)

CRITICAL = {"risk_tier": "CRITICAL", "response_gap": 8.4}
NORMAL = {"risk_tier": "NORMAL", "response_gap": 2.1}


def _breakdown(**overrides):
    return score_response_gap(**{**BASE_INPUTS, **overrides})


class FakeClock:
    def __init__(self, now_s=0.0):
        self._now = float(now_s)

    def now_s(self) -> float:
        return self._now

    def now_iso(self) -> str:
        return f"2026-01-01T00:00:{int(self._now) % 60:02d}Z"

    def advance(self, seconds: float) -> None:
        self._now += seconds


# ---------------------------------------------------------------------------
# Intervention simulation
# ---------------------------------------------------------------------------

class TestInterventionSimulation:
    def test_critical_breakdown_produces_simulations(self):
        sims = simulate_all_interventions(_breakdown())
        assert len(sims) >= 6
        for s in sims:
            assert s["status"] == "projected"
            assert s["effective"] is False  # never pre-claim success
            assert 0.0 <= s["prospective_improvement"] <= 1.0

    def test_every_project_labeled_as_projection(self):
        for s in simulate_all_interventions(_breakdown()):
            assert s["status"] == "projected"
            assert s["after"]["response_gap"] <= s["before"]["response_gap"] + 1e-6

    def test_deterministic_across_calls(self):
        a = simulate_all_interventions(_breakdown())
        b = simulate_all_interventions(_breakdown())
        assert a == b

    def test_sorted_by_improvement_descending(self):
        sims = simulate_all_interventions(_breakdown())
        improvements = [s["prospective_improvement"] for s in sims]
        assert improvements == sorted(improvements, reverse=True)

    def test_shade_raises_shade_coverage_and_lowers_gap(self):
        before = _breakdown()["response_gap"]
        sim = simulate_intervention(_breakdown(), "shade")
        assert sim is not None
        assert sim["projected_inputs"]["shade_coverage_pct"] > 8.0
        assert sim["after"]["response_gap"] < before

    def test_unknown_intervention_returns_none(self):
        assert simulate_intervention(_breakdown(), "teleport") is None

    def test_best_intervention_is_most_impactful(self):
        sims = simulate_all_interventions(_breakdown())
        best = select_best_intervention(_breakdown())
        assert best is not None
        assert best["key"] == sims[0]["key"]

    def test_no_simulations_for_normal_tier(self):
        # NORMAL/no-risk scenes need no mitigation simulation.
        normal_break = score_response_gap(
            peak_temp_f=88.0, relative_humidity_pct=40.0, heat_index_f=86.0,
            consecutive_hours_above_40c=0.0, svi=0.3,
            population_density_per_km2=800, cooling_center_buffer_km=1.0,
            shade_coverage_pct=50.0, operation="delivery",
        )
        assert simulate_all_interventions(normal_break) == []
        assert select_best_intervention(normal_break) is None


# ---------------------------------------------------------------------------
# Confidence
# ---------------------------------------------------------------------------

class TestConfidence:
    def test_live_full_inputs_high(self):
        c = classify_confidence(source="live", breakdown=_breakdown())
        assert c["level"] == "HIGH"
        assert c["is_high_confidence"] is True

    def test_simulated_low(self):
        c = classify_confidence(source="simulated", breakdown=_breakdown())
        assert c["level"] == "LOW"
        assert c["is_high_confidence"] is False
        assert any("simulated" in r for r in c["reasons"])

    def test_cached_moderate(self):
        c = classify_confidence(source="cached", breakdown=_breakdown())
        assert c["level"] == "MODERATE"

    def test_missing_input_lowers_confidence(self):
        c = classify_confidence(
            source="live",
            breakdown={"raw_inputs": {"peak_temp_f": None}},
        )
        assert c["level"] in ("MODERATE", "LOW")
        assert c["missing_inputs"]

    def test_low_confidence_forces_escalation(self):
        c = classify_confidence(source="simulated", breakdown=_breakdown())
        assert assessment_overrides_decision(c) is True

    def test_not_overclaiming_note(self):
        c = classify_confidence(source="live", breakdown=_breakdown())
        assert "NOT a statistical probability" in c["note"]


# ---------------------------------------------------------------------------
# Incident / ack / escalation state machine
# ---------------------------------------------------------------------------

class TestIncidentLifecycle:
    def test_happy_path_to_resolved(self):
        clk = FakeClock(0.0)
        inc = open_incident(site="Thermal, CA", activity_id="act-1", clock=clk)
        assert inc.state == IncidentState.DETECTED
        inc.assess("scored").plan("planned").act("executed").wait_for_ack("dry_run")
        assert inc.state == IncidentState.WAITING_FOR_ACK
        clk.advance(5)
        inc.acknowledge("supervisor-1")
        inc.verify("re-scored").resolve("risk below threshold")
        assert inc.state == IncidentState.RESOLVED
        assert inc.resolution_note

    def test_ack_timeout_escalates(self):
        clk = FakeClock(0.0)
        inc = open_incident(
            site="Thermal, CA", activity_id="act-2", clock=clk, ack_window_s=60
        )
        inc.assess("x").plan("y").act("z").wait_for_ack("live")
        assert inc.ack_overdue() is False
        clk.advance(61)
        assert inc.ack_overdue() is True
        inc.timeout_ack().escalate("ack window elapsed").mark_escalated()
        assert inc.state == IncidentState.ESCALATED
        assert inc.escalation_tier() == "escalated"

    def test_illegal_ack_from_wrong_state(self):
        clk = FakeClock(0.0)
        inc = open_incident(site="S", activity_id="a", clock=clk)
        with pytest.raises(ValueError):
            inc.acknowledge("s")  # cannot ack from DETECTED

    def test_illegal_transition_rejected(self):
        clk = FakeClock(0.0)
        inc = open_incident(site="S", activity_id="a", clock=clk)
        with pytest.raises(ValueError):
            inc.resolve("directly")  # cannot resolve from DETECTED

    def test_snapshot_round_trip(self):
        clk = FakeClock(0.0)
        inc = open_incident(site="S", activity_id="a", clock=clk)
        inc.assess("x").plan("y").act("z").wait_for_ack("dry_run")
        snap = inc.to_dict()
        assert snap["state"] == "WAITING_FOR_ACK"
        assert snap["incident_id"]
        assert snap["site"] == "S"
        assert snap["entries"]

    def test_escalation_tier_maps_states(self):
        clk = FakeClock(0.0)
        inc = open_incident(site="S", activity_id="a", clock=clk)
        assert inc.escalation_tier() == "none"
        inc.assess("x").plan("y").act("z").wait_for_ack("dry_run")
        assert inc.escalation_tier() == "none"


# ---------------------------------------------------------------------------
# Audit identity + response metrics
# ---------------------------------------------------------------------------

class TestAudit:
    def test_id_prefixes(self):
        assert incident_id("abc123").startswith("inc-")
        assert "abc123" in incident_id("abc123")
        assert dispatch_id().startswith("dsp-")

    def test_decision_entry_shape(self):
        e = decision_entry(
            stage="ASSESS", action="classify", reason="r",
            state_before={"risk_tier": "CRITICAL"},
        )
        assert e["stage"] == "ASSESS"
        assert e["id"].startswith("dec-")
        assert e["strategy"] == "deterministic"
        assert e["ts"]

    def test_response_metrics_honest_none(self):
        m = response_metrics(detected_at=None)
        assert m["detect_ms"] is None  # never fabricate latency

    def test_response_metrics_elapsed(self):
        m = response_metrics(
            detected_at="2026-01-01T00:00:00Z",
            acted_at="2026-01-01T00:00:05Z",
        )
        assert m["detect_to_act_ms"] == 5000


# ---------------------------------------------------------------------------
# Closed-loop graph integration
# ---------------------------------------------------------------------------

class TestClosedLoopGraph:
    def test_graph_routes_through_closed_loop(self):
        from app.graph import NODE_NAMES, build_graph

        compiled = build_graph()
        names = set(NODE_NAMES)
        assert {
            "plan_intervention", "execute_intervention",
            "verify_acknowledgement", "reassess_risk",
            "escalate_or_resolve",
        }.issubset(names)
        assert compiled is not None

    def test_critical_run_closes_loop_with_outcome(self):
        from fastapi.testclient import TestClient
        from app.main import app

        with TestClient(app) as c:
            r = c.post(
                "/api/stream-agent",
                json={
                    "thread_id": "cl-critical",
                    "location_name": "Thermal, CA",
                    "latitude": 33.6440, "longitude": -116.1370,
                    "operation_context": "construction",
                },
            )
        res = json_result(r)
        assert res.get("agent_outcome") in (
            "NO_ACTION_REQUIRED", "PROJECTED_RESOLUTION", "ESCALATED",
        )
        assert res.get("incident_id", "").startswith("inc-")
        assert res.get("decision_trace")
        stages = [d["stage"] for d in res["decision_trace"]]
        assert "ASSESS" in stages and "PLAN" in stages and "ACT" in stages
        assert any(s in ("SETTLE", "ESCALATE") for s in stages)
        assert res.get("intervention_simulations")
        assert isinstance(res.get("response_metrics"), dict)

    def test_enterprise_output_carries_closed_loop_fields(self):
        from fastapi.testclient import TestClient
        from app.main import app

        with TestClient(app) as c:
            r = c.post(
                "/api/stream-agent",
                json={
                    "thread_id": "cl-eo",
                    "location_name": "Thermal, CA",
                    "latitude": 33.6440, "longitude": -116.1370,
                    "operation_context": "construction",
                },
            )
        res = json_result(r)
        eo = res.get("enterprise_output") or {}
        assert "decision_trace" in eo
        assert "agent_outcome" in eo
        assert "incident_id" in eo


def json_result(response) -> dict:
    events = {}
    for chunk in response.text.strip().split("\n\n"):
        if not chunk.strip():
            continue
        lines = chunk.split("\n")
        name = lines[0].replace("event: ", "").strip()
        data = lines[1].replace("data: ", "").strip()
        events[name] = __import__("json").loads(data)
    return events.get("result", {})
