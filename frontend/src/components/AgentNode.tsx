// AgentNode — custom React Flow node. Renders an icon for the node_type plus
// a status-colored border. Reads its data from the React Flow `data` prop,
// which is populated by GraphView from the Zustand store.

import { Handle, Position, type NodeProps } from '@xyflow/react';
import type { ReactNode } from 'react';
import type { AgentNodeType, NodeStatus } from '../types';

type AgentNodeData = {
  nodeType: AgentNodeType;
  label: string;
  status: NodeStatus;
  summary: string | null;
};

const STATUS_BORDER: Record<NodeStatus, string> = {
  idle: '#3a3f4b',
  running: '#3b82f6',
  completed: '#22c55e',
  error: '#ef4444',
};

const STATUS_LABEL: Record<NodeStatus, string> = {
  idle: 'idle',
  running: 'running',
  completed: 'done',
  error: 'error',
};

// Minimal inline SVG icons — one per node_type. Pure presentational, no
// external icon library to keep the bundle small.
const ICONS: Record<AgentNodeType, ReactNode> = {
  manager: (
    <svg viewBox="0 0 16 16" width="14" height="14" fill="currentColor">
      <path d="M8 1l2 3h3v3l3 2-3 2v3h-3l-2 3-2-3H3v-3L0 9l3-2V4h3z" />
    </svg>
  ),
  opportunity_discovery: (
    <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.5">
      <circle cx="7" cy="7" r="5" />
      <path d="M11 11l4 4" />
    </svg>
  ),
  approval_router: (
    <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.5">
      <path d="M2 4h12M2 8h12M2 12h12" />
      <circle cx="6" cy="4" r="1.2" fill="currentColor" />
      <circle cx="10" cy="8" r="1.2" fill="currentColor" />
    </svg>
  ),
  human_approval: (
    <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.5">
      <circle cx="8" cy="5" r="3" />
      <path d="M2 14c1.5-3 4-4 6-4s4.5 1 6 4" />
    </svg>
  ),
  ai_approval: (
    <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.5">
      <rect x="3" y="5" width="10" height="8" rx="1.5" />
      <circle cx="6" cy="9" r="0.8" fill="currentColor" />
      <circle cx="10" cy="9" r="0.8" fill="currentColor" />
      <path d="M8 3v2" />
    </svg>
  ),
  deep_dive_subagent: (
    <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.5">
      <rect x="2" y="3" width="12" height="10" rx="2" />
      <path d="M5 7l2 2-2 2M9 11h2" />
    </svg>
  ),
  worth_it_subagent: (
    <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.5">
      <path d="M3 8l3 3 7-7" />
    </svg>
  ),
  orchestration: (
    <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.5">
      <circle cx="4" cy="4" r="1.5" />
      <circle cx="12" cy="4" r="1.5" />
      <circle cx="4" cy="12" r="1.5" />
      <circle cx="12" cy="12" r="1.5" />
      <circle cx="8" cy="8" r="1.5" fill="currentColor" />
    </svg>
  ),
  synthesis: (
    <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.5">
      <path d="M3 2h10v12H3z" />
      <path d="M5 5h6M5 8h6M5 11h4" />
    </svg>
  ),
};

export function AgentNode(props: NodeProps) {
  const data = props.data as AgentNodeData;
  const border = STATUS_BORDER[data.status];
  const isRunning = data.status === 'running';

  return (
    <div
      style={{
        background: '#1a1d24',
        border: `2px solid ${border}`,
        borderRadius: 8,
        padding: '8px 12px',
        minWidth: 140,
        color: '#e6e6e6',
        boxShadow: isRunning ? `0 0 12px ${border}` : 'none',
        animation: isRunning ? 'pulse 1.4s ease-in-out infinite' : 'none',
        display: 'flex',
        flexDirection: 'column',
        gap: 4,
      }}
    >
      <Handle type="target" position={Position.Left} style={{ background: '#3a3f4b' }} />
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <span style={{ color: '#9ca3af' }}>{ICONS[data.nodeType]}</span>
        <span style={{ fontWeight: 500, fontSize: 13 }}>{data.label}</span>
      </div>
      <div style={{ fontSize: 10, color: '#6b7280', textTransform: 'uppercase', letterSpacing: 0.5 }}>
        {STATUS_LABEL[data.status]}
      </div>
      {data.summary && (
        <div style={{ fontSize: 11, color: '#9ca3af', marginTop: 2, lineHeight: 1.3 }}>
          {data.summary}
        </div>
      )}
      <Handle type="source" position={Position.Right} style={{ background: '#3a3f4b' }} />
    </div>
  );
}
