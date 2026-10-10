"""LLM planner: decides the single next A2A delegation.

Runs on ``meta/muse-spark-1.3-contributor`` via OpenRouter (override with
``ORCHESTRATOR_MODEL`` env or ``--planner-model``). The planner only sees
agent keys + skill descriptions from discovery — never URLs or call order —
so adding an agent to ``agents.yaml`` automatically makes it delegatable.
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DEFAULT_PLANNER_MODEL = "meta/muse-spark-1.3-contributor"

_SYSTEM_PROMPT = """You are the planner for a multi-agent system. Agents speak A2A; \
you decide which agent acts next to move the user's goal forward.

Rules:
- Delegate exactly ONE agent per decision. No fan-out in a single step.
- First make sure research exists before design: if no research artifact is \
in the progress, delegate the research agent with the goal as text input.
- Never echo large artifacts back. Research artifacts contain long notes; \
reference items by id instead of copying them.
- The design/architect agent needs the chosen opportunity. Pass data_input as \
{"opportunity_id": "<id from the research artifact>", "domain": "<goal>"}. \
The runner resolves the full object. Never construct the opportunity yourself.
- To pick which opportunity to design, prefer verdict "worth pursuing" over \
"saturated" over "not viable"; say which id you chose in "reasoning".
- Return "finish" only when the goal is satisfied by the artifacts so far \
(e.g. a solution_design exists) or when no agent can usefully proceed. \
Put the final answer for the user in "summary".
- Respond with STRICT JSON only, no prose, no markdown fences, in this shape:
{"action": "delegate" | "finish", "agent": "<agent key or null>",
"text_input": "<string or null>", "data_input": "<object or null>",
"reasoning": "<one sentence>", "summary": "<final answer when finish, else empty>"}"""


@dataclass
class PlannerDecision:
    action: str  # "delegate" | "finish"
    agent: str | None = None
    text_input: str | None = None
    data_input: dict[str, Any] | None = None
    reasoning: str = ""
    summary: str = ""


def resolve_planner_model(explicit: str | None = None) -> str:
    return (
        explicit
        or os.environ.get("ORCHESTRATOR_MODEL")
        or DEFAULT_PLANNER_MODEL
    )


def format_history(trace: list[dict[str, Any]]) -> str:
    if not trace:
        return "(nothing yet — start by delegating research)"
    lines: list[str] = []
    for i, step in enumerate(trace, start=1):
        artifact = step.get("artifact_summary") or "(no artifact)"
        lines.append(
            f"{i}. agent={step.get('agent')} state={step.get('state')} "
            f"artifact={artifact}"
        )
    return "\n".join(lines)


def decide_next_step(
    goal: str,
    agents_block: str,
    trace: list[dict[str, Any]],
    valid_agents: list[str],
    model_name: str | None = None,
) -> PlannerDecision:
    """Synchronous LLM call — invoke via asyncio.to_thread from async code."""
    from research_agent.llm.OpenRouterAPI import get_openrouter_llm

    llm = get_openrouter_llm(
        model_name=resolve_planner_model(model_name),
        temperature=0.2,
        max_tokens=1024,
    )
    user_prompt = (
        f"Goal: {goal}\n\nAvailable agents:\n{agents_block}\n\n"
        f"Progress so far (most recent last):\n{format_history(trace)}\n\n"
        "Decide the single next action as strict JSON."
    )
    raw = llm.invoke(
        [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
    )
    return _parse_decision(raw, valid_agents)


def _strip_code_fences(text: str | None) -> str:
    if not text:
        return ""
    text = text.strip()
    match = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, flags=re.DOTALL)
    return match.group(1).strip() if match else text


def _parse_decision(raw: str | None, valid_agents: list[str]) -> PlannerDecision:
    cleaned = _strip_code_fences(raw)
    try:
        data = json.loads(cleaned)
    except (json.JSONDecodeError, TypeError):
        raise RuntimeError(f"Planner returned unparseable output: {(raw or '')[:300]}")
    if not isinstance(data, dict):
        raise RuntimeError(f"Planner output is not an object: {cleaned[:300]}")

    action = str(data.get("action") or "").strip().lower()
    if action not in ("delegate", "finish"):
        raise RuntimeError(f"Planner action must be delegate|finish, got {action!r}")

    if action == "finish":
        return PlannerDecision(
            action="finish",
            reasoning=str(data.get("reasoning") or ""),
            summary=str(data.get("summary") or ""),
        )

    agent = str(data.get("agent") or "").strip()
    if agent not in valid_agents:
        raise RuntimeError(
            f"Planner chose unknown agent {agent!r}; valid: {valid_agents}"
        )
    text_input = data.get("text_input")
    data_input = data.get("data_input")
    if isinstance(data_input, str):
        try:
            data_input = json.loads(data_input)
        except json.JSONDecodeError:
            data_input = None
    if text_input is None and data_input is None:
        raise RuntimeError("Planner delegate step needs text_input and/or data_input")
    return PlannerDecision(
        action="delegate",
        agent=agent,
        text_input=str(text_input) if text_input is not None else None,
        data_input=dict(data_input) if isinstance(data_input, dict) else None,
        reasoning=str(data.get("reasoning") or ""),
    )
