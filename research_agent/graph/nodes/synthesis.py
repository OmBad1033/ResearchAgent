"""
synthesis node — terminal node.

Reads every deep-dived + worth-it-evaluated opportunity from state and
asks the Bedrock LLM to write a consolidated final report. Writes the
report to `state["final_report"]`.

This is the last node in the graph. Per builder.py it has a static edge
to END, so it does not return a Command — just a plain state update.

Why Bedrock here:
    Synthesis is long-form prose generation over a large structured input.
    Bedrock's Claude model is well-suited to that task. Per the project's
    LLM split, decision-style calls (worth_it, approval) go through
    OpenRouter; prose synthesis goes through Bedrock.

Input contract:
    `state["opportunities"]` is a dict keyed by Opportunity.id. Each entry
    should be both deep-dived and worth-it-evaluated. Iteration order is
    first-discovery order (the merge-by-id reducer preserves key insertion
    position on update). If `orchestration` raised during fan-in the graph
    never reaches this node, so a partial state here is a real bug — we
    surface it instead of writing a half report.
"""

import os

from langgraph.config import get_config, get_stream_writer

from llm.BedrockAPI import BedrockLLM, get_bedrock_llm
from graph.nodes._log import log_node
from graph.state import Opportunity, ResearchState
from api import emit_run_completed


# Match the model/temperature used elsewhere in the project.
_MODEL_NAME = "openai.gpt-oss-120b"
_TEMPERATURE = 0.3
_MAX_TOKENS = 4096


# Lazy-init mirrors the pattern in opportunity_discovery.py / deep_dive_subagent.py.
_bedrock: BedrockLLM | None = None


def _get_bedrock() -> BedrockLLM:
    global _bedrock
    if _bedrock is None:
        _bedrock = get_bedrock_llm(
            model_name=_MODEL_NAME,
            temperature=_TEMPERATURE,
            max_tokens=_MAX_TOKENS,
        )
    return _bedrock


_SYSTEM_PROMPT = """\
You are a senior research analyst writing a final report for a client who
asked about opportunities in a specific domain.

You will receive a list of opportunities, each already annotated with:
- title and description
- existing solutions on the market
- deep-dive research notes (trends, market signals)
- a worth-it verdict from a junior analyst
- the reasoning behind that verdict

Write a final report in well-structured Markdown with these sections:

1. **Executive Summary** — 2-3 sentence overview of the domain landscape.
2. **Recommended Opportunities** — the opportunities worth pursuing, with
   for each: a one-paragraph justification citing the trends and the
   gap in existing solutions.
3. **Saturated Areas** — opportunities rejected because the market is
   crowded. One paragraph each, explaining why the incumbents win.
4. **Not Viable** — opportunities rejected for fundamental reasons.
   Brief, one short paragraph each.
5. **Strategic Recommendations** — 3-5 bullet takeaways for someone
   deciding what to build next.

Rules:
- Only use verdicts that actually appear in the input. Don't invent.
- Cite specific existing solutions or trends from the deep-dive notes
  when justifying a recommendation.
- Do NOT wrap the entire output in a code fence. Output Markdown directly.
- Be specific and decisive. Avoid hedging language like "might" or
  "could potentially" when the data supports a clear call."""


def _format_opportunity(opp: Opportunity, index: int) -> str:
    """Render one opportunity into the user prompt as a labeled block."""
    solutions = opp.get("existing_solutions") or []
    solutions_block = (
        "\n".join(f"  - {s}" for s in solutions)
        if solutions
        else "  (none captured)"
    )

    return (
        f"--- Opportunity {index} ---\n"
        f"ID: {opp.get('id', '????')}\n"
        f"Title: {opp.get('title', '(untitled)')}\n"
        f"Description: {opp.get('description', '')}\n"
        f"Verdict: {opp.get('worth_it_verdict') or '(missing)'}\n"
        f"Verdict reasoning: {opp.get('worth_it_reasoning') or '(missing)'}\n"
        f"Existing solutions:\n{solutions_block}\n"
        f"Deep-dive notes:\n{opp.get('deep_dive_notes') or '(none)'}\n"
    )


def _ensure_all_evaluated(opportunities: dict[str, Opportunity]) -> None:
    """Guard against reaching synthesis with incomplete state."""
    incomplete = [
        opp.get("id", "????")
        for opp in opportunities.values()
        if not opp.get("worth_it_verdict") or not opp.get("deep_dive_notes")
    ]
    if incomplete:
        raise RuntimeError(
            "synthesis: reached terminal node with incomplete opportunities: "
            f"{incomplete}. orchestration should have raised first."
        )


def synthesis_node(state: ResearchState) -> dict:
    """
    Write the consolidated Markdown report into state["final_report"].
    """
    logger = log_node("synthesis", state)
    opportunities: dict[str, Opportunity] = state.get("opportunities", {})
    domain = state.get("domain", "(unknown)")

    if not opportunities:
        # Nothing to synthesize. Write a short stub so the caller still
        # gets a deterministic final_report key, but don't burn tokens.
        logger.info("no opportunities to synthesize; writing stub report")
        return {
            "final_report": (
                f"# Research Report: {domain}\n\n"
                "No opportunities were discovered to evaluate."
            )
        }

    _ensure_all_evaluated(opportunities)

    # Iterate in insertion (first-discovery) order. dict preserves the
    # original key position on update, so this matches what the human/AI
    # saw during approval — same order in the final report.
    opp_list = list(opportunities.values())
    opp_block = "\n\n".join(
        _format_opportunity(opp, i) for i, opp in enumerate(opp_list, start=1)
    )

    user_prompt = (
        f"Domain: {domain}\n\n"
        f"Total opportunities to report on: {len(opp_list)}\n\n"
        f"{opp_block}\n\n"
        "Write the final Markdown report based on the opportunities above."
    )

    llm = _get_bedrock()
    logger.info(f"calling Bedrock (gpt-oss-120b) with {len(opp_list)} opportunities, "
                f"prompt={len(user_prompt)} chars")
    report = llm.invoke(
        [{"role": "user", "content": user_prompt}],
        system=_SYSTEM_PROMPT,
    )

    logger.info(f"report generated; length={len(report)} chars")
    logger.outputs(final_report=f"{len(report)} chars")

    # Bridge: emit the terminal run_completed event. The runner will
    # also emit one as a safety net if the graph short-circuits; the
    # frontend treats duplicate run_completed as idempotent.
    run_id = (
        get_config().get("configurable", {}).get("run_id")
        or get_config().get("configurable", {}).get("thread_id")
        or "unknown"
    )
    emit_run_completed(get_stream_writer(), run_id=run_id)

    return {"final_report": report}