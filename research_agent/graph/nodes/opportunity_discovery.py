"""
opportunity_discovery node.

Reads the user's `domain` from state and uses Tavily + the Bedrock LLM to
surface 3-5 candidate opportunities (problems to solve, gaps in the market).

This node ONLY discovers. The deep_dive dispatch happens in the *manager*
after approval_router + (human_approval | ai_approval) — see `builder.py`
for the full topology. This node never sees the deep_dive sub-graph.

Returns `{"opportunities": {id: Opportunity, ...}}` so the parent's
merge-by-id reducer on `state["opportunities"]` can coalesce parallel
updates from deep_dive / worth_it sub-agents without producing duplicates.

Why Bedrock (not OpenRouter) here: discovery is information gathering, the
same role as `deep_dive_subagent`. Per the project's LLM split, Bedrock is
the info-gathering provider; OpenRouter is reserved for decision-making
nodes (worth_it, approval, synthesis).

Required env vars:
    TAVILY_API_KEY              (Tavily search)
    AWS_BEARER_TOKEN_BEDROCK    (Bedrock)
    BEDROCK_BASE_URL            (optional; defaults to standard regional endpoint)
    AWS_REGION                  (optional, default eu-west-1)
"""

import json
import uuid

from llm.BedrockAPI import BedrockLLM, get_bedrock_llm
from graph.nodes._log import log_node
from graph.state import Opportunity
from tools.web_search import search_problems


# Lazy-init the Bedrock client. Tavily is now handled by tools.web_search.
_bedrock: BedrockLLM | None = None


def _get_bedrock() -> BedrockLLM:
    global _bedrock
    if _bedrock is None:
        _bedrock = get_bedrock_llm(
            model_name="openai.gpt-oss-120b",
            temperature=0.5,  # higher than deep_dive — discovery benefits from variety
            max_tokens=4096,
        )
    return _bedrock


def opportunity_discovery_node(state: dict) -> dict:
    """
    Discover 3-5 opportunities in the user-supplied domain.

    Reads `state["domain"]`, runs a Tavily search, asks the Bedrock LLM to
    distill the raw results into structured opportunities, and returns
    them as a list ready for `operator.add`.
    """
    domain = state.get("domain", "")
    logger = log_node("opportunity_discovery", state)
    if not domain:
        # The manager should have set `domain` before routing here. If it
        # didn't, that's a graph-wiring bug — surface it loudly rather
        # than silently producing empty state.
        raise ValueError("`domain` is empty in state.")

    # --- 1. Tavily: raw search for problems / gaps in the domain ---
    results = search_problems(domain, max_results=8)
    logger.info(f"Tavily returned {len(results)} results for domain={domain!r}")
    raw_text = "\n\n".join(
        f"### {r.title}\n{(r.content or '')[:400]}"
        for r in results
    )

    # --- 2. Bedrock LLM: distill raw text into structured opportunities ---
    llm = _get_bedrock()
    prompt = (
        f"You are a market-research analyst. Given raw search results about "
        f"the `{domain}` domain, identify 3-5 distinct, concrete opportunities "
        f"(problems to solve or gaps to fill). For each, give:\n"
        f"  - title: short, 5-10 words\n"
        f"  - description: 1-2 sentences explaining the problem and why it "
        f"matters\n\n"
        f"Output ONLY a JSON array of objects with `title` and `description` "
        f"fields. No preamble, no explanation outside the JSON.\n\n"
        f"## Raw search results:\n{raw_text}"
    )
    raw_json = llm.invoke(
        [{"role": "user", "content": prompt}],
        system=(
            "You are a precise market-research analyst. Output strict JSON "
            "with no markdown fences and no commentary outside the JSON."
        ),
    )

    # --- 3. Parse the LLM output. Strip code fences if the model added any. ---
    cleaned = raw_json.strip()
    if cleaned.startswith("```"):
        # Drop leading ``` or ```json, drop trailing ```
        cleaned = cleaned.split("```", 2)[1]
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.rstrip("`").strip()

    parsed = json.loads(cleaned)

    # --- 4. Build Opportunity dicts. Only `id`, `title`, `description` are
    #        set here; the research fields are filled in by deep_dive. ---
    opportunities = [
        {
            "id": uuid.uuid4().hex[:8],
            "title": item["title"],
            "description": item["description"],
            "existing_solutions": [],
            "deep_dive_notes": "",
            "worth_it_verdict": "",
            "worth_it_reasoning": "",
        }
        for item in parsed
    ]

    # Wrap as {id: Opportunity} so the state's merging reducer can coalesce
    # parallel updates from deep_dive / worth_it sub-agents without producing
    # duplicates. Keying by id makes the merge contract explicit.
    opportunities_by_id: dict[str, Opportunity] = {
        opp["id"]: opp for opp in opportunities
    }

    logger.info(f"Bedrock distilled into {len(opportunities)} opportunities")
    for opp in opportunities:
        logger.info(f"  + [{opp['id']}] {opp['title']}")
    logger.outputs(opportunities=opportunities_by_id)
    return {"opportunities": opportunities_by_id}
