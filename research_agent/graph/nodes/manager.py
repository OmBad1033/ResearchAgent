"""
manager node — the supervisor / orchestrator of the entire graph.

This node runs at every routing decision point. On each entry it inspects
state and returns a Command(goto=...) that picks the next step. It is
the ONLY node in the graph that dispatches parallel work via Send().

Stages (in order, on a clean run):

    1. entry                   -> opportunity_discovery
    2. after discovery         -> approval_router
    3. after approval          -> Send() fan-out to deep_dive (one per approved id)
    4. after deep-dive fan-in  -> Send() fan-out to worth_it (one per deep-dived)
    5. after worth-it fan-in   -> synthesis
    6. synthesis reached END   -> (manager is never re-entered)

Stage detection heuristic:
    We classify the current state into one of the five buckets by looking
    at `opportunities` and `approved_opportunity_ids`. This is robust to
    re-entry after the orchestrator's fan-in (state is the merged result
    from the parallel sub-graph), but fragile if a stage is skipped —
    `orchestration` raises on incomplete fan-in so we'd notice.

Why Command(goto=...) and not a conditional edge:
    The manager is also responsible for the dynamic Send() fan-out. A
    conditional edge can't emit Send()s, and a Command can. So manager
    has to be a Command-returning node.
"""

from langgraph.config import get_config, get_stream_writer
from langgraph.types import Send

from graph.nodes._log import log_node, log_stage
from graph.state import Opportunity, ResearchState
from api import emit_edge_active, emit_node_added


# Stage names — used as goto targets. Kept as constants so the builder
# and manager agree on the spelling (no stringly-typed coupling).
STAGE_DISCOVERY = "opportunity_discovery"
STAGE_APPROVAL = "approval_router"
STAGE_DEEP_DIVE = "deep_dive"
STAGE_WORTH_IT = "worth_it"
STAGE_SYNTHESIS = "synthesis"


def route_from_manager(state: ResearchState) -> str | list[Send]:
    """
    Pure routing function for the conditional edge attached to `manager`.

    Returns:
      - A node name (string) for static transitions, or
      - A list[Send] for parallel fan-out stages (deep_dive, worth_it), or
      - The string "__end__" to terminate the graph.

    Conditional edges in LangGraph accept either a string or a list of
    Send() objects as the path function's return value — LangGraph uses
    the latter for fan-out. This is the right place to build Send lists,
    not the node function.

    No logging / no state mutation here — that's `manager_node`'s job.
    Both call `_classify_stage` for the actual decision.
    """
    stage = _classify_stage(state)
    opportunities: dict[str, Opportunity] = state.get("opportunities", {})
    approved_ids: list[str] = state.get("approved_opportunity_ids", [])

    if stage == STAGE_DEEP_DIVE:
        sends = _build_deep_dive_sends(opportunities, approved_ids, state.get("domain", ""))
        if not sends:
            return STAGE_SYNTHESIS
        return sends

    if stage == STAGE_WORTH_IT:
        sends = _build_worth_it_sends(opportunities, state.get("domain", ""))
        if not sends:
            return STAGE_SYNTHESIS
        return sends

    return stage


