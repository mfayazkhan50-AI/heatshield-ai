"""
heatmap.py
==========
`POST /api/heatmap` — street-level temperature grid with NDJSON progress
streaming (`?stream=1`).

Streaming contract — one JSON object per line:

    {"type":"progress","status":"polling","attempt":3,"max":20,...}   per poll
    {"type":"fallback","reason":"timeout",...}                        on degrade
    {"type":"cells","cells":[...],"chunk":i,"of":n}                   batched grid
    {"type":"result","payload":{...}}                                 final frame
    {"type":"error","message":"..."}                                  terminal

Resilience ladder:
    observation cache (0 ms) → live FortyGuard poll loop (15 s deadline,
    20 attempts max) → deterministic climate-normal simulation.
The response NEVER hangs and NEVER renders blank: every degradation is an
explicit, labeled event.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, AsyncGenerator, Dict, List, Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.api.deps import enforce_rate_limit
from app.engine.scoring import (
    osha_bin_for_heat_index,
    score_response_gap,
)
from app.services import fortyguard
from app.services.climate_normals import synthesize_simulated_field
from app.services.observation_cache import get_observation_cache
from app.utils.clock import utc_now_iso

router = APIRouter(prefix="/api", tags=["heatmap"])

GRID_CHUNK_SIZE = 96  # cells per NDJSON frame (~1-2 KB each)


class HeatmapRequest(BaseModel):
    """Validated body for POST /api/heatmap."""

    location_name: str = Field(default="Phoenix, AZ", max_length=120)
    latitude: float = Field(default=33.4484, ge=-90, le=90)
    longitude: float = Field(default=-112.0740, ge=-180, le=180)
    operation_context: str = Field(default="construction")
    force_refresh: bool = Field(
        default=False,
        description="Bypass the observation cache and force a fresh fetch.",
    )

    cells_per_side: int = Field(default=24, ge=8, le=48)


def _line(event: Dict[str, Any]) -> str:
    return json.dumps(event, default=str) + "\n"


def _compute_breakdown_for_field(
    frame: Dict[str, Any],
    operation: str,
) -> Dict[str, Any]:
    """Deterministic Response-Gap score for the served field."""
    profile = frame.get("vulnerability_profile", {})

    peak_f = float(frame.get("temperature_f", 95.0))
    rh = float(frame.get("relative_humidity_pct", 30.0))

    # Rothfusz heat index (compact inline re-derivation keeps this module
    # independent of the graph layer).
    simple_hi = 0.5 * (peak_f + 61.0 + ((peak_f - 68.0) * 1.2) + (rh * 0.094))
    if simple_hi < 80.0:
        heat_index = round(simple_hi, 1)
    else:
        T, R = peak_f, rh
        heat_index = round(
            -42.379
            + 2.04901523 * T
            + 10.14333127 * R
            - 0.22475541 * T * R
            - 0.00683783 * T * T
            - 0.05481717 * R * R
            + 0.00122874 * T * T * R
            + 0.00085282 * T * R * R
            - 0.00000199 * T * T * R * R,
            1,
        )

    hours = float(
        frame.get("consecutive_hours_above_40c_est", 0.0) or 0.0
    )

    return score_response_gap(
        peak_temp_f=peak_f,
        relative_humidity_pct=rh,
        heat_index_f=heat_index,
        consecutive_hours_above_40c=hours,
        svi=float(profile.get("svi", 0.5)),
        population_density_per_km2=float(
            profile.get("population_density_per_km2", 1000)
        ),
        cooling_center_buffer_km=float(
            profile.get("cooling_center_buffer_km", 3.0)
        ),
        shade_coverage_pct=float(profile.get("shade_coverage_pct", 25.0)),
        operation=operation,
    )


async def _stream_events(
    req: HeatmapRequest,
    activity_id: str,
) -> AsyncGenerator[str, None]:
    """The full NDJSON event pipeline."""

    cache = get_observation_cache()
    cache_key = ObservationKey(req)

    yield _line(
        {
            "type": "meta",
            "activity_id": activity_id,
            "stage": "started",
            "operation": req.operation_context,
            "ts": utc_now_iso(),
        }
    )

    # ------------------------------------------------------------------
    # Layer 1 — observation cache (0 ms hot path)
    # ------------------------------------------------------------------

    if not req.force_refresh:
        cached = await asyncio.to_thread(cache.get, cache_key)
        if isinstance(cached, dict):
            yield _line(
                {
                    "type": "cache",
                    "hit": True,
                    "lookup_ms": cached.get("cache", {}).get("lookup_ms"),
                }
            )
            # Re-serve the persisted grid so the canvas paints even on a
            # cache hit (cells live in their own NDJSON frames, so a hit
            # that skipped the live path must stream them too).
            stored_cells = cached.get("cells") or []
            for chunk_idx in range(
                max(1, (len(stored_cells) + GRID_CHUNK_SIZE - 1) // GRID_CHUNK_SIZE)
            ):
                start = chunk_idx * GRID_CHUNK_SIZE
                yield _line(
                    {
                        "type": "cells",
                        "chunk": chunk_idx,
                        "of": max(
                            1,
                            (len(stored_cells) + GRID_CHUNK_SIZE - 1)
                            // GRID_CHUNK_SIZE,
                        ),
                        "cells": stored_cells[start : start + GRID_CHUNK_SIZE],
                    }
                )
                await asyncio.sleep(0)
            yield _line({"type": "result", "payload": cached})
            return

    yield _line({"type": "cache", "hit": False})

    # ------------------------------------------------------------------
    # Layer 2 — live FortyGuard poll loop w/ streamed progress
    # ------------------------------------------------------------------

    progress_queue: asyncio.Queue = asyncio.Queue()

    async def on_progress(event: Dict[str, Any]) -> None:
        await progress_queue.put(event)

    poll_task = asyncio.create_task(
        _drain_live(lat=req.latitude, lon=req.longitude, on_progress=on_progress)
    )

    while True:
        if poll_task.done() and progress_queue.empty():
            break

        try:
            progress_event = await asyncio.wait_for(
                progress_queue.get(), timeout=0.05
            )
            yield _line({"type": "progress", **progress_event})
        except asyncio.TimeoutError:
            continue

    frame, poll_meta = await poll_task

    fallback_reason: Optional[str] = None

    if frame is None:
        fallback_reason = (poll_meta or {}).get("reason", "unavailable")

        human_reason = {
            "timeout": "FortyGuard API Polling Timeout",
            "no_key": "FortyGuard API Key Not Configured",
            "zero_cells": "FortyGuard Returned Zero Cells",
        }.get(fallback_reason, "FortyGuard API Unavailable")

        yield _line(
            {
                "type": "fallback",
                "reason": fallback_reason,
                "message": (
                    f"SIMULATED FIELD / DATA ACTIVE — {human_reason}"
                ),
                "attempts": (poll_meta or {}).get("attempts", 0),
            }
        )

        simulated = synthesize_simulated_field(
            location_name=req.location_name,
            lat=req.latitude,
            lon=req.longitude,
            operation=req.operation_context,
            fallback_reason=fallback_reason,
            seed_suffix=activity_id,
            cells_per_side=req.cells_per_side,
        )
        frame = simulated["frame"]
        grid = simulated["grid"]
    else:
        # Live answer: re-anchor the deterministic grid onto the observed
        # peak temperature so tiles match reality.
        grid = build_live_grid(frame, req, activity_id)

    # ------------------------------------------------------------------
    # Deterministic scoring for the served field
    # ------------------------------------------------------------------

    breakdown = _compute_breakdown_for_field(frame, req.operation_context)

    osha_bin = osha_bin_for_heat_index(float(frame["temperature_f"]))

    # ------------------------------------------------------------------
    # Stream the grid in chunks so first paint starts immediately
    # ------------------------------------------------------------------

    cells: List[Dict[str, Any]] = grid["cells"]
    total_chunks = max(1, (len(cells) + GRID_CHUNK_SIZE - 1) // GRID_CHUNK_SIZE)

    for chunk_idx in range(total_chunks):
        start = chunk_idx * GRID_CHUNK_SIZE
        batch = cells[start : start + GRID_CHUNK_SIZE]

        yield _line(
            {
                "type": "cells",
                "chunk": chunk_idx,
                "of": total_chunks,
                "cells": batch,
            }
        )

        # Let the event loop flush frames to the socket progressively
        await asyncio.sleep(0)

    # ------------------------------------------------------------------
    # Final result envelope + cache write
    # ------------------------------------------------------------------

    payload = {
        "activity_id": activity_id,
        "location_name": req.location_name,
        "latitude": req.latitude,
        "longitude": req.longitude,
        "operation_context": req.operation_context,
        "source": frame.get("source", "simulated"),
        "fallback_reason": fallback_reason,
        "provenance": frame.get("provenance"),
        "observed_at": frame.get("observed_at"),
        "peak_temp_f": grid["peak_temp_f"],
        "peak_temp_c": grid["peak_temp_c"],
        "critical_cells": grid["critical_cells"],
        "tile_count": grid["tile_count"],
        "consecutive_hours_above_40c": frame.get(
            "consecutive_hours_above_40c_est", 0.0
        ),
        "osha_bin": osha_bin,
        "risk_breakdown": breakdown,
        "poll_meta": poll_meta or {},
        "generated_at": utc_now_iso(),
    }

    # Persist the grid so a later cache-hit can re-serve the exact tiles
    # without re-running the live poll (see the cache-hit branch below).
    payload_with_cells = {**payload, "cells": cells}

    await asyncio.to_thread(cache.put, cache_key, payload_with_cells)

    yield _line({"type": "result", "payload": payload})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def ObservationKey(req: HeatmapRequest) -> str:
    from app.services.observation_cache import ObservationCache

    return ObservationCache.build_key(
        req.latitude,
        req.longitude,
        req.operation_context,
        req.cells_per_side,
    )


async def _drain_live(
    lat: float,
    lon: float,
    on_progress,
):
    """
    Try REAL street-level conditions first via the task-based env_params
    client (same progress callback so the NDJSON stream reports attempts),
    then fall back to the legacy poll loop. Returns (frame, meta) where
    meta carries a 'reason' for the fallback taxonomy.
    """
    # Primary: real FortyGuard live env_params (source becomes "live").
    frame, err = await fortyguard.fetch_live_env_params(
        lat, lon, on_progress=on_progress
    )
    if frame is not None:
        meta: Dict[str, str] = {"reason": "ok", "attempts": 1}
        return frame, meta

    # Fallback: legacy grid poll (kept for backward-compat/tests).
    last_frame = None
    last_meta = None

    async for frame, meta in fortyguard.poll_live_frame(
        lat, lon, on_progress=on_progress
    ):
        last_frame = frame
        last_meta = meta
        if frame is not None:
            break

    return last_frame, last_meta


def build_live_grid(
    frame: Dict[str, Any],
    req: HeatmapRequest,
    activity_id: str,
) -> Dict[str, Any]:
    """
    Deterministic grid anchored on the live observed peak so tiles match
    reality when FortyGuard answers but doesn't expose cell-level data.
    """
    from app.services.climate_normals import build_micro_grid

    return build_micro_grid(
        lat=float(frame.get("latitude", req.latitude)),
        lon=float(frame.get("longitude", req.longitude)),
        base_temp_f=float(frame["temperature_f"]),
        seed=f"live:{activity_id}",
        cells_per_side=req.cells_per_side,
    )


@router.post("/heatmap", dependencies=[Depends(enforce_rate_limit)])
async def heatmap(
    request: Request,
    body: HeatmapRequest,
    stream: int = Query(default=0, ge=0, le=1),
):
    activity_id = uuid.uuid4().hex[:12]

    if stream:
        return StreamingResponse(
            _stream_events(body, activity_id),
            media_type="application/x-ndjson",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "X-Activity-Id": activity_id,
            },
        )

    # --------------------------------------------------------------
    # Non-streaming JSON mode — same resilience ladder, one shot
    # --------------------------------------------------------------

    cache = get_observation_cache()
    cache_key = ObservationKey(body)

    if not body.force_refresh:
        cached = await asyncio.to_thread(cache.get, cache_key)
        if isinstance(cached, dict):
            return JSONResponse(cached)

    frame, poll_meta = await _drain_poll_simple(body.latitude, body.longitude)

    fallback_reason = None
    if frame is None:
        fallback_reason = (poll_meta or {}).get("reason", "unavailable")
        simulated = synthesize_simulated_field(
            location_name=body.location_name,
            lat=body.latitude,
            lon=body.longitude,
            operation=body.operation_context,
            fallback_reason=fallback_reason,
            seed_suffix=activity_id,
            cells_per_side=body.cells_per_side,
        )
        frame = simulated["frame"]
        grid = simulated["grid"]
    else:
        from app.services.climate_normals import build_micro_grid

        grid = build_micro_grid(
            lat=body.latitude,
            lon=body.longitude,
            base_temp_f=float(frame["temperature_f"]),
            seed=f"live:{activity_id}",
            cells_per_side=body.cells_per_side,
        )

    breakdown = _compute_breakdown_for_field(frame, body.operation_context)

    payload = {
        "activity_id": activity_id,
        "location_name": body.location_name,
        "latitude": body.latitude,
        "longitude": body.longitude,
        "operation_context": body.operation_context,
        "source": frame.get("source", "simulated"),
        "fallback_reason": fallback_reason,
        "provenance": frame.get("provenance"),
        "observed_at": frame.get("observed_at"),
        "peak_temp_f": grid["peak_temp_f"],
        "peak_temp_c": grid["peak_temp_c"],
        "critical_cells": grid["critical_cells"],
        "tile_count": grid["tile_count"],
        "consecutive_hours_above_40c": frame.get(
            "consecutive_hours_above_40c_est", 0.0
        ),
        "osha_bin": osha_bin_for_heat_index(float(frame["temperature_f"])),
        "risk_breakdown": breakdown,
        "poll_meta": poll_meta or {},
        "generated_at": utc_now_iso(),
        "cells": grid["cells"],
    }

    await asyncio.to_thread(cache.put, cache_key, payload)

    return JSONResponse(payload)


async def _drain_poll_simple(lat: float, lon: float):
    frame, err = await fortyguard.fetch_live_env_params(lat, lon)
    if frame is not None:
        return frame, {"reason": "ok"}

    last_frame = None
    last_meta = None

    async for frame, meta in fortyguard.poll_live_frame(lat, lon):
        last_frame = frame
        last_meta = meta
        if frame is not None:
            break

    return last_frame, last_meta
