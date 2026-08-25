"""
actions.py
==========
Deterministic tactical action generator.

When R >= 7.0 (CRITICAL) the UI renders numbered operational directives
(01, 02, 03 …). These are pure template functions of the scoring output —
the LLM may narrate around them but can never invent or reorder them.
"""

from __future__ import annotations

from typing import Any, Dict, List


def build_tactical_actions(
    breakdown: Dict[str, Any],
    osha_bin: str,
) -> List[Dict[str, Any]]:
    """
    Ordered, numbered tactical actions derived strictly from the
    Response-Gap tier + component values. Higher-severity tiers are strict
    supersets of lower tiers (monotonic escalation).
    """

    tier = breakdown.get("risk_tier", "NORMAL")
    raw = breakdown.get("raw_inputs", {})
    components = {
        c["key"]: c["value"] for c in breakdown.get("components", [])
    }

    actions: List[Dict[str, Any]] = []

    def add(action_id: str, title: str, detail: str, horizon: str,
            source_component: str) -> None:
        actions.append(
            {
                "id": action_id,
                "title": title,
                "detail": detail,
                "horizon": horizon,
                "source": source_component,
            }
        )

    if tier in ("ELEVATED", "HIGH", "CRITICAL"):
        add(
            "01",
            "Activate hydration stations",
            (
                "Stage water/electrolyte points within 30 m of every work "
                f"crew. Benchmark: 1 L/hour per worker (heat index bin: "
                f"{osha_bin})."
            ),
            "immediate",
            "heat_exposure",
        )

    if tier in ("HIGH", "CRITICAL"):
        shade_pct = raw.get("shade_coverage_pct", 0)
        add(
            "02",
            "Deploy shade infrastructure",
            (
                f"Site shade coverage is {shade_pct:.0f}%. Erect canopies/"
                f"pop-ups over rest zones now; enforce 15 min shaded rest "
                f"per 45 min work cycles."
            ),
            "within 30 minutes",
            "resource_deficit",
        )
        add(
            "03",
            "Buddy-system pairing",
            (
                "Pair every worker; supervisors run visual check-ins every "
                "20 minutes for heat-stress indicators (confusion, cramps, "
                "hot/dry skin)."
            ),
            "immediate",
            "vulnerability",
        )

    if tier == "CRITICAL":
        buffer_km = raw.get("cooling_center_buffer_km", 0)
        add(
            "04",
            "Halt non-essential outdoor work",
            (
                "Response Gap is CRITICAL (R >= 7.0). Suspend non-essential "
                "operations; relocate crews to cooled vehicles/shelters."
            ),
            "immediate",
            "heat_exposure",
        )
        add(
            "05",
            "Dispatch medical standby",
            (
                f"Nearest cooling center buffer is {buffer_km:.1f} km — "
                "stage an on-site medic/EMT and pre-position cold-immersion "
                "capability before continuing any exposure task."
            ),
            "within 15 minutes",
            "resource_deficit",
        )
        add(
            "06",
            "Autonomous supervisor alert",
            (
                "HeatShield has dispatched SMS + voice alerts to all site "
                "supervisors via the telephony workflow (live or dry-run). "
                "Acknowledgment tracking active."
            ),
            "executed by agent",
            "dispatch_pipeline",
        )

    return actions
