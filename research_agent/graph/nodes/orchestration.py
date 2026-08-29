"""
orchestration node — fan-in marker + completeness validator.

After a parallel sub-graph (deep_dive or worth_it) finishes, the merge-by-id
reducer on `opportunities` has already coalesced N parallel writes into a
dict keyed by Opportunity.id. This node is the single successor required by
the builder's static edges, and its real job is to validate that the merge
actually completed for the expected set of opportunities.

How it knows which stage just finished:
    We compare `state["approved_opportunity_ids"]` (set before the
    deep_dive fan-out) against the opportunities that have / lack
    `worth_it_verdict`. If every approved opportunity still lacks a
    verdict, the deep_dive fan-in just happened. If every approved
    opportunity has a verdict (or no opportunities ever got approved),
    the worth_it fan-in just happened.

On a clean run this node does nothing observable besides logging; on a
buggy run (sub-agent crashed mid-fan-in, Send() didn't fire, etc.) it
raises so the failure is visible instead of silently propagating.

Required to match the builder's contract:
    Returns {} — this node is purely a bridge back to `manager`. It
    does NOT route or mutate state, because that would race with the
    manager's next Command(goto=...) decision.
"""

from graph.nodes._log import log_node
from graph.state import Opportunity, ResearchState


# Required fields on an Opportunity at each stage's end.
_DEEP_DIVE_REQUIRED = {"id", "existing_solutions", "deep_dive_notes"}
_WORTH_IT_REQUIRED = {"id", "worth_it_verdict", "worth_it_reasoning"}


def _missing_fields(opportunity: Opportunity, required: set[str]) -> list[str]:
    return [field for field in required if not opportunity.get(field)]


def _validate_stage(
    opportunities: dict[str, Opportunity],
    approved_ids: list[str],
    stage: str,
    required_fields: set[str],
) -> None:
    """Raise if any approved opportunity is missing required fields for `stage`."""
    approved_set = set(approved_ids)
    if not approved_set:
        # Nothing was approved → nothing should have been fanned out.
        # Not an error (the human may have approved zero), just nothing to check.
        return

    incomplete: list[tuple[str, list[str]]] = []
    for opp_id in approved_set:
        opp = opportunities.get(opp_id)
        if opp is None:
            incomplete.append((opp_id, ["<entire opportunity missing>"]))
            continue
        missing = _missing_fields(opp, required_fields)
        if missing:
            incomplete.append((opp_id, missing))

    if incomplete:
        details = "; ".join(
            f"id={oid} missing={fields}" for oid, fields in incomplete
        )
        raise RuntimeError(
            f"orchestration: {stage} fan-in is incomplete — {details}"
        )


def orchestration_node(state: ResearchState) -> dict:
    """
    Validate the just-completed fan-in, then return {} so the builder's
    static edge routes back to `manager` for the next decision.
    """
    logger = log_node("orchestration", state)
    opportunities: dict[str, Opportunity] = state.get("opportunities", {})
    approved_ids: list[str] = state.get("approved_opportunity_ids", [])

    # Determine which stage just finished.
    # Heuristic: if any approved opportunity has a worth_it_verdict, the
    # worth_it fan-in must have completed (or the manager skipped deep_dive
    # entirely, which is fine — that means there are no approved ids).
    if not opportunities:
        logger.info("no opportunities in state; skipping fan-in validation")
        return {}

    opp_values = opportunities.values()
    any_has_verdict = any(opp.get("worth_it_verdict") for opp in opp_values)
    any_has_deep_dive = any(opp.get("deep_dive_notes") for opp in opp_values)

    if any_has_verdict:
        logger.info("detected worth_it fan-in; validating verdicts")
        _validate_stage(opportunities, approved_ids, "worth_it", _WORTH_IT_REQUIRED)
    elif any_has_deep_dive:
        logger.info("detected deep_dive fan-in; validating notes")
        _validate_stage(opportunities, approved_ids, "deep_dive", _DEEP_DIVE_REQUIRED)
    else:
        # Neither stage appears to have produced output for the approved set.
        # Could be: no opportunities were approved (silent skip — fine), or
        # something went wrong upstream. Distinguish by checking approved_ids.
        if approved_ids:
            raise RuntimeError(
                "orchestration: entered with approved_opportunity_ids set but "
                "no deep_dive_notes or worth_it_verdict on any opportunity — "
                "sub-graph fan-out did not produce results."
            )
        logger.info("no approved ids; nothing to validate")

    logger.info("fan-in validated; routing back to manager")
    return {}