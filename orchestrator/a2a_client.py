"""Shared A2A JSON-RPC client helpers for the orchestrator.

Plain HTTP + JSON-RPC (per buildPlan §5.1: "or plain HTTP + JSON-RPC if
the SDK's client is awkward to use standalone"). Method names match the
SDK's wire protocol (``SendMessage`` / ``GetTask`` / ``CancelTask``).

One function per need:

- ``fetch_agent_card`` — discovery via ``GET /.well-known/agent-card.json``
- ``send_message`` — ``SendMessage`` and require a terminal ``Task``
  (legacy one-shot; kept for backward compatibility)
- ``send_message_once`` — ``SendMessage`` returning whatever task state
  comes back; carries ``contextId``/``taskId`` for multi-turn threads
- ``get_task`` / ``cancel_task`` — ``GetTask`` / ``CancelTask``
- ``wait_for_terminal`` — poll ``GetTask`` until the task settles
- ``extract_data_artifact`` — pull the first DataPart dict out of a task
"""

from __future__ import annotations

import asyncio
import sys
import time
import uuid
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

A2A_VERSION = "1.0"

STATE_SUBMITTED = "TASK_STATE_SUBMITTED"
STATE_WORKING = "TASK_STATE_WORKING"
STATE_COMPLETED = "TASK_STATE_COMPLETED"
STATE_FAILED = "TASK_STATE_FAILED"
STATE_CANCELED = "TASK_STATE_CANCELED"
STATE_REJECTED = "TASK_STATE_REJECTED"
STATE_INPUT_REQUIRED = "TASK_STATE_INPUT_REQUIRED"
STATE_AUTH_REQUIRED = "TASK_STATE_AUTH_REQUIRED"

TERMINAL_STATES = {
    STATE_COMPLETED,
    STATE_FAILED,
    STATE_CANCELED,
    STATE_REJECTED,
}
FAILED_STATES = {
    STATE_FAILED,
    STATE_CANCELED,
    STATE_REJECTED,
}


async def _rpc(
    base_url: str,
    method: str,
    params: dict[str, Any],
    timeout_s: float,
) -> Any:
    """POST one JSON-RPC call and return the ``result`` payload."""
    body = {
        "jsonrpc": "2.0",
        "id": "req-" + uuid.uuid4().hex[:8],
        "method": method,
        "params": params,
    }
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        resp = await client.post(
            base_url.rstrip("/") + "/",
            json=body,
            headers={"A2A-Version": A2A_VERSION, "Content-Type": "application/json"},
        )
        resp.raise_for_status()
        envelope = resp.json()
    if "error" in envelope:
        raise RuntimeError(f"A2A error ({method}): {envelope['error']}")
    return envelope.get("result")


async def fetch_agent_card(base_url: str, timeout_s: float = 10.0) -> dict[str, Any]:
    url = base_url.rstrip("/") + "/.well-known/agent-card.json"
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict):
            raise ValueError(f"Agent Card at {url} is not a JSON object")
        return data


async def send_message_once(
    base_url: str,
    parts: list[dict[str, Any]],
    context_id: str | None = None,
    task_id: str | None = None,
    timeout_s: float = 300.0,
) -> dict[str, Any]:
    """Send one A2A message and return the task in whatever state it is in.

    Pass back the ``context_id`` from a previous task on the same agent to
    continue the conversation instead of starting a new thread.
    """
    message: dict[str, Any] = {
        "messageId": "m-" + uuid.uuid4().hex[:8],
        "role": "ROLE_USER",
        "parts": parts,
    }
    if context_id:
        message["contextId"] = context_id
    if task_id:
        message["taskId"] = task_id
    result = await _rpc(
        base_url, "SendMessage", {"message": message}, timeout_s=timeout_s
    )
    if not isinstance(result, dict):
        raise RuntimeError(f"No result in A2A SendMessage response: {result!r}")
    task = result.get("task")
    if isinstance(task, dict):
        return task
    raise RuntimeError(
        f"No task in A2A SendMessage response (got keys {sorted(result)}); "
        "the agent may require streaming or authentication"
    )


