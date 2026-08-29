// Dagre auto-layout for the React Flow graph.
//
// React Flow expects each node to carry a `position`. We don't want to
// hand-position anything because dynamic sub-agent nodes (deep_dive_opp_*,
// worth_it_opp_*) appear at runtime and the count varies per run.
//
// Strategy: feed every node + a best-effort edge set into dagre, then
// mutate the input nodes' positions in place. Edges aren't required for
// layout to work — dagre just won't lay them out relative to each other.
// Since we already store edges in the graphStore, we recompute layout on
// node-count changes and accept that edge changes alone won't trigger one
// (adding/removing a node is the structurally significant event).

import dagre from 'dagre';
import type { Node, Edge } from '@xyflow/react';

export const LAYOUT_CONFIG = {
  rankdir: 'LR' as const,        // left-to-right matches the manager → ... flow
  nodesep: 60,
  ranksep: 120,
  nodeWidth: 180,
  nodeHeight: 80,
};

export function applyDagreLayout(nodes: Node[], config = LAYOUT_CONFIG): Node[] {
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({
    rankdir: config.rankdir,
    nodesep: config.nodesep,
    ranksep: config.ranksep,
  });

  for (const n of nodes) {
    g.setNode(n.id, { width: config.nodeWidth, height: config.nodeHeight });
  }

  // Only lay out edges whose endpoints exist (defensive — store and static
  // fallback can briefly disagree during the very first events).
  for (const e of inferLayoutEdges(nodes)) {
    g.setEdge(e.source, e.target);
  }

  dagre.layout(g);

  return nodes.map((n) => {
    const pos = g.node(n.id);
    if (!pos) return n;
    // Dagre gives center positions; React Flow wants top-left.
    return {
      ...n,
      position: {
        x: pos.x - config.nodeWidth / 2,
        y: pos.y - config.nodeHeight / 2,
      },
    };
  });
}

// Compute layout-only edges for dagre positioning.
//
// Two sources:
//   1. parentId → child (when the parent exists in the node set). This is
//      what the backend emits for static nodes and gives a stable tree.
//   2. Synthesized sub-agent chain (the runtime never emits a layout edge
//      because deep_dive/worth_it are sub-graph wrappers that aren't
//      rendered as React Flow nodes). We build them here so each
//      opportunity's deep_dive_<id> sits to the right of whichever
//      approval routed to it, and worth_it_<id> continues from there
//      onward to synthesis. Dagre will stack the parallel opportunity
//      rows vertically because they all flow through the same horizontal
//      stages.
function inferLayoutEdges(nodes: Node[]): Edge[] {
  const out: Edge[] = [];
  const nodeIds = new Set(nodes.map((n) => n.id));

  // (1) parent_id edges.
  for (const n of nodes) {
    const parentId = (n.data as { parentId?: string | null }).parentId;
    if (parentId && nodeIds.has(parentId)) {
      out.push({ id: `layout-${parentId}-${n.id}`, source: parentId, target: n.id });
    }
  }

  // (2) Synthesized sub-agent chain.
  const deepDives = nodes.filter((n) => n.id.startsWith('deep_dive_'));
  const worthIts = nodes.filter((n) => n.id.startsWith('worth_it_'));
  const getOppId = (n: Node) => (n.data as { opportunityId?: string | null }).opportunityId;
  const oppIdFor = (nodeId: string) => nodeId.replace(/^(deep_dive_|worth_it_)/, '');

  // approval -> deep_dive_<id>. Pick approval node by the run's chosen
  // mode — the run is always one mode, but we don't have that here, so we
  // emit an edge from whichever approval node is in the set (one of
  // human_approval / ai_approval will be present, the other not).
  const approvalNode = nodes.find((n) => n.id === 'human_approval' || n.id === 'ai_approval');
  if (approvalNode) {
    for (const dd of deepDives) {
      out.push({
        id: `layout-approval-${dd.id}`,
        source: approvalNode.id,
        target: dd.id,
      });
    }
  }

  // deep_dive_<id> -> worth_it_<id>, matched by opportunity_id so each
  // opportunity has a single horizontal chain.
  for (const dd of deepDives) {
    const opp = getOppId(dd) ?? oppIdFor(dd.id);
    const wi = worthIts.find((w) => (getOppId(w) ?? oppIdFor(w.id)) === opp);
    if (wi) {
      out.push({ id: `layout-${dd.id}-${wi.id}`, source: dd.id, target: wi.id });
    }
  }

  // worth_it_<id> -> synthesis (every deep-dived opportunity feeds into
  // the final synthesis node).
  if (nodeIds.has('synthesis')) {
    for (const wi of worthIts) {
      out.push({ id: `layout-${wi.id}-synthesis`, source: wi.id, target: 'synthesis' });
    }
  }

  return out;
}
