"""
Inner node for the deep_dive sub-graph.

Per opportunity (one instance dispatched via Send()), this node:

  1. Searches Tavily for existing products / solutions in the space.
  2. Asks the Bedrock LLM (via get_bedrock_llm) to synthesize trend analysis.
     The LLM is standing in for a trends MCP server that doesn't exist yet
     — it uses its own training knowledge to play the role of a market-trends
     data tool.
  3. Writes results back into the Opportunity's research fields and returns
     a single-key dict fragment `{updated["id"]: updated}` so the parent's
     merge-by-id reducer on `opportunities` coalesces this with the other
     parallel writes (no duplicates).

Reads the opportunity from the Send() payload directly (flat dict with the
Opportunity's fields). Returns `{"opportunities": {id: updated}}` to match
the fan-out / fan-in contract documented in `state.py`.

Required env vars:
    TAVILY_API_KEY              (Tavily search)
    AWS_BEARER_TOKEN_BEDROCK    (Bedrock)
    BEDROCK_BASE_URL            (optional; defaults to standard regional endpoint)
    AWS_REGION                  (optional, default eu-west-1)
"""

import os

from langgraph.config import get_config, get_stream_writer

from llm.BedrockAPI import BedrockLLM, get_bedrock_llm
from graph.nodes._log import log_subagent
from graph.state import Opportunity
from api import emit_node_added, emit_node_status
from tools.web_search import search_solutions


# Lazy-init the Bedrock client. Tavily is now handled by tools.web_search.
_bedrock: BedrockLLM | None = None


def _get_bedrock() -> BedrockLLM:
    global _bedrock
    if _bedrock is None:
        _bedrock = get_bedrock_llm(
            model_name="openai.gpt-oss-120b",
            temperature=0.3,
            max_tokens=2048,
        )
    return _bedrock


def deep_dive_subagent(state: dict) -> dict:
    """
    Per-opportunity deep-dive: search for existing solutions, synthesize
    trends, and return the enriched Opportunity.

    The dispatched Opportunity arrives under `state["opportunities"]` as
    a single-key dict fragment the manager built with `_build_deep_dive_sends`.
    The dispatched id IS the sole key in that dict, so we identify our
    target via `next(iter(opps))`. We do NOT rely on a separate
    `active_opportunity_id` payload field — the subgraph's state schema
    (`ResearchState`) has no channel for it, so it would be stripped at
    the boundary. The single-key-dict shape is the routing signal.

    Why we don't send a flat `{**opp, "domain": domain}` payload: the
    subgraph's `ResearchState` schema has no channels for Opportunity
    fields like `title`/`description`, so they get stripped at the
    boundary too. Wrapping the Opportunity under `opportunities` keeps
    it inside a channel that exists.
    """
    opps = state.get("opportunities") or {}
    active_id = next(iter(opps), None)
    dispatched = opps.get(active_id) or {}
    topic = dispatched.get("title", "")
    description = dispatched.get("description", "")
    opp_id = dispatched.get("id") or active_id or "????????"

    logger = log_subagent("deep_dive_subagent", opp_id)

    # Bridge: emit node_added BEFORE any other side effect so the
    # frontend's "node_added precedes node_status" ordering guarantee
    # is never violated, even on a slow LLM call below.
    run_id = (
        get_config().get("configurable", {}).get("run_id")
        or get_config().get("configurable", {}).get("thread_id")
        or "unknown"
    )
    writer = get_stream_writer()
    emit_node_added(
        writer,
        run_id=run_id,
        node_id=f"deep_dive_{opp_id}",
        node_type="deep_dive_subagent",
        parent_id="deep_dive",
        label=dispatched.get("title") or f"Opportunity {opp_id}",
        opportunity_id=opp_id,
    )
    emit_node_status(
        writer,
        run_id=run_id,
        node_id=f"deep_dive_{opp_id}",
        status="running",
        summary="Searching for existing solutions",
    )

    logger.info(f"researching topic={topic!r}")

    # --- 1. Tavily: existing solutions in this space ---
    results = search_solutions(topic, description, max_results=5)
    logger.info(f"Tavily found {len(results)} existing solutions")
    existing_solutions = [r.to_summary(content_chars=200) for r in results]

    # --- 2. Bedrock LLM: trends analysis (standing in for a trends MCP) ---
    llm = _get_bedrock()
    trends_prompt = (
        f"Analyze the current trends and market signals for this topic.\n\n"
        f"Topic: {topic}\n"
        f"Description: {description}\n\n"
        f"Identify 3-5 key trends, where this space is heading over the next "
        f"1-3 years, and any signals of momentum or fatigue. Be specific."
    )
    trends_analysis = llm.invoke(
        [{"role": "user", "content": trends_prompt}],
        system=(
            "You are a research analyst. Synthesize market trends concisely, "
            "standing in for a market-trends data MCP."
        ),
    )

    # --- 3. Stitch results into the Opportunity's research fields ---
    solutions_bulleted = "\n".join(f"- {s}" for s in existing_solutions)
    deep_dive_notes = (
        f"## Trends Analysis\n{trends_analysis}\n\n"
        f"## Existing Solutions\n{solutions_bulleted}"
    )

    updated = {
        "id": dispatched.get("id") or active_id,
        "title": dispatched.get("title", ""),
        "description": dispatched.get("description", ""),
        "existing_solutions": existing_solutions,
        "deep_dive_notes": deep_dive_notes,
        "worth_it_verdict": dispatched.get("worth_it_verdict", ""),
        "worth_it_reasoning": dispatched.get("worth_it_reasoning", ""),
    }
    # Sanity: the return key MUST equal the dispatched id, otherwise we
    # write into a phantom key (None) that the merge-by-id reducer keeps
    # separate from the real records. Active id is the fall-back we want.
    assert updated["id"], "deep_dive_subagent: lost dispatched id before return"

    logger.info(f"deep_dive complete; notes length={len(deep_dive_notes)} chars")
    logger.outputs(
        existing_solutions=f"[{len(existing_solutions)} items]",
        deep_dive_notes=f"{len(deep_dive_notes)} chars",
    )

    # Bridge: mid-run summary update so the frontend's "what is it
    # doing right now" line doesn't look frozen during the LLM call.
    emit_node_status(
        writer,
        run_id=run_id,
        node_id=f"deep_dive_{opp_id}",
        status="running",
        summary="Summarizing findings",
    )
    emit_node_status(
        writer,
        run_id=run_id,
        node_id=f"deep_dive_{opp_id}",
        status="completed",
        summary="Research complete",
    )

    # Must return under the `opportunities` key (plural) to match the
    # parent's merge-by-id reducer. The return value is a single-key dict
    # so N parallel instances all writing to the same `opportunities`
    # channel collapse via `dict.update` (last write wins per id) instead
    # of producing duplicate records. Returning a list here would silently
    # break the contract — the parent schema declares a dict, not a list.
    return {"opportunities": {updated["id"]: updated}}
