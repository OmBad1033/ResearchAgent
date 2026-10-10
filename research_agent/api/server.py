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
    POST /runs/{run_id}/nodes/{node_id}/design
                                  Ask the Architect Agent (A2A) for a
                                  solution design for one opportunity.
                                  Returns `{design: SolutionDesign}`.

Run with:
    uvicorn research_agent.api.server:app --reload --port 8000
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import httpx

from graph.builder import app as langgraph_app
from api.event_writer import EventWriter, get_writer
from api.runner import (
    get_handle,
    start_run,
)


log = logging.getLogger(__name__)


# Architect Agent (A2A) base URL. Local dev default matches
# `python -m architect_agent.server --port 8002`. In docker-compose the
# backend reaches it as http://architect:8002 — set via environment.
ARCHITECT_AGENT_URL = os.environ.get("ARCHITECT_AGENT_URL", "http://127.0.0.1:8002")
ARCHITECT_CALL_TIMEOUT_S = float(os.environ.get("ARCHITECT_CALL_TIMEOUT_S", "300"))
A2A_VERSION_HEADER = "1.0"


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


class DesignRequestBody(BaseModel):
    """Optional overrides for the Architect call.

    Everything else (opportunity, domain, research notes) comes from the
    run's own checkpointer state — the frontend only sends tweaks.
    """

    domain: str | None = None
    research_notes: str | None = None


def _get_run_state(run_id: str) -> dict[str, Any]:
    """Read the LangGraph checkpointer state for a run or raise 404."""
    config = {"configurable": {"thread_id": run_id}}
    try:
        snapshot = langgraph_app.get_state(config)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Could not read state for run_id={run_id!r}: {exc}",
        )
    if snapshot is None or not snapshot.values:
        raise HTTPException(
            status_code=404,
            detail=f"No state found for run_id={run_id!r}",
        )
    return snapshot.values


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
    try:
        state = _get_run_state(run_id)
    except HTTPException as exc:
        # No state yet (e.g. run just started, snapshot empty) — match
        # the historical behaviour: static shape with nulls, not 404.
        if exc.status_code == 404:
            return {
                "node_id": node_id,
                "opportunity": None,
                "reasoning": None,
                "worth_it_verdict": None,
                "worth_it_reasoning": None,
            }
        raise
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


def _a2a_send_message(base_url: str, parts: list[dict[str, Any]]) -> dict[str, Any]:
    """Send one A2A `SendMessage` JSON-RPC call, return the terminal task.

    Plain httpx + JSON-RPC (same shape as orchestrator/a2a_client.py).
    Kept local so the :8000 bridge has no import dependency on the
    orchestrator package.
    """
    body = {
        "jsonrpc": "2.0",
        "id": "req-" + uuid.uuid4().hex[:8],
        "method": "SendMessage",
        "params": {
            "message": {
                "messageId": "m-" + uuid.uuid4().hex[:8],
                "role": "ROLE_USER",
                "parts": parts,
            }
        },
    }
    try:
        resp = httpx.post(
            base_url.rstrip("/") + "/",
            json=body,
            headers={"A2A-Version": A2A_VERSION_HEADER, "Content-Type": "application/json"},
            timeout=ARCHITECT_CALL_TIMEOUT_S,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Architect Agent unreachable at {base_url}: {exc}",
        )
    try:
        envelope = resp.json()
    except ValueError:
        raise HTTPException(
            status_code=502,
            detail=f"Architect Agent returned non-JSON (HTTP {resp.status_code})",
        )
    if "error" in envelope:
        raise HTTPException(
            status_code=502,
            detail=f"Architect Agent error: {envelope['error']}",
        )
    task = (envelope.get("result") or {}).get("task")
    if not isinstance(task, dict):
        raise HTTPException(
            status_code=502,
            detail=f"Architect Agent returned no task: {envelope}",
        )
    return task


def _a2a_task_text(task: dict[str, Any]) -> str:
    """Best-effort human-readable text from a task's status message."""
    status = task.get("status") or {}
    msg = status.get("message") or {}
    texts = [
        p.get("text", "")
        for p in (msg.get("parts") or [])
        if isinstance(p, dict) and p.get("text")
    ]
    return "\n".join(texts) or f"task state={status.get('state')}"


def _a2a_task_data(task: dict[str, Any]) -> dict[str, Any]:
    """First DataPart dict from a task's artifacts, or raise 502."""
    for artifact in task.get("artifacts") or []:
        if not isinstance(artifact, dict):
            continue
        for part in artifact.get("parts") or []:
            if isinstance(part, dict) and isinstance(part.get("data"), dict):
                return part["data"]
    raise HTTPException(
        status_code=502,
        detail=f"Architect Agent returned no data artifact: {_a2a_task_text(task)}",
    )


@app.post("/runs/{run_id}/nodes/{node_id}/design")
async def node_design_endpoint(
    run_id: str, node_id: str, body: DesignRequestBody | None = None
) -> dict[str, Any]:
    """Ask the Architect Agent (A2A) to design a solution for one opportunity.

    The opportunity + domain + research notes come from this run's own
    checkpointer state; the request body only carries optional overrides.
    The backend forwards them as an A2A `SendMessage` DataPart to the
    Architect Agent and returns the resulting `SolutionDesign` verbatim.

    Responses:
      - 200 `{design: SolutionDesign}` on success.
      - 404 if the run/node has no opportunity (bad run_id, unknown
        node_id, static node, or server restarted and checkpoint lost).
      - 502 if the Architect Agent is unreachable, returns a failed
        task, or returns no data artifact.
    """
    state = _get_run_state(run_id)
    opportunities: dict[str, Any] = state.get("opportunities") or {}
    opp_id = _node_id_to_opportunity_id(node_id)
    opportunity = opportunities.get(opp_id) if opp_id else None
    if opportunity is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No opportunity for node_id={node_id!r} in run {run_id!r}. "
                "Design is only available for deep_dive_/worth_it_ nodes "
                "whose opportunity exists in this run's state."
            ),
        )

    design_request = {
        "opportunity": opportunity,
        "domain": (body.domain if body and body.domain is not None else state.get("domain", "")),
        "research_notes": (
            body.research_notes
            if body and body.research_notes is not None
            else (opportunity.get("deep_dive_notes") or "")
        ),
    }
    task = await asyncio.to_thread(
        _a2a_send_message, ARCHITECT_AGENT_URL, [{"data": design_request}]
    )
    task_state = ((task.get("status") or {}).get("state")) or ""
    if task_state != "TASK_STATE_COMPLETED":
        raise HTTPException(
            status_code=502,
            detail=f"Architect Agent task {task_state}: {_a2a_task_text(task)}",
        )
    return {"design": _a2a_task_data(task)}
