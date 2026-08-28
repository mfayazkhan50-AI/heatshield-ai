"""
nodes.py
========
Isolated LangGraph node functions for the HeatShield AI workflow.

    ingest_environmental_data   FortyGuard microclimate ingestion (live → cache)
    evaluate_heat_risk          DETERMINISTIC Response-Gap scoring (zero-LLM)
    generate_compliance_plan    Grounded LLM prose cascade (Tiers 1-5)
    dispatch_critical_alerts    Autonomous SMS/voice dispatch when R ≥ 7.0
    format_enterprise_output    Final normalized UI/audit payload

HARD INVARIANT: no LLM ever produces a risk number. Every score, tier, and
tactical action originates in app/engine/* pure functions; the LLM layer
only narrates the deterministic artifact it is handed.

Each node receives the shared AgentState and returns a partial state
update that LangGraph merges onto the running thread.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List

from app.engine.actions import build_tactical_actions
from app.engine.scoring import (
    osha_bin_for_heat_index,
    score_response_gap,
)
from app.services import fortyguard
from app.services.climate_normals import (
    build_micro_grid,
    get_city_normal,
    synthesize_simulated_field,
)
from app.services.dispatch import dispatch_critical_alerts
from app.services.llm_router import execute_resilient_llm
from app.services.observation_cache import (
    ObservationCache,
    get_observation_cache,
)
from app.state import VALID_RISK_LEVELS, AgentState
from app.utils.clock import utc_now_iso

logger = logging.getLogger("heatshield.nodes")

CRITICAL_TIER = "CRITICAL"


# ---------------------------------------------------------------------------
# Shared log-entry helper
# ---------------------------------------------------------------------------

def _log_node(
    node: str,
    message: str,
    **extra: Any,
) -> Dict[str, Any]:
    entry = {
        "node": node,
        "message": message,
        "ts": utc_now_iso(),
        **extra,
    }

    logger.info("[%s] %s", node, message)

    return entry


# ---------------------------------------------------------------------------
# Node 1: ingest_environmental_data
# ---------------------------------------------------------------------------

async def ingest_environmental_data(
    state: AgentState,
) -> Dict[str, Any]:
    """
    Pulls hyperlocal street-level microclimate data from the FortyGuard
    Temperature API. Falls back instantly to deterministic climate-normal
    simulation when the key is missing / the request times out / the API
    errors — and labels the provenance either way.
    """

    log: List[Dict[str, Any]] = list(state.get("node_log", []))

    activity_id = state.get("activity_id") or uuid.uuid4().hex[:12]

    location_name = (
        state.get("location_name")
        or "Phoenix, AZ"
    )

    lat = float(state.get("latitude", 33.4484))
    lon = float(state.get("longitude", -112.0740))

    operation = (
        state.get("operation_context")
        or "construction"
    )

    frame: Dict[str, Any] | None = None

    if fortyguard.has_api_key():
        frame, error = await fortyguard.fetch_live_frame(lat, lon)

        if frame is not None:
            log.append(
                _log_node(
                    "ingest_environmental_data",
                    f"Live FortyGuard data ingested for {location_name}.",
                )
            )
        else:
            log.append(
                _log_node(
                    "ingest_environmental_data",
                    (
                        "Live FortyGuard call failed "
                        f"({error!r}); falling back to simulated field."
                    ),
                    level="warning",
                )
            )
    else:
        log.append(
            _log_node(
                "ingest_environmental_data",
                "No FORTYGUARD_API_KEY configured; using simulated field.",
                level="warning",
            )
        )

    grid: Dict[str, Any]

    if frame is not None:
        normal = get_city_normal(location_name)
        grid = build_micro_grid(
            lat=lat,
            lon=lon,
            base_temp_f=float(frame["temperature_f"]),
            seed=f"live:{activity_id}",
        )
        hours_est = frame.get("consecutive_hours_above_40c")
        if hours_est is None:
            hours_est = max(0.0, min(10.0, (grid["peak_temp_f"] - normal["normal_high_f"]) / 2.0))

        vulnerability_profile = {
            "svi": normal["svi"],
            "population_density_per_km2": normal["population_density_per_km2"],
            "cooling_center_buffer_km": normal["cooling_center_buffer_km"],
            "shade_coverage_pct": normal["shade_coverage_pct"],
        }

        # Share this fresh live observation with the thermal-field map so it
        # renders instantly from the agent's fetch instead of competing with a
        # second live FortyGuard poll (which would double API load and slow the
        # whole pipeline). Keyed the same way the /api/heatmap route looks up.
        try:
            cache_key = ObservationCache.build_key(lat, lon, operation, 24)
            cache_obs = get_observation_cache()
            cache_obs.put(
                cache_key,
                {
                    "activity_id": activity_id,
                    "location_name": location_name,
                    "latitude": lat,
                    "longitude": lon,
                    "operation_context": operation,
                    "source": frame.get("source", "live"),
                    "provenance": frame.get("provenance"),
                    "observed_at": frame.get("observed_at"),
                    "peak_temp_f": grid["peak_temp_f"],
                    "peak_temp_c": grid["peak_temp_c"],
                    "critical_cells": grid["critical_cells"],
                    "tile_count": grid["tile_count"],
                    "consecutive_hours_above_40c": hours_est,
                    "cells": grid["cells"],
                },
            )
        except Exception:
            logger.exception("Could not share live observation with map cache")
    else:
        simulated = synthesize_simulated_field(
            location_name=location_name,
            lat=lat,
            lon=lon,
            operation=operation,
            fallback_reason="fortyguard_unavailable",
            seed_suffix=activity_id,
        )
        frame = simulated["frame"]
        grid = simulated["grid"]
        hours_est = frame["consecutive_hours_above_40c_est"]
        vulnerability_profile = frame["vulnerability_profile"]

        log.append(
            _log_node(
                "ingest_environmental_data",
                "SIMULATED FIELD injected from local climate normals.",
                level="warning",
            )
        )

    return {
        "activity_id": activity_id,
        "operation_context": operation,
        "fortyguard_data": frame,
        "heat_grid": grid,
        "vulnerability_profile": vulnerability_profile,
        "sustained_hours": hours_est,
        "node_log": log,
    }


# ---------------------------------------------------------------------------
# Node 2: evaluate_heat_risk  — PURE DETERMINISTIC MATH, ZERO LLM
# ---------------------------------------------------------------------------

async def evaluate_heat_risk(
    state: AgentState,
) -> Dict[str, Any]:
    """
    Computes heat index + the transparent Response-Gap breakdown:

        R = 0.40·Heat_Exposure + 0.35·Vulnerability_Index + 0.25·Resource_Deficit

    All inputs come from the ingest frame + labeled site profile; every
    intermediate value is preserved for the 'Why Flagged?' UI panel.
    """

    log: List[Dict[str, Any]] = list(state.get("node_log", []))

    frame = state.get("fortyguard_data", {})
    profile = state.get("vulnerability_profile", {})

    temp_f = float(frame.get("temperature_f", 95.0) or 95.0)
    rh_pct = float(frame.get("relative_humidity_pct", 30.0) or 30.0)

    # Rothfusz regression (NWS) — deterministic
    heat_index_f = _compute_heat_index_f(temp_f, rh_pct)

    sustained_hours = float(
        state.get("sustained_hours", 0.0) or 0.0
    )

    operation = state.get("operation_context") or "construction"

    breakdown = score_response_gap(
        peak_temp_f=temp_f,
        relative_humidity_pct=rh_pct,
        heat_index_f=heat_index_f,
        consecutive_hours_above_40c=sustained_hours,
        svi=float(profile.get("svi", 0.5)),
        population_density_per_km2=float(
            profile.get("population_density_per_km2", 1000)
        ),
        cooling_center_buffer_km=float(
            profile.get("cooling_center_buffer_km", 3.0)
        ),
        shade_coverage_pct=float(
            profile.get("shade_coverage_pct", 25.0)
        ),
        operation=operation,
    )

    risk_level = osha_bin_for_heat_index(heat_index_f)

    assert risk_level in VALID_RISK_LEVELS

    tier = breakdown["risk_tier"]
    r_score = breakdown["response_gap"]

    log.append(
        _log_node(
            "evaluate_heat_risk",
            (
                f"Deterministic scoring: HI={heat_index_f}°F -> R={r_score} "
                f"[{tier}] ({breakdown['formula_substitution']})"
            ),
        )
    )

    return {
        "heat_index_f": heat_index_f,
        "risk_level": risk_level,
        "risk_breakdown": breakdown,
        "node_log": log,
    }


# ---------------------------------------------------------------------------
# Node 3: generate_compliance_plan — GROUNDED prose generation
# ---------------------------------------------------------------------------

async def generate_compliance_plan(
    state: AgentState,
) -> Dict[str, Any]:
    """
    Delegates to the resilient LLM cascade in services/llm_router.py:

    Tier 1: Groq primary · Tier 2: Groq secondary · Tier 3: Gemini
    Tier 4: BYOK          · Tier 5: deterministic rules (always succeeds)

    The prompt embeds the DETERMINISTIC scoring artifact and explicitly
    forbids the model from computing any number of its own.
    """

    log: List[Dict[str, Any]] = list(state.get("node_log", []))

    cascade = await execute_resilient_llm(state)

    for cascade_event in cascade["events"]:
        extra: Dict[str, Any] = {}
        if cascade_event.get("level") == "warning":
            extra["level"] = "warning"

        log.append(
            _log_node(
                "generate_compliance_plan",
                cascade_event["message"],
                **extra,
            )
        )

    # Numbered tactical actions are generated deterministically regardless
    # of which tier served the prose — the LLM cannot alter them.
    tactical_actions = build_tactical_actions(
        state.get("risk_breakdown", {}),
        state.get("risk_level", "Warning"),
    )

    if tactical_actions:
        log.append(
            _log_node(
                "generate_compliance_plan",
                f"{len(tactical_actions)} deterministic tactical actions attached.",
            )
        )

    return {
        "compliance_plan": cascade["compliance_plan"],
        "active_tier": cascade["active_tier"],
        "tier_trace": cascade["tier_trace"],
        "awaiting_byok": cascade["awaiting_byok"],
        "tactical_actions": tactical_actions,
        "node_log": log,
    }


# ---------------------------------------------------------------------------
# Node 3.5: dispatch_critical_alerts — AUTONOMOUS EXECUTION GATE
# ---------------------------------------------------------------------------

async def dispatch_critical_alerts_node(
    state: AgentState,
) -> Dict[str, Any]:
    """
    Fires real-world workflows ONLY when the deterministic gate opens
    (risk_tier == CRITICAL ⇔ R >= 7.0). SMS + voice via Twilio REST;
    dry-run records with full previews when credentials are absent so the
    demo never breaks and judges can wire keys live.
    """

    log: List[Dict[str, Any]] = list(state.get("node_log", []))

    breakdown = state.get("risk_breakdown", {})

    if breakdown.get("risk_tier") != CRITICAL_TIER:
        log.append(
            _log_node(
                "dispatch_critical_alerts",
                (
                    "Dispatch gate closed: response gap below CRITICAL "
                    f"(R={breakdown.get('response_gap')} < "
                    f"{breakdown.get('dispatch_threshold')}). No alerts sent."
                ),
            )
        )

        return {
            "dispatch_records": [],
            "dispatch_mode": "not_triggered",
            "node_log": log,
        }

    activity_id = state.get("activity_id", "unknown")

    records = await dispatch_critical_alerts(
        site_name=state.get("location_name", "Unknown Site"),
        latitude=float(state.get("latitude", 0.0)),
        longitude=float(state.get("longitude", 0.0)),
        breakdown=breakdown,
        activity_id=activity_id,
    )

    mode = "dry_run" if any(r["mode"] == "dry_run" for r in records) else "live"

    sent = sum(1 for r in records if r["status"] == ("preview" if mode == "dry_run" else "sent"))

    log.append(
        _log_node(
            "dispatch_critical_alerts",
            (
                f"AUTONOMOUS DISPATCH [{mode}]: {len(records)} telephony records "
                f"prepared ({sent} {'previews' if mode == 'dry_run' else 'sent'})."
            ),
            level=("info" if mode == "live" else "warning"),
        )
    )

    return {
        "dispatch_records": records,
        "dispatch_mode": mode,
        "node_log": log,
    }


# ---------------------------------------------------------------------------
# Node 4: format_enterprise_output
# ---------------------------------------------------------------------------

async def format_enterprise_output(
    state: AgentState,
) -> Dict[str, Any]:
    """Normalizes accumulated state into the final v2 UI/audit payload."""

    log: List[Dict[str, Any]] = list(state.get("node_log", []))

    frame = state.get("fortyguard_data", {})
    source = frame.get("source", "simulated")

    output = {
        "location_name": state.get("location_name"),
        "latitude": state.get("latitude"),
        "longitude": state.get("longitude"),
        "observed_at": frame.get("observed_at", utc_now_iso()),
        "activity_id": state.get("activity_id"),
        "operation_context": state.get("operation_context", "construction"),
        "heat_index_f": state.get("heat_index_f"),
        "risk_level": state.get("risk_level"),
        "risk_breakdown": state.get("risk_breakdown"),
        "compliance_plan": state.get("compliance_plan"),
        "tactical_actions": state.get("tactical_actions", []),
        "dispatch_records": state.get("dispatch_records", []),
        "dispatch_mode": state.get("dispatch_mode", "not_triggered"),
        "active_tier": state.get("active_tier"),
        "tier_trace": state.get("tier_trace", []),
        "source": (
            source
            if source in ("live", "cached", "simulated")
            else "deterministic_fallback"
        ),
        "provenance": frame.get("provenance"),
        "fallback_reason": frame.get("fallback_reason"),
    }

    log.append(
        _log_node(
            "format_enterprise_output",
            "Enterprise output payload normalized.",
        )
    )

    return {
        "enterprise_output": output,
        "node_log": log,
    }


# ---------------------------------------------------------------------------
# Local NWS Rothfusz heat index (kept dependency-free for tests)
# ---------------------------------------------------------------------------

def _compute_heat_index_f(temp_f: float, rh_pct: float) -> float:
    """NWS Rothfusz regression with the standard adjustments."""

    T, R = temp_f, rh_pct

    simple_hi = 0.5 * (
        T + 61.0 + ((T - 68.0) * 1.2) + (R * 0.094)
    )

    if simple_hi < 80.0:
        return round(simple_hi, 1)

    hi = (
        -42.379
        + 2.04901523 * T
        + 10.14333127 * R
        - 0.22475541 * T * R
        - 0.00683783 * T * T
        - 0.05481717 * R * R
        + 0.00122874 * T * T * R
        + 0.00085282 * T * R * R
        - 0.00000199 * T * T * R * R
    )

    if R < 13 and 80 <= T <= 112:
        hi -= (
            ((13 - R) / 4)
            * ((17 - abs(T - 95.0)) / 17) ** 0.5
        )

    elif R > 85 and 80 <= T <= 87:
        hi += ((R - 85) / 10) * ((87 - T) / 5)

    return round(hi, 1)
