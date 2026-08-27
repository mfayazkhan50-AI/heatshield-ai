"""
conftest.py
===========
Shared fixtures for the HeatShield AI regression suite.

Guarantees hermetic execution: zero network, zero API keys, in-memory
persistence, deterministic pacing, and per-test cache isolation so the
suite runs in seconds with zero cross-contamination.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

# Deterministic, key-free environment — MUST be configured before any
# test imports app.main (module-level reads). We set empty strings (NOT pop)
# so that `load_dotenv()` in app/main.py cannot re-inject the real keys from
# backend/.env at import time (load_dotenv won't override existing keys).
os.environ["CHECKPOINT_DB_PATH"] = ":memory:"
os.environ["OBSERVATION_CACHE_PATH"] = ":memory:"
os.environ["AGENT_NODE_PACE_SECONDS"] = "0"

for _key in (
    "FORTYGUARD_API_KEY",
    "GROQ_API_KEY_1",
    "GROQ_API_KEY_2",
    "GEMINI_API_KEY",
    "TWILIO_ACCOUNT_SID",
    "TWILIO_AUTH_TOKEN",
    "TWILIO_FROM_NUMBER",
):
    os.environ[_key] = ""


@pytest_asyncio.fixture
async def client():
    """TestClient with lifespan (graph initialized in-memory)."""
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest_asyncio.fixture
async def client_no_lifespan():
    """TestClient without graph execution (transport/schema checks)."""
    from app.main import app

    # Enter context anyway — cheap on :memory: and keeps behavior uniform.
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def isolated_observation_cache():
    """
    Fresh observation-cache singleton per test: no hit/miss counter bleed,
    no hot-mirror carryover between test cases.
    """
    from app.services.observation_cache import reset_observation_cache

    reset_observation_cache()
    yield
    reset_observation_cache()


@pytest.fixture(autouse=True)
def fresh_rate_limiter():
    """Reset the shared sliding window between tests."""
    from app.api import deps as api_deps

    api_deps.rate_limiter.reset()
    yield
    api_deps.rate_limiter.reset()
