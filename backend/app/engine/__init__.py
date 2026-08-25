"""
engine — deterministic computation layer for HeatShield AI.

Everything in this package is pure math: no I/O, no clock reads, no LLM.
If a number appears in the UI, it was produced here and can be re-derived
by hand from the raw inputs.
"""

from app.engine.scoring import (  # noqa: F401
    DISPATCH_THRESHOLD,
    OPERATION_PROFILES,
    RISK_TIERS,
    score_response_gap,
    tier_for_score,
)

__all__ = [
    "DISPATCH_THRESHOLD",
    "OPERATION_PROFILES",
    "RISK_TIERS",
    "score_response_gap",
    "tier_for_score",
]
