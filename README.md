# HeatShield AI

**Autonomous Heat Intelligence & OSHA Compliance for Outdoor Worksites**
Built for the FortyGuard Global AI Hackathon '26 — Track 06 (Agentic AI) × Track 03 (Industrial & Enterprise Automation)

![status](https://img.shields.io/badge/tests-111%2F111-brightgreen) ![python](https://img.shields.io/badge/python-3.11%2B-blue) ![next](https://img.shields.io/badge/next.js-14-black)

## 🔴 Live Demo

> **Try it now — both services are live.**

| Frontend | Backend API |
|---|---|
| [heatshield-ai.vercel.app](https://heatshield-ai.vercel.app) | [heatshield-ai.up.railway.app](https://heatshield-ai.up.railway.app) |

- Frontend: command console — pick a site & operation, press **Run Heat Intelligence Agent**.
- Backend health check: `GET /api/health` → `{"status":"ok"}`.
- **Demo scenario:** select **Thermal, CA + Roadwork** and Run → real live FortyGuard
  data, `CRITICAL` `R≈8.1`, and the Autonomous Dispatch Log fires 4 dry-run SMS + voice
  previews.

## The pitch

Heat is the deadliest weather-related workplace hazard in the U.S., and site managers
still make shade/rest/hydration calls off a phone weather app that describes an entire
metro area — not the street corner someone is standing on.

**HeatShield AI closes that gap in four moves:**

1. **Sense** — autonomously ingests hyperlocal, street-level microclimate data from the
   FortyGuard Temperature API (with an honest, clearly-labeled climate-normal fallback).
2. **Score** — computes a deterministic **Response Gap** `R = 0.40E + 0.35V + 0.25D`
   (Exposure × Vulnerability × Resource Deficit). The LLM *never* computes a number;
   it narrates around the rule-engine artifact.
3. **Act** — when `R ≥ 7.0` (CRITICAL), a LangGraph dispatch node **autonomously fires
   SMS + voice-call alerts** to site supervisors via Twilio (dry-run previews without
   credentials — judges see exactly what *would* be sent).
4. **Prove** — every number on screen is traceable to the scoring engine's audit
   artifact (`formula_substitution`, per-component contributions), streamed live over
   SSE/NDJSON with provenance footers and activity IDs.

The reasoning layer is wrapped in a **5-tier resilient cascade** so the app **never**
shows an error screen — under rate limits, missing keys, or dead networks it always
returns a valid, actionable compliance plan.

## Architecture

```
heatshield-ai/
├── backend/                          FastAPI + LangGraph agent (Python 3.11+)
│   ├── main.py                       Compat entrypoint → app.main:app
│   ├── requirements.txt              Pinned; prod + dev sections
│   ├── .env.example                  Structure-only key template (all optional)
│   └── app/
│       ├── state.py                  AgentState schema + Pydantic wire contracts
│       ├── nodes.py                  5 isolated LangGraph node functions
│       ├── graph.py                  StateGraph + conditional dispatch gate + checkpointer
│       ├── main.py                   FastAPI gateway: SSE /api/stream-agent, cache stats
│       ├── api/
│       │   ├── heatmap.py            NDJSON progress-streaming /api/heatmap route
│       │   └── deps.py               Sliding-window rate limiting dependency
│       ├── engine/
│       │   ├── scoring.py            ★ Deterministic R = 0.40E + 0.35V + 0.25D engine
│       │   └── actions.py            Numbered tactical directives (01–06)
│       ├── services/
│       │   ├── fortyguard.py         Polling client w/ progress events + terminal taxonomy
│       │   ├── climate_normals.py    City climate profiles + deterministic grid synthesizer
│       │   ├── observation_cache.py  Hot-mirror + SQLite WAL observation cache
│       │   ├── dispatch.py           Twilio SMS/voice (live | dry-run) telephony
│       │   ├── llm_router.py         5-tier cascade + multi-provider BYOK transport
│       │   └── rate_limiter.py       Injectable-clock sliding window limiter
│       └── utils/
│           ├── osha_rules.py         Pure OSHA/NWS heat-index math
│           └── clock.py              UTC timestamp helper
└── frontend/                         Next.js 14 (App Router) · React 18 · Tailwind CSS
    ├── src/app/page.tsx              3-column command console + location/op caches
    ├── src/components/
    │   ├── TopBar.tsx                Global RiskTier status propagation (accent line/glow/pill)
    │   ├── ThermalCanvasMap.tsx      OSM tiles darkened via canvas filter + blended thermal raster (60fps)
    │   ├── TemporalHeatChart.tsx     Zero-dep SVG shift projection chart (OSHA 90°F ref)
    │   ├── RadiantZoneSim.tsx        Interactive geofence sim (+4°F radiant zone projection)
    │   ├── ComplianceExportBar.tsx   CSV download + PDF print-report export (zero deps)
    │   ├── DecisionRationale.tsx     "Why Flagged?" verbatim formula audit panel
    │   ├── TacticalActions.tsx       Numbered directives + autonomous dispatch log
    │   └── …                         Gauge, pipeline, compliance cards, BYOK, footer
    ├── src/hooks/
    │   ├── useAgentStream.ts         POST-fetch SSE consumer (param capture, no URL leaks)
    │   └── useHeatmapStream.ts       NDJSON consumer (progress/fallback/cells/result)
    └── src/lib/
        ├── exportUtils.ts            CSV builder + styled print-report generator
        ├── types.ts                  v2 wire contracts
        └── constants.ts              Brand tokens, demo sites, provider registry
```

### Agent graph

```
ingest_environmental_data → evaluate_heat_risk → generate_compliance_plan
        → [dispatch_critical_alerts  only if risk_tier == CRITICAL]
        → format_enterprise_output
```

Every run is checkpointed to SQLite (`AsyncSqliteSaver`, or in-memory via
`CHECKPOINT_DB_PATH=":memory:"`) keyed by `thread_id` — one thread per site — so a run
that pauses for a BYOK key can resume exactly where it left off, and switching sites
can never cross-contaminate state.

### The Deterministic Response-Gap Engine

```
R = 0.40·E + 0.35·V + 0.25·D          (weighted sum of 0–10 subscores)

E  Heat Exposure      peak temp, heat index, consecutive hours ≥40°C,
                      operation profile (roadwork adds +4°F radiant offset)
V  Vulnerability      SVI percentile, crew duration scale, acclimatization
D  Resource Deficit   cooling-center distance decay, shade/water deficit

R ≥ 7.0 → CRITICAL → autonomous dispatch unlocked
```

Every render of the score ships its full audit trail:
`components[{value × weight = contribution}], raw_inputs, formula_substitution` —
rendered verbatim by the frontend "Why Flagged?" panel. Zero LLM math, anywhere.

### The 5-Tier Resilient Cascade

| Tier | Provider | Trigger |
|---|---|---|
| 1 | Groq (`GROQ_API_KEY_1`) | Primary path, ultra-low latency |
| 2 | Groq (`GROQ_API_KEY_2`) | Silent fallback on 429 / quota |
| 3 | Gemini (`GEMINI_API_KEY`) | Tertiary safety net |
| 4 | BYOK — **Groq \| Gemini \| OpenAI \| Anthropic \| DeepSeek** | Hosted tiers exhausted; inline badge expands to key form |
| 5 | Deterministic rule engine | Zero-LLM, zero-network — always succeeds |

Tier 4 calls OpenAI-compatible providers over plain `httpx` (no SDK sprawl);
Anthropic gets a dedicated `/v1/messages` transport. Unknown provider names are
rejected cleanly into Tier-5 fallback.

### Streaming & resilience (backend)

- `POST /api/stream-agent` — SSE: `status → node(start/end)×5 → token* → result → status`,
  with pacing (`AGENT_NODE_PACE_SECONDS`) so judges can watch the agent think.
- `POST /api/heatmap?stream=1` — NDJSON progress contract:
  `meta → cache{hit} → progress{attempt,max}* → fallback{reason,message} → cells{chunk}* → result{payload}`.
  Live polling budget is env-tunable; degradation is honest (SIMULATED DATA banner),
  never silent.
- Sliding-window rate limiting on both routes (`RATE_LIMIT_MAX/WINDOW_S`, default 60/min).

### Enterprise features & UX hardening

| Feature | What it does |
|---|---|
| **CSV / PDF export** | One-click OSHA compliance log export: CSV (Blob download, Excel/Sheets-ready) and styled print-report PDF via `window.print()`. Zero npm deps. |
| **Frontend wake-up ping** | Invisible `fetch('/api/health')` on page mount (+ staggered retry) so the Railway/Render backend is live before the user finishes reading the header — eliminates cold-start feel. |
| **Radiant zone simulation** | Interactive geofence demo button: "Simulate worker entering high radiant zone (+4 °F)". Reuses the production R formula client-side with published weights; shows before/after tier flip + DISPATCH ARMED flash when crossing R ≥ 7.0. Clearly labeled as a projection. |

## Running locally

### Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                   # fill whatever keys you have — all optional
uvicorn app.main:app --reload --port 8000
```

Health check: `GET http://localhost:8000/api/health`

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Visit `http://localhost:3000`. Set `NEXT_PUBLIC_API_BASE_URL` in `frontend/.env.local`
if the backend isn't on `localhost:8000`.

### Tests

```bash
cd backend
pytest                 # 111 tests — scoring math, dispatch gate, rate limits,
                       # schemas, NDJSON contract, live env_params client, SSE runs
```

### Demo paths

**With a FortyGuard key** (`FORTYGUARD_API_KEY` set): the ingest node calls the real
task-based `POST /v1/env_params`, polls `GET /v1/status/{id}`, and marks the run
**`SOURCE: FORTYGUARD API (live)`** — the dashboard header, Response Gap, and
temporal chart all anchor on genuine observed street-level temperature.

**Zero-key fallback (still fully functional):** select **Thermal, CA** → the pipeline
streams end-to-end via Tier 5, the thermal field renders from the labeled
climate-normal synthesizer, the map blends CRITICAL crimson over darkened
OpenStreetMap streets, the Response Gap shows ~8.1/10, and the **Autonomous Dispatch
Log** fires 4 dry-run SMS+voice records with full previews.
Add Twilio creds + supervisor numbers in `.env` and the same click goes LIVE.

## Environment variables (all optional)

See `backend/.env.example`. Highlights:

| Var | Purpose |
|---|---|
| `FORTYGUARD_API_KEY` | tOS Enterprise API key — anchors scoring on REAL observed temperature (blank ⇒ simulated field) |
| `GROQ_API_KEY_1/2`, `GEMINI_API_KEY` | Hosted cascade tiers |
| `OBSERVATION_CACHE_PATH` | SQLite cache file (`:memory:` in tests) |
| `RATE_LIMIT_MAX`, `RATE_LIMIT_WINDOW_S` | API throttling (60/min default) |
| `FORTYGUARD_*` timeout vars | Live-polling budget before fallback |
| `HEATSHIELD_SUPERVISOR_CONTACTS` | Comma-separated E.164 alert recipients |
| `TWILIO_ACCOUNT_SID/AUTH_TOKEN/FROM_NUMBER` | Live SMS/voice (blank ⇒ dry-run) |

## Deployment

- **Backend** → Render/Railway/Fly: start command
  `gunicorn -k uvicorn.workers.UvicornWorker app.main:app -w 1 --threads 8 -b 0.0.0.0:$PORT`
  (single worker keeps the LangGraph/checkpointer singleton coherent).
- **Frontend** → Vercel: set `NEXT_PUBLIC_API_BASE_URL` to the deployed API.
- CORS already allows `localhost:3000` and any `*.vercel.app` origin
  (extend via `EXTRA_CORS_ORIGINS`).

## Map & data attribution

Base map tiles © [OpenStreetMap contributors](https://www.openstreetmap.org/copyright)
(public raster, darkened locally via a canvas filter — no API key, no watermark).
Thermal field values are FortyGuard observations or the clearly-labeled
deterministic climate-normal simulation — provenance is always on-screen.

## Judging alignment

- **Impact & Relevance (40%)** — turns a metro forecast into a per-site, per-shift
  action plan with autonomous escalation to humans.
- **Technical Execution (35%)** — real LangGraph StateGraph + checkpointing,
  deterministic scoring core, dual streaming protocols, 111-test regression suite.
- **Innovation (15%)** — the 5-tier cascade and honest-degradation design turn
  hackathon infrastructure fragility into a demoed product feature; the dispatch gate
  makes the agent close the loop in the physical world.
- **Communication (10%)** — the dashboard visualizes the agent's own reasoning path,
  the exact arithmetic behind every flag, and which tier resolved each run — live.
