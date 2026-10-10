// ReportViewer — renders the synthesis report as markdown. Two layouts:
//   - "modal" (default): centered card overlay, used to auto-open when a
//     run completes.
//   - "drawer": full-height side panel (kept for re-opening later).
// Polls GET /runs/{runId}/report while the report isn't ready (404),
// then renders markdown via react-markdown + remark-gfm.

import { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useRunReport } from '../hooks/useRunReport';
import { useRunOpportunities } from '../hooks/useRunOpportunities';

export type ReportViewerVariant = 'modal' | 'drawer';

export type ReportViewerProps = {
  runId: string;
  open: boolean;
  onClose: () => void;
  variant?: ReportViewerVariant;
  // Called when the user picks an opportunity and hits "deep dive".
  // The parent (GraphView) swaps to the full-screen architect graph.
  onDeepDive?: (oppId: string, title: string, description: string) => void;
};

export function ReportViewer({ runId, open, onClose, variant = 'modal', onDeepDive }: ReportViewerProps) {
  if (!open) return null;

  if (variant === 'drawer') {
    return (
      <div
        role="dialog"
        aria-modal="true"
        style={{
          position: 'fixed',
          inset: 0,
          background: 'rgba(15, 17, 21, 0.7)',
          zIndex: 50,
          display: 'flex',
          justifyContent: 'flex-end',
        }}
        onClick={onClose}
      >
        <aside
          onClick={(e) => e.stopPropagation()}
          style={{
            width: 'min(820px, 100vw)',
            height: '100vh',
            background: '#161922',
            borderLeft: '1px solid #2a2f3a',
            padding: '24px 32px',
            overflowY: 'auto',
            boxSizing: 'border-box',
          }}
        >
          <ReportBody runId={runId} onClose={onClose} onDeepDive={onDeepDive} />
        </aside>
      </div>
    );
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Research report"
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(15, 17, 21, 0.7)',
        zIndex: 50,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 24,
        boxSizing: 'border-box',
      }}
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: '#161922',
          border: '1px solid #2a2f3a',
          borderRadius: 12,
          boxShadow: '0 20px 60px rgba(0,0,0,0.6)',
          width: 'min(880px, 100%)',
          maxHeight: 'calc(100vh - 48px)',
          padding: '24px 32px',
          overflowY: 'auto',
          color: '#e6e6e6',
          boxSizing: 'border-box',
        }}
      >
        <ReportBody runId={runId} onClose={onClose} onDeepDive={onDeepDive} />
      </div>
    </div>
  );
}

function ReportBody({
  runId,
  onClose,
  onDeepDive,
}: {
  runId: string;
  onClose: () => void;
  onDeepDive?: (oppId: string, title: string, description: string) => void;
}) {
  const { data, loading, notReady, error, refetch } = useRunReport(runId, { pollUntilReady: true });
  // Opportunity picker for the deep-dive handoff. Fetched lazily only
  // when the user opens the picker, so the report modal stays fast.
  const [pickerOpen, setPickerOpen] = useState(false);
  const [selectedOppId, setSelectedOppId] = useState<string | null>(null);
  const { data: oppData, loading: oppLoading, error: oppError } = useRunOpportunities(runId, pickerOpen);

  const selectedOpp = oppData?.opportunities.find((o) => o.id === selectedOppId) ?? null;

  const handleDeepDive = () => {
    if (!selectedOpp || !onDeepDive) return;
    onDeepDive(selectedOpp.id, selectedOpp.title, selectedOpp.description);
  };

  return (
    <>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <h2 style={{ margin: 0, fontSize: 18, fontWeight: 600 }}>research report</h2>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          {onDeepDive && data && (
            <button onClick={() => setPickerOpen((v) => !v)} style={deepDiveButtonStyle}>
              deep dive
            </button>
          )}
          <button onClick={onClose} style={closeButtonStyle}>close</button>
        </div>
      </div>

      {pickerOpen && (
        <div style={pickerStyle}>
          <div style={{ fontSize: 12, fontWeight: 600, color: '#9ca3af', marginBottom: 8, textTransform: 'uppercase', letterSpacing: 0.5 }}>
            pick an opportunity to design
          </div>
          {oppLoading && <div style={{ color: '#6b7280', fontSize: 12 }}>loading opportunities…</div>}
          {oppError && <div style={{ color: '#fca5a5', fontSize: 12 }}>failed: {oppError}</div>}
          {oppData && oppData.opportunities.length === 0 && (
            <div style={{ color: '#6b7280', fontSize: 12 }}>no opportunities in this run.</div>
          )}
          {oppData && oppData.opportunities.length > 0 && (
            <>
              <select
                value={selectedOppId ?? ''}
                onChange={(e) => setSelectedOppId(e.target.value || null)}
                style={selectStyle}
              >
                <option value="">— choose —</option>
                {oppData.opportunities.map((o) => (
                  <option key={o.id} value={o.id}>
                    {o.title}
                  </option>
                ))}
              </select>
              {selectedOpp && (
                <p style={{ margin: '8px 0 0', fontSize: 12, color: '#9ca3af', lineHeight: 1.5 }}>
                  {selectedOpp.description}
                </p>
              )}
              <button
                onClick={handleDeepDive}
                disabled={!selectedOpp}
                style={{ ...deepDiveButtonStyle, marginTop: 10, opacity: selectedOpp ? 1 : 0.5, cursor: selectedOpp ? 'pointer' : 'default' }}
              >
                start architect deep dive →
              </button>
            </>
          )}
        </div>
      )}

      {loading && !data && (
        <div style={{ color: '#9ca3af', fontSize: 13 }}>
          {notReady ? 'synthesis hasn\'t finished yet — checking…' : 'loading report…'}
        </div>
      )}
      {error && (
        <div style={{ color: '#fca5a5', fontSize: 13 }}>
          failed to load report: {error}
          <button onClick={refetch} style={{ ...closeButtonStyle, marginLeft: 8 }}>retry</button>
        </div>
      )}
      {data && (
        <>
          <div style={{ fontSize: 11, color: '#6b7280', marginBottom: 16 }}>
            generated {new Date(data.generated_at).toLocaleString()}
          </div>
          <div className="report-markdown" style={markdownStyle}>
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{data.markdown}</ReactMarkdown>
          </div>
        </>
      )}
    </>
  );
}

const deepDiveButtonStyle: React.CSSProperties = {
  background: '#3b82f6',
  color: 'white',
  border: 'none',
  borderRadius: 4,
  padding: '4px 12px',
  cursor: 'pointer',
  fontSize: 12,
  fontWeight: 500,
};

const pickerStyle: React.CSSProperties = {
  background: '#0f1115',
  border: '1px solid #2a2f3a',
  borderRadius: 8,
  padding: 16,
  marginBottom: 16,
};

const selectStyle: React.CSSProperties = {
  width: '100%',
  background: '#161922',
  color: '#e6e6e6',
  border: '1px solid #2a2f3a',
  borderRadius: 4,
  padding: '6px 8px',
  fontSize: 13,
};

const closeButtonStyle: React.CSSProperties = {
  background: 'transparent',
  border: '1px solid #2a2f3a',
  color: '#9ca3af',
  borderRadius: 4,
  padding: '4px 10px',
  cursor: 'pointer',
  fontSize: 12,
};

const markdownStyle: React.CSSProperties = {
  color: '#e6e6e6',
  fontSize: 14,
  lineHeight: 1.6,
};
