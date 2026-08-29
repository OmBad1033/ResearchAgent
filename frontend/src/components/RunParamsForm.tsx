// RunParamsForm — modal overlay shown on first load. Collects the inputs
// that go into the session-start frame per contract.md §"Session start":
//   - domain (required)
//   - hitl_mode (required)
//   - report_focus (optional)
//   - max_opportunities (optional, integer)
//
// Calls onSubmit with the parsed params; the parent owns submission so it
// can wire the values into the socket hook.

import { useState, type FormEvent } from 'react';
import type { HitlMode, RunParams } from '../types';

export type RunParamsFormProps = {
  onSubmit: (params: RunParams) => void;
};

export function RunParamsForm({ onSubmit }: RunParamsFormProps) {
  const [domain, setDomain] = useState('');
  const [hitlMode, setHitlMode] = useState<HitlMode>('ai');
  const [reportFocus, setReportFocus] = useState('');
  const [maxOpportunities, setMaxOpportunities] = useState('');
  const [error, setError] = useState<string | null>(null);

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const trimmedDomain = domain.trim();
    if (!trimmedDomain) {
      setError('domain is required');
      return;
    }
    let parsedMax: number | undefined;
    if (maxOpportunities.trim() !== '') {
      const n = Number(maxOpportunities);
      if (!Number.isInteger(n) || n < 1) {
        setError('max opportunities must be a positive integer');
        return;
      }
      parsedMax = n;
    }
    setError(null);
    onSubmit({
      domain: trimmedDomain,
      hitlMode,
      reportFocus: reportFocus.trim() || undefined,
      maxOpportunities: parsedMax,
    });
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(15, 17, 21, 0.85)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 100,
      }}
    >
      <form
        onSubmit={handleSubmit}
        style={{
          background: '#161922',
          border: '1px solid #2a2f3a',
          borderRadius: 10,
          padding: 28,
          width: 460,
          maxWidth: '90vw',
          display: 'flex',
          flexDirection: 'column',
          gap: 16,
          boxShadow: '0 20px 60px rgba(0,0,0,0.5)',
        }}
      >
        <div>
          <h2 style={{ margin: '0 0 4px', fontSize: 18, fontWeight: 600 }}>start a research run</h2>
          <p style={{ margin: 0, fontSize: 12, color: '#9ca3af' }}>
            these inputs set the agenda for the agent. you can leave the optional ones blank.
          </p>
        </div>

        <Field label="domain" required>
          <input
            type="text"
            value={domain}
            onChange={(e) => setDomain(e.target.value)}
            placeholder="e.g. fintech, elder care"
            autoFocus
            style={inputStyle}
          />
        </Field>

        <Field label="approval mode" required>
          <div style={{ display: 'flex', gap: 8 }}>
            {(['ai', 'human'] as const).map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => setHitlMode(m)}
                style={{
                  flex: 1,
                  padding: '8px 12px',
                  borderRadius: 6,
                  border: `1px solid ${hitlMode === m ? '#3b82f6' : '#2a2f3a'}`,
                  background: hitlMode === m ? '#1e3a8a' : 'transparent',
                  color: hitlMode === m ? '#dbeafe' : '#9ca3af',
                  cursor: 'pointer',
                  fontSize: 13,
                  fontWeight: 500,
                }}
              >
                {m === 'ai' ? 'AI decides autonomously' : 'human approval'}
              </button>
            ))}
          </div>
        </Field>

        <Field label="report focus" hint="optional steer for the synthesis step">
          <input
            type="text"
            value={reportFocus}
            onChange={(e) => setReportFocus(e.target.value)}
            placeholder='e.g. "B2B SaaS", "early-stage"'
            style={inputStyle}
          />
        </Field>

        <Field label="max opportunities" hint="optional cap on parallel fan-out (1–20)">
          <input
            type="number"
            min={1}
            max={20}
            value={maxOpportunities}
            onChange={(e) => setMaxOpportunities(e.target.value)}
            placeholder="leave blank for no cap"
            style={inputStyle}
          />
        </Field>

        {error && (
          <div style={{ color: '#fca5a5', fontSize: 12 }}>{error}</div>
        )}

        <button
          type="submit"
          style={{
            marginTop: 4,
            padding: '10px 16px',
            background: '#3b82f6',
            color: 'white',
            border: 'none',
            borderRadius: 6,
            cursor: 'pointer',
            fontSize: 14,
            fontWeight: 500,
          }}
        >
          start run
        </button>
      </form>
    </div>
  );
}

function Field({
  label,
  required,
  hint,
  children,
}: {
  label: string;
  required?: boolean;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <label style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <span style={{ fontSize: 12, fontWeight: 500, color: '#d1d5db' }}>
        {label}
        {required && <span style={{ color: '#fca5a5' }}> *</span>}
      </span>
      {children}
      {hint && <span style={{ fontSize: 11, color: '#6b7280' }}>{hint}</span>}
    </label>
  );
}

const inputStyle: React.CSSProperties = {
  padding: '8px 12px',
  borderRadius: 6,
  border: '1px solid #2a2f3a',
  background: '#0f1115',
  color: '#e6e6e6',
  fontSize: 13,
  fontFamily: 'inherit',
};
