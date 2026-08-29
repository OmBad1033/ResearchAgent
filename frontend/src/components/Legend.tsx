// Legend — small overlay that explains the status colors. Lives in the top-left
// so it doesn't collide with the run-completed badge in the top-right.

const ROWS: Array<{ color: string; label: string }> = [
  { color: '#3a3f4b', label: 'idle' },
  { color: '#3b82f6', label: 'running' },
  { color: '#22c55e', label: 'completed' },
  { color: '#ef4444', label: 'error' },
];

export function Legend() {
  return (
    <div
      style={{
        position: 'absolute',
        top: 12,
        left: 12,
        background: 'rgba(22, 25, 34, 0.92)',
        border: '1px solid #2a2f3a',
        borderRadius: 6,
        padding: '8px 12px',
        fontSize: 11,
        color: '#d1d5db',
        zIndex: 5,
        backdropFilter: 'blur(4px)',
      }}
    >
      <div style={{ fontWeight: 600, marginBottom: 6, textTransform: 'uppercase', letterSpacing: 0.5, fontSize: 10, color: '#9ca3af' }}>
        status
      </div>
      {ROWS.map((r) => (
        <div key={r.label} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '2px 0' }}>
          <span
            style={{
              display: 'inline-block',
              width: 12,
              height: 12,
              borderRadius: 3,
              background: 'transparent',
              border: `2px solid ${r.color}`,
            }}
          />
          <span>{r.label}</span>
        </div>
      ))}
    </div>
  );
}
