"""
main.py
=======

FastAPI gateway for HeatShield AI.

Exposes:
  GET  /api/health
  POST /api/stream-agent          SSE agent run (grounded, deterministic math)
  POST /api/heatmap[?stream=1]    NDJSON progress-streamed heat grid
  GET  /api/cache/stats           observation-cache transparency
  GET  /api/thread/{thread_id}

This module contains ONLY transport concerns: CORS middleware, rate
limiting, router setup, and streaming endpoints. All agent logic lives in
app/nodes.py, app/graph.py, app/api/* and app/services/*.

Run locally:

    uvicorn app.main:app --port 8000
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Dict

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from app.api.deps import RATE_LIMIT_MAX, RATE_LIMIT_WINDOW_S, enforce_rate_limit
from app.api.heatmap import router as heatmap_router
from app.graph import NODE_NAMES, close_graph, get_graph, init_graph
from app.state import AgentRequest

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------

load_dotenv()

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(level=logging.INFO)

logger = logging.getLogger("heatshield.main")


# ---------------------------------------------------------------------------
# Agent execution pacing
#
# Intentional visual pause between SSE node updates so the agent's
# thought process is readable for non-technical viewers
# (anti-black-box UX). Override via AGENT_NODE_PACE_SECONDS.
# ---------------------------------------------------------------------------

NODE_PACE_SECONDS = float(
    os.getenv(
        "AGENT_NODE_PACE_SECONDS",
        "0.4",
    )
)


# ---------------------------------------------------------------------------
# FastAPI lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(
    app: FastAPI,
):
    """
    Application lifecycle.

    Delegates graph + checkpointer construction to app.graph so this
    module stays a thin transport layer.
    """

    await init_graph()

    logger.info(
        "HeatShield AI API ready "
        "(node pacing: %.2fs · rate limit %d/%ds)",
        NODE_PACE_SECONDS,
        RATE_LIMIT_MAX,
        RATE_LIMIT_WINDOW_S,
    )

    try:
        yield

    finally:
        await close_graph()


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="HeatShield AI",
    description=(
        "Autonomous Heat Intelligence & OSHA Compliance Agent "
        "(FortyGuard Hackathon '26) — deterministic Response-Gap scoring, "
        "NDJSON progress streaming, autonomous telephony dispatch."
    ),
    version="2.0.0",
    lifespan=lifespan,
)

app.include_router(heatmap_router)


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------

DEFAULT_ORIGINS = [
    "http://localhost:3000",
    "https://*.vercel.app",
]

EXTRA_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "EXTRA_CORS_ORIGINS",
        "",
    ).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=(
        DEFAULT_ORIGINS
        + EXTRA_ORIGINS
    ),
    allow_origin_regex=(
        r"https://.*\.vercel\.app"
    ),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Activity-Id"],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sse_event(
    event: str,
    data: Dict[str, Any],
) -> str:
    """
    Format an application event as a raw SSE frame (wire-identical to
    sse-starlette's output, minus the extra task machinery).
    """

    return (
        f"event: {event}\n"
        f"data: {json.dumps(data, default=str)}\n\n"
    )


def _is_agent_node(name: Any) -> bool:
    return name in set(NODE_NAMES)


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------

@app.get("/api/health")
async def health() -> Dict[str, str]:
    return {
        "status": "ok",
        "service": "heatshield-ai-backend",
    }


@app.get("/api/cache/stats")
async def cache_stats() -> Dict[str, Any]:
    """Observation-cache transparency for the Provenance Footer."""
    from app.services.observation_cache import get_observation_cache

    return get_observation_cache().stats()


# ---------------------------------------------------------------------------
# Agent SSE endpoint
# ---------------------------------------------------------------------------

@app.post("/api/stream-agent")
async def stream_agent(
    request: AgentRequest,
    _rate: None = Depends(enforce_rate_limit),
):
    """
    Streams real-time node status and LLM token events using SSE.

    Accepts a JSON body so sensitive BYOK credentials never transit
    the URL/query string (which FastAPI/uvicorn logs verbatim).
    FastAPI validates the AgentRequest body and returns 422 automatically
    on malformed payloads.

    Body schema:
        {
          "thread_id": "...",
          "location_name": "...",
          "latitude": 0.0,
          "longitude": 0.0,
          "operation_context": "construction|delivery|roadwork",
          "byok_provider": "...",   # optional
          "byok_key": "..."         # optional
        }
    """

    graph = get_graph()

    # -----------------------------------------------------------------------
    # LangGraph configuration
    # -----------------------------------------------------------------------

    config = {
        "configurable": {
            "thread_id": request.thread_id,
        }
    }

    activity_id = uuid.uuid4().hex[:12]

    # -----------------------------------------------------------------------
    # Initial state — built strictly from THIS request's parameters so a
    # new location can never inherit another site's checkpointed data.
    # -----------------------------------------------------------------------

    initial_state: Dict[str, Any] = {
        "thread_id": request.thread_id,
        "location_name": request.location_name,
        "latitude": request.latitude,
        "longitude": request.longitude,
        "operation_context": request.operation_context,
        "activity_id": activity_id,
        "byok_provider": request.byok_provider,
        "byok_key": request.byok_key,
        "node_log": [],
    }

    # -----------------------------------------------------------------------
    # SSE event generator
    # -----------------------------------------------------------------------

    async def event_generator() -> AsyncGenerator[Dict[str, str], None]:

        try:

            yield _sse_event(
                "status",
                {
                    "phase": "start",
                    "thread_id": (
                        request.thread_id
                    ),
                },
            )

            final_state: Dict[
                str,
                Any,
            ] = {}

            async for event in graph.astream_events(
                initial_state,
                config=config,
                version="v2",
            ):

                kind = event.get("event")

                # -----------------------------------------------------------
                # Node start
                # -----------------------------------------------------------

                if (
                    kind == "on_chain_start"
                    and _is_agent_node(event.get("name"))
                ):

                    yield _sse_event(
                        "node",
                        {
                            "name": event["name"],
                            "phase": "start",
                            "status": "running",
                        },
                    )

                    # Controlled pacing between node updates
                    await asyncio.sleep(NODE_PACE_SECONDS)

                # -----------------------------------------------------------
                # Node end
                # -----------------------------------------------------------

                elif (
                    kind == "on_chain_end"
                    and _is_agent_node(event.get("name"))
                ):

                    output = (
                        event.get(
                            "data",
                            {},
                        ).get(
                            "output"
                        )
                        or {}
                    )

                    if isinstance(output, dict):
                        final_state.update(output)

                    yield _sse_event(
                        "node",
                        {
                            "name": event["name"],
                            "phase": "end",
                            "status": "completed",
                        },
                    )

                    # Controlled pacing between node updates
                    await asyncio.sleep(NODE_PACE_SECONDS)

                # -----------------------------------------------------------
                # LLM token stream
                # -----------------------------------------------------------

                elif kind == "on_chat_model_stream":

                    chunk = (
                        event.get(
                            "data",
                            {},
                        ).get(
                            "chunk"
                        )
                    )

                    text = getattr(chunk, "content", None)

                    if text:
                        yield _sse_event(
                            "token",
                            {
                                "text": text,
                            },
                        )

            # ===============================================================
            # Get authoritative checkpointed state
            # ===============================================================

            snapshot = await graph.aget_state(config)

            if snapshot and snapshot.values:
                merged = dict(snapshot.values)
            else:
                merged = final_state

            # ===============================================================
            # Final result
            # ===============================================================

            yield _sse_event(
                "result",
                {
                    "enterprise_output": merged.get("enterprise_output"),
                    "risk_breakdown": merged.get("risk_breakdown"),
                    "tactical_actions": merged.get("tactical_actions", []),
                    "dispatch_records": merged.get("dispatch_records", []),
                    "dispatch_mode": merged.get("dispatch_mode"),
                    "activity_id": merged.get("activity_id"),
                    "awaiting_byok": merged.get("awaiting_byok", False),
                    "active_tier": merged.get("active_tier"),
                    "tier_trace": merged.get("tier_trace", []),
                    "node_log": merged.get("node_log", []),
                    # Closed-loop agent artifacts
                    "incident_id": merged.get("incident_id"),
                    "agent_outcome": merged.get("agent_outcome"),
                    "incident": merged.get("incident"),
                    "confidence": merged.get("confidence"),
                    "decision_trace": merged.get("decision_trace", []),
                    "intervention_simulations": merged.get(
                        "intervention_simulations", []
                    ),
                    "selected_intervention": merged.get("selected_intervention"),
                    "reassessment": merged.get("reassessment"),
                    "response_metrics": merged.get("response_metrics"),
                },
            )

            yield _sse_event(
                "status",
                {
                    "phase": "complete",
                    "thread_id": request.thread_id,
                },
            )

        except Exception as exc:

            logger.exception("Agent stream failed")

            yield _sse_event(
                "error",
                {
                    "message": str(exc),
                },
            )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Thread state endpoint
# ---------------------------------------------------------------------------

@app.get("/api/thread/{thread_id}")
async def get_thread_state(
    thread_id: str,
) -> Dict[str, Any]:
    """
    Fetch the last checkpointed state for a thread.
    """

    graph = get_graph()

    config = {
        "configurable": {
            "thread_id": thread_id,
        }
    }

    snapshot = await graph.aget_state(config)

    if not snapshot or not snapshot.values:
        raise HTTPException(
            status_code=404,
            detail=(
                "No checkpoint found "
                "for thread_id"
            ),
        )

    return dict(snapshot.values)


# ---------------------------------------------------------------------------
# Local execution
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8000)),
        reload=True,
    )
