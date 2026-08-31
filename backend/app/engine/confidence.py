"""
confidence.py
=============
Deterministic confidence / uncertainty classifier for the agent's decision.

We do NOT overclaim statistical certainty. Confidence is a transparent,
documented ranking derived from (a) data provenance and (b) input
completeness. It is a *categorical* label (HIGH / MODERATE / LOW) plus the
reasoning that produced it, never a fake probability.

Provenance is the single most powerful signal:
  live     -> the FortyGuard API served measured data   -> HIGH
  cached   -> a recent live observation was replayed    -> MODERATE
  simulated -> local climate-normal synthesis           -> LOW
"""

from __future__ import annotations

from typing import Any, Dict, List

CONFIDENCE_LEVELS = ("HIGH", "MODERATE", "LOW")

_SOURCE_CONFIDENCE = {
    "live": "HIGH",
    "cached": "MODERATE",
    "simulated": "LOW",
    "deterministic_fallback": "LOW",
}

# Inputs whose absence lowers confidence (missing signal weakens the model).
_REQUIRED_FOR_HIGH = (
    "peak_temp_f",
    "heat_index_f",
    "svi",
    "cooling_center_buffer_km",
    "shade_coverage_pct",
)


def _provenance(source: Any) -> str:
    source = str(source or "simulated").lower()
    return source if source in _SOURCE_CONFIDENCE else "simulated"


def _missing_keys(breakdown: Dict[str, Any]) -> List[str]:
    raw = breakdown.get("raw_inputs")
    if not isinstance(raw, dict):
        return list(_REQUIRED_FOR_HIGH)
    missing = [k for k in _REQUIRED_FOR_HIGH if raw.get(k) is None]
    return missing


def classify_confidence(
    *,
    source: Any,
    breakdown: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Return a deterministic confidence assessment for the current decision.

    Provenance rules (honest, never overclaim):
      - live (measured) + all required inputs -> HIGH
      - live (measured) + missing input        -> MODERATE
      - cached (replay of a recent live obs)   -> MODERATE
      - simulated / deterministic fallback      -> LOW   (synthesized, not measured)

      ~= more measured evidence -> higher confidence. Synthetic data can
      inform a decision but must never be treated as a high-confidence
      observation, so simulated scenes ALWAYS reduce to LOW and therefore
      trigger escalation rather than a claim of resolution.
    """
    prov = _provenance(source)
    missing = _missing_keys(breakdown)
    reasons: List[str] = [f"data source: {prov}"]

    if prov == "live":
        if not missing:
            level = "HIGH"
            reasons.append("measured inputs complete")
        else:
            level = "MODERATE"
            reasons.append(f"measured but missing {len(missing)} required input(s)")
    elif prov == "cached":
        level = "MODERATE"
        reasons.append("replayed recent live observation")
    else:  # simulated / deterministic_fallback
        level = "LOW"
        reasons.append("synthesized data — not a measured observation")

    reason_gate = "assessment_forces_escalation" if level == "LOW" else ""
    if reason_gate:
        reasons.append(
            "low-confidence scenes escalate for human review rather than "
            "claiming resolution"
        )

    return {
        "level": level,
        "model": "deterministic_categorical",
        "source": prov,
        "reasons": reasons,
        "missing_inputs": missing,
        "is_high_confidence": level == "HIGH",
        "note": (
            "Confidence is a categorical ranking from provenance + input "
            "completeness. It is NOT a statistical probability and should "
            "not be treated as one."
        ),
    }


def assessment_overrides_decision(
    confidence: Dict[str, Any],
) -> bool:
    """
    When confidence is LOW the agent must NOT claim a definitive resolution
    from a single pass — it escalates for human review instead.
    """
    return confidence.get("level") == "LOW"
