"""A2A bridge: run the existing LangGraph research pipeline headlessly.

This module does NOT change any graph logic. It calls the same compiled
``app`` that ``research_agent/main.py`` uses, in ``ai`` mode (no human
interrupt), and converts the final ``ResearchState`` into the
``ResearchResult`` pydantic shape defined in ``a2a_schemas.py``.

Why ai mode: ``human`` mode pauses on ``interrupt()`` and needs an
interactive resume. An A2A ``execute()`` call is request/response — it
must finish within one call — so the A2A wrapper always runs the
autonomous path.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from uuid import uuid4

# Allow `import research_agent.X` style imports to keep working when this
# file is executed as `python research_agent/a2a_agent.py` from the repo
# root, and also when imported as a package module.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# The existing graph code uses top-level imports (`from graph...`,
# `from api...`, `from llm...`, `from tools...`) — it expects the
# `research_agent/` directory itself on sys.path (Docker sets
# PYTHONPATH=/app and copies research_agent/ to /). Mirror that here.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from research_agent.a2a_schemas import Opportunity, ResearchResult


def run_research(domain: str, timeout_s: float = 300.0) -> ResearchResult:
    """Run the full graph for ``domain`` and return structured opportunities.

    Raises whatever the graph raises (LLM/auth errors, etc.) — the A2A
    executor catches those and turns them into a ``failed`` task.
    """
    from research_agent.graph.builder import app

    thread_id = str(uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    # The graph is sync; run it in a thread so async executors/servers
    # never block the event loop.
    async def _invoke() -> dict:
        return await asyncio.to_thread(
            app.invoke, {"domain": domain, "hitl_mode": "ai"}, config
        )

    # ``asyncio.run`` vs existing loop: the A2A executor already runs
    # inside a loop, so expose a sync entry that creates its own loop
    # only when called from sync contexts (tests, scripts).
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is None:
        result = asyncio.run(_invoke())
    else:
        # Called from inside a running loop — the caller should use
        # ``arun_research`` instead. Fail loudly rather than deadlock.
        raise RuntimeError("run_research() called from a running event loop; use arun_research()")

    return _state_to_result(domain, result)


async def arun_research(domain: str) -> ResearchResult:
    """Async variant for use inside a running event loop (A2A executor)."""
    from research_agent.graph.builder import app

    thread_id = str(uuid4())
    config = {"configurable": {"thread_id": thread_id}}
    result = await asyncio.to_thread(
        app.invoke, {"domain": domain, "hitl_mode": "ai"}, config
    )
    return _state_to_result(domain, result)


def _state_to_result(domain: str, state: dict) -> ResearchResult:
    opps = state.get("opportunities") or {}
    # Only evaluated (approved) opportunities are candidates: discovery may
    # find more than approval keeps, and unapproved ones carry no verdict
    # or deep-dive notes. Mirrors the synthesis node's scoping.
    approved_ids = state.get("approved_opportunity_ids")
    if approved_ids is not None:
        approved = set(approved_ids)
        opps = {k: v for k, v in opps.items() if k in approved}
    # Dict insertion order == first-discovery order (merge-by-id reducer
    # preserves key position on update), so list(opps.values()) matches
    # what the CLI prints.
    return ResearchResult(
        domain=domain,
        opportunities=[
            Opportunity(
                id=str(o.get("id") or ""),
                title=o.get("title") or "",
                description=o.get("description") or "",
                existing_solutions=list(o.get("existing_solutions") or []),
                deep_dive_notes=o.get("deep_dive_notes") or "",
                worth_it_verdict=o.get("worth_it_verdict") or "",
                worth_it_reasoning=o.get("worth_it_reasoning") or "",
            )
            for o in opps.values()
            if isinstance(o, dict)
        ],
    )
