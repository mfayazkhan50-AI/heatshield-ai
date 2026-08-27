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

# The current FortyGuard tOS Enterprise API is task-based: you POST a task
# (e.g. /v1/env_params) and get an activity_id back, then poll
# GET /v1/status/{activity_id} until the task terminates. Authentication is a
# plain `api-key` header (no bearer/OAuth). The legacy synchronous
# GET /v1/temperature/current endpoint no longer exists — that is why naive
# integrations see 401. See docs-api.fortyguard.com.
FORTYGUARD_BASE_URL = os.getenv("FORTYGUARD_BASE_URL", "https://api.fortyguard.com")

# Default snapshot date for environmental analysis. The catalog covers
# 2021 → today. We use "yesterday" so requests are always within coverage.
import datetime as _dt

_DEFAULT_START_DATE = (
    (_dt.date.today() - _dt.timedelta(days=1)).isoformat()
)
_DEFAULT_START_TIME = "15:00"

# env_params task may take seconds-to-minutes to complete — give the live
# task a dedicated, longer budget than the legacy heatmap poll deadline.
ENV_SUBMIT_TIMEOUT_S = float(os.getenv("FORTYGUARD_SUBMIT_TIMEOUT_S", "20.0"))
ENV_POLL_INTERVAL_S = float(os.getenv("FORTYGUARD_POLL_INTERVAL_S", "3.0"))
ENV_TASK_DEADLINE_S = float(os.getenv("FORTYGUARD_ENV_DEADLINE_S", "120.0"))
# Single status GET timeout.
ENV_STATUS_TIMEOUT_S = float(os.getenv("FORTYGUARD_ATTEMPT_TIMEOUT_S", "8.0"))

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


# ---------------------------------------------------------------------------
# Real live ingestion — FortyGuard tOS Enterprise API (task-based)
#
# The current API is asynchronous: POST /v1/env_params (a point analysis that
# returns, among many parameters, apparent temperature + heat index) to get an
# activity_id, then poll GET /v1/status/{activity_id} until it terminates.
# We use this to anchor the deterministic engine on REAL observed conditions,
# which flips the provenance from "simulated" to "live".
#
# The legacy GET /v1/temperature/current path (401/no_such_endpoint) is no
# longer used for live data; poll_live_frame/heatmap remains the resilient
# grid path but this env_params flow is what feeds the scoring graph.
# ---------------------------------------------------------------------------

async def _post_env_params(
    client: httpx.AsyncClient,
    api_key: str,
    lat: float,
    lon: float,
    fallback_temp_c: float,
) -> Optional[str]:
    """POST /v1/env_params and return the activity_id, or None."""
    resp = await client.post(
        f"{FORTYGUARD_BASE_URL}/v1/env_params",
        headers={"api-key": api_key, "Content-Type": "application/json"},
        json={
            "latitude": lat,
            "longitude": lon,
            "temperature": fallback_temp_c,
            "date_time": {
                "start_date": _DEFAULT_START_DATE,
                "start_time": _DEFAULT_START_TIME,
                "filter_type": 1,
            },
        },
    )
    resp.raise_for_status()
    body = resp.json()
    if body.get("error"):
        raise RuntimeError(body.get("message") or "env_params submission failed")
    try:
        return body["data"]["activity_id"]
    except KeyError as exc:
        raise RuntimeError(f"Unexpected submission shape: {body}") from exc


def _status_is_terminal(status: str) -> str:
    """Return 'ok', 'failed', or '' (still processing)."""
    s = (status or "").strip().lower()
    if s in ("completed", "succeeded", "success"):
        return "ok"
    if s in ("failed", "error", "cancelled"):
        return "failed"
    return ""


async def _poll_env_result(
    client: httpx.AsyncClient,
    api_key: str,
    activity_id: str,
    on_progress: Optional[ProgressCallback],
    total_deadline_s: float,
) -> Dict[str, Any]:
    """Poll GET /v1/status/{activity_id} until terminal. Returns result dict."""
    started = time.perf_counter()
    attempt = 0

    # Honest poll budget: the loop is time-bounded by `total_deadline_s`, not
    # an arbitrary 100. Derive the effective max polls from the deadline and
    # the poll interval so the streamed counter can genuinely reach 100%.
    poll_interval = ENV_POLL_INTERVAL_S
    max_polls = max(1, int(total_deadline_s / poll_interval) + 1)

    while True:
        elapsed = time.perf_counter() - started
        if elapsed >= total_deadline_s:
            raise TimeoutError(
                f"FortyGuard env task {activity_id} exceeded {total_deadline_s:.0f}s"
            )

        attempt += 1
        pct = min(100.0, round(attempt / max_polls * 100.0, 1))
        if on_progress is not None:
            await _maybe_await(
                on_progress(
                    {
                        "status": "polling",
                        "attempt": attempt,
                        "max": max_polls,
                        "pct": pct,
                        "elapsed_ms": round(elapsed * 1000.0, 1),
                        "deadline_s": total_deadline_s,
                        "phase": "env_params",
                    }
                )
            )

        try:
            resp = await client.get(
                f"{FORTYGUARD_BASE_URL}/v1/status/{activity_id}",
                headers={"api-key": api_key},
            )
            if resp.status_code == 404:
                # Eventual consistency right after submit — keep polling.
                await asyncio.sleep(ENV_POLL_INTERVAL_S)
                continue
            resp.raise_for_status()
            body = resp.json()
            data = body.get("data") or {}
            state = _status_is_terminal(data.get("status", ""))
            if state == "failed":
                raise RuntimeError(
                    f"FortyGuard task {activity_id} failed: {data.get('message') or body}"
                )
            if state == "ok":
                result = data.get("result") or data
                if isinstance(result, dict):
                    return result
                # Some statuses nest the payload under a list/wrapper — be lenient.
                return {"raw": result}
        except asyncio.CancelledError:
            raise
        except (httpx.TimeoutException, httpx.HTTPError) as exc:
            logger.warning("FortyGuard status poll attempt %s: %r", attempt, exc)
        except Exception as exc:
            logger.warning("FortyGuard status poll attempt %s: %r", attempt, exc)

        await asyncio.sleep(ENV_POLL_INTERVAL_S)


