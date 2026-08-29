"""
Worth-it sub-graph.

State schema: ResearchState (shared with parent graph).

Mirrors `deep_dive_graph.py` — same shape, different inner node. See
that file for why we share the parent's schema instead of declaring
a sub-graph-specific one.
"""

from langgraph.graph import StateGraph, START, END

from graph.state import ResearchState
from graph.nodes.worth_it_subagent import worth_it_subagent


def build_worth_it_subgraph() -> StateGraph:
    subgraph = StateGraph(ResearchState)

    subgraph.add_node("worth_it_subagent", worth_it_subagent)

    subgraph.add_edge(START, "worth_it_subagent")
    subgraph.add_edge("worth_it_subagent", END)

    return subgraph