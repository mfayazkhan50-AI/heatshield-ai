"""
state.py
========
Core state contracts for the HeatShield AI LangGraph agent.

`AgentState` is the mutable graph-wide state object threaded through every
node in nodes.py. It is intentionally a TypedDict (LangGraph's native state
container) rather than a Pydantic model, because LangGraph applies reducers
(like `add_messages`) declaratively via `Annotated[...]` metadata on
TypedDict fields.

Everything the API layer accepts/returns (main.py) is validated instead with
the Pydantic v2 models below, so untrusted network input never touches the
graph state directly.
"""

from __future__ import annotations

from typing import Annotated, Any, Dict, List, Literal, Optional, TypedDict

from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field, field_validator

# ---------------------------------------------------------------------------
# Risk taxonomies
#
# Two orthogonal deterministic scales:
#   1. OSHA heat-index bins (legacy compliance templates)
#   2. Response-Gap tiers  NORMAL / ELEVATED / HIGH / CRITICAL  (UI + dispatch)
# ---------------------------------------------------------------------------

RiskLevel = Literal["Low", "Caution", "Warning", "Danger", "Extreme Danger"]

VALID_RISK_LEVELS: List[RiskLevel] = [
    "Low",
    "Caution",
    "Warning",
    "Danger",
    "Extreme Danger",
]

ResponseGapTier = Literal["NORMAL", "ELEVATED", "HIGH", "CRITICAL"]
OperationContext = Literal["construction", "delivery", "roadwork"]

VALID_OPERATIONS: List[str] = ["construction", "delivery", "roadwork"]


# ---------------------------------------------------------------------------
# LangGraph state (internal, graph-native)
# ---------------------------------------------------------------------------

class AgentState(TypedDict, total=False):
    """
    The single shared state object that flows through every node in the
    compiled StateGraph. `total=False` lets nodes return partial updates
    (LangGraph merges them onto the running state).
    """

    # Running interaction/tool trace. `add_messages` is LangGraph's built-in
    # reducer: instead of overwriting this list on every node update, it
    # appends new messages onto the existing thread history.
    messages: Annotated[list, add_messages]

    # Raw + normalized microclimate payload pulled from FortyGuard
    # (or injected from simulated climate normals when live is unavailable).
    fortyguard_data: Dict[str, Any]

    # Deterministic street-level grid for map rendering (may be synthesized
    # from climate normals when the live API cannot serve cells).
    heat_grid: Dict[str, Any]

    # Site/request identity
    thread_id: str
    location_name: str
    latitude: float
    longitude: float

    # Operation context selected in the UI (construction/delivery/roadwork)
    operation_context: str

    # Per-run activity id surfaced in the Provenance Footer
    activity_id: str

    # Labeled site vulnerability profile (SVI, density, cooling access)
    vulnerability_profile: Dict[str, Any]

    # Estimated consecutive hours above 40 °C (deterministic heuristic)
    sustained_hours: float

    # Computed by evaluate_heat_risk — DETERMINISTIC ONLY
    heat_index_f: float
    risk_level: str          # OSHA bin (compliance template selector)
    risk_breakdown: Dict[str, Any]   # full transparent scoring output

    # Produced by generate_compliance_plan (resilient cascade output)
    compliance_plan: Dict[str, Any]

    # Numbered tactical directives + autonomous dispatch results
    tactical_actions: List[Dict[str, Any]]
    dispatch_records: List[Dict[str, Any]]
    dispatch_mode: str   # "live" | "dry_run" | "not_triggered"

    # Which cascade tier actually satisfied the last LLM-backed node.
    active_tier: str
    tier_trace: List[str]

    # Set to True by the cascade if Tiers 1-4 exhausted and the client needs
    # to prompt the user for a BYOK (bring your own key) token.
    awaiting_byok: bool
    byok_key: Optional[str]
    byok_provider: Optional[str]

    # Final normalized payload for the UI / audit export
    enterprise_output: Dict[str, Any]

    # Node-level status log, streamed to the frontend as SSE progress events
    node_log: List[Dict[str, Any]]

    # ------------------------------------------------------------------
    # Closed-loop agent (P0): OBSERVE->ASSESS->PLAN->ACT->VERIFY->REASSESS
    # ------------------------------------------------------------------

    # Audit identity: run/incident/decision ids + provenance chain.
    incident_id: str
    decision_ids: List[str]

    # Deterministic confidence/uncertainty assessment for this decision.
    confidence: Dict[str, Any]

    # PLAN stage: projected before/after for every candidate intervention
    # (deterministic re-scores of the SAME R engine).
    intervention_simulations: List[Dict[str, Any]]
    selected_intervention: Dict[str, Any]

    # ACT stage: what the agent actually did + re-scored after-projection.
    executed_action: Dict[str, Any]

    # Server-authoritative incident lifecycle snapshot (from Incident.to_dict).
    incident: Dict[str, Any]

    # Immutable decision trace (list of decision_entry records).
    decision_trace: List[Dict[str, Any]]

    # REASSESS result: before/after gap + whether risk was mitigated.
    reassessment: Dict[str, Any]

    # Final outcome: RESOLVED when verified below threshold, else ESCALATED.
    agent_outcome: str

    # Deterministic response-metric delays (ms).
    response_metrics: Dict[str, Any]


