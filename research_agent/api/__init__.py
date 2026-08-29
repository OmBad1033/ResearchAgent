"""
Event-emission helpers for the FastAPI bridge.

This module exposes a single `emit_event` function that graph nodes call
via LangGraph's `get_stream_writer()`. Every event emitted here matches
one of the four shapes in CONTRACT.md:

    - node_added
    - node_status
    - edge_active
    - run_completed

The runner in api/runner.py reads these via `stream_mode="custom"` and
forwards them to the WebSocket. Keeping the emitter tiny means nodes
don't import FastAPI / WebSocket code — the bridge is the only thing
that knows about the network.

`run_id` is supplied at graph invocation time via
config["configurable"]["run_id"] (in addition to the existing
`thread_id`). Nodes don't pass it explicitly; the emitter reads it from
the same config.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def now_iso() -> str:
    """UTC timestamp in ISO 8601, second precision, trailing 'Z'."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _envelope(event_type: str, run_id: str, **fields: Any) -> dict[str, Any]:
    """Build a CONTRACT.md-shaped event dict with timestamp + run_id."""
    return {
        "type": event_type,
        "run_id": run_id,
        "timestamp": now_iso(),
        **fields,
    }


def emit_node_added(
    writer,
    *,
    run_id: str,
    node_id: str,
    node_type: str,
    parent_id: str | None,
    label: str,
    opportunity_id: str | None = None,
) -> None:
    """Emit a `node_added` event. Call this BEFORE any node_status for the
    same node_id, per CONTRACT.md's ordering guarantee."""
    writer(
        _envelope(
            "node_added",
            run_id,
            node_id=node_id,
            node_type=node_type,
            parent_id=parent_id,
            label=label,
            opportunity_id=opportunity_id,
        )
    )


def emit_node_status(
    writer,
    *,
    run_id: str,
    node_id: str,
    status: str,
    summary: str | None = None,
) -> None:
    """Emit a `node_status` event. `status` must be one of:
    idle | running | completed | error."""
    writer(
        _envelope(
            "node_status",
            run_id,
            node_id=node_id,
            status=status,
            summary=summary,
        )
    )


def emit_edge_active(
    writer,
    *,
    run_id: str,
    from_node: str,
    to_node: str,
) -> None:
    """Emit an `edge_active` event. Used by the manager to mark which
    next-step decision was just made."""
    writer(
        _envelope(
            "edge_active",
            run_id,
            **{"from": from_node, "to": to_node},
        )
    )


def emit_run_completed(writer, *, run_id: str) -> None:
    """Emit the terminal `run_completed` event. Called once per run after
    the synthesis node finishes (or after the graph otherwise reaches END)."""
    writer(_envelope("run_completed", run_id))


def resolve_run_id_from_writer(writer) -> str:
    """Best-effort run_id resolution. The runner stamps run_id on the
    payload before forwarding to the websocket, so even a node that
    can't reach config (e.g. running in a unit test without a config)
    will get its events tagged with the right run_id on the way out.

    Returns "unknown" as a last-resort fallback. Prefer resolving via
    `get_config()` inside the node and passing the explicit value to
    emit_* so this fallback is never observed in production."""
    return "unknown"
