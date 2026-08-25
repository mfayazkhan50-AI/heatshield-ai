"""
fortyguard.py
=============
FortyGuard Temperature API client with transparent poll-loop resilience.

The live API is optional. When it is slow (>15 s deadline), erroring, or
returns zero cells, callers fall back to local climate normals — but every
poll attempt is reported through an async progress callback so the NDJSON
route can stream `{"status": "polling", "attempt": N, "max": M}` frames to
the browser in real time. No more silent freezes.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, AsyncGenerator, Callable, Dict, Optional, Tuple

import httpx

from app.services.climate_normals import (
    build_micro_grid,
    get_city_normal,
)
from app.utils.clock import utc_now_iso

logger = logging.getLogger("heatshield.fortyguard")

FORTYGUARD_BASE_URL = "https://api.fortyguard.com/v1/temperature"

# Resilience tuning (env-overridable, deterministic defaults)
POLL_MAX_ATTEMPTS = int(os.getenv("FORTYGUARD_POLL_MAX_ATTEMPTS", "20"))
POLL_INTERVAL_S = float(os.getenv("FORTYGUARD_POLL_INTERVAL_S", "0.75"))
POLL_ATTEMPT_TIMEOUT_S = float(os.getenv("FORTYGUARD_ATTEMPT_TIMEOUT_S", "3.0"))
POLL_TOTAL_DEADLINE_S = float(os.getenv("FORTYGUARD_DEADLINE_S", "15.0"))

ProgressCallback = Callable[[Dict[str, Any]], Any]


def has_api_key() -> bool:
    """True when a FortyGuard API key is configured in the environment."""
    return bool(os.getenv("FORTYGUARD_API_KEY", ""))


# ---------------------------------------------------------------------------
# Payload normalization — guards against malformed / empty responses
# ---------------------------------------------------------------------------

def normalize_payload(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Convert a provider payload into the canonical frame dict.
    Returns None when the payload carries zero usable temperature data
    (the "zero cells" guard).
    """
    if not isinstance(payload, dict):
        return None

    temp_f = payload.get("temperature_f")

    cells = payload.get("cells")
    if temp_f is None and isinstance(cells, list):
        temps = [
            c.get("temp_f") or c.get("temperature_f")
            for c in cells
            if isinstance(c, dict)
        ]
        temps = [t for t in temps if isinstance(t, (int, float))]
        if temps:
            temp_f = max(temps)

    if not isinstance(temp_f, (int, float)):
        return None

    rh = payload.get("relative_humidity_pct")
    if not isinstance(rh, (int, float)):
        rh = 30.0

    return {
        "temperature_f": float(temp_f),
        "relative_humidity_pct": float(rh),
        "wind_mph": float(payload.get("wind_mph") or 0.0),
        "solar_load": str(payload.get("solar_load") or "unknown"),
        "observed_at": str(payload.get("observed_at") or utc_now_iso()),
        "source": "live",
    }


# ---------------------------------------------------------------------------
# Poll loop with live progress reporting
# ---------------------------------------------------------------------------

