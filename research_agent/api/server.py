"""
FastAPI server — exposes the LangGraph research agent over WebSocket
and REST per CONTRACT.md.

Endpoints:
    WS  /ws/{run_id}              Stream events for one run. First
                                  client frame must be the session
                                  start message ({"domain", "hitl_mode"}).
    POST /runs/{run_id}/resume    Continue a paused run (human mode).
                                  Body: {"approved_opportunity_ids": [...]}.
    GET  /runs/{run_id}/nodes/{node_id}/history
                                  REST detail for a single node. Returns
                                  shape per CONTRACT.md.

Run with:
    uvicorn research_agent.api.server:app --reload --port 8000
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from graph.builder import app as langgraph_app
from api.event_writer import EventWriter, get_writer
from api.runner import (
    get_handle,
    start_run,
)


log = logging.getLogger(__name__)


app = FastAPI(title="Research Agent Bridge")

# CORS — see D6 in backend_plan.md. We use allow_origin_regex so the
# WebSocket handshake works from non-browser clients (raw `websockets`
# lib without an Origin header) as well as the React dev server on
# :5173. Tighten this at merge time if you expose this beyond localhost.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ResumeRequest(BaseModel):
    approved_opportunity_ids: list[str]


def _node_id_to_opportunity_id(node_id: str) -> str | None:
    """Reverse the `{stage}_{opportunity_id}` convention for dynamic
    sub-agent node IDs. Returns None for static nodes."""
    if node_id.startswith("deep_dive_") or node_id.startswith("worth_it_"):
        parts = node_id.split("_", 2)
        if len(parts) == 3:
            return parts[2]
    return None


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.websocket("/ws/{run_id}")
async def ws_endpoint(websocket: WebSocket, run_id: str) -> None:
    """One WebSocket per run.

    Protocol:
        1. Client connects to /ws/{run_id}.
        2. Client sends ONE JSON frame: {"domain": "...", "hitl_mode": "..."}.
        3. Server streams CONTRACT.md events back as they arrive.
        4. Stream ends with a run_completed event, after which the
           server closes the socket.

    Concurrent connections for the same run_id are not supported: the
    second connection will simply attach to the same EventWriter and
    receive the same events. For the POC, we assume one client per run.
    """
    print(f"[ws_endpoint] new connection: run_id={run_id!r} client={websocket.client}", flush=True)
    await websocket.accept()

    # The client may connect-then-immediately-close before sending its
    # start frame (e.g. React's StrictMode double-invokes effects, the
    # first mount is torn down before its WS can send). That's expected
    # and not an error — treat it as a clean cancellation.
    try:
        start_msg = await websocket.receive_json()
    except WebSocketDisconnect:
        print(f"[ws_endpoint] client closed before sending start frame: run_id={run_id!r}", flush=True)
        return

    try:
        domain = start_msg.get("domain")
        hitl_mode = start_msg.get("hitl_mode")
        if not domain or hitl_mode not in ("human", "ai"):
            await websocket.send_json(
                {
                    "type": "error",
                    "message": (
                        "First frame must be {\"domain\": str, "
                        "\"hitl_mode\": \"human\"|\"ai\"}"
                    ),
                }
            )
            await websocket.close(code=1008)
            return

        # 2. Find or start the run.
        writer = get_writer(run_id)
        if writer is None:
            writer = EventWriter(run_id)
            await start_run(
                run_id=run_id,
                domain=domain,
                hitl_mode=hitl_mode,
                writer=writer,
            )

        # 3. Forward events to the client until the run closes.
        try:
            async for event in writer.subscribe():
                await websocket.send_json(event)
        except WebSocketDisconnect:
            # Client went away. The runner keeps going — a future
            # reconnect (e.g. for human resume) will re-subscribe via
            # a fresh /ws call, but events that fired during the
            # disconnect are NOT replayed.
            pass

    except WebSocketDisconnect:
        # Mid-stream disconnect. Same as above — silent cleanup.
        print(f"[ws_endpoint] client disconnected mid-stream: run_id={run_id!r}", flush=True)
    except Exception as exc:
        log.exception("ws_endpoint failed for run %s", run_id)
        try:
            await websocket.send_json({"type": "error", "message": str(exc)})
        except Exception:
            pass


@app.post("/runs/{run_id}/resume", status_code=202)
async def resume_endpoint(run_id: str, body: ResumeRequest) -> dict[str, Any]:
    """Resume a run paused at human_approval.

    Body: {"approved_opportunity_ids": ["opp_1", "opp_3"]} OR
          ["__all__"] to approve everything.
    Response: 202 Accepted. The websocket stream continues with the
    post-resume events.
    """
    handle = get_handle(run_id)
    if handle is None:
        # No active run. Two options:
        # - Run is finished (terminal state already reached)
        # - Run ID is bogus
        # - Run completed without a checkpoint on this server (the
        #   InMemorySaver is per-process; if this server restarted,
        #   we can't resume from another process)
        raise HTTPException(
            status_code=404,
            detail=f"No active run found for run_id={run_id!r}",
        )

    approved_ids = body.approved_opportunity_ids
    if "__all__" in approved_ids:
        # We don't have access to the discovered opportunities here
        # without round-tripping to the checkpointer. The runner +
        # human_approval normalize "__all__" inside the node, but the
        # bridge interface per CONTRACT.md passes concrete ids. So
        # translate "__all__" into the wake-up payload that
        # human_approval understands directly.
        payload = {"approved_ids": ["__all__"]}
    else:
        payload = {"approved_ids": approved_ids}

    handle.request_resume(payload)
    return {"status": "accepted", "run_id": run_id, "approved": approved_ids}


@app.get("/runs/{run_id}/nodes/{node_id}/history")
async def node_history_endpoint(run_id: str, node_id: str) -> dict[str, Any]:
    """Return the CONTRACT.md-shaped history for a single node.

    Source of truth: the graph's checkpointer. For dynamic sub-agent
    nodes, we extract the relevant Opportunity from state. For static
    nodes, we return the opportunity field as null and the reasoning/
    verdict fields as null too (see D2 in backend_plan.md — there's no
    separate `reasoning` channel on Opportunity today).
    """
    config = {"configurable": {"thread_id": run_id}}
    try:
        snapshot = langgraph_app.get_state(config)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Could not read state for run_id={run_id!r}: {exc}",
        )

    state = snapshot.values if snapshot else {}
    opportunities: dict[str, Any] = state.get("opportunities") or {}

    opp_id = _node_id_to_opportunity_id(node_id)
    opportunity = opportunities.get(opp_id) if opp_id else None

    if opportunity is None:
        # Static node fall-through. Per CONTRACT.md, opportunity is
        # allowed to be null for static nodes.
        return {
            "node_id": node_id,
            "opportunity": None,
            "reasoning": None,
            "worth_it_verdict": None,
            "worth_it_reasoning": None,
        }

    return {
        "node_id": node_id,
        "opportunity": opportunity,
        "reasoning": opportunity.get("deep_dive_notes"),  # see D2
        "worth_it_verdict": opportunity.get("worth_it_verdict") or None,
        "worth_it_reasoning": opportunity.get("worth_it_reasoning") or None,
    }


@app.get("/runs/{run_id}/opportunities")
async def run_opportunities_endpoint(run_id: str) -> dict[str, Any]:
    """Return the list of discovered opportunities for the run.

    Used by the frontend's human-approval UI to render checkboxes for
    the user to choose which opportunities to deep-dive. Each item
    carries the minimum the UI needs to render a label and identify
    the opportunity for the /resume call.
    """
    config = {"configurable": {"thread_id": run_id}}
    try:
        snapshot = langgraph_app.get_state(config)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Could not read state for run_id={run_id!r}: {exc}",
        )

    if snapshot is None:
        return {"opportunities": []}

    state = snapshot.values or {}
    opportunities: dict[str, Any] = state.get("opportunities") or {}

    return {
        "opportunities": [
            {
                "id": opp.get("id"),
                "title": opp.get("title"),
                "description": opp.get("description"),
            }
            for opp in opportunities.values()
            if opp.get("id")
        ]
    }


@app.get("/runs/{run_id}/report")
async def run_report_endpoint(run_id: str) -> dict[str, Any]:
    """Return the synthesis report markdown for a run.

    Per contract.md §"REST: run report":
      - 200 with `{markdown, generated_at}` if synthesis has run.
      - 404 if the run hasn't reached synthesis yet (frontend polls).

    `generated_at` is the wall-clock timestamp when synthesis
    completed; we approximate it with the snapshot's checkpoint
    metadata. If the run state was lost (server restarted, no
    InMemorySaver checkpoint for this run_id) we 404 — the
    frontend's polling loop will surface that to the user.
    """
    config = {"configurable": {"thread_id": run_id}}
    try:
        snapshot = langgraph_app.get_state(config)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Could not read state for run_id={run_id!r}: {exc}",
        )

    if snapshot is None:
        raise HTTPException(
            status_code=404,
            detail=f"No state found for run_id={run_id!r}",
        )

    state = snapshot.values or {}
    markdown = state.get("final_report")
    if not markdown:
        raise HTTPException(
            status_code=404,
            detail=f"Synthesis hasn't completed for run_id={run_id!r}",
        )

    # Prefer the checkpoint's wall-clock time if available; fall
    # back to "now" if the checkpointer doesn't track one. The
    # frontend just renders this as a human-readable timestamp.
    generated_at = None
    if snapshot.metadata and "created_at" in snapshot.metadata:
        generated_at = snapshot.metadata["created_at"]
    if generated_at is None:
        from api import now_iso
        generated_at = now_iso()

    return {"markdown": markdown, "generated_at": generated_at}
