"""
Runner — drives one LangGraph execution for one run_id and forwards
normalized events to an EventWriter.

Design history:
    v1 used `astream_events(version="v2")` and discovered that
    `get_stream_writer()` payloads do NOT surface as `on_custom_event`
    in langgraph 1.2.
    v2 used `astream(stream_mode=["custom", "updates"])` and
    discovered that subgraph-level custom events do NOT propagate
    to the parent's custom stream.
    v3 (current): hybrid. The graph is driven by `astream(..., stream_mode=["custom", "updates"])`.
    Custom payloads from the parent graph (manager, human_approval,
    synthesis) propagate fine; the runner forwards them verbatim.
    Custom payloads from sub-graph inner nodes (deep_dive_subagent,
    worth_it_subagent) DO NOT propagate — but the manager already
    knows which per-instance IDs it will dispatch, so it emits
    `node_added` for each one via `get_stream_writer()` BEFORE the
    Send fires (see `manager_node`). The runner correlates each
    sub-graph wrapper's `updates` entry with its instance IDs.

Specifically:
    - Static nodes (`manager`, `opportunity_discovery`, `approval_router`,
      `human_approval`, `ai_approval`, `orchestration`, `synthesis`):
      lifecycle events derived from `updates` stream mode.
    - Dynamic sub-agent instances (`deep_dive_{opp_id}`,
      `worth_it_{opp_id}`): `node_added` is emitted by `manager`
      before dispatch (via writer, which DOES propagate from parent).
      `node_status: running` is emitted when the wrapper subgraph
      appears in `updates`. `node_status: completed` is emitted when
      the wrapper subgraph completes (i.e., the next superstep starts).
    - `edge_active` events from `manager`: surface directly from the
      custom stream (parent-level).
    - `run_completed` from `synthesis`: surfaces directly.

For nodes that emit `node_status: completed` mid-run via writer
(rare, but used for sub-agents in the future), they propagate fine
from parent nodes. The current dynamic sub-agents rely on the
manager-side bookkeeping, which is enough for the POC.

Human-in-the-loop:
    `interrupt()` surfaces as a `__interrupt__` key in an `updates`
    dict; the iterator ends normally. The driver catches a
    `_GraphPaused` sentinel and parks until /resume is hit.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from graph.builder import app
from api.event_writer import (
    EventWriter,
    register_writer,
    unregister_writer,
)


log = logging.getLogger(__name__)


class _GraphPaused(Exception):
    """Internal sentinel raised by `_drain_iteration` when the graph
    hit `interrupt()`. langgraph 1.2 surfaces this as a regular
    `__interrupt__` updates dict (not as `GraphInterrupt` raised
    from astream), so we use our own exception for the driver's
    resume loop."""

    def __init__(self, interrupt_payload: Any) -> None:
        super().__init__(f"graph paused at interrupt: {interrupt_payload!r}")
        self.interrupt_payload = interrupt_payload


# Static node names — these get `node_added`/`node_status` translated
# from the `updates` stream mode by the runner. Dynamic sub-agent
# nodes (`deep_dive_subagent`, `worth_it_subagent`) emit their own
# `node_added` via the manager's writer helper and their lifecycle
# is inferred from the wrapper subgraph.
STATIC_NODE_NAMES = {
    "manager",
    "opportunity_discovery",
    "approval_router",
    "human_approval",
    "ai_approval",
    "orchestration",
    "synthesis",
}

# Wrapper nodes for sub-graphs. The manager emits per-instance
# `node_added` via writer before dispatching a Send to one of these.
# When the wrapper shows up in `updates`, we mark all expected
# instance nodes as running.
SUBGRAPH_NODES = {
    "deep_dive",
    "worth_it",
}

STATIC_NODE_LABELS = {
    "manager": "Manager",
    "opportunity_discovery": "Opportunity Discovery",
    "approval_router": "Approval Router",
    "human_approval": "Human Approval",
    "ai_approval": "AI Approval",
    "orchestration": "Orchestration",
    "synthesis": "Synthesis",
}

STATIC_NODE_PARENTS = {
    "manager": None,
    "opportunity_discovery": "manager",
    "approval_router": "manager",
    "human_approval": "manager",
    "ai_approval": "manager",
    "orchestration": "manager",
    "synthesis": "manager",
}


def _now_iso() -> str:
    from api import now_iso
    return now_iso()


def _make_envelope(event_type: str, run_id: str, **fields: Any) -> dict[str, Any]:
    from api import _envelope
    return _envelope(event_type, run_id, **fields)


class RunHandle:
    """Public handle returned by `start_run`. The HTTP /resume handler
    uses `request_resume(...)` to wake the runner after human approval."""

    def __init__(self, run_id: str, task: asyncio.Task) -> None:
        self.run_id = run_id
        self.task = task
        self._resume_event = asyncio.Event()
        self._resume_payload: dict[str, Any] | None = None

    def request_resume(self, payload: dict[str, Any]) -> None:
        self._resume_payload = payload
        self._resume_event.set()

    async def wait_for_resume(self) -> dict[str, Any]:
        await self._resume_event.wait()
        assert self._resume_payload is not None
        return self._resume_payload


_handles: dict[str, RunHandle] = {}


def get_handle(run_id: str) -> RunHandle | None:
    return _handles.get(run_id)


def _translate_updates(
    updates: dict[str, Any],
    run_id: str,
    seen_static: set[str],
    last_static_node: list[str | None],
    pending_dynamic_nodes: set[str],
    running_dynamic_nodes: set[str],
) -> list[dict[str, Any]]:
    """Translate one `updates` dict into CONTRACT events.

    Handles three cases per superstep:
      - Static node name appears for the first time -> emit node_added.
      - Static node name appears -> emit node_status: running.
      - Previous frame had a static node "running" (last_static_node) ->
        mark it completed.
      - Sub-graph wrapper appears -> mark all pending dynamic nodes
        as running.
    """
    out: list[dict[str, Any]] = []

    # Node-added for newly seen static nodes.
    newly_seen = [n for n in updates.keys() if n in STATIC_NODE_NAMES and n not in seen_static]
    for node_name in newly_seen:
        seen_static.add(node_name)
        out.append(
            _make_envelope(
                "node_added",
                run_id,
                node_id=node_name,
                node_type=node_name,
                parent_id=STATIC_NODE_PARENTS.get(node_name),
                label=STATIC_NODE_LABELS.get(node_name, node_name),
                opportunity_id=None,
            )
        )

    # Emit running for the static node(s) in this update.
    for node_name in updates.keys():
        if node_name in STATIC_NODE_NAMES:
            out.append(
                _make_envelope(
                    "node_status",
                    run_id,
                    node_id=node_name,
                    status="running",
                    summary=None,
                )
            )

    # Run any dynamic-instance nodes whose wrapper just appeared.
    for node_name in updates.keys():
        if node_name in SUBGRAPH_NODES:
            prefix = "deep_dive_" if node_name == "deep_dive" else "worth_it_"
            for inst_id in list(pending_dynamic_nodes):
                if inst_id.startswith(prefix):
                    pending_dynamic_nodes.discard(inst_id)
                    running_dynamic_nodes.add(inst_id)
                    out.append(
                        _make_envelope(
                            "node_status",
                            run_id,
                            node_id=inst_id,
                            status="running",
                            summary=None,
                        )
                    )

    # Mark previously-running static node as completed.
    if last_static_node[0] and last_static_node[0] != "__end__":
        out.append(
            _make_envelope(
                "node_status",
                run_id,
                node_id=last_static_node[0],
                status="completed",
                summary=None,
            )
        )

    # If a sub-graph wrapper just completed (i.e., we're seeing
    # the NEXT superstep), mark all currently-running dynamic
    # instances as completed.
    static_names_in_update = [n for n in updates.keys() if n in STATIC_NODE_NAMES]
    if static_names_in_update:
        # We've moved to a new superstep. Any dynamic nodes still
        # running are done.
        for inst_id in list(running_dynamic_nodes):
            out.append(
                _make_envelope(
                    "node_status",
                    run_id,
                    node_id=inst_id,
                    status="completed",
                    summary=None,
                )
            )
            running_dynamic_nodes.discard(inst_id)
        last_static_node[0] = static_names_in_update[0]

    return out


def _translate_custom_payload(payload: Any, run_id: str) -> dict[str, Any] | None:
    """Pass through a custom stream payload if it's a CONTRACT-shaped
    event dict (has `type` field). Stamp run_id/timestamp if missing.

    Also captures `node_added` events for dynamic sub-agent instances
    so the runner can track them in pending_dynamic_nodes (the manager
    emits these via writer before dispatching Send).
    """
    if not isinstance(payload, dict):
        return None
    if "type" not in payload:
        return None
    if "run_id" not in payload:
        payload["run_id"] = run_id
    if "timestamp" not in payload:
        payload["timestamp"] = _now_iso()
    return payload


async def _drain_iteration(
    config: RunnableConfig,
    input_or_command: Any,
    run_id: str,
    writer: EventWriter,
    seen_static: set[str],
    last_static_node: list[str | None],
    pending_dynamic_nodes: set[str],
    running_dynamic_nodes: set[str],
) -> None:
    """One pass through the graph. Forwards every CONTRACT event into
    the writer. Raises `_GraphPaused` when the graph hit interrupt()."""
    interrupt_payload: Any = None
    # Buffer custom payloads briefly so that the manager's per-instance
    # `node_added` events (emitted BEFORE the Send fires) are registered
    # into pending_dynamic_nodes BEFORE we see the wrapper subgraph
    # in the updates stream.
    custom_buffer: list[dict[str, Any]] = []

    async for mode, payload in app.astream(
        input_or_command,
        config=config,
        stream_mode=["custom", "updates"],
    ):
        if mode == "custom":
            translated = _translate_custom_payload(payload, run_id)
            if translated is None:
                continue
            # Track per-instance node_added for dynamic dispatch.
            if (
                translated.get("type") == "node_added"
                and translated.get("node_type") in ("deep_dive_subagent", "worth_it_subagent")
            ):
                node_id = translated.get("node_id", "")
                if node_id:
                    pending_dynamic_nodes.add(node_id)
            writer.emit(translated)

        elif mode == "updates":
            if "__interrupt__" in payload:
                interrupt_payload = payload["__interrupt__"]
                continue
            for translated in _translate_updates(
                payload, run_id, seen_static, last_static_node,
                pending_dynamic_nodes, running_dynamic_nodes,
            ):
                writer.emit(translated)

    if interrupt_payload is not None:
        raise _GraphPaused(interrupt_payload)


async def start_run(
    *,
    run_id: str,
    domain: str,
    hitl_mode: str,
    writer: EventWriter,
) -> RunHandle:
    """Spawn the asyncio task that drives the graph for `run_id` and
    returns a handle the HTTP layer can use to resume after human
    approval."""
    register_writer(writer)

    config: RunnableConfig = {
        "configurable": {
            "thread_id": run_id,
            "run_id": run_id,
        }
    }

    handle = RunHandle(run_id, task=None)
    _handles[run_id] = handle

    async def _drive() -> None:
        seen_static: set[str] = set()
        last_static_node: list[str | None] = [None]
        pending_dynamic_nodes: set[str] = set()
        running_dynamic_nodes: set[str] = set()
        initial_input: dict[str, Any] = {
            "domain": domain,
            "hitl_mode": hitl_mode,
        }

        # Per contract.md §"Event schema", static nodes are sent
        # once at run start. Emit them up front so the
        # node_added -> node_status ordering guarantee holds for
        # static nodes too (the lifecycle translator in
        # _drain_iteration will only emit node_added for static
        # nodes when they first appear in the updates stream —
        # which doesn't happen for nodes that call interrupt()
        # before producing output, like human_approval).
        for static_name in STATIC_NODE_NAMES:
            writer.emit(_make_envelope(
                "node_added",
                run_id,
                node_id=static_name,
                node_type=static_name,
                parent_id=STATIC_NODE_PARENTS.get(static_name),
                label=STATIC_NODE_LABELS.get(static_name, static_name),
                opportunity_id=None,
            ))
            seen_static.add(static_name)

        try:
            # First pass.
            try:
                await _drain_iteration(
                    config, initial_input, run_id, writer,
                    seen_static, last_static_node,
                    pending_dynamic_nodes, running_dynamic_nodes,
                )
            except _GraphPaused:
                pass  # Fall through to resume handling below.
            else:
                # Graph reached END cleanly. Mark last node complete.
                if last_static_node[0] and last_static_node[0] != "__end__":
                    writer.emit(
                        _make_envelope(
                            "node_status",
                            run_id,
                            node_id=last_static_node[0],
                            status="completed",
                            summary=None,
                        )
                    )
                return

            # Park until /resume.
            payload = await handle.wait_for_resume()

            # Second pass.
            try:
                await _drain_iteration(
                    config, Command(resume=payload), run_id, writer,
                    seen_static, last_static_node,
                    pending_dynamic_nodes, running_dynamic_nodes,
                )
            except _GraphPaused:
                log.warning(
                    "run %s: graph paused again after first resume; ending",
                    run_id,
                )

            if last_static_node[0] and last_static_node[0] != "__end__":
                writer.emit(
                    _make_envelope(
                        "node_status",
                        run_id,
                        node_id=last_static_node[0],
                        status="completed",
                        summary=None,
                    )
                )

        except Exception as exc:
            log.exception("run %s failed", run_id)
            writer.emit(
                _make_envelope(
                    "node_status",
                    run_id,
                    node_id=run_id,
                    status="error",
                    summary=str(exc)[:200],
                )
            )
        finally:
            # Always emit a terminal run_completed so the frontend has
            # a clean sentinel even if the graph short-circuited.
            writer.emit(_make_envelope("run_completed", run_id))
            writer.close()
            unregister_writer(run_id)
            _handles.pop(run_id, None)

    handle.task = asyncio.create_task(_drive(), name=f"run-{run_id}")
    return handle
