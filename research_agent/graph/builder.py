"""
Graph assembly for the Research Agent.

This file wires the StateGraphs together. It does NOT contain any business
logic — node behavior lives in `graph/nodes/*.py`.

Topology:

    Main graph (ResearchState):
        START -> manager
        manager -> opportunity_discovery   (first pass: route by state inspection)
        opportunity_discovery -> approval_router
        approval_router -> human_approval  (if hitl_mode == "human")
        approval_router -> ai_approval     (if hitl_mode == "ai")
        human_approval -> manager
        ai_approval    -> manager
        manager -> [deep_dive sub-graph]   (Send() fan-out, decided by manager)
        deep_dive sub-graph (fan-in) -> orchestration
        orchestration -> manager
        manager -> [worth_it sub-graph]    (Send() fan-out, decided by manager)
        worth_it sub-graph (fan-in) -> orchestration
        orchestration -> manager
        manager -> synthesis
        synthesis -> END

The manager is a router: it inspects state and returns Command(goto=...) to
choose the next step. It also owns the dynamic Send() fan-out for the
sub-graphs (deep_dive and worth_it).

Each sub-graph (StateGraph(Opportunity)) is built with a single internal node
and compiled, then added to the main graph as a node. The sub-graph receives
a single Opportunity via Send({"opportunity": op}) and returns a list
containing the updated Opportunity so the parent's operator.add reducer
concatenates correctly.

NOTE: this file imports node functions whose bodies are still empty. It will
fail at import time until you fill in at least stub functions in:
    graph/nodes/manager.py
    graph/nodes/opportunity_discovery.py
    graph/nodes/approval_router.py
    graph/nodes/human_approval.py            (NEW — see below)
    graph/nodes/ai_approval.py               (NEW — see below)
    graph/nodes/orchestration.py             (NEW — fan-in router)
    graph/nodes/synthesis.py
    graph/nodes/deep_dive_subagent.py
    graph/nodes/worth_it_subagent.py
    graph/subgraphs/deep_dive_graph.py       (sub-graph node function)
    graph/subgraphs/worth_it_graph.py        (sub-graph node function)
"""

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command, Send

from graph.state import ResearchState, Opportunity

# Main-graph node functions (behavior in graph/nodes/*.py).
from graph.nodes.manager import manager_node, route_from_manager
from graph.nodes.opportunity_discovery import opportunity_discovery_node
from graph.nodes.approval_router import approval_router_node
from graph.nodes.human_approval import human_approval_node
from graph.nodes.ai_approval import ai_approval_node
from graph.nodes.orchestration import orchestration_node
from graph.nodes.synthesis import synthesis_node

# Sub-graph node functions (the *inner* node each sub-graph contains).
# These are the per-Opportunity workers; the sub-graphs are compiled around them.
from graph.subgraphs.deep_dive_graph import build_deep_dive_subgraph
from graph.subgraphs.worth_it_graph import build_worth_it_subgraph


# ---------------------------------------------------------------------------
# Checkpointer
# ---------------------------------------------------------------------------
# Module-level in-memory checkpointer. Swapping to PostgresSaver later means
# changing exactly this line and passing a connection string — the rest of the
# graph is unaware of the persistence backend.
memory = InMemorySaver()


# ---------------------------------------------------------------------------
# Sub-graphs
# ---------------------------------------------------------------------------
# Each sub-graph has its own state schema (Opportunity) and is compiled before
# being added to the main graph. Compiled sub-graphs are valid node targets —
# from the parent's perspective they're just nodes that happen to have their
# own internal execution.
#
# The sub-graph node function is expected to:
#   - read state["opportunity"] (the single Opportunity it was Send()ed)
#   - do work (LLM calls, tool calls, etc.)
#   - return {"opportunity": [updated_opportunity]} — a LIST, so the parent's
#     `operator.add` reducer on `opportunities` concatenates correctly.
deep_dive_subgraph = build_deep_dive_subgraph().compile()
worth_it_subgraph = build_worth_it_subgraph().compile()


# ---------------------------------------------------------------------------
# Main graph
# ---------------------------------------------------------------------------
graph = StateGraph(ResearchState)