def _extract_live_temperatures(result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Pull the physically meaningful temperature signal out of the env_params
    result. The API returns per-location parameter arrays (°C) across the
    requested window:

        { "metadata": {..., "timestamps": [...]},
          "locations": [ { "lat":..., "lon":..., "temperature": 40.0,
                           "parameters": {
                             "apparent_temperature_celsius": [45.6],
                             "heat_index_celsius": [37.1],
                             "relative_humidity_percent": [10.9], ... } } ] }

    The heat-index alone is humidity-pegged (can peak overnight), while
    apparent_temperature follows the real diurnal cycle — so we anchor on the
    max apparent temperature (the genuine "hot hour") and record the heat
    index at that same hour.
    """
    locations = result.get("locations")
    if not isinstance(locations, list) or not locations:
        return None

    best_apparent: Optional[float] = None
    best_hi: Optional[float] = None
    best_air: Optional[float] = None
    best_rh: Optional[float] = None

    for loc in locations:
        if not isinstance(loc, dict):
            continue
        params = loc.get("parameters") or {}
        if not isinstance(params, dict):
            params = {}

        def _max_arr(d: Dict[str, Any], key: str) -> Optional[float]:
            v = d.get(key)
            if isinstance(v, list):
                vals = [x for x in v if isinstance(x, (int, float))]
                return max(vals) if vals else None
            if isinstance(v, (int, float)):
                return float(v)
            return None

        ap = _max_arr(params, "apparent_temperature_celsius")
        hi = _max_arr(params, "heat_index_celsius")
        air = _max_arr(
            params,
            "air_temperature_celsius",
        ) or _max_arr(params, "temperature_celsius")
        rh = _max_arr(params, "relative_humidity_percent")

        if ap is not None and (best_apparent is None or ap > best_apparent):
            best_apparent = ap
            if hi is not None:
                best_hi = hi
            if air is not None:
                best_air = air
            if rh is not None:
                best_rh = rh

    if best_apparent is None and best_air is None:
        return None

    anchor_c = best_apparent if best_apparent is not None else best_air
    anchor_f = anchor_c * 9.0 / 5.0 + 32.0
    hi_f = (best_hi * 9.0 / 5.0 + 32.0) if best_hi is not None else anchor_f

    return {
        "temperature_f": round(anchor_f, 2),
        "apparent_temp_f": round(anchor_f, 2),
        "heat_index_f": round(hi_f, 2),
        "relative_humidity_pct": best_rh if best_rh is not None else 30.0,
        "solar_load": "high" if anchor_f >= 90.0 else "moderate",
        "source": "live",
    }


async def fetch_live_env_params(
    lat: float,
    lon: float,
    *,
    on_progress: Optional[ProgressCallback] = None,
) -> Tuple[Optional[Dict[str, Any]], Optional[Exception]]:
    """
    Pull REAL street-level environmental parameters via the current FortyGuard
    task-based API. Never raises: returns `(frame, None)` on success or
    `(None, error)` when the API is unreachable, slow, or malformed, so the
    deterministic fallback can proceed. frame["source"] == "live".
    """
    api_key = os.getenv("FORTYGUARD_API_KEY", "")
    if not api_key:
        return None, None

    # Reasonable fallback temp anchor (used only when API omits it); not
    # surfaced to the user — replaced by the real observed value on success.
    fallback_temp_c = 40.0

    try:
        async with httpx.AsyncClient(timeout=ENV_SUBMIT_TIMEOUT_S) as client:
            activity_id = await _post_env_params(
                client, api_key, lat, lon, fallback_temp_c
            )
            if not activity_id:
                raise RuntimeError("env_params returned no activity_id")

            result = await _poll_env_result(
                client,
                api_key,
                activity_id,
                on_progress,
                total_deadline_s=ENV_TASK_DEADLINE_S,
            )

        frame = _extract_live_temperatures(result)
        if frame is None:
            return None, ValueError("env_params: no usable temperature signal")

        frame["latitude"] = lat
        frame["longitude"] = lon
        frame["observed_at"] = utc_now_iso()
        frame["activity_id"] = activity_id
        return frame, None

    except Exception as exc:  # noqa: BLE001 — resilient by design
        logger.warning("Live FortyGuard env_params failed: %r", exc)
        return None, exc


async def fetch_live_frame(
    lat: float,
    lon: float,
) -> Tuple[Optional[Dict[str, Any]], Optional[Exception]]:
    """
    One-shot live call used by the LangGraph ingest node. Attempts REAL
    FortyGuard live data via the current task-based env_params endpoint;
    falls back to `(None, error)` so the deterministic engine uses the
    simulated field when live data is unavailable. Never raises.
    """
    return await fetch_live_env_params(lat, lon)


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
