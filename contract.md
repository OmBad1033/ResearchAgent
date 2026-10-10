# Shared Contract — Backend ↔ Frontend

Both agents must treat this file as the source of truth. If either side needs
to deviate, update this file first, in a way the other agent will also see —
don't let the two implementations drift silently.

## Ports & URLs (local dev)

- Backend (FastAPI): `http://localhost:8000`
- WebSocket endpoint: `ws://localhost:8000/ws/{run_id}`
- History REST endpoint: `GET http://localhost:8000/runs/{run_id}/nodes/{node_id}/history`
- HITL resume endpoint: `POST http://localhost:8000/runs/{run_id}/resume`
- Frontend dev server: `http://localhost:5173` (Vite default)
- Backend must enable CORS for `http://localhost:5173`.

## Node ID convention

- Static nodes use their literal graph node name as `node_id`:
  `manager`, `opportunity_discovery`, `approval_router`, `human_approval`,
  `ai_approval`, `orchestration`, `synthesis`.
- Dynamic sub-agent nodes use `{stage}_{opportunity_id}`, e.g. `deep_dive_opp_3`,
  `worth_it_opp_3`. This is the join key between the two `orchestration` passes
  for the same opportunity — the frontend may use it to visually link a
  `deep_dive_opp_3` node to the later `worth_it_opp_3` node.

## Event schema (WebSocket, backend → frontend)

Every message is one JSON object with a `type` field. No batching — one event
per message.

```jsonc
// 1. A node instance now exists (static nodes: sent once at run start;
//    dynamic sub-agents: sent when manager's Send() dispatches them)
{
  "type": "node_added",
  "run_id": "string",
  "node_id": "string",
  "node_type": "manager" | "opportunity_discovery" | "approval_router" |
               "human_approval" | "ai_approval" | "deep_dive_subagent" |
               "orchestration" | "worth_it_subagent" | "synthesis",
  "parent_id": "string | null",   // which node/stage to draw the edge from
  "label": "string",              // human-readable, shown on the node
  "opportunity_id": "string | null",
  "timestamp": "ISO 8601 string"
}

// 2. A node's status changed
{
  "type": "node_status",
  "run_id": "string",
  "node_id": "string",
  "status": "idle" | "running" | "completed" | "error",
  "summary": "string | null",     // short human-readable current action
  "timestamp": "ISO 8601 string"
}

// 3. Manager picked a next step — drives the animated/active edge
{
  "type": "edge_active",
  "run_id": "string",
  "from": "string",   // node_id
  "to": "string",     // node_id
  "timestamp": "ISO 8601 string"
}

// 4. Run finished
{
  "type": "run_completed",
  "run_id": "string",
  "timestamp": "ISO 8601 string"
}
```

Ordering guarantee the backend must uphold: a `node_added` for a given
`node_id` is always sent before any `node_status` for that same `node_id`.
The frontend is allowed to assume this and will not defensively create a
missing node on `node_status`.

## REST: node history

`GET /runs/{run_id}/nodes/{node_id}/history` → `200 OK`

```jsonc
{
  "node_id": "string",
  "opportunity": { "...Opportunity fields..." } | null,
  "reasoning": "string | null",
  "worth_it_verdict": "string | null",
  "worth_it_reasoning": "string | null"
}
```

Static nodes without an associated opportunity (`manager`,
`opportunity_discovery`, etc.) may return `opportunity: null` and just the
fields that make sense — frontend renders whatever is non-null.

## REST: resume after human approval

`POST /runs/{run_id}/resume`

Request body:
```jsonc
{ "approved_opportunity_ids": ["opp_1", "opp_3"] }
```
Response: `202 Accepted`, no body required. The websocket stream continues
with subsequent events after this call.

## Session start

The frontend opens the websocket first, then sends one JSON message as the
first frame to kick off the run:

```jsonc
{
  "domain": "string",
  "hitl_mode": "human" | "ai",
  "report_focus": "string?",     // optional steer for synthesis (e.g. "B2B SaaS", "early-stage")
  "max_opportunities": "int?"    // optional cap on deep_dive / worth_it fan-out count
}
```

