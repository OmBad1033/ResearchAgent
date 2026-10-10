// ArchitectDesignReport — multi-page solution-design report, one page
// per opportunity. Each page renders a single SolutionDesign (stack,
// components, data flow, deploy, effort, risks, open questions) with
// prev/next + a page picker to move between opportunities.
//
// Used two ways:
//   1. Inside ArchitectGraphView — single page for the just-designed
//      opportunity (auto-opens when the design POST resolves).
//   2. (Future) multi-opportunity runs can pass several pages at once.

import { useState } from 'react';
import type { SolutionDesign } from '../types';
import type { ArchitectOpportunity } from '../ArchitectGraphView';

export type ArchitectDesignPage = {
  opportunity: ArchitectOpportunity;
  design: SolutionDesign;
};

export type ArchitectDesignReportProps = {
  open: boolean;
  pages: ArchitectDesignPage[];
  initialPage?: number;
  onClose: () => void;
};

export function ArchitectDesignReport({ open, pages, initialPage = 0, onClose }: ArchitectDesignReportProps) {
  const [pageIdx, setPageIdx] = useState(initialPage);
  if (!open || pages.length === 0) return null;

  const safeIdx = Math.min(Math.max(pageIdx, 0), pages.length - 1);
  const page = pages[safeIdx];
  const multi = pages.length > 1;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Architect solution design"
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
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
          <h2 style={{ margin: 0, fontSize: 18, fontWeight: 600 }}>solution design</h2>
          <button onClick={onClose} style={closeButtonStyle}>close</button>
        </div>

        <div style={{ fontSize: 13, color: '#9ca3af', marginBottom: 4 }}>{page.opportunity.title}</div>
        <p style={{ margin: '0 0 16px', fontSize: 12, color: '#6b7280', lineHeight: 1.5 }}>
          {page.opportunity.description}
        </p>

        {multi && (
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 16 }}>
            <button
              onClick={() => setPageIdx((i) => Math.max(i - 1, 0))}
              disabled={safeIdx === 0}
              style={{ ...navButtonStyle, opacity: safeIdx === 0 ? 0.4 : 1 }}
            >
              ← prev
            </button>
            <span style={{ fontSize: 12, color: '#9ca3af' }}>
              page {safeIdx + 1} of {pages.length}
            </span>
            <button
              onClick={() => setPageIdx((i) => Math.min(i + 1, pages.length - 1))}
              disabled={safeIdx === pages.length - 1}
              style={{ ...navButtonStyle, opacity: safeIdx === pages.length - 1 ? 0.4 : 1 }}
            >
              next →
            </button>
            <select
              value={safeIdx}
              onChange={(e) => setPageIdx(Number(e.target.value))}
              style={selectStyle}
            >
              {pages.map((p, i) => (
                <option key={p.opportunity.id} value={i}>
                  {i + 1}. {p.opportunity.title}
                </option>
              ))}
            </select>
          </div>
        )}

        <div style={{ display: 'flex', flexDirection: 'column', gap: 14, fontSize: 13 }}>
          {page.design.proposed_stack.length > 0 && (
            <section>
              <h4 style={sectionHeadingStyle}>stack</h4>
              <div style={{ fontSize: 13, color: '#d1d5db' }}>{page.design.proposed_stack.join(', ')}</div>
            </section>
          )}
          {page.design.components.length > 0 && (
            <section>
              <h4 style={sectionHeadingStyle}>components</h4>
              <ul style={listStyle}>
                {page.design.components.map((c, i) => (
                  <li key={i}>{c}</li>
                ))}
              </ul>
            </section>
          )}
          {page.design.data_flow_summary && (
            <section>
              <h4 style={sectionHeadingStyle}>data flow</h4>
              <p style={{ margin: 0, fontSize: 13, lineHeight: 1.6, color: '#d1d5db' }}>
                {page.design.data_flow_summary}
              </p>
            </section>
          )}
          {page.design.deployment_target && (
            <div style={{ fontSize: 13, color: '#9ca3af' }}>
              <span style={sectionHeadingStyle}>deploy → </span>
              {page.design.deployment_target}
            </div>
          )}
          {page.design.build_effort_estimate && (
            <div style={{ fontSize: 13, color: '#9ca3af' }}>
              <span style={sectionHeadingStyle}>effort → </span>
              {page.design.build_effort_estimate}
            </div>
          )}
          {page.design.risks.length > 0 && (
            <section>
              <h4 style={sectionHeadingStyle}>risks</h4>
              <ul style={{ ...listStyle, color: '#fca5a5' }}>
                {page.design.risks.map((r, i) => (
                  <li key={i}>{r}</li>
                ))}
              </ul>
            </section>
          )}
          {page.design.open_questions.length > 0 && (
            <section>
              <h4 style={sectionHeadingStyle}>open questions</h4>
              <ul style={{ ...listStyle, color: '#9ca3af' }}>
                {page.design.open_questions.map((q, i) => (
                  <li key={i}>{q}</li>
                ))}
              </ul>
            </section>
          )}
        </div>
      </div>
    </div>
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

const navButtonStyle: React.CSSProperties = {
  background: 'transparent',
  border: '1px solid #2a2f3a',
  color: '#9ca3af',
  borderRadius: 4,
  padding: '4px 10px',
  cursor: 'pointer',
  fontSize: 12,
};

const selectStyle: React.CSSProperties = {
  background: '#0f1115',
  color: '#e6e6e6',
  border: '1px solid #2a2f3a',
  borderRadius: 4,
  padding: '4px 8px',
  fontSize: 12,
  maxWidth: 320,
};

const sectionHeadingStyle: React.CSSProperties = {
  margin: '0 0 6px',
  fontSize: 11,
  fontWeight: 600,
  textTransform: 'uppercase',
  letterSpacing: 0.6,
  color: '#6b7280',
};

const listStyle: React.CSSProperties = {
  margin: '4px 0 0',
  paddingLeft: 16,
  fontSize: 13,
  color: '#d1d5db',
  display: 'flex',
  flexDirection: 'column',
  gap: 4,
  lineHeight: 1.5,
};
