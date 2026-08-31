"""
audit.py
========
Audit identity + response metrics for the closed-loop agent.

Generates collision-resistant run/decision/dispatch ids, builds an immutable
decision-provenance chain, and computes deterministic response-metric
delays (detect->assess->plan->act) from supplied timestamps.
"""

from __future__ import annotations

import secrets
from typing import Any, Dict, List, Optional

from app.utils.clock import utc_now_iso
from app.engine.confidence import classify_confidence


def _token() -> str:
    return secrets.token_hex(6)


def incident_id(activity_id: Optional[str] = None) -> str:
    """Stable per-run incident id, derived from the activity id when given."""
    if activity_id:
        return f"inc-{str(activity_id)[:12]}"
    return f"inc-{_token()}"


def decision_id(prefix: str = "dec") -> str:
    return f"{prefix}-{_token()}"


def dispatch_id() -> str:
    return f"dsp-{_token()}"


def _epoch_ms(ts_iso: Optional[str]) -> Optional[float]:
    if not ts_iso:
        return None
    try:
        from datetime import datetime

        dt = datetime.fromisoformat(str(ts_iso).replace("Z", "+00:00"))
        return dt.timestamp() * 1000.0
    except Exception:
        return None


def _elapsed_ms(start: Optional[str], end: Optional[str]) -> Optional[int]:
    s, e = _epoch_ms(start), _epoch_ms(end)
    if s is None or e is None or e < s:
        return None
    return int(round(e - s))


def response_metrics(
    *,
    detected_at: Optional[str] = None,
    assessed_at: Optional[str] = None,
    planned_at: Optional[str] = None,
    acted_at: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Deterministic response-metric delays (ms). Each field is None when the
    required timestamp pair is absent so we never fabricate a latency.
    """
    return {
        "detect_ms": _elapsed_ms(
            detected_at, assessed_at
        ),
        "assess_ms": _elapsed_ms(assessed_at, planned_at),
        "plan_ms": _elapsed_ms(planned_at, acted_at),
        "detect_to_act_ms": _elapsed_ms(detected_at, acted_at),
    }


def decision_entry(
    *,
    stage: str,
    action: str,
    reason: str,
    state_before: Dict[str, Any],
    strategy: str = "deterministic",
    confidence: Optional[Dict[str, Any]] = None,
    decision_id_val: Optional[str] = None,
    ts: Optional[str] = None,
) -> Dict[str, Any]:
    """
    One immutable node in the agent decision trace.

    `state_before` is the decision-relevant input evidence (a projection of
    the live state, not the whole state object) so the trace is small,
    auditable, and stable across runs.
    """
    return {
        "id": decision_id_val or decision_id(),
        "stage": stage,  # OBSERVE | ASSESS | PLAN | ACT | VERIFY | REASSESS | ESCALATE | RESOLVE
        "action": action,
        "reason": reason,
        "strategy": strategy,
        "confidence": confidence or {},
        "state_before": dict(state_before),
        "ts": ts or utc_now_iso(),
    }
