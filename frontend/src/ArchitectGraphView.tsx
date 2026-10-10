// ArchitectGraphView — full-screen architect canvas shown after the user
// clicks "deep dive" in the research report.
//
// Frontend-only simulation (per plan): the REAL SolutionDesign comes from
// POST /runs/{runId}/nodes/{nodeId}/design (existing backend proxy → A2A).
// The staged graph animation (intake → context → design → review) is a
// timed simulation so the canvas feels like the research graph — nodes
// light up running → completed while the design POST is in flight.
//
// Props:
//   runId        — same run id as the research graph (design lookup key)
//   opportunity  — { id, title, description } picked in the report picker
//   onBack       — return to the research graph
//   onDesignReady— fires with the fetched SolutionDesign so the parent can
//                  collect pages for the multi-page architect report

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ReactFlow, Background, Controls, MiniMap, ReactFlowProvider, useReactFlow, type Node, type Edge } from '@xyflow/react';
import '@xyflow/react/dist/style.css';

import { AgentNode } from './components/AgentNode';
import { Legend } from './components/Legend';
import { ArchitectDesignReport } from './components/ArchitectDesignReport';
import { applyDagreLayout, LAYOUT_CONFIG } from './lib/layout';
import type { AgentNodeType, SolutionDesign } from './types';

export type ArchitectOpportunity = {
  id: string;
  title: string;
  description: string;
};

export type ArchitectGraphViewProps = {
  runId: string;
  opportunity: ArchitectOpportunity;
  onBack: () => void;
  onDesignReady?: (design: SolutionDesign) => void;
};

const nodeTypes = { agent: AgentNode };

// Staged pipeline — mirrors how the research graph reads stage by stage.
// Node ids are namespaced `arch_*` so they never collide with research ids.
const STAGES = [
  { id: 'arch_intake', label: 'arch intake', summary: 'reading opportunity' },
  { id: 'arch_context', label: 'arch context', summary: 'gathering research notes' },
  { id: 'arch_design', label: 'arch design', summary: 'architect agent designing' },
  { id: 'arch_review', label: 'arch review', summary: 'validating solution' },
] as const;

type StageStatus = 'idle' | 'running' | 'completed' | 'error';

const DESIGN_URL = (runId: string, nodeId: string) =>
  `http://localhost:8000/runs/${runId}/nodes/${nodeId}/design`;

