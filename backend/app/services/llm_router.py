"""
llm_router.py
=============
The 4-Tier Resilient LLM Cascade (`execute_resilient_llm`) plus the
Tier 5 deterministic rule-engine fallbacks.

Tier order:

    1. Groq  (primary key)
    2. Groq  (secondary key)
    3. Gemini (tertiary)
    4. BYOK  (user-supplied key: groq | gemini | openai | anthropic |
       deepseek)
    5. Deterministic pure-Python rules — always succeeds

The router is transport-only: it returns structured results plus a list of
human-readable events; callers own log formatting/persistence.
"""

from __future__ import annotations

import copy
import json
import logging
import os
from typing import Any, Dict, List, Mapping, TypedDict

logger = logging.getLogger("heatshield.llm_router")

GROQ_MODEL = "openai/gpt-oss-120b"
GEMINI_MODEL = "gemini-1.5-flash"


# ---------------------------------------------------------------------------
# Structured result contract
# ---------------------------------------------------------------------------

class LLMCascadeResult(TypedDict):
    compliance_plan: Dict[str, Any]
    active_tier: str
    tier_trace: List[str]
    awaiting_byok: bool
    # Human-readable progress events: {"message": str, "level": "info"|"warning"}
    events: List[Dict[str, Any]]


def _event(
    message: str,
    level: str = "info",
) -> Dict[str, Any]:
    return {"message": message, "level": level}


# ---------------------------------------------------------------------------
# Prompt construction / response parsing
#
# GROUNDING CONTRACT: the deterministic scoring artifact (risk_breakdown) is
# the single source of numeric truth. The model narrates; it NEVER computes.
# The static instruction block leads the prompt as a stable prefix so the
# provider's automatic prompt cache (Groq KV-cache) keeps repeat runs fast.
# ---------------------------------------------------------------------------

_PROMPT_PREAMBLE = (
    "You are HeatShield AI, an OSHA-compliance safety engine for outdoor "
    "worksite managers.\n"
    "STRICT RULES:\n"
    "1. ALL risk scores, temperatures, thresholds and classifications in the "
    "DETERMINISTIC SCORING ARTIFACT below were computed by a certified "
    "rule engine. Treat them as immutable ground truth.\n"
    "2. You MUST NOT compute, estimate, alter or invent ANY number. Never "
    "output a score that is not already present in the artifact.\n"
    "3. Your job is language only: operational prose around the fixed "
    "numbers.\n"
    "Produce a strict JSON object (no markdown, no prose outside JSON) with "
    "these keys:\n"
    '  "work_rest_cycle": string '
    '(e.g. "15 min shade rest per 45 min work"),\n'
    '  "hydration_benchmark": string '
    '(e.g. "1L water per hour minimum"),\n'
    '  "monitoring_indicators": array of 3-5 short strings '
    "(symptoms/metrics to watch),\n"
    '  "mandatory_ppe": array of short strings,\n'
    '  "escalation_protocol": string describing when to halt work / call '
    "for medical aid.\n\n"
)


def _format_breakdown_for_prompt(
    breakdown: Mapping[str, Any],
) -> str:
    components = breakdown.get("components", [])
    lines = [
        f"response_gap_R: {breakdown.get('response_gap')}",
        f"risk_tier: {breakdown.get('risk_tier')}",
        f"formula: {breakdown.get('formula_substitution')}",
    ]

    for c in components:
        subs = ", ".join(
            f"{s['key']}={s['value']}" for s in c.get("subs", [])
        )
        lines.append(f"component {c['key']}: {c['value']} ({subs})")

    raw = breakdown.get("raw_inputs", {})
    for key in (
        "peak_temp_f",
        "heat_index_f",
        "consecutive_hours_above_40c",
        "svi",
        "cooling_center_buffer_km",
    ):
        if key in raw:
            lines.append(f"{key}: {raw[key]}")

    return "\n".join(lines)


def build_llm_prompt(
    state: Mapping[str, Any],
) -> str:

    frame = state.get(
        "fortyguard_data",
        {},
    )

    breakdown = state.get("risk_breakdown") or {}

    artifact = (
        _format_breakdown_for_prompt(breakdown)
        if breakdown
        else (
            f"Heat Index: {state.get('heat_index_f')}°F · "
            f"OSHA bin: {state.get('risk_level')}"
        )
    )

    return (
        _PROMPT_PREAMBLE
        + "\nDETERMINISTIC SCORING ARTIFACT (ground truth):\n"
        + artifact
        + "\n\n"
        + f"Location: {state.get('location_name')}\n"
        + f"Temperature: {frame.get('temperature_f')}°F\n"
        + f"Relative Humidity: {frame.get('relative_humidity_pct')}%\n"
        + f"OSHA Risk Category: {state.get('risk_level')}\n"
        + f"Response-Gap Tier: {(breakdown or {}).get('risk_tier', state.get('risk_level'))}\n\n"
        + "Respond with ONLY the JSON object."
    )


