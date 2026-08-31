"""
interventions.py
================
Deterministic intervention simulation (the PLAN / SIMULATE stage of the
closed-loop agent).

Given the Response-Gap scoring artifact and its raw site inputs, this module
re-runs the SAME deterministic R engine (`score_response_gap`) under each
candidate intervention's modified conditions to produce a *projected*
before/after response gap. The agent therefore never guesses — every
projection is derived from the same transparent formula the risk tier came
from.

HARD INVARIANT: every value here is labelled PROJECTED (never observed).
A simulated intervention is explicitly `effective=False` until the VERIFY
loop confirms real-world change. Nothing in this module performs I/O.

Intervention effect model (documented, deterministic multipliers on the
raw inputs that feed the R formula):

  shade           -> +shade_coverage_pct  (reduces Heat/Resource exposure)
  hydration       -> -effective exposure via rest/cycling (sustained hours)
  rest_cycling    -> -consecutive hours above threshold
  relocation      -> -cooling_center_buffer_km (crews moved nearer cooling)
  buddy_system    -> -vulnerability (detection reduces unmonitored exposure)
  work_stoppage   -> -peak_temp_f (non-essential outdoor work suspended)
  medical_standby -> -vulnerability + reduces R via on-site care access
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.engine.scoring import score_response_gap

# Deterministic cap so projected R can never exceed the raw scale.
SCORE_FLOOR = 0.0
SCORE_CEIL = 10.0

# Intervention effect parameters (documented heuristics, deterministic).
_EFFECT: Dict[str, Dict[str, Any]] = {
    "shade": {
        "label": "Deploy shade infrastructure",
        "message": "Erect canopies over rest zones; enforce shaded rest cycles.",
        "inputs": {"shade_coverage_pct": (lambda v: min(80.0, v + 25.0))},
        "resource": {"cost": "medium", "eta_min": 20, "staff": 3},
    },
    "hydration": {
        "label": "Activate hydration stations",
        "message": "Stage water/electrolyte points within 30 m of every crew.",
        "inputs": {"consecutive_hours_above_40c": (lambda v: max(0.0, v - 1.0))},
        "resource": {"cost": "low", "eta_min": 5, "staff": 1},
    },
    "rest_cycling": {
        "label": "Enforce duty/rest cycling",
        "message": "15 min shaded rest per 45 min work; reduce cumulative exposure.",
        "inputs": {"consecutive_hours_above_40c": (lambda v: max(0.0, v - 1.5))},
        "resource": {"cost": "low", "eta_min": 0, "staff": 2},
    },
    "relocation": {
        "label": "Relocate crews to cooled zones",
        "message": "Move crews to the nearest cooled vehicle/shelter bay.",
        "inputs": {"cooling_center_buffer_km": (lambda v: max(0.5, v - 2.0))},
        "resource": {"cost": "high", "eta_min": 30, "staff": 4},
    },
    "buddy_system": {
        "label": "Buddy-system monitoring",
        "message": "Pair workers; supervisors run visual check-ins for heat stress.",
        "inputs": {"svi": (lambda v: max(0.3, v - 0.15))},
        "resource": {"cost": "low", "eta_min": 0, "staff": 2},
    },
    "work_stoppage": {
        "label": "Halt non-essential outdoor work",
        "message": "Suspend non-essential operations at CRITICAL threshold.",
        "inputs": {"peak_temp_f": (lambda v: max(90.0, v - 4.0))},
        "resource": {"cost": "high", "eta_min": 0, "staff": 0},
    },
    "medical_standby": {
        "label": "Dispatch medical standby",
        "message": "Stage on-site medic/EMT with cold-immersion capability.",
        "inputs": {
            "svi": (lambda v: max(0.3, v - 0.12)),
            "cooling_center_buffer_km": (lambda v: max(1.0, v - 0.8)),
        },
        "resource": {"cost": "high", "eta_min": 15, "staff": 2},
    },
}

# Preferred ordering for presentation (fixed, not alphabetical).
_ORDER = [
    "shade",
    "hydration",
    "rest_cycling",
    "buddy_system",
    "relocation",
    "medical_standby",
    "work_stoppage",
]


def _component_value(breakdown: Dict[str, Any], key: str) -> Optional[float]:
    for comp in breakdown.get("components", []):
        if comp.get("key") == key:
            return comp.get("value")
    return None


def _score_inputs(
    breakdown: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """
    Reconstruct the raw inputs `score_response_gap` was called with so a
    modelled intervention can adjust them and re-run the engine.
    """
    raw = breakdown.get("raw_inputs")
    if not isinstance(raw, dict):
        return None

    heat_index_f = raw.get("heat_index_f")
    if heat_index_f is None:
        # Fall back to the formula's implied peak (rare / older payloads).
        heat_index_f = raw.get("peak_temp_f", 0.0)

    return {
        "peak_temp_f": float(raw.get("peak_temp_f", 90.0)),
        "relative_humidity_pct": float(raw.get("relative_humidity_pct", 30.0)),
        "heat_index_f": float(heat_index_f),
        "consecutive_hours_above_40c": float(
            raw.get("consecutive_hours_above_40c", 0.0)
        ),
        "svi": float(raw.get("svi", 0.5)),
        "population_density_per_km2": float(
            raw.get("population_density_per_km2", 1000)
        ),
        "cooling_center_buffer_km": float(
            raw.get("cooling_center_buffer_km", 3.0)
        ),
        "shade_coverage_pct": float(raw.get("shade_coverage_pct", 25.0)),
        "operation": str(raw.get("operation", "construction")),
    }


def _apply_inputs(
    inputs: Dict[str, Any],
    modifiers: Dict[str, Any],
) -> Dict[str, Any]:
    """Return a shallow-copied input dict with intervention modifiers applied."""
    projected = dict(inputs)
    for key, fn in modifiers.items():
        if key in projected:
            current = projected[key]
            projected[key] = round(float(fn(current)), 2)
    return projected


def simulate_intervention(
    breakdown: Dict[str, Any],
    intervention_key: str,
) -> Optional[Dict[str, Any]]:
    """
    Simulate a single intervention against a scoring artifact.

    Returns a PROJECTED before/after dict, or None when the intervention key
    is unknown or the artifact has no reconstructable inputs.
    """
    spec = _EFFECT.get(intervention_key)
    if spec is None:
        return None

    base = _score_inputs(breakdown)
    if base is None:
        return None

    before_gap = float(breakdown.get("response_gap", 0.0))
    before_tier = breakdown.get("risk_tier", "NORMAL")

    projected_inputs = _apply_inputs(base, spec["inputs"])
    after = score_response_gap(**projected_inputs)

    after_gap = float(after["response_gap"])
    delta = before_gap - after_gap
    # Relative improvement in [0, 1] — 0 when there is nothing to improve.
    improvement = (
        round(min(1.0, max(0.0, delta / before_gap)), 3)
        if before_gap > 0
        else 0.0
    )

    resource = dict(spec["resource"])

    return {
        "key": intervention_key,
        "title": spec["label"],
        "message": spec["message"],
        "status": "projected",
        "effective": False,  # never claim success before VERIFY
        "before": {
            "response_gap": round(before_gap, 3),
            "risk_tier": before_tier,
        },
        "after": {
            "response_gap": round(after_gap, 3),
            "risk_tier": after["risk_tier"],
        },
        "prospective_delta": round(delta, 3),
        "prospective_improvement": improvement,
        "projected_inputs": projected_inputs,
        "resource": resource,
    }


def simulate_all_interventions(
    breakdown: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """
    Deterministically simulate every candidate intervention and sort by
    prospective improvement (descending), ties broken by the fixed ordering.
    Never raises on a bad artifact — returns [] instead.
    """
    base = _score_inputs(breakdown)
    if base is None:
        return []

    # Only plan interventions for scenes with real, actionable risk. A
    # NORMAL/no-risk scene needs no mitigation simulation.
    tier = breakdown.get("risk_tier", "NORMAL")
    if tier not in ("ELEVATED", "HIGH", "CRITICAL"):
        return []

    results: List[Dict[str, Any]] = []
    for key in _ORDER:
        sim = simulate_intervention(breakdown, key)
        if sim is not None:
            results.append(sim)

    results.sort(
        key=lambda s: (-s["prospective_improvement"], _ORDER.index(s["key"]))
    )
    return results


def select_best_intervention(
    breakdown: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """
    Pick the single most impactful intervention purely from projection.
    Returns the full simulation record, or None when nothing improves R.
    """
    sims = simulate_all_interventions(breakdown)
    if not sims:
        return None
    best = sims[0]
    if best["prospective_delta"] <= 0.0:
        return None
    return best