async def send_message(
    base_url: str,
    parts: list[dict[str, Any]],
    timeout_s: float = 300.0,
) -> dict[str, Any]:
    """Send one A2A message and return the terminal task dict.

    Raises:
        httpx.HTTPError: transport failure.
        RuntimeError: server returned a JSON-RPC error, no task payload,
            or a non-terminal task state.
    """
    task = await send_message_once(base_url, parts, timeout_s=timeout_s)
    state = task_state(task)
    if state in (STATE_SUBMITTED, STATE_WORKING, STATE_INPUT_REQUIRED):
        task = await wait_for_terminal(
            base_url, task_id(task), timeout_s=timeout_s
        )
        state = task_state(task)
    if state not in TERMINAL_STATES:
        raise RuntimeError(f"Task left in non-terminal state: {state!r}")
    return task


async def get_task(
    base_url: str,
    task_id_: str,
    timeout_s: float = 30.0,
) -> dict[str, Any]:
    """Poll the current state of a task via ``GetTask``."""
    result = await _rpc(base_url, "GetTask", {"id": task_id_}, timeout_s=timeout_s)
    if not isinstance(result, dict):
        raise RuntimeError(f"No task in A2A GetTask response: {result!r}")
    return result


async def cancel_task(
    base_url: str,
    task_id_: str,
    timeout_s: float = 30.0,
) -> dict[str, Any]:
    """Request cancellation of a task via ``CancelTask``."""
    result = await _rpc(
        base_url, "CancelTask", {"id": task_id_}, timeout_s=timeout_s
    )
    if not isinstance(result, dict):
        raise RuntimeError(f"No task in A2A CancelTask response: {result!r}")
    return result


async def wait_for_terminal(
    base_url: str,
    task_id_: str,
    timeout_s: float = 300.0,
    poll_interval_s: float = 3.0,
) -> dict[str, Any]:
    """Poll ``GetTask`` until the task reaches a decision-point state.

    Returns on COMPLETED / FAILED / CANCELED / REJECTED (terminal) as well
    as INPUT_REQUIRED / AUTH_REQUIRED (needs a human or credentials).
    Raises TimeoutError if the task is still SUBMITTED/WORKING past the
    deadline.
    """
    deadline = time.monotonic() + timeout_s
    task = await get_task(base_url, task_id_)
    while task_state(task) in (STATE_SUBMITTED, STATE_WORKING):
        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"Task {task_id_} still {task_state(task)} after {timeout_s}s"
            )
        await asyncio.sleep(poll_interval_s)
        task = await get_task(base_url, task_id_)
    return task


def task_state(task: dict[str, Any]) -> str:
    return str((task.get("status") or {}).get("state") or "")


def task_id(task: dict[str, Any]) -> str:
    tid = task.get("id")
    if not tid:
        raise ValueError(f"A2A task has no id: {task!r}")
    return str(tid)


def task_context_id(task: dict[str, Any]) -> str | None:
    for key in ("contextId", "context_id"):
        cid = task.get(key)
        if cid:
            return str(cid)
    return None


def task_message_text(task: dict[str, Any]) -> str:
    """Best-effort text from the task's status message parts."""
    status = task.get("status") or {}
    msg = status.get("message") or {}
    texts = [
        p.get("text", "")
        for p in (msg.get("parts") or [])
        if isinstance(p, dict) and p.get("text")
    ]
    return "\n".join(texts)


def task_failed_message(task: dict[str, Any]) -> str:
    """Best-effort human-readable error from a failed task's status message."""
    return task_message_text(task) or f"task state={task_state(task)}"


def extract_data_artifact(task: dict[str, Any]) -> dict[str, Any]:
    """Return the first DataPart payload dict from the task's artifacts."""
    for artifact in task.get("artifacts") or []:
        if not isinstance(artifact, dict):
            continue
        for part in artifact.get("parts") or []:
            if isinstance(part, dict) and isinstance(part.get("data"), dict):
                return part["data"]
    raise ValueError("Task has no DataPart artifact")