def parse_llm_json(
    raw_text: str,
) -> Dict[str, Any]:
    """
    Parse a model response into JSON, tolerating markdown code fences and
    leading/trailing prose. Raises ValueError when no JSON object exists.
    """

    cleaned = raw_text.strip()

    if cleaned.startswith("```"):
        first_line_break = cleaned.find("\n")
        if first_line_break != -1:
            cleaned = cleaned[first_line_break + 1:]

        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rstrip()[:-3]

    cleaned = cleaned.strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")

        if start == -1 or end <= start:
            raise ValueError(
                f"No JSON object found in LLM output: {raw_text[:120]!r}"
            )

        return json.loads(cleaned[start : end + 1])


# ---------------------------------------------------------------------------
# Provider adapters
#
# Hosted tiers (1-3) stay Groq + Gemini via their LangChain clients.
# Tier 4 BYOK accepts any provider in BYOK_PROVIDERS: OpenAI-compatible
# APIs (OpenAI, DeepSeek, Groq) share one httpx transport; Anthropic and
# Gemini get dedicated adapters.
# ---------------------------------------------------------------------------

BYOK_PROVIDERS: Dict[str, Dict[str, str]] = {
    "groq": {"kind": "langchain_groq"},
    "gemini": {"kind": "langchain_gemini"},
    "openai": {
        "kind": "openai",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
    },
    "deepseek": {
        "kind": "openai",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
    },
    "anthropic": {
        "kind": "anthropic",
        "base_url": "https://api.anthropic.com/v1",
        "model": "claude-3-5-haiku-latest",
    },
}

_BYOK_TIMEOUT_S = 20.0


async def _try_openai_compatible(
    base_url: str,
    model: str,
    api_key: str,
    prompt: str,
) -> Dict[str, Any]:
    """Chat-completions transport shared by OpenAI / DeepSeek / Groq."""

    import httpx

    async with httpx.AsyncClient(timeout=_BYOK_TIMEOUT_S) as client:
        resp = await client.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "temperature": 0.2,
                "messages": [{"role": "user", "content": prompt}],
            },
        )

    if resp.status_code >= 400:
        raise RuntimeError(
            f"provider HTTP {resp.status_code}: {resp.text[:160]}"
        )

    payload = resp.json()
    content = (
        payload.get("choices", [{}])[0]
        .get("message", {})
        .get("content", "")
    )

    if not content:
        raise ValueError("empty completion content")

    return parse_llm_json(content)


async def _try_anthropic(
    base_url: str,
    model: str,
    api_key: str,
    prompt: str,
) -> Dict[str, Any]:
    import httpx

    async with httpx.AsyncClient(timeout=_BYOK_TIMEOUT_S) as client:
        resp = await client.post(
            f"{base_url.rstrip('/')}/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": 1024,
                "temperature": 0.2,
                "messages": [
                    {
                        "role": "user",
                        "content": (
                            f"{prompt}\n\nRespond with ONLY the raw JSON "
                            "object, no markdown fences."
                        ),
                    }
                ],
            },
        )

    if resp.status_code >= 400:
        raise RuntimeError(
            f"anthropic HTTP {resp.status_code}: {resp.text[:160]}"
        )

    blocks = resp.json().get("content", [])
    text = "".join(
        b.get("text", "") for b in blocks if isinstance(b, dict)
    ).strip()

    if not text:
        raise ValueError("empty anthropic response")

    return parse_llm_json(text)


async def _try_byok(
    provider: str,
    api_key: str,
    prompt: str,
) -> Dict[str, Any]:
    spec = BYOK_PROVIDERS.get(provider)

    if spec is None:
        raise ValueError(
            f"unsupported BYOK provider {provider!r}; "
            f"expected one of {sorted(BYOK_PROVIDERS)}"
        )

    kind = spec["kind"]

    if kind == "langchain_groq":
        return await _try_groq(api_key, prompt)

    if kind == "langchain_gemini":
        return await _try_gemini(api_key, prompt)

    if kind == "openai":
        return await _try_openai_compatible(
            spec["base_url"], spec["model"], api_key, prompt
        )

    return await _try_anthropic(
        spec["base_url"], spec["model"], api_key, prompt
    )


