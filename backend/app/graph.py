"""
graph.py
========
StateGraph assembly and checkpointer lifecycle for HeatShield AI.

Graph shape (5 nodes with a conditional dispatch gate):

    ingest_environmental_data
              |
              v
      evaluate_heat_risk        <-- DETERMINISTIC scoring (zero-LLM)
              |
              v
    generate_compliance_plan    <-- grounded prose cascade lives here
              |
        [risk_tier == CRITICAL ?]   (R >= 7.0 gate)
         /                    \
       YES                     NO
        |                       |
        v                       |
   dispatch_critical_alerts     |
   (SMS/voice telephony)        |
        |                      /
        +----------+----------+
                   v
        format_enterprise_output

Persistence:
    Checkpointing is provided by the AsyncSqliteSaver created in
    init_graph() (or an in-memory MemorySaver when
    CHECKPOINT_DB_PATH=":memory:"). The graph itself does NOT create or
    own the SQLite connection — FastAPI's lifespan drives
    init_graph()/close_graph().
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

import aiosqlite
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, StateGraph

from app.nodes import (
    dispatch_critical_alerts_node,
    escalate_or_resolve,
    evaluate_heat_risk,
    execute_intervention,
    format_enterprise_output,
    generate_compliance_plan,
    ingest_environmental_data,
    plan_intervention,
    reassess_risk,
    verify_acknowledgement,
)
from app.state import AgentState

logger = logging.getLogger("heatshield.graph")

# ---------------------------------------------------------------------------
# Canonical node ordering — also used by the SSE stream filter in main.py
#
# Base OBSERVE/ASSESS/DISPATCH/REPORT chain is preserved so existing SSE
# consumers and tests keep working; the closed-loop stage is appended.
# ---------------------------------------------------------------------------

NODE_NAMES = [
    "ingest_environmental_data",
    "evaluate_heat_risk",
    "generate_compliance_plan",
    "dispatch_critical_alerts",
    "plan_intervention",          # ASSESS + PLAN
    "execute_intervention",       # ACT
    "verify_acknowledgement",     # VERIFY
    "reassess_risk",              # REASSESS
    "escalate_or_resolve",        # ESCALATE / RESOLVE
    "format_enterprise_output",
]

DISPATCH_NODE = "dispatch_critical_alerts"
PLAN_NODE = "plan_intervention"
FINAL_NODE = "format_enterprise_output"

NODE_FUNCS = {
    "ingest_environmental_data": ingest_environmental_data,
    "evaluate_heat_risk": evaluate_heat_risk,
    "generate_compliance_plan": generate_compliance_plan,
    "dispatch_critical_alerts": dispatch_critical_alerts_node,
    "plan_intervention": plan_intervention,
    "execute_intervention": execute_intervention,
    "verify_acknowledgement": verify_acknowledgement,
    "reassess_risk": reassess_risk,
    "escalate_or_resolve": escalate_or_resolve,
    "format_enterprise_output": format_enterprise_output,
}


def route_after_plan(state: AgentState) -> str:
    """Deterministic dispatch gate: CRITICAL (R >= 7.0) → telephony node.

    Both branches converge on the closed-loop stage (plan_intervention),
    which gracefully handles the non-critical path.
    """
    breakdown = state.get("risk_breakdown") or {}

    if breakdown.get("risk_tier") == "CRITICAL":
        return DISPATCH_NODE

    return PLAN_NODE


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

def build_graph(
    checkpointer: Optional[BaseCheckpointSaver] = None,
):
    """
    Build and compile the HeatShield LangGraph.

    The checkpointer is injected by the caller so the async SQLite
    connection remains under application-lifecycle management. When no
    checkpointer is supplied, a volatile MemorySaver is used.
    """

    if checkpointer is None:
        checkpointer = MemorySaver()

    builder = StateGraph(AgentState)

    for name in NODE_NAMES:
        builder.add_node(name, NODE_FUNCS[name])

    builder.set_entry_point(NODE_NAMES[0])

    builder.add_edge("ingest_environmental_data", "evaluate_heat_risk")
    builder.add_edge("evaluate_heat_risk", "generate_compliance_plan")

    builder.add_conditional_edges(
        "generate_compliance_plan",
        route_after_plan,
        {
            DISPATCH_NODE: DISPATCH_NODE,
            PLAN_NODE: PLAN_NODE,
        },
    )

    builder.add_edge(DISPATCH_NODE, PLAN_NODE)

    builder.add_edge(PLAN_NODE, "execute_intervention")
    builder.add_edge("execute_intervention", "verify_acknowledgement")
    builder.add_edge("verify_acknowledgement", "reassess_risk")
    builder.add_edge("reassess_risk", "escalate_or_resolve")
    builder.add_edge("escalate_or_resolve", FINAL_NODE)
    builder.add_edge(FINAL_NODE, END)

    return builder.compile(checkpointer=checkpointer)


# ---------------------------------------------------------------------------
# Process-wide graph resources + lifecycle
# ---------------------------------------------------------------------------

_db: Optional[aiosqlite.Connection] = None
_checkpointer: Optional[BaseCheckpointSaver] = None
_graph: Any = None


async def init_graph() -> None:
    """
    Create the process-wide compiled graph.

    Uses AsyncSqliteSaver against CHECKPOINT_DB_PATH, or a MemorySaver when
    the path is ":memory:" / unset to memory explicitly.
    """

    global _db
    global _checkpointer
    global _graph

    db_path = os.getenv(
        "CHECKPOINT_DB_PATH",
        "./heatshield_checkpoints.sqlite",
    )

    if db_path == ":memory:":
        logger.info(
            "Using in-memory MemorySaver checkpointer"
        )

        _db = None
        _checkpointer = MemorySaver()

        _graph = build_graph(_checkpointer)

        logger.info(
            "HeatShield AI graph initialized successfully"
        )

        return

    logger.info(
        "Opening SQLite checkpoint database: %s",
        db_path,
    )

    # -----------------------------------------------------------------------
    # Open async SQLite connection
    # -----------------------------------------------------------------------

    _db = await aiosqlite.connect(db_path)

    # -----------------------------------------------------------------------
    # SQLite configuration
    # -----------------------------------------------------------------------

    await _db.execute("PRAGMA journal_mode=WAL;")
    await _db.execute("PRAGMA foreign_keys=ON;")
    await _db.commit()

    # -----------------------------------------------------------------------
    # Async LangGraph checkpointer
    # -----------------------------------------------------------------------

    _checkpointer = AsyncSqliteSaver(_db)

    _graph = build_graph(_checkpointer)

    logger.info(
        "HeatShield AI graph initialized successfully"
    )


async def close_graph() -> None:
    """Release graph resources; safe to call multiple times."""

    global _db
    global _checkpointer
    global _graph

    logger.info("Shutting down HeatShield AI...")

    if _db is not None:
        await _db.close()

    _db = None
    _checkpointer = None
    _graph = None

    logger.info("SQLite connection closed")


def get_graph() -> Any:
    """
    Returns the initialized LangGraph instance.

    Raises RuntimeError when init_graph() has not completed yet.
    """

    if _graph is None:
        raise RuntimeError(
            "LangGraph has not been initialized."
        )

    return _graph
