# Agent 2 — Frontend — Context

You are building the React Flow graph UI per `frontend.md`, consuming events
from a backend that is being built in parallel by a separate agent.

**Read `CONTRACT.md` first — it is the exact interface the backend will
implement.** You will not have a working backend to test against for most of
your build. Build against a mock event emitter that reproduces this contract
exactly, so that swapping the mock for the real WebSocket at merge time is a
one-line change (just the URL), not a rewrite.

## Build a mock that matches the contract exactly

Do not invent a simplified or "close enough" event shape for convenience —
copy the JSON examples in `CONTRACT.md` verbatim. Write a mock emitter that
plays back a realistic sequence, e.g.:

```
node_added(manager) → node_status(manager, running) → edge_active(manager→opportunity_discovery)
→ node_added(opportunity_discovery) → node_status(opportunity_discovery, running) → node_status(opportunity_discovery, completed)
→ edge_active(manager→approval_router) → node_status(approval_router, running/completed)
→ edge_active(approval_router→ai_approval) → node_status(ai_approval, running/completed)
→ edge_active(manager→deep_dive)
→ node_added(deep_dive_opp_1, parent_id=deep_dive) → node_status(deep_dive_opp_1, running)
→ node_added(deep_dive_opp_2, parent_id=deep_dive) → node_status(deep_dive_opp_2, running)
   ... (fire 2-3 of these in parallel to rehearse the "dynamic nodes appearing
        concurrently + auto-layout reflow" case, since that's the trickiest
        part of your build)
→ node_status(deep_dive_opp_1, completed) → node_status(deep_dive_opp_2, completed)
→ node_status(orchestration, running/completed)
→ edge_active(manager→worth_it) → node_added(worth_it_opp_1, ...) → ...
→ edge_active(manager→synthesis) → node_status(synthesis, running/completed)
→ run_completed
```

Gate this behind an env var or a `?mock=true` query param so it's trivial to
switch off at merge time.

## Why the backend's shape is the way it is (context, not action items)

- **`node_id` for dynamic nodes is `{stage}_{opportunity_id}`** — this is
  deliberate: it lets you visually link a `deep_dive_opp_3` node to the later
  `worth_it_opp_3` node for the same opportunity (e.g. same color accent, or
  a subtle connecting line) if you want that polish, since they share the
  `opp_3` suffix.
- **The backend's `manager` is a router node that runs multiple times** —
  once at start, and again after every `orchestration` fan-in. This is why
  you'll see `edge_active(manager→X)` fire repeatedly throughout a single
  run rather than once. Don't assume `manager`'s node only transitions to
  `running` once — expect it to cycle `running`↔`completed` several times,
  and reset the previously-active edge's `animated` flag each time a new
  `edge_active` arrives (per `frontend.md`'s `setEdgeActive` implementation).
- **`deep_dive` and `worth_it` are parallel fan-outs (`Send()`), count is
  dynamic** — the number of `node_added` events for these stages equals the
  number of approved opportunities, which varies per run (could be 1, could
  be 5). Don't hardcode assumptions about how many sub-agent nodes will
  appear; your dagre layout call must handle an arbitrary, changing count.
- **`orchestration` is a fan-in marker, not a "real" processing step** — it
  will appear as `running`→`completed` very quickly relative to the
  sub-agent nodes feeding into it. Don't be surprised if its `running` state
  is nearly instantaneous; that's correct backend behavior, not a bug to
  work around.
- **HITL mode is optional** — if you build an approval UI at all (calling
  `POST /runs/{run_id}/resume`), know that this only matters when
  `hitl_mode: "human"` was sent at session start. For `hitl_mode: "ai"`
  (likely your default for a fast POC loop), `ai_approval` completes on its
  own with no frontend action needed.

## Your scope

- Implement everything in `frontend.md`.
- Do not build any backend code or make assumptions about LangGraph
  internals beyond what's in `CONTRACT.md` and this file.
- Get the full UI working and demo-able against the mock emitter alone —
  this should be true regardless of the backend's progress.

## Merge step

Follow the "Merge checklist" at the bottom of `CONTRACT.md`. Your specific
responsibility there: swap the mock emitter URL for
`ws://localhost:8000/ws/{run_id}`, confirm the `node_type` values you switch
on in `AgentNode` cover every value Agent 1 actually emits, and sit in on the
end-to-end test run together.