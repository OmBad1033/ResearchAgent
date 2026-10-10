"""A2A executor for the Research Agent.

Reads the domain string from the incoming message's TextParts, runs the
existing LangGraph pipeline via ``a2a_agent.arun_research``, and emits
the result as a DataPart artifact conforming to ``ResearchResult``.

Lifecycle contract (per buildPlan §1 + Phase 4):
- Every path ends in a terminal state: ``completed`` on success,
  ``failed`` on any error — never leaves the task in ``working``.
"""

from __future__ import annotations

import traceback

from a2a.helpers.proto_helpers import (
    get_data_parts,
    get_message_text,
    new_data_part,
    new_task_from_user_message,
    new_text_message,
)
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import TaskState

from research_agent.a2a_agent import arun_research


class ResearchAgentExecutor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        task = context.current_task
        if task is None:
            if context.message is None:
                raise ValueError("No message provided")
            task = new_task_from_user_message(context.message)
            await event_queue.enqueue_event(task)

        updater = TaskUpdater(
            event_queue=event_queue, task_id=task.id, context_id=task.context_id
        )
        await updater.update_status(
            TaskState.TASK_STATE_WORKING,
            message=new_text_message("Researching opportunities..."),
        )

        try:
            # Prefer a structured DataPart if the caller sent one
            # (e.g. {"domain": "..."}); fall back to raw text.
            domain = _extract_domain(context)
            if not domain:
                raise ValueError(
                    "No domain provided: send a TextPart with the domain "
                    'or a DataPart like {"domain": "fintech"}'
                )
            result = await arun_research(domain)
            await updater.add_artifact(
                parts=[
                    new_data_part(
                        result.model_dump(), media_type="application/json"
                    )
                ],
                name="research_result",
            )
            await updater.update_status(
                TaskState.TASK_STATE_COMPLETED,
                message=new_text_message(
                    f"Found {len(result.opportunities)} opportunities in {domain!r}."
                ),
            )
        except Exception as exc:  # noqa: BLE001 — must terminal-state the task
            traceback.print_exc()
            await updater.update_status(
                TaskState.TASK_STATE_FAILED,
                message=new_text_message(f"Research failed: {exc}"),
            )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        task = context.current_task
        if task is None:
            raise ValueError("No task to cancel")
        updater = TaskUpdater(
            event_queue=event_queue, task_id=task.id, context_id=task.context_id
        )
        await updater.update_status(
            TaskState.TASK_STATE_CANCELED,
            message=new_text_message("Research task cancelled."),
        )


def _extract_domain(context: RequestContext) -> str:
    if context.message is not None:
        for payload in get_data_parts(context.message.parts):
            if isinstance(payload, dict) and payload.get("domain"):
                return str(payload["domain"]).strip()
    text = context.get_user_input().strip()
    return text
