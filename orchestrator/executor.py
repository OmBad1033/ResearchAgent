"""A2A executor: one delegation with the full task lifecycle.

Builds TextPart/DataPart payloads from the planner decision, reuses the
per-agent ``contextId`` so follow-ups continue the same conversation,
polls ``tasks/get`` when an agent returns a non-terminal state, and
surfaces ``input-required`` (human reply) vs terminal failure distinctly.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from orchestrator import a2a_client as raw


@dataclass
class DelegationResult:
    agent_key: str
    task: dict[str, Any]
    state: str
    context_id: str | None
    artifact: dict[str, Any] | None
    message: str


def summarize_artifact(artifact: Any, limit: int = 1500) -> str:
    if artifact is None:
        return "(no artifact)"
    if isinstance(artifact, dict) and isinstance(artifact.get("opportunities"), list):
        lines = [
            f"{o.get('id')}: {o.get('title')} [{o.get('worth_it_verdict') or 'unjudged'}]"
            for o in artifact["opportunities"]
            if isinstance(o, dict)
        ]
        return "opportunities:\n" + "\n".join(f"  - {line}" for line in lines)
    if isinstance(artifact, dict) and artifact.get("proposed_stack") is not None:
        stack = ", ".join(str(s) for s in (artifact.get("proposed_stack") or []))
        return f"solution_design: stack=[{stack}] effort={artifact.get('build_effort_estimate') or '?'}"
    try:
        text = json.dumps(artifact, default=str)
    except (TypeError, ValueError):
        text = str(artifact)
    return text if len(text) <= limit else text[:limit] + "...[truncated]"


async def delegate(
    agent_key: str,
    base_url: str,
    text_input: str | None = None,
    data_input: dict[str, Any] | None = None,
    context_id: str | None = None,
    task_id: str | None = None,
    timeout_s: float = 300.0,
    poll_interval_s: float = 3.0,
) -> DelegationResult:
    """Send one A2A message and drive it to a decision point.

    Returns on COMPLETED (with artifact), INPUT_REQUIRED / AUTH_REQUIRED
    (needs human / credentials), or terminal failure. WORKING/SUBMITTED
    tasks are polled via tasks/get until they settle or timeout_s elapses.
    """
    parts: list[dict[str, Any]] = []
    if text_input:
        parts.append({"text": text_input})
    if data_input is not None:
        parts.append({"data": data_input})
    if not parts:
        raise ValueError("delegate needs text_input and/or data_input")

    task = await raw.send_message_once(
        base_url,
        parts,
        context_id=context_id,
        task_id=task_id,
        timeout_s=timeout_s,
    )
    state = raw.task_state(task)
    if state in (raw.STATE_SUBMITTED, raw.STATE_WORKING):
        task = await raw.wait_for_terminal(
            base_url,
            raw.task_id(task),
            timeout_s=timeout_s,
            poll_interval_s=poll_interval_s,
        )
        state = raw.task_state(task)

    try:
        artifact = raw.extract_data_artifact(task)
    except ValueError:
        artifact = None
    return DelegationResult(
        agent_key=agent_key,
        task=task,
        state=state,
        context_id=raw.task_context_id(task) or context_id,
        artifact=artifact,
        message=raw.task_message_text(task),
    )
