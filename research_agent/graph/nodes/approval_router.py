"""
approval_router node.

Pure routing function — no side effects, no LLM calls, no state mutation.
Inspects `state["hitl_mode"]` and tells the graph which approval node to
go to next.

Contract (see graph/builder.py):
    Returns {"next_node": "human_approval" | "ai_approval"} so the
    conditional edge attached to this node can route accordingly.
"""

from graph.nodes._log import log_node
from graph.state import ResearchState


def approval_router_node(state: ResearchState) -> dict:
    """Decide which approval path to take based on hitl_mode."""
    logger = log_node("approval_router", state)
    hitl_mode = state.get("hitl_mode")

    if hitl_mode == "human":
        logger.info(f"hitl_mode={hitl_mode!r} -> routing to human_approval")
        logger.outputs(next_node="human_approval")
        return {"next_node": "human_approval"}
    if hitl_mode == "ai":
        logger.info(f"hitl_mode={hitl_mode!r} -> routing to ai_approval")
        logger.outputs(next_node="ai_approval")
        return {"next_node": "ai_approval"}

    # If hitl_mode is unset or invalid, fail loudly — silent fall-through
    # to one branch would hide a wiring bug at graph invocation time.
    logger.info(f"hitl_mode is unset/invalid: {hitl_mode!r}")
    raise ValueError(
        f"approval_router: `hitl_mode` must be 'human' or 'ai', got {hitl_mode!r}"
    )