# Node registration
graph.add_node("manager", manager_node)
graph.add_node("opportunity_discovery", opportunity_discovery_node)
graph.add_node("approval_router", approval_router_node)
graph.add_node("human_approval", human_approval_node)
graph.add_node("ai_approval", ai_approval_node)
graph.add_node("orchestration", orchestration_node)
graph.add_node("deep_dive", deep_dive_subgraph)        # compiled sub-graph as a node
graph.add_node("worth_it", worth_it_subgraph)          # compiled sub-graph as a node
graph.add_node("synthesis", synthesis_node)

# Entry point: the manager is the orchestrator, so the graph starts there.
# Initial state (domain, hitl_mode) is provided by the caller at invoke() time.
graph.add_edge(START, "manager")

# After opportunity_discovery populates state, loop back to manager so it
# can classify the next stage (approval_router, etc.) via Command(goto=...).
# Without this edge, LangGraph treats opportunity_discovery as a terminal
# node and the graph ends right after discovery.
graph.add_edge("opportunity_discovery", "manager")


# ---------------------------------------------------------------------------
# Conditional edges (the only places with branching logic in the builder)
# ---------------------------------------------------------------------------
# Each conditional edge has:
#   - a source node
#   - a routing function (lives in the relevant node module)
#   - a path map: keys = what the router returns, values = node names

# After the manager runs, it returns either a node name (string), a list of
# Send() objects for parallel fan-out, or "__end__". We declare the static
# destinations via a path_map so LangGraph doesn't prune nodes that are
# only reachable through the manager's runtime decisions. (The previous
# design used Command(goto=...), which hid those destinations and caused
# the compiled graph to consist of only `manager` + `__end__`.)
graph.add_conditional_edges(
    "manager",
    route_from_manager,  # pure routing function; not the manager node itself
    {
        # Keys = values the manager can produce. Values = node names.
        # For deep_dive / worth_it, the manager builds a list[Send] which
        # LangGraph uses for parallel fan-out; those keys still map to
        # themselves because LangGraph matches by name when the routing
        # function returns a Send list.
        "opportunity_discovery": "opportunity_discovery",
        "approval_router": "approval_router",
        "deep_dive": "deep_dive",
        "worth_it": "worth_it",
        "synthesis": "synthesis",
        "__end__": "__end__",
    },
)

# After approval_router: branch by hitl_mode.
def _route_after_approval(state: ResearchState) -> str:
    # approval_router_node is the *node function* — it takes state and
    # returns {"next_node": ...}. For a conditional edge, LangGraph
    # calls this routing function with the current state at runtime,
    # so we read hitl_mode directly here instead of re-invoking the node.
    mode = state.get("hitl_mode")
    if mode == "human":
        return "human_approval"
    if mode == "ai":
        return "ai_approval"
    # Default to human approval if unset — fails loudly inside the node
    # if the routing was wrong, but keeps the graph runnable for tests
    # that forget to set hitl_mode.
    return "human_approval"


graph.add_conditional_edges(
    "approval_router",
    _route_after_approval,
    {
        "human_approval": "human_approval",
        "ai_approval": "ai_approval",
    },
)

# After human_approval (which calls interrupt() and resumes), flow back to
# the manager so it can decide the next step (likely dispatch_deep_dive).
graph.add_edge("human_approval", "manager")

# After ai_approval, same: back to the manager.
graph.add_edge("ai_approval", "manager")

# After the deep_dive sub-graph fan-in (LangGraph auto-fan-in when multiple
# parallel invocations of a node complete), the next single-target node is
# orchestration. Orchestration does whatever fan-in work is needed (e.g.,
# validating that all deep-dives completed) and then routes back to manager.
graph.add_edge("deep_dive", "orchestration")
graph.add_edge("orchestration", "manager")

# Same pattern for worth_it: sub-graph fan-in -> orchestration -> manager.
graph.add_edge("worth_it", "orchestration")

# After synthesis, we're done.
graph.add_edge("synthesis", END)


# ---------------------------------------------------------------------------
# Compile
# ---------------------------------------------------------------------------
# `app` is the compiled, runnable graph. main.py imports this and calls
# .invoke() / .stream() on it.
#
# The checkpointer is attached here. For thread-scoped state (so that
# interrupt() / Command(resume=...) can pause and resume), the caller MUST
# pass a `thread_id` in config["configurable"] at invoke() time.
app = graph.compile(checkpointer=memory)