def _classify_stage(state: ResearchState) -> str:
    """Decide which stage the manager should hand control to next."""
    opportunities: dict[str, Opportunity] = state.get("opportunities", {})
    approved_ids: list[str] = state.get("approved_opportunity_ids", [])
    final_report = state.get("final_report", "")

    # Terminal guard: if a final_report already exists, the manager is
    # being re-entered after synthesis — shouldn't happen on a clean run,
    # but if it does, route to END instead of looping forever.
    if final_report:
        return "__end__"

    # Stage 1: nothing discovered.
    if not opportunities:
        return STAGE_DISCOVERY

    # Are there any verdicts yet? If yes, worth_it fan-in completed.
    opp_values = opportunities.values()
    has_verdicts = any(opp.get("worth_it_verdict") for opp in opp_values)
    has_deep_dive = any(opp.get("deep_dive_notes") for opp in opp_values)

    # Stage 5: every approved opportunity has a verdict.
    if has_verdicts:
        return STAGE_SYNTHESIS

    # Stage 4: deep-dive fan-in happened, but worth-it hasn't yet.
    if has_deep_dive:
        return STAGE_WORTH_IT

    # Stage 3: opportunities exist but nothing has been deep-dived yet.
    # The approval node always sets `approved_opportunity_ids` (possibly
    # to an empty list) when it runs. So:
    #   - key absent from state  -> approval hasn't run yet -> route to it
    #   - key present but empty  -> approval ran, approved nothing ->
    #                                skip the empty sub-graph work and go
    #                                straight to synthesis with whatever
    #                                was discovered.
    #   - key present and non-empty -> fall through to deep_dive fan-out
    #                                  (handled by manager_node below).
    if "approved_opportunity_ids" not in state:
        return STAGE_APPROVAL
    if not approved_ids:
        return STAGE_SYNTHESIS

    # Fall through with non-empty approved_ids — manager_node will build
    # the deep_dive Send() list. Returning STAGE_DEEP_DIVE here would be
    # redundant since the manager builds that send-list itself.
    return STAGE_DEEP_DIVE


def _build_deep_dive_sends(
    opportunities: dict[str, Opportunity],
    approved_ids: list[str],
    domain: str,
) -> list[Send]:
    """One Send() per approved opportunity.

    The payload travels under `opportunities` (a reducer-keyed field on
    the shared ResearchState schema) so the dispatched Opportunity
    survives the subgraph boundary — LangGraph strips any payload keys
    that aren't channels on its state schema, and Opportunity fields
    like `title` / `description` are NOT channels. Wrapping the
    Opportunity under `opportunities` keeps it inside a channel that is.

    The dispatched record is the SOLE key in the payload's `opportunities`
    dict, so the inner node can identify its target via `next(iter(...))`.
    We do NOT add a separate `active_opportunity_id` field — it would be
    stripped at the boundary for the same reason. The single-key dict IS
    the routing signal.

    `opportunities` is already keyed by id (the parent state's merge-by-id
    reducer guarantees this), so the lookup is direct.
    """
    sends: list[Send] = []
    for opp_id in approved_ids:
        opp = opportunities.get(opp_id)
        if opp is None:
            continue
        payload = {
            "opportunities": {opp_id: opp},
            "domain": domain,
        }
        sends.append(Send(STAGE_DEEP_DIVE, payload))
    return sends


def _build_worth_it_sends(
    opportunities: dict[str, Opportunity],
    domain: str,
) -> list[Send]:
    """One Send() per opportunity that has been deep-dived but not yet evaluated.

    Same payload shape as `_build_deep_dive_sends` — Opportunity travels
    under `opportunities` as the sole key in a single-key dict, so the
    inner node identifies its target via `next(iter(state['opportunities']))`.
    """
    sends: list[Send] = []
    for opp_id, opp in opportunities.items():
        if not opp.get("deep_dive_notes"):
            continue
        payload = {
            "opportunities": {opp_id: opp},
            "domain": domain,
        }
        sends.append(Send(STAGE_WORTH_IT, payload))
    return sends