function ArchitectGraphViewInner({ runId, opportunity, onBack, onDesignReady }: ArchitectGraphViewProps) {
  // Per-stage status map — drives the simulated running → completed sweep.
  const [stages, setStages] = useState<Record<string, StageStatus>>(() =>
    Object.fromEntries(STAGES.map((s) => [s.id, 'idle' as StageStatus])),
  );
  const [design, setDesign] = useState<SolutionDesign | null>(null);
  const [designError, setDesignError] = useState<string | null>(null);
  const [reportOpen, setReportOpen] = useState(false);
  const timersRef = useRef<ReturnType<typeof setTimeout>[]>([]);
  const reactFlow = useReactFlow();

  // The design node id reuses the research convention
  // `{stage}_{opportunity_id}` so the backend proxy finds the same
  // opportunity in run state (contract.md §"Node ID convention").
  const designNodeId = `deep_dive_${opportunity.id}`;

  const flowNodes: Node[] = useMemo(() => {
    const base: Node[] = STAGES.map((s, i) => ({
      id: s.id,
      type: 'agent' as const,
      position: { x: 0, y: 0 },
      data: {
        nodeType: 'orchestration' as AgentNodeType,
        label: s.label,
        status: stages[s.id] ?? 'idle',
        summary: s.summary,
        parentId: i === 0 ? null : STAGES[i - 1].id,
      },
    }));
    return applyDagreLayout(base, LAYOUT_CONFIG);
  }, [stages]);

  const flowEdges: Edge[] = useMemo(
    () =>
      STAGES.slice(1).map((s, i) => ({
        id: `e-${STAGES[i].id}-${s.id}`,
        source: STAGES[i].id,
        target: s.id,
        animated: stages[s.id] === 'running',
      })),
    [stages],
  );

  useEffect(() => {
    const t = setTimeout(() => {
      try {
        reactFlow.fitView({ duration: 400, padding: 0.15 });
      } catch {
        // reactFlow may not be ready yet on first paint; ignore.
      }
    }, 60);
    return () => clearTimeout(t);
  }, [flowNodes.length, reactFlow]);

  // Kick off: sweep stages running → completed on timers, and fire the
  // real design POST. The last stage flips to completed/error when the
  // fetch settles.
  useEffect(() => {
    const timers = timersRef.current;
    // Stage sweep — 700ms per stage gives the canvas a live feel while
    // the (slower) LLM call runs underneath.
    STAGES.forEach((s, i) => {
      timers.push(
        setTimeout(() => {
          setStages((prev) => ({ ...prev, [s.id]: 'running' }));
        }, i * 700),
      );
      if (i < STAGES.length - 1) {
        timers.push(
          setTimeout(() => {
            setStages((prev) => ({ ...prev, [s.id]: 'completed' }));
          }, i * 700 + 600),
        );
      }
    });

    const controller = new AbortController();
    fetch(DESIGN_URL(runId, designNodeId), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
      signal: controller.signal,
    })
      .then(async (res) => {
        if (!res.ok) {
          let detail = `HTTP ${res.status}`;
          try {
            const errBody = (await res.json()) as { detail?: string };
            if (errBody.detail) detail = errBody.detail;
          } catch {
            // Non-JSON error body — keep the HTTP status.
          }
          throw new Error(detail);
        }
        return (await res.json()) as { design: SolutionDesign };
      })
      .then((json) => {
        setDesign(json.design);
        onDesignReady?.(json.design);
        setStages((prev) => ({ ...prev, arch_review: 'completed', arch_design: 'completed' }));
        setReportOpen(true);
      })
      .catch((err: Error) => {
        if (err.name === 'AbortError') return;
        setDesignError(err.message);
        setStages((prev) => ({ ...prev, arch_review: 'error' }));
      });

    return () => {
      controller.abort();
      for (const t of timersRef.current) clearTimeout(t);
      timersRef.current = [];
    };
    // Fire once per opportunity — do NOT re-run when `stages` changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, designNodeId]);

  const handleNodeClick = useCallback(() => {
    // Nodes are presentational here — detail lives in the design report.
    // Clicking opens the report once a design exists.
    setReportOpen((open) => (design ? true : open));
  }, [design]);

  const done = design !== null || designError !== null;

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

      <div
        style={{
          position: 'absolute',
          top: 12,
          left: '50%',
          transform: 'translateX(-50%)',
          display: 'flex',
          gap: 8,
          alignItems: 'center',
          zIndex: 5,
        }}
      >
        <div
          style={{
            background: '#161922',
            border: '1px solid #2a2f3a',
            color: '#e6e6e6',
            padding: '6px 12px',
            borderRadius: 6,
            fontSize: 12,
            fontWeight: 500,
            maxWidth: 480,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
        >
          architect: {opportunity.title}
        </div>
        <button onClick={onBack} style={pillButtonStyle}>
          ← research graph
        </button>
        {design && (
          <button onClick={() => setReportOpen(true)} style={primaryPillStyle}>
            view design
          </button>
        )}
      </div>

      {!done && (
        <div
          style={{
            position: 'absolute',
            bottom: 16,
            left: '50%',
            transform: 'translateX(-50%)',
            background: 'rgba(22, 25, 34, 0.92)',
            border: '1px solid #2a2f3a',
            borderRadius: 6,
            padding: '8px 16px',
            fontSize: 12,
            color: '#9ca3af',
            zIndex: 5,
          }}
        >
          asking the architect agent…
        </div>
      )}
      {designError && (
        <div
          style={{
            position: 'absolute',
            bottom: 16,
            left: '50%',
            transform: 'translateX(-50%)',
            background: '#161922',
            border: '1px solid #ef4444',
            borderRadius: 6,
            padding: '8px 16px',
            fontSize: 12,
            color: '#fca5a5',
            zIndex: 5,
          }}
        >
          design failed: {designError}
        </div>
      )}

      {design && (
        <ArchitectDesignReport
          open={reportOpen}
          pages={[{ opportunity, design }]}
          onClose={() => setReportOpen(false)}
        />
      )}
    </div>
  );
}

export function ArchitectGraphView(props: ArchitectGraphViewProps) {
  return (
    <ReactFlowProvider>
      <ArchitectGraphViewInner {...props} />
    </ReactFlowProvider>
  );
}

const pillButtonStyle: React.CSSProperties = {
  background: '#1f2937',
  color: '#e6e6e6',
  border: '1px solid #2a2f3a',
  padding: '6px 14px',
  borderRadius: 6,
  fontSize: 12,
  fontWeight: 500,
  cursor: 'pointer',
};

const primaryPillStyle: React.CSSProperties = {
  background: '#3b82f6',
  color: 'white',
  border: 'none',
  padding: '6px 14px',
  borderRadius: 6,
  fontSize: 12,
  fontWeight: 500,
  cursor: 'pointer',
};
