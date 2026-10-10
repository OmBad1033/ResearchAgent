"""A2A executor for the Architect Agent.

Same lifecycle pattern as the Research Agent's executor:
parse input parts -> validate -> call ``agent.design_solution`` ->
emit DataPart artifact -> mark ``completed``; any error -> ``failed``.

Input accepted as either:
- a DataPart carrying the full ``DesignRequest`` JSON
  (``{"opportunity": {...}, "domain": "...", "research_notes": "..."}``), or
- a DataPart carrying just the ``Opportunity`` JSON, or
- plain text (treated as the opportunity title with empty context —
  valid but thin; the LLM still returns a schema-conforming design).
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from a2a.helpers.proto_helpers import (
    get_data_parts,
    new_data_part,
    new_task_from_user_message,
    new_text_message,
)
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import TaskState
from pydantic import ValidationError

from architect_agent.agent import design_solution
from architect_agent.schemas import DesignRequest
from research_agent.a2a_schemas import Opportunity


class ArchitectAgentExecutor(AgentExecutor):
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
            message=new_text_message("Designing solution..."),
        )

        try:
            request = _parse_design_request(context)
            _validate_request(request)
            design = await _run_in_thread(request)
            await updater.add_artifact(
                parts=[
                    new_data_part(
                        design.model_dump(), media_type="application/json"
                    )
                ],
                name="solution_design",
            )
            await updater.update_status(
                TaskState.TASK_STATE_COMPLETED,
                message=new_text_message(
                    f"Designed {len(design.components)} components "
                    f"for {request.opportunity.title!r}."
                ),
            )
        except Exception as exc:  # noqa: BLE001 — must terminal-state the task
            traceback.print_exc()
            await updater.update_status(
                TaskState.TASK_STATE_FAILED,
                message=new_text_message(f"Design failed: {exc}"),
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
            message=new_text_message("Design task cancelled."),
        )


async def _run_in_thread(request: DesignRequest):
    import asyncio

    return await asyncio.to_thread(design_solution, request)


def _parse_design_request(context: RequestContext) -> DesignRequest:
    if context.message is not None:
        for payload in get_data_parts(context.message.parts):
            if isinstance(payload, dict):
                if "opportunity" in payload:
                    try:
                        return DesignRequest.model_validate(payload)
                    except ValidationError as exc:
                        raise ValueError(f"Invalid DesignRequest: {exc}") from exc
                if "title" in payload or "id" in payload:
                    try:
                        opp = Opportunity.model_validate(payload)
                    except ValidationError as exc:
                        raise ValueError(f"Invalid Opportunity: {exc}") from exc
                    return DesignRequest(opportunity=opp)
    text = context.get_user_input().strip()
    if not text:
        raise ValueError(
            "No design input provided: send a DataPart with the DesignRequest "
            "or Opportunity JSON, or a TextPart describing the problem"
        )
    return DesignRequest(opportunity=Opportunity(id="text-input", title=text))


def _validate_request(request: DesignRequest) -> None:
    missing = []
    if not request.opportunity.title:
        missing.append("opportunity.title")
    if missing:
        raise ValueError(
            f"DesignRequest missing required fields: {', '.join(missing)}"
        )