# ---------------------------------------------------------------------------
# API layer models (Pydantic v2) — validate everything crossing the wire
# ---------------------------------------------------------------------------

class AgentRequest(BaseModel):
    """Validated JSON request body for POST /api/stream-agent.

    Credentials (byok_provider/byok_key) travel in the encrypted request
    body instead of the URL so they never appear in access logs, browser
    history, or proxy records.
    """

    thread_id: str = Field(
        ..., min_length=1, max_length=128,
        description="Client-supplied conversation/session id for checkpoint persistence.",
    )
    location_name: str = Field(default="Phoenix, AZ", max_length=120)
    latitude: float = Field(default=33.4484, ge=-90, le=90)
    longitude: float = Field(default=-112.0740, ge=-180, le=180)

    # Operation-specific context selector
    operation_context: OperationContext = Field(default="construction")

    # Optional BYOK token supplied by a judge/user after a Tier 4 prompt.
    byok_provider: Optional[
        Literal["groq", "gemini", "openai", "anthropic", "deepseek"]
    ] = None
    byok_key: Optional[str] = Field(default=None, max_length=256)

    @field_validator("thread_id")
    @classmethod
    def _no_whitespace(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("thread_id cannot be blank")
        return v


class CompliancePlanModel(BaseModel):
    """Structured, enterprise-ready actionable rules."""

    risk_level: RiskLevel
    heat_index_f: float
    work_rest_cycle: str
    hydration_benchmark: str
    monitoring_indicators: List[str]
    mandatory_ppe: List[str] = Field(default_factory=list)
    escalation_protocol: str
    generated_by_tier: str


class ComponentSubInput(BaseModel):
    key: str
    label: str
    value: float
    sub_weight: float
    anchor: str


class ScoreComponent(BaseModel):
    key: str
    label: str
    value: float
    weight: float
    method: str
    contribution: float
    subs: List[ComponentSubInput] = Field(default_factory=list)
    effective_inputs: Dict[str, Any] = Field(default_factory=dict)


class RiskBreakdownModel(BaseModel):
    """The full transparent scoring artifact rendered by 'Why Flagged?'."""

    schema_version: str
    engine: str
    response_gap: float = Field(..., ge=0.0, le=10.0)
    risk_tier: ResponseGapTier
    dispatch_eligible: bool
    dispatch_threshold: float
    formula_expression: str
    formula_substitution: str
    components: List[ScoreComponent]
    raw_inputs: Dict[str, Any]
    operation_profile: Dict[str, Any]


class TacticalAction(BaseModel):
    id: str
    title: str
    detail: str
    horizon: str
    source: str


class DispatchRecord(BaseModel):
    activity_id: str
    to: str
    site: str
    channel: Literal["sms", "voice"]
    mode: Literal["live", "dry_run"]
    status: str
    preview: Optional[str] = None
    provider_ref: Optional[str] = None
    error: Optional[str] = None
    ts: str


class EnterpriseOutput(BaseModel):
    """Normalized payload shape returned to the UI / audit trail."""

    location_name: str
    latitude: float
    longitude: float
    observed_at: str
    activity_id: str
    operation_context: OperationContext

    heat_index_f: float
    risk_level: RiskLevel
    risk_breakdown: RiskBreakdownModel

    compliance_plan: CompliancePlanModel
    tactical_actions: List[TacticalAction] = Field(default_factory=list)
    dispatch_records: List[DispatchRecord] = Field(default_factory=list)
    dispatch_mode: Literal["live", "dry_run", "not_triggered"]

    active_tier: str
    tier_trace: List[str]
    source: Literal["live", "cached", "simulated", "deterministic_fallback"]
