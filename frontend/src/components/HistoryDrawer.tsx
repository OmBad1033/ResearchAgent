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
import { useSolutionDesign } from '../hooks/useSolutionDesign';

export type HistoryDrawerProps = {
  runId: string;
  nodeId: string | null;
  onClose: () => void;
};

export function HistoryDrawer({ runId, nodeId, onClose }: HistoryDrawerProps) {
  const { data, loading, error, refetch } = useNodeHistory(runId, nodeId);
  const {
    design,
    requesting,
    error: designError,
    requestDesign,
    reset: resetDesign,
  } = useSolutionDesign(runId, nodeId);

  // Only dynamic sub-agent nodes map to an opportunity the Architect can
  // design for (backend 404s otherwise — same {stage}_{opportunity_id}
  // convention as contract.md §"Node ID convention").
  const canDesign =
    !!nodeId && (nodeId.startsWith('deep_dive_') || nodeId.startsWith('worth_it_'));

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

          {canDesign && (
            <section>
              <h4 style={sectionHeadingStyle}>architect</h4>
              {!design && !requesting && !designError && (
                <button onClick={requestDesign} style={designButtonStyle}>
                  generate design
                </button>
              )}
              {requesting && (
                <div style={{ color: '#6b7280', fontSize: 12 }}>
                  asking the architect agent…
                </div>
              )}
              {designError && (
                <div style={{ color: '#fca5a5', fontSize: 12 }}>
                  design failed: {designError}
                  <button onClick={requestDesign} style={{ ...retryButtonStyle, marginLeft: 8 }}>
                    retry
                  </button>
                </div>
              )}
              {design && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                  {design.proposed_stack.length > 0 && (
                    <div>
                      <div style={designLabelStyle}>stack</div>
                      <div style={{ fontSize: 12, color: '#d1d5db' }}>
                        {design.proposed_stack.join(', ')}
                      </div>
                    </div>
                  )}
                  {design.components.length > 0 && (
                    <div>
                      <div style={designLabelStyle}>components</div>
                      <ul style={{ margin: '4px 0 0', paddingLeft: 16, fontSize: 12, color: '#d1d5db', display: 'flex', flexDirection: 'column', gap: 2 }}>
                        {design.components.map((c, i) => (
                          <li key={i}>{c}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {design.data_flow_summary && (
                    <div>
                      <div style={designLabelStyle}>data flow</div>
                      <p style={{ margin: '4px 0 0', fontSize: 12, lineHeight: 1.5, color: '#d1d5db' }}>
                        {design.data_flow_summary}
                      </p>
                    </div>
                  )}
                  {design.deployment_target && (
                    <div style={{ fontSize: 12, color: '#9ca3af' }}>
                      <span style={designLabelStyle}>deploy → </span>
                      {design.deployment_target}
                    </div>
                  )}
                  {design.build_effort_estimate && (
                    <div style={{ fontSize: 12, color: '#9ca3af' }}>
                      <span style={designLabelStyle}>effort → </span>
                      {design.build_effort_estimate}
                    </div>
                  )}
                  {design.risks.length > 0 && (
                    <div>
                      <div style={designLabelStyle}>risks</div>
                      <ul style={{ margin: '4px 0 0', paddingLeft: 16, fontSize: 12, color: '#fca5a5', display: 'flex', flexDirection: 'column', gap: 2 }}>
                        {design.risks.map((r, i) => (
                          <li key={i}>{r}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {design.open_questions.length > 0 && (
                    <div>
                      <div style={designLabelStyle}>open questions</div>
                      <ul style={{ margin: '4px 0 0', paddingLeft: 16, fontSize: 12, color: '#9ca3af', display: 'flex', flexDirection: 'column', gap: 2 }}>
                        {design.open_questions.map((q, i) => (
                          <li key={i}>{q}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                  <button onClick={resetDesign} style={retryButtonStyle}>
                    clear design
                  </button>
                </div>
              )}
            </section>
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

const retryButtonStyle: React.CSSProperties = {
  background: 'transparent',
  color: '#9ca3af',
  border: '1px solid #2a2f3a',
  borderRadius: 4,
  padding: '2px 8px',
  cursor: 'pointer',
  fontSize: 11,
};

const designButtonStyle: React.CSSProperties = {
  width: '100%',
  padding: '8px 12px',
  background: '#3b82f6',
  color: 'white',
  border: 'none',
  borderRadius: 6,
  cursor: 'pointer',
  fontSize: 13,
  fontWeight: 500,
};

const designLabelStyle: React.CSSProperties = {
  fontSize: 11,
  fontWeight: 600,
  textTransform: 'uppercase',
  letterSpacing: 0.6,
  color: '#6b7280',
};
