"""
human_approval node.

Pauses the graph with interrupt() so a human can review the discovered
opportunities and pick which ones to deep-dive. On resume, the chosen
opportunity IDs are written to `state["approved_opportunity_ids"]`.

How the resume payload works:
    `interrupt({...})` pauses the graph and surfaces its argument to the
    caller. The caller then resumes with `Command(resume=<value>)`, and
    that value comes back as the return value of the `interrupt(...)`
    call inside this node.

Expected resume payload from the caller:
    {"approved_ids": ["abc12345", "f6a8..."]}     # approve a subset
    {"approved_ids": ["__all__"]}                # approve everything
    {"approved_ids": []}                         # approve nothing — graph ends

Required for resume to work:
    The compiled graph must have a checkpointer attached (see builder.py).
    The caller must pass a stable `thread_id` in config at invoke() time.
"""

from langgraph.config import get_config, get_stream_writer
from langgraph.types import interrupt

from graph.nodes._log import log_node
from graph.state import Opportunity, ResearchState
from api import emit_node_status


def _format_opportunities(opportunities: dict[str, Opportunity]) -> str:
    """Render opportunities as a numbered block for stdout display.

    Iterates in insertion (first-discovery) order, matching what the
    merge-by-id reducer preserves in state.
    """
    if not opportunities:
        return "  (no opportunities were discovered)"
    lines = []
    for i, opp in enumerate(opportunities.values(), start=1):
        lines.append(
            f"  {i}. [{opp.get('id', '????')}] {opp.get('title', '(untitled)')}\n"
            f"     {opp.get('description', '')}"
        )
    return "\n".join(lines)


def human_approval_node(state: ResearchState) -> dict:
    """
    Present the discovered opportunities, pause for human input, and
    write the approved IDs into state.

    Per the builder, this node's only outgoing edge is back to `manager`.
    The graph's checkpointer persists state across the interrupt so the
    caller can resume from where we paused.
    """
    logger = log_node("human_approval", state)
    opportunities: dict[str, Opportunity] = state.get("opportunities", {})
    domain = state.get("domain", "(unknown)")

    logger.info(f"presenting {len(opportunities)} opportunities for human approval")
    for i, opp in enumerate(opportunities.values(), start=1):
        logger.info(f"  {i}. [{opp.get('id', '????')}] {opp.get('title', '(untitled)')}")

    # Bridge: emit a "Waiting for approval" summary BEFORE interrupt()
    # so the frontend can show the user what's being waited on.
    run_id = (
        get_config().get("configurable", {}).get("run_id")
        or get_config().get("configurable", {}).get("thread_id")
        or "unknown"
    )
    emit_node_status(
        get_stream_writer(),
        run_id=run_id,
        node_id="human_approval",
        status="running",
        summary=f"Waiting for approval ({len(opportunities)} opportunities)",
    )

    # Print to stdout so a CLI caller (Phase 1) sees them immediately.
    # The interrupt payload carries the same data so a future UI
    # (Phase 2 React/WebSocket) can render it without re-reading state.
    print(f"\n=== Approval needed: {len(opportunities)} opportunities in '{domain}' ===")
    print(_format_opportunities(opportunities))
    print(
        "\nResume with `Command(resume={\"approved_ids\": [...]})`. "
        "Use [\"__all__\"] to approve all, or [] to approve none."
    )

    # The interrupt payload is what the caller sees on the streaming channel.
    # Keeping the opportunities in the payload means the UI doesn't need a
    # separate state-fetch round-trip. The dict shape matches state — any
    # future UI consumes both via the same schema.
    chosen = interrupt(
        {
            "type": "approval_request",
            "domain": domain,
            "opportunities": opportunities,
            "instructions": (
                "Respond with {\"approved_ids\": [<list of opportunity ids>]}. "
                "Use [\"__all__\"] for all, or [] for none."
            ),
        }
    )

    # Normalize the resume payload. We accept either a bare list, a dict
    # with `approved_ids`, or the sentinel "__all__" string inside the list.
    if isinstance(chosen, dict):
        approved_ids = chosen.get("approved_ids", [])
    elif isinstance(chosen, list):
        approved_ids = chosen
    else:
        approved_ids = []

    if "__all__" in approved_ids:
        approved_ids = list(opportunities.keys())

    # Filter to IDs that actually exist — protects against typos in the resume.
    valid_ids = set(opportunities.keys())
    approved_ids = [oid for oid in approved_ids if oid in valid_ids]

    logger.info(f"human approved {len(approved_ids)} of {len(valid_ids)} opportunities")
    if approved_ids:
        logger.info(f"approved_ids = {approved_ids}")
    logger.outputs(approved_opportunity_ids=approved_ids)

    return {"approved_opportunity_ids": approved_ids}