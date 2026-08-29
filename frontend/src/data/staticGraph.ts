// Static graph topology — hardcoded from contract.md so the skeleton has
// something to render before the websocket / mock emitter feeds it events.
//
// Dynamic nodes (deep_dive_opp_*, worth_it_opp_*) are NOT listed here; they
// arrive via `node_added` events at runtime. dagre layout will recompute when
// they show up.

import type { Node, Edge } from '@xyflow/react';

export type AgentNodeType =
  | 'manager'
  | 'opportunity_discovery'
  | 'approval_router'
  | 'human_approval'
  | 'ai_approval'
  | 'deep_dive_subagent'
  | 'orchestration'
  | 'worth_it_subagent'
  | 'synthesis';

export const STATIC_NODES: Node[] = [
  { id: 'manager', position: { x: 0, y: 0 }, data: { label: 'manager', nodeType: 'manager' as AgentNodeType } },
  { id: 'opportunity_discovery', position: { x: 0, y: 0 }, data: { label: 'opportunity_discovery', nodeType: 'opportunity_discovery' as AgentNodeType } },
  { id: 'approval_router', position: { x: 0, y: 0 }, data: { label: 'approval_router', nodeType: 'approval_router' as AgentNodeType } },
  { id: 'human_approval', position: { x: 0, y: 0 }, data: { label: 'human_approval', nodeType: 'human_approval' as AgentNodeType } },
  { id: 'ai_approval', position: { x: 0, y: 0 }, data: { label: 'ai_approval', nodeType: 'ai_approval' as AgentNodeType } },
  { id: 'orchestration', position: { x: 0, y: 0 }, data: { label: 'orchestration', nodeType: 'orchestration' as AgentNodeType } },
  { id: 'synthesis', position: { x: 0, y: 0 }, data: { label: 'synthesis', nodeType: 'synthesis' as AgentNodeType } },
];

// Placeholder edges between the static stages. Real edges will be driven by
// `edge_active` events at runtime; these are just to make the skeleton
// legible in the review.
export const STATIC_EDGES: Edge[] = [
  { id: 'e-mgr-disc',    source: 'manager',                target: 'opportunity_discovery' },
  { id: 'e-disc-approv', source: 'opportunity_discovery',  target: 'approval_router' },
  { id: 'e-apr-human',   source: 'approval_router',        target: 'human_approval' },
  { id: 'e-apr-ai',      source: 'approval_router',        target: 'ai_approval' },
  { id: 'e-orch-syn',    source: 'orchestration',          target: 'synthesis' },
];
