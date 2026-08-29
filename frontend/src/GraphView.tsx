import { useMemo, useState, useCallback, useEffect, useRef } from 'react';
import { ReactFlow, Background, Controls, MiniMap, ReactFlowProvider, useReactFlow, type Node, type Edge } from '@xyflow/react';
import '@xyflow/react/dist/style.css';

import { useGraphStore } from './store/graphStore';
import { AgentNode } from './components/AgentNode';
import { HistoryDrawer } from './components/HistoryDrawer';
import { Legend } from './components/Legend';
import { ReportViewer } from './components/ReportViewer';
import { ApprovalPanel } from './components/ApprovalPanel';
import { useGraphSocket } from './hooks/useGraphSocket';
import { applyDagreLayout, LAYOUT_CONFIG } from './lib/layout';
import { STATIC_NODES } from './data/staticGraph';
import type { AgentNodeType, RunParams } from './types';

const nodeTypes = { agent: AgentNode };

function buildStaticFallback(): Node[] {
  return STATIC_NODES.map((n) => ({
    ...n,
    type: 'agent' as const,
    data: {
      nodeType: (n.data as { nodeType: AgentNodeType }).nodeType,
      label: (n.data as { label: string }).label,
      status: 'idle' as const,
      summary: null,
    },
  }));
}

export type GraphViewProps = {
  runId: string;
  params: RunParams | null;
  onNewRun?: () => void;
};

export function GraphView(props: GraphViewProps) {
  return (
    <ReactFlowProvider>
      <GraphViewInner {...props} />
    </ReactFlowProvider>
  );
}

function GraphViewInner({ runId, params, onNewRun }: GraphViewProps) {
  useGraphSocket(runId, params);

  const storeNodes = useGraphStore((s) => s.nodes);
  const storeEdges = useGraphStore((s) => s.edges);
  const runCompleted = useGraphStore((s) => s.runCompleted);
  const humanApprovalStatus = useGraphStore((s) => s.nodes.human_approval?.status);
  const isPausedAtApproval = humanApprovalStatus === 'running' && !runCompleted;

  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [reportOpen, setReportOpen] = useState(false);

  const reactFlow = useReactFlow();
  const lastNodeCountRef = useRef<number>(0);

  const flowNodes: Node[] = useMemo(() => {
    const fromStore: Node[] = Object.entries(storeNodes).map(([id, n]) => ({
      id,
      type: 'agent',
      position: { x: 0, y: 0 },
      data: {
        nodeType: n.nodeType,
        label: n.label,
        status: n.status,
        summary: n.summary,
        parentId: n.parentId,
      },
    }));
    const base = fromStore.length > 0 ? fromStore : buildStaticFallback();
    return applyDagreLayout(base, LAYOUT_CONFIG);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [Object.keys(storeNodes).length]);

  const flowEdges: Edge[] = useMemo(() => {
    const fromStore: Edge[] = Object.entries(storeEdges).map(([id, e]) => ({
      id,
      source: e.from,
      target: e.to,
      animated: e.animated,
    }));
    if (fromStore.length > 0) return fromStore;
    return [];
  }, [storeEdges]);

  const handleNodeClick = useCallback((_: unknown, node: Node) => {
    setSelectedNodeId(node.id);
  }, []);

  // Auto-open the centered report modal the moment the run completes.
  useEffect(() => {
    if (runCompleted) {
      setReportOpen(true);
    }
    // Don't show the report modal for a stale previous run that we just
    // reset (handled below via params-change effect).
  }, [runCompleted]);

  // When params change (parent signalled a new run), make sure the report
  // modal from the previous run is gone.
  useEffect(() => {
    setReportOpen(false);
  }, [params]);

  // Re-fit the viewport whenever the dynamic-node count changes — without
  // this, the user keeps looking at the static-only layout when the
  // deep_dive/worth_it nodes appear off-screen to the right.
  useEffect(() => {
    const n = flowNodes.length;
    if (n !== lastNodeCountRef.current) {
      lastNodeCountRef.current = n;
      // Small defer so React Flow has the new positions laid out before
      // we ask it to fit.
      const t = setTimeout(() => {
        try {
          reactFlow.fitView({ duration: 400, padding: 0.15 });
        } catch {
          // reactFlow may not be ready yet on first paint; ignore.
        }
      }, 60);
      return () => clearTimeout(t);
    }
  }, [flowNodes.length, reactFlow]);

  return (
    <div style={{ width: '100vw', height: '100vh', position: 'relative' }}>
      <ReactFlow
        nodes={flowNodes}
        edges={flowEdges}
        nodeTypes={nodeTypes}
        onNodeClick={handleNodeClick}
        fitView
        proOptions={{ hideAttribution: true }}
      >
        <Background />
        <Controls />
        <MiniMap
          nodeStrokeColor="#3a3f4b"
          nodeColor={(n) => {
            const status = (n.data as { status?: string }).status ?? 'idle';
            if (status === 'running') return '#3b82f6';
            if (status === 'completed') return '#22c55e';
            if (status === 'error') return '#ef4444';
            return '#1a1d24';
          }}
          style={{ background: '#161922', border: '1px solid #2a2f3a' }}
        />
      </ReactFlow>

      <Legend />
      {isPausedAtApproval && (
        <div
          role="dialog"
          aria-label="Approval required"
          style={{
            position: 'absolute',
            top: 12,
            left: '50%',
            transform: 'translateX(-50%)',
            width: 520,
            maxWidth: 'calc(100vw - 24px)',
            maxHeight: 'calc(100vh - 24px)',
            background: '#161922',
            border: '1px solid #2a2f3a',
            borderRadius: 10,
            padding: 20,
            boxShadow: '0 20px 60px rgba(0,0,0,0.5)',
            zIndex: 20,
            color: '#e6e6e6',
            overflowY: 'auto',
            boxSizing: 'border-box',
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
            <h2 style={{ margin: 0, fontSize: 16, fontWeight: 600 }}>approval required</h2>
          </div>
          <ApprovalPanel runId={runId} />
        </div>
      )}
      {runCompleted && !reportOpen && (
        <div
          style={{
            position: 'absolute',
            top: 12,
            right: 12,
            display: 'flex',
            gap: 8,
            alignItems: 'center',
          }}
        >
          <div
            style={{
              background: '#166534',
              color: '#dcfce7',
              padding: '6px 12px',
              borderRadius: 6,
              fontSize: 12,
              fontWeight: 500,
            }}
          >
            run completed
          </div>
          <button
            onClick={() => setReportOpen(true)}
            style={{
              background: '#3b82f6',
              color: 'white',
              border: 'none',
              padding: '6px 14px',
              borderRadius: 6,
              fontSize: 12,
              fontWeight: 500,
              cursor: 'pointer',
            }}
          >
            view report
          </button>
          {onNewRun && (
            <button
              onClick={onNewRun}
              style={{
                background: '#1f2937',
                color: '#e6e6e6',
                border: '1px solid #2a2f3a',
                padding: '6px 14px',
                borderRadius: 6,
                fontSize: 12,
                fontWeight: 500,
                cursor: 'pointer',
              }}
            >
              start new run
            </button>
          )}
        </div>
      )}
      <HistoryDrawer
        runId={runId}
        nodeId={selectedNodeId}
        onClose={() => setSelectedNodeId(null)}
      />
      <ReportViewer
        runId={runId}
        open={reportOpen}
        onClose={() => setReportOpen(false)}
      />
    </div>
  );
}
