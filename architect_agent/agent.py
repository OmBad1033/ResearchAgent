"""Architect Agent core logic: one focused LLM call, structured output.

Reuses the Research Agent's LLM split: decision-style calls go through
OpenRouter (same as ``worth_it_subagent`` / ``ai_approval``), so this
module imports ``get_openrouter_llm`` directly — no new provider, no
unified factory (per project taste).

The LLM is asked for STRICT JSON matching ``SolutionDesign``; parsing
falls back field-by-field so a slightly-off response still yields a
valid schema object instead of crashing.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from architect_agent.schemas import DesignRequest, SolutionDesign
from research_agent.llm.OpenRouterAPI import get_openrouter_llm

_MODEL_NAME = "google/gemini-3.5-flash"
_TEMPERATURE = 0.3
_MAX_TOKENS = 2048

_SYSTEM_PROMPT = """You are a pragmatic software architect. Given one specific \
problem statement and why it is worth solving, propose ONE sensible, \
buildable architecture. Do not hedge with multiple options unless asked.

Respond with STRICT JSON only, in this exact shape:
{
  "proposed_stack": ["..."],
  "components": ["..."],
  "data_flow_summary": "...",
  "deployment_target": "...",
  "build_effort_estimate": "...",
  "risks": ["..."],
  "open_questions": ["..."]
}

Rules:
- proposed_stack: concrete technologies (languages, frameworks, infra).
- components: the main services/modules and what each owns.
- data_flow_summary: 3-5 sentences on how data moves through the system.
- deployment_target: where this runs (cloud, provider, shape).
- build_effort_estimate: rough sizing (e.g. team size x weeks).
- Respond with JSON only. No prose, no markdown fences."""


def _strip_code_fences(text: str | None) -> str:
    if not text:
        return ""
    text = text.strip()
    match = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, flags=re.DOTALL)
    if match:
        return match.group(1).strip()
    return text


def design_solution(request: DesignRequest) -> SolutionDesign:
    """Run the architect LLM call and return a validated SolutionDesign."""
    opp = request.opportunity
    solutions = opp.existing_solutions or []
    solutions_block = (
        "\n".join(f"  - {s}" for s in solutions) if solutions else "  (none captured)"
    )
    context_block = request.research_notes or opp.deep_dive_notes or "(none)"

    user_prompt = f"""Domain: {request.domain or '(unknown)'}

Problem title: {opp.title}
Problem description: {opp.description}
Why worth solving: {opp.worth_it_reasoning or '(no reasoning captured)'}

Existing solutions:
{solutions_block}

Research notes:
{context_block}

Propose the architecture as strict JSON only."""

    llm = get_openrouter_llm(
        model_name=_MODEL_NAME,
        temperature=_TEMPERATURE,
        max_tokens=_MAX_TOKENS,
    )
    raw = llm.invoke(
        [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
    )
    return _parse_solution(raw)


def _parse_solution(raw: str | None) -> SolutionDesign:
    cleaned = _strip_code_fences(raw)
    try:
        data = json.loads(cleaned)
    except (json.JSONDecodeError, TypeError):
        return SolutionDesign(
            data_flow_summary=(raw or "").strip()[:2000],
            open_questions=["LLM returned unparseable output; see data_flow_summary."],
        )
    if not isinstance(data, dict):
        data = {}
    return SolutionDesign(
        proposed_stack=_str_list(data.get("proposed_stack")),
        components=_str_list(data.get("components")),
        data_flow_summary=str(data.get("data_flow_summary") or ""),
        deployment_target=str(data.get("deployment_target") or ""),
        build_effort_estimate=str(data.get("build_effort_estimate") or ""),
        risks=_str_list(data.get("risks")),
        open_questions=_str_list(data.get("open_questions")),
    )


def _str_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(v) for v in value if v is not None]
