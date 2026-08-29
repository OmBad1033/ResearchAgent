"""
ai_approval node.

Autonomous counterpart to human_approval: asks an LLM (Xiaomi MiMo via
OpenRouter) to pick which discovered opportunities are worth deep-diving.

Writes the chosen IDs to `state["approved_opportunity_ids"]` so the
manager can fan out the deep_dive sub-agents over them.
"""

import json
import re

from llm.OpenRouterAPI import get_openrouter_llm
from graph.nodes._log import log_node
from graph.state import Opportunity, ResearchState


# Xiaomi MiMo via OpenRouter. Low temperature for consistent selection.
_MODEL_NAME = "xiaomi/mimo-v2.5"
_TEMPERATURE = 0.2
_MAX_TOKENS = 1024

# Match the cap you'd realistically want a single deep-dive pass to handle.
# Adjust here if you want AI mode to be more or less aggressive than human mode.
_MAX_APPROVALS = 5


_SYSTEM_PROMPT = """You are a portfolio-selection analyst. Given a list of \
candidate opportunities in a domain, pick the ones most worth researching \
in depth right now.

Selection criteria (in priority order):
1. Clear market gap or unmet need (not just incremental tweaks)
2. Signal of momentum — emerging trends, regulatory tailwinds, demand
3. Feasibility to evaluate in a short research pass
4. Diversity — prefer distinct opportunities over redundant ones

Respond with STRICT JSON only, in this exact shape:
{
  "approved_ids": ["id1", "id2", "id3"],
  "reasoning": "<1-2 sentences explaining your selection>"
}

Rules:
- `approved_ids` must reference IDs from the input list. Empty array is fine.
- Respond with JSON only. No prose, no markdown fences."""


def _strip_code_fences(text: str | None) -> str:
    if text is None:
        # Defensive: the OpenRouter client can return None on auth/quota
        # failure modes. Treating that as "no JSON payload" lets the
        # downstream json.loads branch fall back to the safe default
        # (approve nothing) instead of crashing the graph mid-run.
        return ""
    text = text.strip()
    if not text:
        return ""
    match = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, flags=re.DOTALL)
    if match:
        return match.group(1).strip()
    return text


def ai_approval_node(state: ResearchState) -> dict:
    """
    Ask the LLM to select opportunities to deep-dive, then write the
    selected IDs to state so the manager can dispatch them in parallel.
    """
    logger = log_node("ai_approval", state)
    opportunities: dict[str, Opportunity] = state.get("opportunities", {})
    domain = state.get("domain", "(unknown)")

    if not opportunities:
        # Nothing discovered → nothing to approve. Skip the LLM call.
        logger.info("no opportunities to evaluate; approving none")
        logger.outputs(approved_opportunity_ids=[])
        return {"approved_opportunity_ids": []}

    # Number the opportunities in the prompt so the model can reference them
    # by index if it wants, but we still require it to use real IDs in JSON.
    # Iterates in insertion (first-discovery) order via the dict's values.
    opp_lines = [
        f"  - id={opp.get('id', '????')}: {opp.get('title', '(untitled)')}\n"
        f"    {opp.get('description', '')}"
        for opp in opportunities.values()
    ]
    opportunities_block = "\n".join(opp_lines)
    valid_ids = list(opportunities.keys())

    user_prompt = f"""Domain: {domain}

Candidate opportunities (pick at most {_MAX_APPROVALS}):
{opportunities_block}

Valid IDs you may use in approved_ids: {valid_ids}

Respond with strict JSON only."""

    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    llm = get_openrouter_llm(
        model_name=_MODEL_NAME,
        temperature=_TEMPERATURE,
        max_tokens=_MAX_TOKENS,
    )
    raw = llm.invoke(messages)

    cleaned = _strip_code_fences(raw)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        # Model didn't return valid JSON — safest fallback is to approve
        # nothing rather than risk looping on bad state.
        logger.info("MiMo returned invalid JSON; approving none")
        logger.outputs(approved_opportunity_ids=[])
        return {"approved_opportunity_ids": []}

    approved_ids = data.get("approved_ids", [])
    if not isinstance(approved_ids, list):
        approved_ids = []

    # Coerce to strings, drop IDs that don't exist, cap to _MAX_APPROVALS.
    valid_set = set(valid_ids)
    approved_ids = [
        str(oid) for oid in approved_ids if str(oid) in valid_set
    ][: _MAX_APPROVALS]

    logger.info(f"MiMo reasoning: {data.get('reasoning', '')[:200]}")
    logger.info(f"MiMo selected {len(approved_ids)} of {len(opportunities)} opportunities")
    if approved_ids:
        logger.info(f"approved_ids = {approved_ids}")
    logger.outputs(approved_opportunity_ids=approved_ids)
    return {"approved_opportunity_ids": approved_ids}