All fields except `domain` are optional. The backend must not reject the frame
for missing optional fields and must ignore unknown fields gracefully. The
backend does not start executing the graph until it receives this frame.

## REST: run opportunities

`GET /runs/{run_id}/opportunities` → `200 OK`

```jsonc
{
  "opportunities": [
    {
      "id": "string",
      "title": "string",
      "description": "string"
    }
  ]
}
```

Returns the list of discovered opportunities for a run. Used by the
frontend's human-approval UI to render checkboxes so the user can
choose which opportunities to deep-dive before POSTing `/resume`.

If the run has no state (server restarted, no checkpoint for this
thread_id), returns `{ "opportunities": [] }` with status 200 — the
frontend renders an empty-state hint.

## REST: run report

`GET /runs/{run_id}/report` → `200 OK`

```jsonc
{
  "markdown": "string",            // full synthesis output as markdown
  "generated_at": "ISO 8601 string"
}
```

Returns `404` if the run hasn't reached `synthesis` yet. Frontend polls this
endpoint (or shows a loading state) until it returns 200 after `run_completed`.

The report lives on its own endpoint rather than on `synthesis/history` so the
report payload doesn't bloat the per-node history shape and so Agent 1 can
evolve the report path (streaming, regeneration) without touching history.

## REST: solution design (Architect Agent via A2A)

`POST /runs/{run_id}/nodes/{node_id}/design` → `200 OK`

```jsonc
{
  "design": {
    "proposed_stack": ["string"],
    "components": ["string"],
    "data_flow_summary": "string",
    "deployment_target": "string",
    "build_effort_estimate": "string",
    "risks": ["string"],
    "open_questions": ["string"]
  }
}
```

Request body: `{}` normally — the opportunity, domain, and research notes
come from this run's own checkpointer state. Optional overrides
`{ "domain": "string?", "research_notes": "string?" }` replace the
state-derived values before forwarding.

Only `deep_dive_{opp}` / `worth_it_{opp}` node ids are valid. Returns
`404` for static nodes, unknown node ids, or runs with no checkpoint
state. Returns `502` when the Architect Agent is unreachable, returns a
failed task, or returns no data artifact — the `detail` string carries
the underlying A2A error.

The backend implements this as a true server-to-server A2A call: it builds
a `DesignRequest` DataPart from run state and POSTs `SendMessage` JSON-RPC
to the Architect Agent (`ARCHITECT_AGENT_URL`, default
`http://127.0.0.1:8002`, `http://architect:8002` in docker-compose), then
returns the `SolutionDesign` artifact verbatim. The frontend's HistoryDrawer
shows a "generate design" button for dynamic nodes that hits this endpoint.

## What each agent builds against while working independently

- **Backend agent**: no frontend dependency at all — test with a raw
  `websockets` client script per `backend.md`.
- **Frontend agent**: build against a **mock event emitter** that plays back
  a canned sequence of events matching this schema exactly (see
  `agent2_frontend_context.md`). Do not hand-wave the shape "close enough" —
  copy the JSON examples above verbatim into the mock.

## Merge checklist

- [ ] Point frontend's `useGraphSocket` at the real backend URL instead of the mock.
- [ ] Confirm `node_type` values emitted by backend match the set frontend switches on.
- [ ] Confirm CORS allows the frontend's actual dev port.
- [ ] Run one full graph execution end-to-end and diff observed events against this file.
- [ ] Verify `node_added` always precedes `node_status` for the same `node_id` (see ordering guarantee above) — this is the most likely real bug.
- [ ] Confirm backend reads `report_focus` and `max_opportunities` from session-start frame (or ignores them gracefully if not implemented).
- [ ] Confirm `GET /runs/{run_id}/report` is implemented and returns the contract shape.
- [ ] Confirm `GET /runs/{run_id}/opportunities` is implemented and the human-approval UI can POST `/resume` with the chosen ids.
- [ ] Confirm `POST /runs/{run_id}/nodes/{node_id}/design` returns a `SolutionDesign` for a dynamic node (Architect reachable) and 404/502 otherwise.