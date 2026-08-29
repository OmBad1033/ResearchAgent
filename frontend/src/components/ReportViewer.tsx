// ReportViewer — renders the synthesis report as markdown. Two layouts:
//   - "modal" (default): centered card overlay, used to auto-open when a
//     run completes.
//   - "drawer": full-height side panel (kept for re-opening later).
// Polls GET /runs/{runId}/report while the report isn't ready (404),
// then renders markdown via react-markdown + remark-gfm.

import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useRunReport } from '../hooks/useRunReport';

export type ReportViewerVariant = 'modal' | 'drawer';

export type ReportViewerProps = {
  runId: string;
  open: boolean;
  onClose: () => void;
  variant?: ReportViewerVariant;
};

export function ReportViewer({ runId, open, onClose, variant = 'modal' }: ReportViewerProps) {
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
          <ReportBody runId={runId} onClose={onClose} />
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
        <ReportBody runId={runId} onClose={onClose} />
      </div>
    </div>
  );
}

function ReportBody({ runId, onClose }: { runId: string; onClose: () => void }) {
  const { data, loading, notReady, error, refetch } = useRunReport(runId, { pollUntilReady: true });

  return (
    <>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <h2 style={{ margin: 0, fontSize: 18, fontWeight: 600 }}>research report</h2>
        <button onClick={onClose} style={closeButtonStyle}>close</button>
      </div>

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
