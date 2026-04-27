export default function StatCard({ label, value, sub, valueStyle }) {
  return (
    <div className="card p-4 flex flex-col gap-1">
      <span style={{ fontSize: '11px', color: 'var(--color-dim)', fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase' }}>
        {label}
      </span>
      <span style={{ fontSize: '22px', fontWeight: 800, fontFamily: 'var(--font-mono)', ...valueStyle }}>
        {value ?? '—'}
      </span>
      {sub && (
        <span style={{ fontSize: '12px', color: 'var(--color-dim)' }}>{sub}</span>
      )}
    </div>
  )
}