async def poll_live_frame(
    lat: float,
    lon: float,
    *,
    on_progress: Optional[ProgressCallback] = None,
    max_attempts: int = POLL_MAX_ATTEMPTS,
    interval_s: float = POLL_INTERVAL_S,
    attempt_timeout_s: float = POLL_ATTEMPT_TIMEOUT_S,
    total_deadline_s: float = POLL_TOTAL_DEADLINE_S,
) -> AsyncGenerator[Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]], None]:
    """
    Attempt the live FortyGuard fetch up to `max_attempts` times inside a
    hard `total_deadline_s` budget, emitting one progress event per attempt:

        {"status": "polling", "attempt": 3, "max": 20,
         "elapsed_ms": 2310, "deadline_s": 15}

    Terminal yields:
        (frame, {"reason": "ok"})                      on success
        (None,  {"reason": "timeout"|"error"|"zero_cells",
                 "attempts": n, "elapsed_ms": ms})     on fallback trigger
    """

    started = time.perf_counter()

    def elapsed_ms() -> float:
        return (time.perf_counter() - started) * 1000.0

    api_key = os.getenv("FORTYGUARD_API_KEY", "")

    if not api_key:
        yield None, {
            "reason": "no_key",
            "attempts": 0,
            "elapsed_ms": round(elapsed_ms(), 1),
        }
        return

    last_error: Optional[str] = None

    for attempt in range(1, max_attempts + 1):

        if elapsed_ms() / 1000.0 >= total_deadline_s:
            yield None, {
                "reason": "timeout",
                "attempts": attempt - 1,
                "elapsed_ms": round(elapsed_ms(), 1),
                "message": (
                    f"FortyGuard polling exceeded {total_deadline_s:.0f}s deadline"
                ),
            }
            return

        if on_progress is not None:
            await _maybe_await(
                on_progress(
                    {
                        "status": "polling",
                        "attempt": attempt,
                        "max": max_attempts,
                        "elapsed_ms": round(elapsed_ms(), 1),
                        "deadline_s": total_deadline_s,
                    }
                )
            )

        try:
            async with httpx.AsyncClient(timeout=attempt_timeout_s) as client:
                resp = await client.get(
                    f"{FORTYGUARD_BASE_URL}/current",
                    params={"lat": lat, "lon": lon},
                    headers={"Authorization": f"Bearer {api_key}"},
                )
                resp.raise_for_status()
                payload = resp.json()

        except httpx.TimeoutException as exc:
            last_error = f"attempt_timeout:{exc.__class__.__name__}"
            logger.warning("FortyGuard attempt %s timed out", attempt)

        except Exception as exc:
            last_error = f"error:{exc.__class__.__name__}"
            logger.warning(
                "FortyGuard attempt %s failed: %r", attempt, exc
            )

        else:
            frame = normalize_payload(payload)

            if frame is not None:
                frame["latency_ms"] = round(elapsed_ms(), 1)
                yield frame, {"reason": "ok", "attempts": attempt}
                return

            last_error = "zero_cells"

        remaining_budget = total_deadline_s - elapsed_ms() / 1000.0
        if remaining_budget <= 0:
            break

        await asyncio.sleep(min(interval_s, remaining_budget))

    yield None, {
        "reason": _terminal_reason(last_error, elapsed_ms() / 1000.0 >= total_deadline_s),
        "attempts": max_attempts,
        "elapsed_ms": round(elapsed_ms(), 1),
        "message": f"FortyGuard unreachable after {max_attempts} attempts",
    }


def _terminal_reason(last_error: Optional[str], deadline_hit: bool) -> str:
    """Normalize failure modes onto the documented fallback taxonomy."""
    if deadline_hit:
        return "timeout"
    if last_error == "zero_cells":
        return "zero_cells"
    if last_error and last_error.startswith("attempt_timeout"):
        return "timeout"
    return "error"


async def _maybe_await(result: Any) -> None:
    """Support both sync and async progress callbacks."""
    if hasattr(result, "__await__"):
        await result


async def fetch_live_frame(
    lat: float,
    lon: float,
) -> Tuple[Optional[Dict[str, Any]], Optional[Exception]]:
    """
    Legacy one-shot live call kept for the LangGraph ingest node.
    Returns `(frame, None)` on success or `(None, error)`. Never raises.
    """
    api_key = os.getenv("FORTYGUARD_API_KEY", "")

    if not api_key:
        return None, None

    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            resp = await client.get(
                f"{FORTYGUARD_BASE_URL}/current",
                params={"lat": lat, "lon": lon},
                headers={"Authorization": f"Bearer {api_key}"},
            )
            resp.raise_for_status()
            payload = resp.json()

    except Exception as exc:
        logger.warning("Live FortyGuard call failed: %r", exc)
        return None, exc

    frame = normalize_payload(payload)

    if frame is None:
        return None, ValueError("zero_cells_or_malformed_payload")

    return frame, None


# ---------------------------------------------------------------------------
# Backwards-compatible cached-frame helpers (now climate-normal backed)
# ---------------------------------------------------------------------------

def get_cached_frame(location_name: str) -> Dict[str, Any]:
    """Simulated climate-normal frame for a location (provenance-stamped)."""
    normal = get_city_normal(location_name)
    grid = build_micro_grid(33.4484, -112.0740, normal["normal_high_f"], seed="legacy")
    return {
        "temperature_f": grid["peak_temp_f"],
        "relative_humidity_pct": normal["normal_rh_pct"],
        "wind_mph": 6.2,
        "solar_load": "high",
        "observed_at": "simulated:climate-normal",
        "source": "simulated",
    }
