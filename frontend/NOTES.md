# Frontend build notes — contract decisions & assumptions

This file tracks every assumption I'm making against `contract.md` and the
frontend spec, so when we merge with the backend agent we can diff this list
against what they actually emit and resolve any drift explicitly.

## Confirmed against contract.md (no ambiguity)

- Static `node_id` set: `manager`, `opportunity_discovery`, `approval_router`,
  `human_approval`, `ai_approval`, `orchestration`, `synthesis`.
- Dynamic `node_id` pattern: `{stage}_{opportunity_id}`, e.g. `deep_dive_opp_3`,
  `worth_it_opp_3`.
- `node_type` enum (the values we will switch on in `AgentNode`):
  `manager`, `opportunity_discovery`, `approval_router`, `human_approval`,
  `ai_approval`, `deep_dive_subagent`, `orchestration`, `worth_it_subagent`,
  `synthesis`.
- Event shapes: `node_added`, `node_status`, `edge_active`, `run_completed`
  per contract.md §"Event schema".
- Ordering guarantee: `node_added` precedes any `node_status` for the same
  `node_id`. We rely on this and will NOT defensively create nodes on status.
- Manager is a router that fires `edge_active` repeatedly (cycles
  `running`↔`completed`); only the latest edge should be `animated`.
- `deep_dive` and `worth_it` are parallel fan-outs with a **dynamic, runtime
  count** — dagre layout must handle arbitrary N, no hardcoding.
- `parent_id` on `node_added` is the stage node to draw the edge from
  (`manager` for top-level stages, `deep_dive` for sub-agents, etc.).
- REST history endpoint shape and the POST `/resume` body shape — frontend
  builds to these exactly.

## Decisions we made in this session

- **Stack**: Vite + React 19 + TS, React Flow (`@xyflow/react`), dagre,
  Zustand, react-markdown + remark-gfm. Tailwind deliberately skipped — plain CSS.
- **Location**: `/frontend` at repo root, sibling to `research_agent/`.
- **Vite dev port**: default `5173`, matching contract.md.

## Contract additions I proposed in contract.md

- Session-start frame extended with optional `report_focus` and `max_opportunities`.
- New REST endpoint `GET /runs/{run_id}/report` returning `{ markdown, generated_at }`.
- Merge checklist now includes both.

Both edits are in `contract.md` and visible to Agent 1. They should confirm
or push back before the merge step. Frontend builds against the proposed shape
either way — if Agent 1 rejects the additions, the only changes are: drop
`report_focus`/`max_opportunities` from the form, drop the report button.

## What's built

- **Step 1 — static skeleton**: hardcoded 7 nodes / 5 edges from contract.md.
- **Step 2 — AgentNode + Zustand store**: custom React Flow node with per-`node_type` inline SVG icons + status-colored border + summary line; flat store keyed by id.
- **Step 3 — mock emitter**: `buildMockSequence()` + `MockRunner` that schedules the full frontend_plan.md sequence with realistic timings (including 3 parallel deep_dive + 3 parallel worth_it fan-outs).
- **Step 4 — `useGraphSocket`**: single hook; `?mock=true` or `VITE_USE_MOCK=true` toggles mock. Real WS at `ws://localhost:8000/ws/{runId}` with the contract's session-start frame on `onopen`.
- **Step 5 — dagre auto-layout**: re-layouts on node-count changes; layout uses `parentId` from store so dynamic sub-agent nodes anchor to their parent stage.
- **Step 6 — HistoryDrawer**: opens on node click, hits `GET /runs/{runId}/nodes/{nodeId}/history`, renders whatever fields are non-null.
- **Step 7 — minimap + legend**: MiniMap with status-tinted nodes, Legend in top-left.
- **Bonus — research inputs form**: `RunParamsForm` modal collects `domain`, `hitl_mode`, optional `report_focus` and `max_opportunities`. Submitted values drive the session-start frame sent on WS open.
- **Bonus — report viewer**: `ReportViewer` drawer opens via "view report" button in the run-completed banner. Polls `GET /runs/{run_id}/report` until ready, then renders markdown via `react-markdown` + `remark-gfm` with dark-theme styling.
- **Architect design in drawer**: `HistoryDrawer` shows a "generate design" button for `deep_dive_*` / `worth_it_*` nodes. `useSolutionDesign` POSTs to the backend proxy `POST /runs/{runId}/nodes/{nodeId}/design` (backend does the real server-to-server A2A `SendMessage` to the Architect); renders stack/components/data-flow/deploy/effort/risks/open-questions inline. 404 (no opportunity) and 502 (architect down/failed) surface as error text with retry.

## File map

```
frontend/
├── NOTES.md
├── src/
│   ├── App.tsx
│   ├── GraphView.tsx
│   ├── main.tsx
│   ├── index.css
│   ├── App.css
│   ├── types.ts                  # event + REST types (mirror contract.md)
│   ├── components/
│   │   ├── AgentNode.tsx
│   │   ├── ApprovalPanel.tsx     # NEW: human-approval checkbox UI
│   │   ├── HistoryDrawer.tsx     # renders ApprovalPanel when paused
│   │   │                         # + "generate design" (Architect A2A) for dynamic nodes
│   │   ├── Legend.tsx
│   │   ├── ReportViewer.tsx
│   │   └── RunParamsForm.tsx
│   ├── data/
│   │   └── staticGraph.ts
│   ├── hooks/
│   │   ├── useGraphSocket.ts
│   │   ├── useNodeHistory.ts
│   │   ├── useResume.ts          # NEW: POST /runs/{id}/resume
│   │   ├── useRunOpportunities.ts# NEW: GET /runs/{id}/opportunities
│   │   ├── useRunReport.ts
│   │   └── useSolutionDesign.ts  # NEW: POST /runs/{id}/nodes/{node}/design (Architect)
│   ├── lib/
│   │   ├── MockRunner.ts
│   │   ├── layout.ts
│   │   └── mockEmitter.ts
│   └── store/
│       └── graphStore.ts
```

## Open questions / things to verify at merge time

- **CORS port alignment**: contract.md says backend enables CORS for
  `http://localhost:5173`. If the backend agent picks a different port (e.g.
  Vite chosen a different default), we update this file and tell them.
- **`useGraphSocket` URL swap**: mock URL placeholder → real
  `ws://localhost:8000/ws/{run_id}` at merge time, one-line change.
- **Initial graph topology**: I'm hardcoding the static nodes from
  contract.md. Backend may or may not send `node_added` for the static ones
  at run start — if it does, our store merges by id (no duplicate). If it
  doesn't, the hardcoded set remains the visible skeleton.
- **History drawer field for `opportunity`**: contract says it's "Opportunity
  fields" without enumerating. I'm rendering key/value pairs generically so
  we don't bake in a schema the backend hasn't promised.
- **HITL approval UI**: spec mentions a `HistoryDrawer` and the resume
  endpoint, but doesn't require an approval list UI in the drawer. I'm
  leaving that out of the skeleton; flag if you want it as a separate step.

## Mock emitter contract

The mock emitter (used until backend lands) replays the exact sequence from
`frontend_plan.md` §"Build a mock that matches the contract exactly". Events
use the same JSON shape verbatim — no shortcuts.

The mock is gated behind `?mock=true` query param AND `VITE_USE_MOCK=true`
env var; either turns it on, otherwise we attempt a real WS connection. This
matches the plan's "trivial to switch off at merge time" requirement.
