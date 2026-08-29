"""
Deep-dive sub-graph.

State schema: ResearchState (shared with parent graph).

The main graph dispatches one of these per approved opportunity via Send().
Each Send() carries a flat dict with the dispatched Opportunity's fields
plus `domain` (enrichment for the inner node).

Why ResearchState and not a sub-graph-specific schema:
    LangGraph's Send() with subgraphs requires a shared state schema for
    the reducer to merge parallel writes back into the parent. If the
    sub-graph declares its own schema with no overlapping reducer-keyed
    fields with the parent, the inner node's return value cannot reach
    the parent's `opportunities` reducer — it's dropped silently.

    Sharing ResearchState means the inner node can return
    `{"opportunities": {id: updated}}` and the parent's merge-by-id
    reducer on `opportunities` will coalesce N parallel writes into a
    single dict with one entry per opportunity (no duplicates).

Inner node contract:
    Receives a flat dict (the Send payload) with the dispatched
    Opportunity's fields plus `domain`. Returns a single-key dict
    fragment `{"opportunities": {id: updated}}` so the reducer merges
    it into the parent's opportunities dict without producing a duplicate.
"""

from langgraph.graph import StateGraph, START, END

from graph.state import ResearchState
from graph.nodes.deep_dive_subagent import deep_dive_subagent


def build_deep_dive_subgraph() -> StateGraph:
    subgraph = StateGraph(ResearchState)

    # Single inner node: does the actual research work for one opportunity.
    # The inner node owns the LLM/tool calls — the subgraph itself just wires it up.
    subgraph.add_node("deep_dive_subagent", deep_dive_subagent)

    # Linear flow — no branching inside the sub-graph. The real branching
    # happens at the manager level, which decides how many of these to
    # dispatch (one per approved opportunity).
    subgraph.add_edge(START, "deep_dive_subagent")
    subgraph.add_edge("deep_dive_subagent", END)

    return subgraph
