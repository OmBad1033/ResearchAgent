// ApprovalPanel — rendered inside HistoryDrawer when the selected
// node is human_approval and status is "running" (i.e. the run is
// paused waiting for the user's choice). Shows the discovered
// opportunities as checkboxes + "approve selected" / "approve all"
// buttons.
//
// Per contract.md §"REST: resume after human approval", the POST
// /resume body is { approved_opportunity_ids: [...] }. The backend
// also accepts ["__all__"] as a shorthand for approve-everything.

import { useState, useEffect } from 'react';
import type { OpportunitySummary } from '../types';
import { useRunOpportunities } from '../hooks/useRunOpportunities';
import { useResume } from '../hooks/useResume';

export type ApprovalPanelProps = {
  runId: string;
};

const SENTINEL_ALL = '__all__';

export function ApprovalPanel({ runId }: ApprovalPanelProps) {
  const { data, loading, error, refetch } = useRunOpportunities(runId, true);
  const { resume, submitting, error: resumeError } = useResume(runId);

  const opps: OpportunitySummary[] = data?.opportunities ?? [];

  // Default selection: check all. The user can uncheck what they
  // don't want — matches the contract's "approve_opportunity_ids"
  // semantics where omitting an id means "don't approve it".
  const [selected, setSelected] = useState<Set<string>>(() => new Set());

  // Re-seed selection whenever the opportunity list size changes
  // (e.g. the user refetches, or the run_id changes and a new list
  // arrives). Without this, the user would see zero boxes checked
  // on first render.
  useEffect(() => {
    if (opps.length > 0) {
      setSelected(new Set(opps.map((o) => o.id)));
    }
  }, [opps.length, opps]);

  const toggle = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleApproveSelected = async () => {
    await resume(Array.from(selected));
  };

  const handleApproveAll = async () => {
    await resume([SENTINEL_ALL]);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <p style={{ margin: 0, fontSize: 12, color: '#9ca3af' }}>
        the graph is paused at <code style={{ fontSize: 11 }}>human_approval</code>.
        pick which opportunities to deep-dive.
      </p>

      {loading && !data && (
        <div style={{ color: '#6b7280', fontSize: 12 }}>loading opportunities…</div>
      )}
      {error && (
        <div style={{ color: '#fca5a5', fontSize: 12 }}>
          failed to load: {error}
          <button
            onClick={refetch}
            style={retryButtonStyle}
          >
            retry
          </button>
        </div>
      )}

      {data && opps.length === 0 && (
        <div style={{ color: '#6b7280', fontSize: 12 }}>
          no opportunities were discovered — you can still approve an
          empty set to continue (the graph will go straight to
          synthesis with no deep-dive).
        </div>
      )}

      {data && opps.length > 0 && (
        <>
          <ul style={{ listStyle: 'none', padding: 0, margin: 0, display: 'flex', flexDirection: 'column', gap: 8 }}>
            {opps.map((opp) => {
              const isChecked = selected.has(opp.id);
              return (
                <li
                  key={opp.id}
                  style={{
                    background: '#0f1115',
                    border: '1px solid #2a2f3a',
                    borderRadius: 6,
                    padding: 10,
                    display: 'flex',
                    gap: 10,
                    alignItems: 'flex-start',
                  }}
                >
                  <input
                    type="checkbox"
                    checked={isChecked}
                    onChange={() => toggle(opp.id)}
                    disabled={submitting}
                    style={{ marginTop: 3, cursor: 'pointer' }}
                  />
                  <label
                    onClick={() => !submitting && toggle(opp.id)}
                    style={{
                      flex: 1,
                      cursor: submitting ? 'default' : 'pointer',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: 2,
                    }}
                  >
                    <span style={{ fontSize: 13, fontWeight: 500, color: '#e6e6e6' }}>
                      {opp.title || `Opportunity ${opp.id}`}
                    </span>
                    {opp.description && (
                      <span style={{ fontSize: 11, color: '#9ca3af', lineHeight: 1.4 }}>
                        {opp.description}
                      </span>
                    )}
                    <span style={{ fontSize: 10, color: '#6b7280' }}>id: {opp.id}</span>
                  </label>
                </li>
              );
            })}
          </ul>

          <div style={{ display: 'flex', gap: 8, marginTop: 4 }}>
            <button
              onClick={handleApproveSelected}
              disabled={submitting}
              style={{
                flex: 1,
                padding: '8px 12px',
                background: '#3b82f6',
                color: 'white',
                border: 'none',
                borderRadius: 6,
                cursor: submitting ? 'wait' : 'pointer',
                fontSize: 13,
                fontWeight: 500,
                opacity: submitting ? 0.7 : 1,
              }}
            >
              {submitting ? 'resuming…' : `approve selected (${selected.size})`}
            </button>
            <button
              onClick={handleApproveAll}
              disabled={submitting}
              style={{
                flex: 1,
                padding: '8px 12px',
                background: 'transparent',
                color: '#d1d5db',
                border: '1px solid #3b82f6',
                borderRadius: 6,
                cursor: submitting ? 'wait' : 'pointer',
                fontSize: 13,
                fontWeight: 500,
                opacity: submitting ? 0.7 : 1,
              }}
            >
              approve all
            </button>
          </div>

          {resumeError && (
            <div style={{ color: '#fca5a5', fontSize: 11 }}>
              resume failed: {resumeError}
            </div>
          )}

          <p style={{ margin: 0, fontSize: 11, color: '#6b7280' }}>
            selected: {selected.size} of {opps.length}
          </p>
        </>
      )}

      </div>
  );
}

const retryButtonStyle: React.CSSProperties = {
  marginLeft: 8,
  background: 'transparent',
  color: '#9ca3af',
  border: '1px solid #2a2f3a',
  borderRadius: 4,
  padding: '2px 8px',
  cursor: 'pointer',
  fontSize: 11,
};