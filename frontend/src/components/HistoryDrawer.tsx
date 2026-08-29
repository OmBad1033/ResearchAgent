// HistoryDrawer — opens when a node is clicked. Fetches its history from
// the REST endpoint and renders whatever fields are non-null. Per
// contract.md §"REST: node history", the backend may return opportunity: null
// for static nodes, and we render gracefully in that case.
//
// Note: human-approval UI lives in a separate top-level overlay in
// GraphView.tsx (the ApprovalPanel), NOT inside this drawer — that
// way users see it the moment the run pauses, without having to
// click any node first.

import { useNodeHistory } from '../hooks/useNodeHistory';

export type HistoryDrawerProps = {
  runId: string;
  nodeId: string | null;
  onClose: () => void;
};

export function HistoryDrawer({ runId, nodeId, onClose }: HistoryDrawerProps) {
  const { data, loading, error, refetch } = useNodeHistory(runId, nodeId);

  if (!nodeId) return null;

  return (
    <aside
      style={{
        position: 'fixed',
        top: 0,
        right: 0,
        width: 360,
        height: '100vh',
        background: '#161922',
        borderLeft: '1px solid #2a2f3a',
        padding: 20,
        overflowY: 'auto',
        boxSizing: 'border-box',
        zIndex: 10,
        color: '#e6e6e6',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h3 style={{ margin: 0, fontSize: 14, fontWeight: 600 }}>{nodeId}</h3>
        <button
          onClick={onClose}
          style={{
            background: 'transparent',
            border: '1px solid #2a2f3a',
            color: '#9ca3af',
            borderRadius: 4,
            padding: '2px 8px',
            cursor: 'pointer',
            fontSize: 12,
          }}
        >
          close
        </button>
      </div>

      {loading && <div style={{ color: '#6b7280', fontSize: 13 }}>loading history…</div>}
      {error && (
        <div style={{ color: '#fca5a5', fontSize: 13 }}>
          failed to load: {error}
          <button onClick={refetch} style={{ marginLeft: 8, background: 'transparent', color: '#9ca3af', border: '1px solid #2a2f3a', borderRadius: 4, padding: '2px 8px', cursor: 'pointer', fontSize: 11 }}>
            retry
          </button>
        </div>
      )}

      {data && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16, fontSize: 13 }}>
          {data.opportunity && (
            <section>
              <h4 style={sectionHeadingStyle}>opportunity</h4>
              <pre style={preStyle}>{JSON.stringify(data.opportunity, null, 2)}</pre>
            </section>
          )}
          {data.reasoning && (
            <section>
              <h4 style={sectionHeadingStyle}>reasoning</h4>
              <p style={{ margin: 0, lineHeight: 1.4, color: '#d1d5db' }}>{data.reasoning}</p>
            </section>
          )}
          {data.worth_it_verdict && (
            <section>
              <h4 style={sectionHeadingStyle}>verdict</h4>
              <p style={{ margin: 0, lineHeight: 1.4, color: '#d1d5db' }}>{data.worth_it_verdict}</p>
            </section>
          )}
          {data.worth_it_reasoning && (
            <section>
              <h4 style={sectionHeadingStyle}>worth-it reasoning</h4>
              <p style={{ margin: 0, lineHeight: 1.4, color: '#d1d5db' }}>{data.worth_it_reasoning}</p>
            </section>
          )}
          {!data.opportunity && !data.reasoning && !data.worth_it_verdict && !data.worth_it_reasoning && (
            <div style={{ color: '#6b7280', fontSize: 12 }}>no history fields populated for this node.</div>
          )}
        </div>
      )}
    </aside>
  );
}

const sectionHeadingStyle: React.CSSProperties = {
  margin: '0 0 6px',
  fontSize: 11,
  fontWeight: 600,
  textTransform: 'uppercase',
  letterSpacing: 0.6,
  color: '#6b7280',
};

const preStyle: React.CSSProperties = {
  margin: 0,
  padding: 10,
  background: '#0f1115',
  borderRadius: 4,
  border: '1px solid #2a2f3a',
  fontSize: 11,
  lineHeight: 1.4,
  color: '#d1d5db',
  overflowX: 'auto',
};
