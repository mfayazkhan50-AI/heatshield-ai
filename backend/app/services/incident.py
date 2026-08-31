"""
incident.py
===========
Server-authoritative incident lifecycle + acknowledgement / escalation
state machine for the closed-loop agent.

The agent does NOT decide it "solved" a heat incident on its own. It opens
an incident, dispatches, then waits for acknowledgement and re-verifies
against fresh conditions. If acknowledgement does not arrive within a
configurable window, or confidence stays LOW, the agent ESCALATES to a human
reviewer instead of claiming a false resolution.

This is a PURE, deterministic state machine with an injectable clock so
timing logic is fully unit-testable and reproducible in demos.

States:
    DETECTED -> ASSESSING -> PLANNED -> ACTING -> WAITING_FOR_ACK
        -> ACK_TIMED_OUT -> ESCALATING -> ESCALATED
        -> ACKNOWLEDGED -> VERIFYING -> RESOLVED

Transitions are legal only from the documented predecessors; anything else
raises `ValueError` so invalid state drift is impossible.
"""

from __future__ import annotations

import os
from enum import Enum
from typing import Any, Dict, List, Optional


class IncidentState(str, Enum):
    DETECTED = "DETECTED"
    ASSESSING = "ASSESSING"
    PLANNED = "PLANNED"
    ACTING = "ACTING"
    WAITING_FOR_ACK = "WAITING_FOR_ACK"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    ACK_TIMED_OUT = "ACK_TIMED_OUT"
    ESCALATING = "ESCALATING"
    ESCALATED = "ESCALATED"
    VERIFYING = "VERIFYING"
    RESOLVED = "RESOLVED"


_ACK_WINDOW_S = float(os.getenv("HEATSHIELD_ACK_WINDOW_S", "600.0") or "600.0")
_VERIFY_INTERVAL_S = float(
    os.getenv("HEATSHIELD_VERIFY_INTERVAL_S", "300.0") or "300.0"
)

# stage == ... : legal transitions
_TRANSITIONS: Dict[IncidentState, set] = {
    IncidentState.DETECTED: {IncidentState.ASSESSING},
    IncidentState.ASSESSING: {IncidentState.PLANNED},
    IncidentState.PLANNED: {IncidentState.ACTING},
    IncidentState.ACTING: {IncidentState.WAITING_FOR_ACK},
    IncidentState.WAITING_FOR_ACK: {
        IncidentState.ACKNOWLEDGED,
        IncidentState.ACK_TIMED_OUT,
    },
    IncidentState.ACKNOWLEDGED: {IncidentState.VERIFYING},
    IncidentState.VERIFYING: {IncidentState.RESOLVED, IncidentState.ESCALATING},
    IncidentState.ACK_TIMED_OUT: {IncidentState.ESCALATING},
    IncidentState.ESCALATING: {IncidentState.ESCALATED},
    IncidentState.ESCALATED: set(),
    IncidentState.RESOLVED: set(),
}


class Clock:
    """Injectable clock abstraction (defaults to real wall-clock seconds)."""

    def now_s(self) -> float:
        from time import time

        return time()

    def now_iso(self) -> str:
        from app.utils.clock import utc_now_iso

        return utc_now_iso()


class _SystemClock(Clock):
    """Reads real wall-clock via the default Clock methods."""


def _default_clock() -> Clock:
    return _SystemClock()