def manager_node(state: ResearchState) -> dict:
    """
    Graph node for the manager. Logs the routing decision and returns an
    empty state update.

    Why this returns {} (not a string or Command):
        LangGraph node functions must return a dict (a state update). They
        cannot return a string, a list of Send()s, or a Command. The actual
        routing decision is made by `route_from_manager`, which is wired
        up as the conditional edge's path function in builder.py.

    This split lets us:
      - Log inside the node (visible in the trace)
      - Build Send lists and decide the next node in the routing function
        (which is the right place per LangGraph's contract)
    """
    logger = log_node("manager", state)
    stage = _classify_stage(state)
    opportunities: dict[str, Opportunity] = state.get("opportunities", {})
    approved_ids: list[str] = state.get("approved_opportunity_ids", [])

    # Bridge: emit edge_active for the routing decision. The actual
    # next-node is decided by `route_from_manager` AFTER this node
    # returns, so we mirror its decision here using the same stage
    # classification + Send-list construction. See D1 in backend_plan.md
    # for why this is in `manager_node` and not `route_from_manager`.
    run_id = (
        get_config().get("configurable", {}).get("run_id")
        or get_config().get("configurable", {}).get("thread_id")
        or "unknown"
    )
    writer = get_stream_writer()
    target = stage  # default for static transitions

    if stage == STAGE_DEEP_DIVE:
        sends = _build_deep_dive_sends(opportunities, approved_ids, state.get("domain", ""))
        if not sends:
            target = STAGE_SYNTHESIS  # short-circuit; no real fan-out
            logger.info(f"decision: skip deep_dive (no valid approved ids) -> {STAGE_SYNTHESIS}")
        else:
            log_stage(f"manager -> deep_dive fan-out ({len(sends)} parallel)")
            logger.info(f"decision: fan out deep_dive to {len(sends)} opportunities")
            target = STAGE_DEEP_DIVE
            # Bridge: emit node_added for each dynamic instance BEFORE
            # the Send fires. The runner correlates these with the
            # `deep_dive` wrapper's updates entry to drive running/
            # completed events.
            for send in sends:
                payload_opps = send.arg.get("opportunities", {})
                for opp_id, opp in payload_opps.items():
                    emit_node_added(
                        writer,
                        run_id=run_id,
                        node_id=f"deep_dive_{opp_id}",
                        node_type="deep_dive_subagent",
                        parent_id="deep_dive",
                        label=opp.get("title") or f"Opportunity {opp_id}",
                        opportunity_id=opp_id,
                    )
        logger.outputs(goto=f"[Send -> {STAGE_DEEP_DIVE} x{len(sends)}]" if sends else STAGE_SYNTHESIS)

    elif stage == STAGE_WORTH_IT:
        sends = _build_worth_it_sends(opportunities, state.get("domain", ""))
        if not sends:
            target = STAGE_SYNTHESIS
            logger.info(f"decision: skip worth_it (no deep-dived opportunities) -> {STAGE_SYNTHESIS}")
        else:
            log_stage(f"manager -> worth_it fan-out ({len(sends)} parallel)")
            logger.info(f"decision: fan out worth_it to {len(sends)} opportunities")
            target = STAGE_WORTH_IT
            for send in sends:
                payload_opps = send.arg.get("opportunities", {})
                for opp_id, opp in payload_opps.items():
                    emit_node_added(
                        writer,
                        run_id=run_id,
                        node_id=f"worth_it_{opp_id}",
                        node_type="worth_it_subagent",
                        parent_id="worth_it",
                        label=opp.get("title") or f"Opportunity {opp_id}",
                        opportunity_id=opp_id,
                    )
        logger.outputs(goto=f"[Send -> {STAGE_WORTH_IT} x{len(sends)}]" if sends else STAGE_SYNTHESIS)

    elif stage == "__end__":
        # Don't emit an edge_active into __end__ — the run_completed
        # event is the right terminal signal.
        target = None
        logger.info("decision: graph complete -> END")
        logger.outputs(goto="__end__")

    else:
        log_stage(f"manager -> {stage}")
        logger.info(f"decision: next stage = {stage}")
        logger.outputs(goto=stage)

    if target and target != "__end__":
        emit_edge_active(writer, run_id=run_id, from_node="manager", to_node=target)

    # Node function must return a state update (dict). The manager doesn't
    # mutate state — it only decides routing. Return an empty dict so
    # LangGraph's reducer contract is satisfied.
    return {}