# Agent 1 — Backend — Context

You are building the FastAPI bridge that streams events from an existing
LangGraph research agent to a frontend, per `backend.md`.

**Read `CONTRACT.md` first — it is the exact interface you must implement.**
The frontend is being built in parallel by a separate agent against that same
contract, using a mock event stream. Your job is to make the real backend
emit output indistinguishable from that mock. Any deviation from
`CONTRACT.md`'s event shapes, field names, or the ordering guarantee will
break the merge even if your code otherwise "works."

## Why the frontend needs what it needs (so you don't cut corners on fields)

- **`node_added` before any `node_status`** — the frontend does not create
  nodes reactively on first status update; it only updates existing nodes.
  If you emit a `node_status` for a `deep_dive_opp_3` node before its
  `node_added`, that event is silently dropped on the frontend side and the
  node will appear stuck at `idle` forever. Emit `node_added` as the very
  first thing inside `deep_dive_subagent` / `worth_it_subagent`, before any
  other writer call.
- **`parent_id` on `node_added`** — the frontend uses this to draw the edge
  from the stage node to the new sub-agent node and to run auto-layout. If
  this is `null` or wrong for a dynamic node, that node renders disconnected
  from the graph.
- **`summary` on `node_status`** — this is displayed directly under the node
  label in the UI as the "what is it doing right now" line. Keep it short
  (under ~50 chars) and update it at meaningful checkpoints (e.g. "Searching
  for existing solutions" → "Summarizing findings"), not just at start/end,
  or the graph will look frozen during long-running nodes.
- **`edge_active` on every `manager` decision** — this is the only signal
  the frontend uses to animate which path was just taken. If you only emit
  `node_status` for `manager` itself, the frontend graph will show the
  manager as "running" but give no indication of where execution is headed —
  emit `edge_active` right when `manager` decides its `Command(goto=...)`,
  before returning.
- **History endpoint fields (`reasoning`, `worth_it_verdict`,
  `worth_it_reasoning`)** — these populate a side panel that opens on node
  click. Null is fine and handled gracefully by the frontend; missing keys
  entirely are not — always return the full shape from `CONTRACT.md` even
  if some fields are null.

## Your scope

- Implement everything in `backend.md`.
- Do not build any frontend code, mock UI, or make assumptions about how
  events are rendered — that's Agent 2's job and is already contract-bound.
- Test independently: write a small `websockets` client script that connects
  to `/ws/{run_id}`, sends the session-start frame from `CONTRACT.md`, and
  prints every event received. Verify the sequence and shapes match
  `CONTRACT.md` exactly before considering your work mergeable.

## Merge step (you'll do this together with Agent 2 at the end)

Follow the "Merge checklist" at the bottom of `CONTRACT.md`. Your specific
responsibility there: confirm CORS is configured for the frontend's actual
dev port, and be the one running the end-to-end test since you own the
process that produces the real event sequence.

---

## Contract implementation notes (running log)

Decisions and open questions as I implement. Newest at the bottom.

### D1. Where `edge_active` actually comes from

The plan says "emit `edge_active` from `manager` before it returns its
`Command(goto=...)`." In the current graph (`graph/nodes/manager.py`),
the manager does NOT return a Command — it returns `{}`. Routing is done
by `route_from_manager`, a pure conditional-edge function. So the
`writer(...)` call for `edge_active` lives inside `route_from_manager`
(and in the synthesis-end fallback) rather than inside `manager_node`.

### D2. `reasoning` on the history endpoint

`CONTRACT.md` asks for `reasoning: string | null` on the history
endpoint. The current `Opportunity` state does NOT have a separate
`reasoning` field — it has `deep_dive_notes` (which contains trend
analysis + existing solutions) and `worth_it_reasoning`. Until we add
an explicit `reasoning` channel, the history endpoint will return
`reasoning: None` for all nodes. Flagging this as an open contract
question rather than inventing a field.

### D3. Existing bug blocks end-to-end test

`graph/nodes/ai_approval.py::_strip_code_fences` calls `.strip()` on
the LLM response without guarding against `None`. When the OpenRouter
client returns `None` (which it does in some failure modes), the graph
crashes inside `ai_approval` before reaching the part of the run the
bridge needs to observe. Patched defensively (treat `None` as
"approve nothing") to unblock the smoke test. Pre-existing bug — flag
for review.

### D4. Threading model

Per-run asyncio task owns the LangGraph stream. Each WebSocket connection
hands its `run_id` to the runner, awaits completion, and forwards events
as they arrive. WebSocket handler stays thin; runner is unit-testable
without a socket.

### D5. Event ordering guarantee

`node_added` before `node_status` for dynamic sub-agents is enforced by
emitting the `node_added` writer call as the very first line of
`deep_dive_subagent` / `worth_it_subagent`, before any other side
effect. This matches what `contract.md` requires the frontend to assume.

### D6. CORS

`CORSMiddleware` is configured with `allow_origin_regex` matching
`http(s)://localhost(:port)` and `http(s)://127.0.0.1(:port)`. The
regex form is required because starlette's `allow_origins=[...]` with
`allow_credentials=True` rejects requests whose Origin isn't in the
exact list — including browser WebSocket upgrade requests, which DO
carry an Origin header. Note that uvicorn binds to `0.0.0.0` (not
`127.0.0.1`) because macOS resolves `localhost` to `::1` first, and a
loopback-only listener silently rejects the IPv6 path.

### D7. Streaming API choice in langgraph 1.2

The plan (`backend.md` section 3) suggested `astream_events(version="v2")`
as the single driver. That doesn't work for our case: langgraph 1.2's
`astream_events` does NOT surface payloads written via `get_stream_writer()`
as `on_custom_event`. So I switched to `astream(..., stream_mode=["custom", "updates"])`,
which yields both writer payloads (parent-level only) and per-node state
updates from a single driver.

### D8. Sub-graph custom event propagation

Related to D7: custom payloads from inside a sub-graph's inner nodes
(e.g. `deep_dive_subagent` running inside the `deep_dive` sub-graph)
do NOT propagate to the parent's `astream(stream_mode="custom")`.
Mitigation: the manager knows which per-instance IDs it will dispatch
(via `_build_deep_dive_sends` / `_build_worth_it_sends`), so it emits
`node_added(deep_dive_opp_X)` for each one via `get_stream_writer()`
BEFORE the Send fires. The runner tracks these in
`pending_dynamic_nodes` and synthesizes `running`/`completed` events
for each instance when the wrapper subgraph (`deep_dive`) appears in
`updates` and when the next superstep starts. This matches the
frontend's per-instance model without requiring sub-graph writer
calls to propagate.

Per-instance mid-run `summary` updates (e.g. "Searching for existing
solutions" → "Summarizing findings") currently do NOT reach the
frontend for dynamic sub-agents. If you want them, the fix is to
either (a) move those writer calls into the manager-side dispatch
orchestration, or (b) introduce a state-channel (`messages` with
`add_messages`) that the runner translates to events. Filed as a
known limitation rather than a blocker for the POC.

### D9. `interrupt()` surfaces as `__interrupt__` update, not exception

The plan implied `app.astream` raises `GraphInterrupt` at the
`interrupt()` call site. In langgraph 1.2, astream with the checkpointer
attached yields a normal `updates` dict with `__interrupt__` and then
the iterator ends. Driver catches this via a `_GraphPaused` internal
sentinel and parks for resume.