async def _try_groq(
    api_key: str,
    prompt: str,
) -> Dict[str, Any]:

    from langchain_groq import ChatGroq

    llm = ChatGroq(
        model=GROQ_MODEL,
        api_key=api_key,
        temperature=0.2,
        timeout=15,
    )

    response = await llm.ainvoke(prompt)

    return parse_llm_json(
        response.content
    )


async def _try_gemini(
    api_key: str,
    prompt: str,
) -> Dict[str, Any]:

    from langchain_google_genai import (
        ChatGoogleGenerativeAI,
    )

    llm = ChatGoogleGenerativeAI(
        model=GEMINI_MODEL,
        google_api_key=api_key,
        temperature=0.2,
    )

    response = await llm.ainvoke(prompt)

    return parse_llm_json(
        response.content
    )


# ---------------------------------------------------------------------------
# Tier 5 — deterministic zero-LLM fallback
# ---------------------------------------------------------------------------

STATIC_THRESHOLDS: Dict[
    str,
    Dict[str, Any],
] = {

    "Low": {
        "work_rest_cycle": (
            "Normal schedule; no mandatory rest "
            "breaks beyond standard shift breaks"
        ),
        "hydration_benchmark": (
            "0.5L water per hour, at will"
        ),
        "monitoring_indicators": [
            "General fatigue",
            "Ambient temp trend",
        ],
        "mandatory_ppe": [
            "Hat",
            "Sunscreen",
        ],
        "escalation_protocol": (
            "No action required; re-check hourly."
        ),
    },

    "Caution": {
        "work_rest_cycle": (
            "10 min shade rest per 50 min work"
        ),
        "hydration_benchmark": (
            "0.75L water per hour"
        ),
        "monitoring_indicators": [
            "Excess sweating",
            "Fatigue",
            "Thirst",
        ],
        "mandatory_ppe": [
            "Hat",
            "Sunscreen",
            "Light-colored breathable clothing",
        ],
        "escalation_protocol": (
            "Supervisor spot-checks every 2 hours."
        ),
    },

    "Warning": {
        "work_rest_cycle": (
            "15 min shade rest per 45 min work"
        ),
        "hydration_benchmark": (
            "1L water per hour minimum"
        ),
        "monitoring_indicators": [
            "Heavy sweating",
            "Headache",
            "Dizziness",
            "Cramping",
        ],
        "mandatory_ppe": [
            "Hat",
            "Sunscreen",
            "Cooling vest",
            "Electrolyte supplement",
        ],
        "escalation_protocol": (
            "Buddy system mandatory; "
            "supervisor check-in every hour."
        ),
    },

    "Danger": {
        "work_rest_cycle": (
            "20 min shade/AC rest per 40 min work"
        ),
        "hydration_benchmark": (
            "1L water per hour + electrolyte "
            "replacement every 2 hours"
        ),
        "monitoring_indicators": [
            "Confusion",
            "Rapid pulse",
            "Nausea",
            "Hot/dry or clammy skin",
        ],
        "mandatory_ppe": [
            "Cooling vest",
            "Wide-brim hat",
            "Reflective clothing",
        ],
        "escalation_protocol": (
            "Immediate supervisor notification; "
            "on-site medic on standby; "
            "consider work stoppage."
        ),
    },

    "Extreme Danger": {
        "work_rest_cycle": (
            "Suspend non-essential outdoor work immediately"
        ),
        "hydration_benchmark": (
            "Continuous hydration access; "
            "no unsupervised solo work"
        ),
        "monitoring_indicators": [
            "Loss of consciousness risk",
            "Seizure risk",
            "Core temp >103°F",
        ],
        "mandatory_ppe": [
            "Full cooling PPE",
            "Emergency comms device",
        ],
        "escalation_protocol": (
            "Halt all outdoor operations; "
            "activate emergency medical response protocol."
        ),
    },
}


def deterministic_plan(
    risk_level: str,
) -> Dict[str, Any]:
    """
    Tier 5 — pure zero-LLM Python logic. Returns a deep copy so callers
    can never mutate the shared threshold table.
    """

    plan = copy.deepcopy(
        STATIC_THRESHOLDS.get(
            risk_level,
            STATIC_THRESHOLDS["Warning"],
        )
    )

    plan["generated_by_tier"] = (
        "Tier 5: Deterministic Rule Engine"
    )

    return plan


# ---------------------------------------------------------------------------
# The resilient cascade itself
# ---------------------------------------------------------------------------

