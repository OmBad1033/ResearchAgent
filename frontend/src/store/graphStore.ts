// Zustand store — flat shape keyed by node_id / edge_id.
//
// Nodes carry everything inline (status, summary, nodeType, parent_id, ...)
// so a click handler can read node state with one lookup. Edges store
// `animated` directly; the latest `edge_active` event wins, all others
// reset to false (per spec §"setEdgeActive").

import { create } from 'zustand';
import type {
  AgentNodeType,
  NodeStatus,
  WsEvent,
  NodeAddedEvent,
  NodeStatusEvent,
  EdgeActiveEvent,
} from '../types';

export type GraphNodeData = {
  nodeType: AgentNodeType;
  label: string;
  status: NodeStatus;
  summary: string | null;
  parentId: string | null;
  opportunityId: string | null;
  timestamp: string | null;
};

export type GraphEdgeData = {
  from: string;
  to: string;
  animated: boolean;
};

export type GraphStore = {
  nodes: Record<string, GraphNodeData>;
  edges: Record<string, GraphEdgeData>;
  activeEdgeId: string | null;
  runCompleted: boolean;

  // Derived selectors used by React Flow rendering live in GraphView.
  applyEvent: (event: WsEvent) => void;
  reset: () => void;
};

const edgeIdFor = (from: string, to: string) => `e-${from}-${to}`;

export const useGraphStore = create<GraphStore>((set) => ({
  nodes: {},
  edges: {},
  activeEdgeId: null,
  runCompleted: false,

  applyEvent: (event) =>
    set((state) => {
      switch (event.type) {
        case 'node_added': {
          const e = event as NodeAddedEvent;
          return {
            nodes: {
              ...state.nodes,
              [e.node_id]: {
                nodeType: e.node_type,
                label: e.label,
                status: 'idle',
                summary: null,
                parentId: e.parent_id,
                opportunityId: e.opportunity_id,
                timestamp: e.timestamp,
              },
            },
          };
        }
        case 'node_status': {
          const e = event as NodeStatusEvent;
          const existing = state.nodes[e.node_id];
          if (!existing) {
            // The contract promises node_added precedes node_status, but
            // in practice the backend can emit a node_status (e.g. the
            // very first one, fired from inside the node itself) before
            // the matching node_added arrives. Don't go dark on the
            // user — synthesize a placeholder node with minimal info so
            // the status can render. If a real node_added arrives later
            // it'll be merged in by the normal path.
            // eslint-disable-next-line no-console
            console.warn(`node_status for unknown node_id: ${e.node_id} — synthesizing placeholder`);
            return {
              nodes: {
                ...state.nodes,
                [e.node_id]: {
                  nodeType: 'manager' as unknown as AgentNodeType, // overwritten by later node_added if any
                  label: e.node_id,
                  status: e.status,
                  summary: e.summary,
                  parentId: null,
                  opportunityId: null,
                  timestamp: e.timestamp,
                },
              },
            };
          }
          return {
            nodes: {
              ...state.nodes,
              [e.node_id]: {
                ...existing,
                status: e.status,
                summary: e.summary,
                timestamp: e.timestamp,
              },
            },
          };
        }
        case 'edge_active': {
          const e = event as EdgeActiveEvent;
          const id = edgeIdFor(e.from, e.to);
          // Reset all edges to not animated, then animate only the new one.
          const resetEdges: Record<string, GraphEdgeData> = {};
          for (const [k, v] of Object.entries(state.edges)) {
            resetEdges[k] = { ...v, animated: false };
          }
          resetEdges[id] = {
            from: e.from,
            to: e.to,
            animated: true,
          };
          return {
            edges: resetEdges,
            activeEdgeId: id,
          };
        }
        case 'run_completed':
          return { ...state, runCompleted: true };
      }
    }),

  reset: () => set({ nodes: {}, edges: {}, activeEdgeId: null, runCompleted: false }),
}));