class Incident:
    """
    A single heat-incident lifecycle object.

    Usable both as a long-lived object and as a serializable snapshot via
    `to_dict()` / `from_dict()` so the graph can persist it and the API can
    serve it without leaking internal mutations.
    """

    def __init__(
        self,
        *,
        incident_id: str,
        site: str,
        activity_id: str,
        ack_window_s: float = _ACK_WINDOW_S,
        clock: Optional[Clock] = None,
    ) -> None:
        self.incident_id = incident_id
        self.site = site
        self.activity_id = activity_id
        self.ack_window_s = max(0.0, ack_window_s)
        self._clock = clock or _default_clock()
        self.state = IncidentState.DETECTED
        self.created_at_iso = self._clock.now_iso()
        self.created_at_s = self._clock.now_s()
        self.entries: List[Dict[str, Any]] = []
        self.acknowledged_at_iso: Optional[str] = None
        self.acknowledged_by: Optional[str] = None
        self.ack_window_s_used: Optional[float] = None
        self.resolution_note: Optional[str] = None
        self.escalation_reasons: List[str] = []
        self._record("incident opened", f"site={site}", state=self.state)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _record(
        self, action: str, detail: str, state: IncidentState
    ) -> None:
        self.entries.append(
            {
                "state": state.value,
                "action": action,
                "detail": detail,
                "ts": self._clock.now_iso(),
            }
        )

    def _transition(self, target: IncidentState, action: str, reason: str) -> None:
        if target not in _TRANSITIONS[self.state]:
            raise ValueError(
                f"illegal transition {self.state.value} -> {target.value}"
            )
        self.state = target
        self._record(action, reason, state=target)

    # ------------------------------------------------------------------
    # Transitions
    # ------------------------------------------------------------------

    def assess(self, reason: str) -> "Incident":
        if self.state == IncidentState.ESCALATED:
            raise ValueError("cannot assess an escalated incident")
        self._transition(
            IncidentState.ASSESSING, "assessment started", reason
        )
        return self

    def plan(self, reason: str) -> "Incident":
        self._transition(IncidentState.PLANNED, "plan determined", reason)
        return self

    def act(self, reason: str) -> "Incident":
        self._transition(
            IncidentState.ACTING, "intervention executed", reason
        )
        return self

    def wait_for_ack(self, dispatched_mode: str) -> "Incident":
        self._transition(
            IncidentState.WAITING_FOR_ACK,
            "alert dispatched",
            f"mode={dispatched_mode}; ack window {self.ack_window_s:g}s",
        )
        return self

    def acknowledge(self, by: str) -> "Incident":
        if self.state != IncidentState.WAITING_FOR_ACK:
            raise ValueError(
                f"cannot ack from {self.state.value}; expected WAITING_FOR_ACK"
            )
        self._transition(
            IncidentState.ACKNOWLEDGED, "acknowledged", f"by={by}"
        )
        return self

    def timeout_ack(self) -> "Incident":
        """Mark the ack window as elapsed without acknowledgement."""
        if self.state != IncidentState.WAITING_FOR_ACK:
            raise ValueError(
                f"cannot time-out ack from {self.state.value}; "
                "expected WAITING_FOR_ACK"
            )
        self._transition(
            IncidentState.ACK_TIMED_OUT,
            "ack timeline",
            "ack window elapsed without acknowledgement",
        )
        return self

    def verify(self, reason: str) -> "Incident":
        self._transition(
            IncidentState.VERIFYING, "verification started", reason
        )
        return self

    def resolve(self, note: str) -> "Incident":
        self._transition(IncidentState.RESOLVED, "resolved", note)
        self.resolution_note = note
        return self

    def escalate(self, reason: str) -> "Incident":
        if self.state == IncidentState.RESOLVED:
            raise ValueError("cannot escalate a resolved incident")
        if self.state not in (
            IncidentState.VERIFYING,
            IncidentState.ACK_TIMED_OUT,
        ):
            self._transition(IncidentState.ESCALATING, "escalating", reason)
        else:
            self._transition(IncidentState.ESCALATING, "escalating", reason)
        self.escalation_reasons.append(reason)
        return self

    def mark_escalated(self) -> "Incident":
        self._transition(
            IncidentState.ESCALATED, "escalated", "human review required"
        )
        return self

    # ------------------------------------------------------------------
    # Query helpers (deterministic)
    # ------------------------------------------------------------------

    def ack_overdue(self) -> bool:
        """True when currently waiting for ack and past the window."""
        if self.state != IncidentState.WAITING_FOR_ACK:
            return False
        return (self._clock.now_s() - self.created_at_s) > self.ack_window_s

    def escalation_tier(self) -> str:
        """
        Deterministic escalation tier inferred from ack state + confidence:
          none       -> no wait; no escalation needed
          supervisor -> ack window elapsed without acknowledgement
          manager    -> ack window elapsed AND unresolved risk remains
        """
        if self.state == IncidentState.ESCALATED:
            return "escalated"
        if self.state == IncidentState.ACK_TIMED_OUT:
            return "manager" if self.escalation_reasons else "supervisor"
        return "none"

    # ------------------------------------------------------------------
    # Snapshot / restore
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "incident_id": self.incident_id,
            "site": self.site,
            "activity_id": self.activity_id,
            "state": self.state.value,
            "ack_window_s": self.ack_window_s,
            "created_at_iso": self.created_at_iso,
            "acknowledged_at_iso": self.acknowledged_at_iso,
            "acknowledged_by": self.acknowledged_by,
            "ack_overdue": self.ack_overdue(),
            "escalation_tier": self.escalation_tier(),
            "escalation_reasons": list(self.escalation_reasons),
            "resolution_note": self.resolution_note,
            "entries": list(self.entries),
        }


def open_incident(
    *,
    site: str,
    activity_id: str,
    incident_id: Optional[str] = None,
    ack_window_s: Optional[float] = None,
    clock: Optional[Clock] = None,
) -> Incident:
    from app.engine.audit import incident_id as _new_incident_id

    inc = Incident(
        incident_id=incident_id or _new_incident_id(activity_id),
        site=site,
        activity_id=activity_id,
        ack_window_s=ack_window_s if ack_window_s is not None else _ACK_WINDOW_S,
        clock=clock,
    )
    return inc
