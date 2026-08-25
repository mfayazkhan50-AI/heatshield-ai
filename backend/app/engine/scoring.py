"""
scoring.py
==========
Deterministic Response-Gap scoring engine — the mathematical heart of
HeatShield AI. PURE FUNCTIONS ONLY: no I/O, no clock, no network, no LLM.

    R = 0.40 * Heat_Exposure + 0.35 * Vulnerability_Index + 0.25 * Resource_Deficit

Every sub-score lives on a normalized 0-10 scale built from piecewise-linear
interpolations between published safety thresholds, so every number the UI
renders can be re-derived by hand from the raw inputs. The LLM layer NEVER
produces these values — it only narrates them.

References for anchor points:
    - OSHA Technical Manual / NWS heat-index risk bins (80/91/103/125 °F)
    - NWS extreme-danger guidance (124 °F heat index)
    - CDC/ATSDR Social Vulnerability Index (0-1 percentile composite)
    - Urban cooling-access literature: walkable cool-zone radius ≈ 800 m,
      severe deficit beyond ≈ 5 km.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Canonical weights — surfaced verbatim in the UI "Why Flagged?" panel
# ---------------------------------------------------------------------------

WEIGHT_HEAT_EXPOSURE: float = 0.40
WEIGHT_VULNERABILITY: float = 0.35
WEIGHT_RESOURCE_DEFICIT: float = 0.25

SCHEMA_VERSION = "rsp-gap-1.0"

# 40 °C expressed in Fahrenheit — the directive's consecutive-hour threshold.
TEMP_40C_F: float = 104.0


# ---------------------------------------------------------------------------
# Operation-specific context profiles (Construction / Delivery / Roadwork)
#
# Each profile overlays a deterministic baseline adjustment BEFORE scoring:
#   - radiant_offset_f: added to observed peak temp (asphalt/steel radiant
#     load, equipment proximity) — OSHA outdoor-work guidance.
#   - duration_scale: multiplies sustained-exposure hours (delivery crews
#     rotate vehicles with A/C micro-breaks; roadwork crews do not).
# ---------------------------------------------------------------------------

OPERATION_PROFILES: Dict[str, Dict[str, float]] = {
    "construction": {"radiant_offset_f": 2.0, "duration_scale": 1.00},
    "delivery": {"radiant_offset_f": 0.0, "duration_scale": 0.85},
    "roadwork": {"radiant_offset_f": 4.0, "duration_scale": 1.15},
}

DEFAULT_OPERATION = "construction"


# ---------------------------------------------------------------------------
# Risk-tier taxonomy (drives brand status propagation in the UI)
#
#   NORMAL   green   R < 3.0
#   ELEVATED amber   3.0 <= R < 5.5
#   HIGH     orange  5.5 <= R < 7.0
#   CRITICAL crimson R >= 7.0  → autonomous dispatch unlocked
# ---------------------------------------------------------------------------

RISK_TIERS: List[str] = ["NORMAL", "ELEVATED", "HIGH", "CRITICAL"]

DISPATCH_THRESHOLD: float = 7.0


def clamp_score(value: float) -> float:
    """Clamp any sub-score onto the canonical 0-10 scale."""
    return max(0.0, min(10.0, float(value)))


def linear_ramp(value: float, low: float, high: float) -> float:
    """
    Rising piecewise-linear normalization onto 0-10.

        value <= low  → 0      value >= high → 10      else linear between
    """
    if high <= low:
        return 0.0
    return clamp_score(10.0 * (float(value) - low) / (high - low))


def decay_ramp(value: float, near: float, far: float) -> float:
    """
    Falling piecewise-linear normalization onto 0-10 (10 = worst).

        value <= near → 10 (max deficit at zero distance/access)
        value >= far  → 0  (fully resourced beyond `far`)
    """
    if far <= near:
        return 10.0
    return clamp_score(10.0 * (far - float(value)) / (far - near))


def round2(value: float) -> float:
    return round(float(value), 2)


# ---------------------------------------------------------------------------
# Component E — Heat Exposure (0-10)
# ---------------------------------------------------------------------------

def compute_heat_exposure(
    peak_temp_f: float,
    relative_humidity_pct: float,
    consecutive_hours_above_40c: float,
    heat_index_f: float,
    operation: str = DEFAULT_OPERATION,
) -> Dict[str, Any]:
    """
    E = 0.45·HI + 0.35·PEAK + 0.20·DURATION

        HI       heat-index ramp anchored at OSHA Caution(91°F)→Extreme(124°F)
        PEAK     air-temp ramp anchored 95°F(metro normal)→118°F(deadly surge),
                 shifted upward by the operation's radiant offset
        DURATION consecutive hours above 40 °C ramped 0 h→6 h
    """
    profile = OPERATION_PROFILES.get(operation, OPERATION_PROFILES[DEFAULT_OPERATION])

    eff_peak_f = float(peak_temp_f) + profile["radiant_offset_f"]
    eff_duration_h = float(consecutive_hours_above_40c) * profile["duration_scale"]

    hi_sub = linear_ramp(heat_index_f, 91.0, 124.0)
    peak_sub = linear_ramp(eff_peak_f, 95.0, 118.0)
    dur_sub = linear_ramp(eff_duration_h, 0.0, 6.0)

    exposure = round2(0.45 * hi_sub + 0.35 * peak_sub + 0.20 * dur_sub)

    return {
        "key": "heat_exposure",
        "label": "Heat Exposure (E)",
        "value": exposure,
        "weight": WEIGHT_HEAT_EXPOSURE,
        "method": "E = 0.45·HI + 0.35·PEAK + 0.20·DURATION",
        "subs": [
            {
                "key": "heat_index",
                "label": "Heat Index",
                "value": round2(hi_sub),
                "sub_weight": 0.45,
                "anchor": "91°F (OSHA Caution) → 124°F (Extreme Danger)",
            },
            {
                "key": "peak_temp",
                "label": "Peak Air Temp (radiant-adjusted)",
                "value": round2(peak_sub),
                "sub_weight": 0.35,
                "anchor": "95°F → 118°F",
            },
            {
                "key": "sustained_hours",
                "label": f"Sustained >40°C hours ×{profile['duration_scale']:.2f}",
                "value": round2(dur_sub),
                "sub_weight": 0.20,
                "anchor": "0 h → 6 h",
            },
        ],
        "effective_inputs": {
            "effective_peak_f": round2(eff_peak_f),
            "effective_duration_h": round2(eff_duration_h, ),
            "radiant_offset_f": profile["radiant_offset_f"],
        },
    }


# ---------------------------------------------------------------------------
# Component V — Vulnerability Index (0-10)
# ---------------------------------------------------------------------------

def compute_vulnerability(
    svi: float,
    population_density_per_km2: float,
) -> Dict[str, Any]:
    """
    V = 0.70·SVI + 0.30·DENSITY

        SVI      CDC/ATSDR Social Vulnerability Index percentile (0-1) × 10
        DENSITY  population density ramp 250 → 4000 persons/km² (rescue-demand
                 pressure: denser sites mean slower per-capita aid).
    """
    svi_clamped = max(0.0, min(1.0, float(svi)))
    svi_sub = clamp_score(svi_clamped * 10.0)
    density_sub = linear_ramp(population_density_per_km2, 250.0, 4000.0)

    vulnerability = round2(0.70 * svi_sub + 0.30 * density_sub)

    return {
        "key": "vulnerability",
        "label": "Vulnerability Index (V)",
        "value": vulnerability,
        "weight": WEIGHT_VULNERABILITY,
        "method": "V = 0.70·SVI + 0.30·DENSITY",
        "subs": [
            {
                "key": "svi",
                "label": "CDC/ATSDR SVI percentile",
                "value": round2(svi_sub),
                "sub_weight": 0.70,
                "anchor": "0.0 → 1.0 × 10",
            },
            {
                "key": "density",
                "label": "Population density",
                "value": round2(density_sub),
                "sub_weight": 0.30,
                "anchor": "250 → 4000 persons/km²",
            },
        ],
        "effective_inputs": {},
    }


# ---------------------------------------------------------------------------
# Component D — Resource Deficit (0-10)
# ---------------------------------------------------------------------------

def compute_resource_deficit(
    cooling_center_buffer_km: float,
    shade_coverage_pct: float,
) -> Dict[str, Any]:
    """
    D = 0.60·COOLING + 0.40·SHADE

        COOLING  access-deficit ramp: 0 km (cooling center on-site) → 0 pts,
                 ≥ 5 km → 10 pts (no reachable cool zone). Walkable-access
                 literature anchors the 5 km severe-deficit radius.
        SHADE    shade-deficit ramp: 100 % coverage → 0, 0 % → 10.
    """
    cooling_sub = linear_ramp(cooling_center_buffer_km, 0.0, 5.0)
    shade_deficit = 100.0 - max(0.0, min(100.0, float(shade_coverage_pct)))
    shade_sub = linear_ramp(shade_deficit, 0.0, 100.0)

    deficit = round2(0.60 * cooling_sub + 0.40 * shade_sub)

    return {
        "key": "resource_deficit",
        "label": "Resource Deficit (D)",
        "value": deficit,
        "weight": WEIGHT_RESOURCE_DEFICIT,
        "method": "D = 0.60·COOLING + 0.40·SHADE",
        "subs": [
            {
                "key": "cooling_access",
                "label": "Cooling-center buffer distance",
                "value": round2(cooling_sub),
                "sub_weight": 0.60,
                "anchor": "on-site → 0 pts · ≥5 km → 10 pts",
            },
            {
                "key": "shade",
                "label": "Shade coverage deficit",
                "value": round2(shade_sub),
                "sub_weight": 0.40,
                "anchor": "100 % cover → 0 pts · bare → 10 pts",
            },
        ],
        "effective_inputs": {},
    }


# ---------------------------------------------------------------------------
# Tier mapping + dispatch gate
# ---------------------------------------------------------------------------

def tier_for_score(response_gap: float) -> str:
    """Map R ∈ [0,10] onto the four brand-status tiers."""
    if response_gap < 3.0:
        return "NORMAL"
    if response_gap < 5.5:
        return "ELEVATED"
    if response_gap < DISPATCH_THRESHOLD:
        return "HIGH"
    return "CRITICAL"


def is_dispatch_eligible(response_gap: float, tier: Optional[str] = None) -> bool:
    """Autonomous dispatch gate — strictly R >= 7.0 (or tier CRITICAL)."""
    if tier is not None:
        return tier == "CRITICAL"
    return response_gap >= DISPATCH_THRESHOLD


def osha_bin_for_heat_index(heat_index_f: float) -> str:
    """
    Legacy OSHA-aligned bin (Low/Caution/Warning/Danger/Extreme Danger) kept
    for compliance-template selection. Orthogonal to — and independent of —
    the Response-Gap tier; both scales are fully deterministic.
    """
    if heat_index_f < 80:
        return "Low"
    if heat_index_f < 91:
        return "Caution"
    if heat_index_f < 103:
        return "Warning"
    if heat_index_f < 125:
        return "Danger"
    return "Extreme Danger"


# ---------------------------------------------------------------------------
# Top-level scorer — single entry point used by the LangGraph node
# ---------------------------------------------------------------------------

def score_response_gap(
    *,
    peak_temp_f: float,
    relative_humidity_pct: float,
    heat_index_f: float,
    consecutive_hours_above_40c: float,
    svi: float,
    population_density_per_km2: float,
    cooling_center_buffer_km: float,
    shade_coverage_pct: float,
    operation: str = DEFAULT_OPERATION,
) -> Dict[str, Any]:
    """
    Compute the full transparent Response-Gap breakdown.

    Returns an audit-ready dict containing raw inputs, per-component
    derivations, the substituted formula string, the final R, its tier,
    and the dispatch gate decision. Pure: identical inputs always yield
    byte-identical output (modulo caller-supplied timestamps).
    """

    e = compute_heat_exposure(
        peak_temp_f=peak_temp_f,
        relative_humidity_pct=relative_humidity_pct,
        consecutive_hours_above_40c=consecutive_hours_above_40c,
        heat_index_f=heat_index_f,
        operation=operation,
    )

    v = compute_vulnerability(
        svi=svi,
        population_density_per_km2=population_density_per_km2,
    )

    d = compute_resource_deficit(
        cooling_center_buffer_km=cooling_center_buffer_km,
        shade_coverage_pct=shade_coverage_pct,
    )

    for component in (e, v, d):
        component["contribution"] = round2(component["weight"] * component["value"])

    components = [e, v, d]

    response_gap = round2(
        e["weight"] * e["value"]
        + v["weight"] * v["value"]
        + d["weight"] * d["value"]
    )
    response_gap = clamp_score(response_gap)

    tier = tier_for_score(response_gap)

    substitution = (
        f"R = {e['weight']:.2f}×{e['value']:.2f} "
        f"+ {v['weight']:.2f}×{v['value']:.2f} "
        f"+ {d['weight']:.2f}×{d['value']:.2f} = {response_gap:.2f}"
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "engine": "deterministic-response-gap/v1 (zero-LLM)",
        "response_gap": response_gap,
        "risk_tier": tier,
        "dispatch_eligible": is_dispatch_eligible(response_gap, tier),
        "dispatch_threshold": DISPATCH_THRESHOLD,
        "formula_expression": (
            "R = 0.40·Heat_Exposure + 0.35·Vulnerability_Index "
            "+ 0.25·Resource_Deficit"
        ),
        "formula_substitution": substitution,
        "components": components,
        "raw_inputs": {
            "peak_temp_f": round2(peak_temp_f),
            "relative_humidity_pct": round2(relative_humidity_pct),
            "heat_index_f": round2(heat_index_f),
            "consecutive_hours_above_40c": round2(consecutive_hours_above_40c),
            "svi": round(svi, 3),
            "population_density_per_km2": population_density_per_km2,
            "cooling_center_buffer_km": round2(cooling_center_buffer_km),
            "shade_coverage_pct": round2(shade_coverage_pct),
            "temp_40c_in_f": TEMP_40C_F,
            "operation": operation,
        },
        "operation_profile": OPERATION_PROFILES.get(
            operation, OPERATION_PROFILES[DEFAULT_OPERATION]
        ),
    }
