"""
HeatShield AI application package.

Single-responsibility modules:

    app/state.py           AgentState schema + Pydantic API contracts
    app/utils/osha_rules.py  Pure OSHA/NWS heat-index math
    app/services/fortyguard.py  FortyGuard API client + cached/mock frames
    app/services/llm_router.py  Resilient multi-tier LLM cascade
    app/nodes.py           LangGraph node functions
    app/graph.py           StateGraph assembly + checkpointer lifecycle
    app/main.py            FastAPI gateway (CORS + SSE streaming)
"""

__version__ = "1.0.0"
