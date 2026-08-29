"""
Worth-it evaluation sub-agent.

Receives a single Opportunity (passed via Send() from the manager after
the deep-dive stage) and asks the LLM to judge whether it's worth
pursuing, given existing solutions and the deep-dive research notes.

Returns a single-key dict fragment `{id: updated}` so the parent graph's
merge-by-id reducer on `opportunities` coalesces this update with the
other parallel writes (last write wins per id, no duplicates).
"""

import json
import re

from langgraph.config import get_config, get_stream_writer

from llm.OpenRouterAPI import get_openrouter_llm
from graph.nodes._log import log_subagent
from graph.state import Opportunity, ResearchState
from api import emit_node_added, emit_node_status

# Constants for the model + a small temperature for more consistent verdicts.
_MODEL_NAME = "google/gemini-3.5-flash"
_TEMPERATURE = 0.2
_MAX_TOKENS = 1024

# Valid verdict values for the Opportunity.worth_it_verdict field.
_VALID_VERDICTS = {"worth pursuing", "saturated", "not viable"}
_DEFAULT_VERDICT = "not viable"


_SYSTEM_PROMPT = """You are an analyst evaluating whether a product/opportunity \
in a given domain is worth pursuing.

You will receive:
- The domain the opportunity lives in
- The opportunity's title and description
- A list of existing solutions already on the market
- Deep-dive research notes

Your job is to judge viability and respond with STRICT JSON only, \
with this exact shape:
{
  "verdict": "worth pursuing" | "saturated" | "not viable",
  "reasoning": "<2-4 sentence explanation of your verdict>"
}

Verdict guidance:
- "worth pursuing": clear gap or meaningful improvement over existing solutions
- "saturated": crowded market with strong incumbents and limited differentiation
- "not viable": fundamental problems (no market, regulatory blockers, etc.)

Respond with JSON only. No prose before or after. No markdown fences."""


def _strip_code_fences(text: str) -> str:
    """Remove ```json ... ``` wrappers if the model adds them anyway."""
    text = text.strip()
    match = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, flags=re.DOTALL)
    if match:
        return match.group(1).strip()
    return text


def _parse_verdict_response(raw: str) -> tuple[str, str]:
    """Parse the model's JSON response into (verdict, reasoning).

    Coerces invalid verdicts to the safe default and falls back to the
    raw text as reasoning if JSON parsing fails entirely.
    """
    cleaned = _strip_code_fences(raw)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        # Model didn't return valid JSON. Treat the whole thing as reasoning
        # with the safe default verdict so the graph doesn't crash.
        return _DEFAULT_VERDICT, raw.strip()

    verdict = data.get("verdict", _DEFAULT_VERDICT)
    if verdict not in _VALID_VERDICTS:
        verdict = _DEFAULT_VERDICT

    reasoning = data.get("reasoning", "")
    if not isinstance(reasoning, str):
        reasoning = str(reasoning)

    return verdict, reasoning.strip()


def worth_it_subagent(state: dict) -> dict:
    """Evaluate a single opportunity and return an updated Opportunity dict.

    The manager invokes this once per approved opportunity via Send(). The
    payload carries the dispatched Opportunity under `state["opportunities"]`
    as a single-key dict fragment. The dispatched id IS the sole key in
    that dict — we identify our target via `next(iter(opps))`. See
    `deep_dive_subagent` for the full explanation of why we use this
    indirection instead of a flat `{**opp, ...}` payload.

    The inner node returns `{"opportunities": {id: updated}}` which the
    parent's merge-by-id reducer coalesces with N parallel writes.
    """
    opps = state.get("opportunities") or {}
    active_id = next(iter(opps), None)
    opportunity = opps.get(active_id) or {}
    domain = state.get("domain", "")
    opp_id = opportunity.get("id") or active_id or "????????"

    logger = log_subagent("worth_it_subagent", opp_id)

    # Bridge: emit node_added BEFORE any other side effect.
    run_id = (
        get_config().get("configurable", {}).get("run_id")
        or get_config().get("configurable", {}).get("thread_id")
        or "unknown"
    )
    writer = get_stream_writer()
    emit_node_added(
        writer,
        run_id=run_id,
        node_id=f"worth_it_{opp_id}",
        node_type="worth_it_subagent",
        parent_id="worth_it",
        label=opportunity.get("title") or f"Opportunity {opp_id}",
        opportunity_id=opp_id,
    )
    emit_node_status(
        writer,
        run_id=run_id,
        node_id=f"worth_it_{opp_id}",
        status="running",
        summary="Evaluating viability",
    )

    logger.info(f"evaluating verdict for {opportunity.get('title', '(untitled)')!r}")

    user_prompt = f"""Domain: {domain}

Opportunity title: {opportunity.get('title', '')}

Opportunity description: {opportunity.get('description', '')}

Existing solutions: {opportunity.get('existing_solutions', [])}

Deep-dive research notes:
{opportunity.get('deep_dive_notes', '')}

Decide whether this opportunity is worth pursuing and respond with strict JSON only."""

    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    llm = get_openrouter_llm(
        model_name=_MODEL_NAME,
        temperature=_TEMPERATURE,
        max_tokens=_MAX_TOKENS,
    )
    raw_response = llm.invoke(messages)

    verdict, reasoning = _parse_verdict_response(raw_response)

    updated = {
        "id": opportunity.get("id") or active_id,
        "title": opportunity.get("title", ""),
        "description": opportunity.get("description", ""),
        "existing_solutions": opportunity.get("existing_solutions", []),
        "deep_dive_notes": opportunity.get("deep_dive_notes", ""),
        "worth_it_verdict": verdict,
        "worth_it_reasoning": reasoning,
    }

    logger.info(f"verdict = {verdict!r}")
    logger.info(f"reasoning: {reasoning[:200]}")
    logger.outputs(worth_it_verdict=verdict)

    # Bridge: completion emit.
    emit_node_status(
        writer,
        run_id=run_id,
        node_id=f"worth_it_{opp_id}",
        status="completed",
        summary=f"Verdict: {verdict}",
    )

    # Single-key dict fragment so the parent's merge-by-id reducer on
    # `opportunities` coalesces this with N parallel writes without
    # producing duplicate records. `messages` uses add_messages and
    # handles parallel writes correctly.
    return {
        "opportunities": {updated["id"]: updated},
        "messages": [
            {"role": "assistant", "content": reasoning or verdict},
        ],
    }