async def execute_resilient_llm(
    state: Mapping[str, Any],
) -> LLMCascadeResult:
    """
    Run Tiers 1-5 in order and return the first successful plan together
    with the full tier trace. Never raises: Tier 5 always succeeds.
    """

    trace: List[str] = []
    events: List[Dict[str, Any]] = []

    prompt = build_llm_prompt(state)

    risk_level = state.get(
        "risk_level",
        "Warning",
    )

    byok_key = state.get(
        "byok_key"
    )

    # -----------------------------------------------------------------------
    # Tiers 1 & 2 — Groq primary then secondary key
    # -----------------------------------------------------------------------

    groq_attempts = [
        (
            "tier_1_groq_primary",
            "Tier 1: Groq (primary key)",
            "Tier 1 (Groq primary)",
            os.getenv("GROQ_API_KEY_1", ""),
        ),
        (
            "tier_2_groq_secondary",
            "Tier 2: Groq (secondary key)",
            "Tier 2 (Groq secondary)",
            os.getenv("GROQ_API_KEY_2", ""),
        ),
    ]

    for trace_key, tier_title, tier_label, api_key in groq_attempts:

        if not api_key:
            trace.append(f"{trace_key}:skipped_no_key")
            continue

        try:
            plan = await _try_groq(api_key, prompt)

            plan["generated_by_tier"] = tier_title
            trace.append(f"{trace_key}:success")
            events.append(_event(f"{tier_label} succeeded."))

            return LLMCascadeResult(
                compliance_plan=plan,
                active_tier=tier_title,
                tier_trace=trace,
                awaiting_byok=False,
                events=events,
            )

        except Exception as exc:
            trace.append(f"{trace_key}:failed:{exc.__class__.__name__}")
            events.append(_event(f"{tier_label} failed: {exc!r}", "warning"))

    # -----------------------------------------------------------------------
    # Tier 3 — Gemini tertiary
    # -----------------------------------------------------------------------

    gemini_api_key = os.getenv("GEMINI_API_KEY", "")

    if gemini_api_key:
        try:
            plan = await _try_gemini(gemini_api_key, prompt)

            plan["generated_by_tier"] = "Tier 3: Gemini (tertiary)"
            trace.append("tier_3_gemini:success")
            events.append(_event("Tier 3 (Gemini) succeeded."))

            return LLMCascadeResult(
                compliance_plan=plan,
                active_tier="Tier 3: Gemini (tertiary)",
                tier_trace=trace,
                awaiting_byok=False,
                events=events,
            )

        except Exception as exc:
            trace.append(f"tier_3_gemini:failed:{exc.__class__.__name__}")
            events.append(_event(f"Tier 3 (Gemini) failed: {exc!r}", "warning"))

    else:
        trace.append("tier_3_gemini:skipped_no_key")

    # -----------------------------------------------------------------------
    # Tier 4 — BYOK
    # -----------------------------------------------------------------------

    if byok_key:
        provider = state.get(
            "byok_provider",
            "groq",
        ) or "groq"

        try:
            plan = await _try_byok(provider, byok_key, prompt)

            tier_title = f"Tier 4: BYOK ({provider})"
            plan["generated_by_tier"] = tier_title
            trace.append(f"tier_4_byok_{provider}:success")
            events.append(_event(f"Tier 4 (BYOK {provider}) succeeded."))

            return LLMCascadeResult(
                compliance_plan=plan,
                active_tier=tier_title,
                tier_trace=trace,
                awaiting_byok=False,
                events=events,
            )

        except Exception as exc:
            trace.append(f"tier_4_byok:failed:{exc.__class__.__name__}")
            events.append(_event(f"Tier 4 (BYOK) failed: {exc!r}", "warning"))

    else:
        trace.append("tier_4_byok:awaiting_user_input")
        events.append(
            _event(
                "Tiers 1-3 exhausted and no BYOK "
                "key present; flagging frontend "
                "to show BYOK input.",
                "warning",
            )
        )

        plan = deterministic_plan(risk_level)
        trace.append("tier_5_deterministic:used_as_interim")

        return LLMCascadeResult(
            compliance_plan=plan,
            active_tier=(
                "Tier 5: Deterministic Rule Engine "
                "(interim, BYOK available)"
            ),
            tier_trace=trace,
            awaiting_byok=True,
            events=events,
        )

    # -----------------------------------------------------------------------
    # Tier 5 — final deterministic safety net
    # -----------------------------------------------------------------------

    plan = deterministic_plan(risk_level)

    trace.append("tier_5_deterministic:success")
    events.append(
        _event(
            "All LLM tiers exhausted; "
            "served Tier 5 deterministic plan."
        )
    )

    return LLMCascadeResult(
        compliance_plan=plan,
        active_tier=plan["generated_by_tier"],
        tier_trace=trace,
        awaiting_byok=False,
        events=events,
    )
