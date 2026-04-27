import { useQuery } from '@tanstack/react-query'
import { api } from '@/services/api'
import { useAuthStore } from '@/store/useAuthStore'
import TopBar from '@/components/TopBar'
import { PageSpinner } from '@/components/ui/Spinner'
import { cleanPair, formatPrice, formatPnl, pnlColor } from '@/utils/helpers'
import { Lock, TestTube2, AlertTriangle } from 'lucide-react'

function LabSignalCard({ s }) {
  const isLong = s.direction === 'LONG'
  return (
    <div className="card mb-3 p-3">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span className="font-mono font-bold">{cleanPair(s.pair)}</span>
          <span className={isLong ? 'badge-long' : 'badge-short'}>{s.direction}</span>
          <span style={{ fontSize: 9, fontWeight: 700, padding: '2px 6px', borderRadius: 4, background: 'var(--color-surface-2)', border: '1px solid var(--color-border)', color: 'var(--color-text)', textTransform: 'uppercase' }}>
            {s.status}
          </span>
        </div>
        <div className="font-mono font-bold" style={{ color: pnlColor(s.pnl), fontSize: 14 }}>
          {formatPnl(s.pnl)}
        </div>
      </div>
      
      <div style={{ fontSize: 11, color: 'var(--color-dim)', background: 'rgba(255,107,157,0.08)', border: '1px solid rgba(255,107,157,0.2)', padding: '4px 8px', borderRadius: 6, marginBottom: 8, display: 'inline-block' }}>
        <strong>Path:</strong> {s.path_name || s.rule_matched || 'Experimental'}
      </div>

      <div className="grid grid-cols-2 gap-2 mt-2 pt-2" style={{ borderTop: '1px solid var(--color-border)' }}>
        <div>
          <div style={{ fontSize: 10, color: 'var(--color-dim)' }}>Entry</div>
          <div className="font-mono font-bold text-sm">{formatPrice(s.entry_price)}</div>
        </div>
        <div className="text-right">
          <div style={{ fontSize: 10, color: 'var(--color-dim)' }}>Stop Loss</div>
          <div className="font-mono font-bold text-sm" style={{ color: 'var(--color-red)' }}>{formatPrice(s.sl_price)}</div>
        </div>
      </div>
    </div>
  )
}

function PathStatRow({ path, stat }) {
  return (
    <div className="flex justify-between items-center py-2" style={{ borderBottom: '1px solid var(--color-border)' }}>
      <div style={{ fontSize: 12, fontWeight: 600 }}>{path}</div>
      <div className="text-right">
        <div style={{ fontSize: 12, fontWeight: 700, color: stat.win_rate >= 50 ? 'var(--color-green)' : 'var(--color-red)' }}>
          {stat.win_rate?.toFixed(1) ?? 0}% WR
        </div>
        <div style={{ fontSize: 10, color: 'var(--color-dim)' }}>
          {stat.total ?? 0} signals
        </div>
      </div>
    </div>
  )
}

export default function Lab() {
  const { user } = useAuthStore()

  const { data, isLoading } = useQuery({
    queryKey: ['lab-signals'],
    queryFn: () => api.get('/api/admin/lab/signals').then(r => r.data),
    enabled: !!user?.is_admin,
  })

  if (!user?.is_admin) {
    return (
      <>
        <TopBar title="Admin Lab" />
        <div className="flex flex-col items-center justify-center px-6 pt-20 text-center gap-4">
          <Lock size={48} style={{ color: 'var(--color-red)', opacity: 0.6 }} />
          <h2 style={{ fontSize: '20px', fontWeight: 800 }}>Admin Only</h2>
          <p style={{ color: 'var(--color-dim)', fontSize: '14px', maxWidth: 280 }}>
            This section contains experimental signals and is restricted to administrators.
          </p>
        </div>
      </>
    )
  }

  const signals = data?.signals ?? []
  const stats = data?.path_stats ?? {}

  return (
    <>
      <TopBar title="Admin Lab" />
      
      <div className="px-4 pt-4 pb-20">
        <div className="card p-4 mb-4" style={{ display: 'flex', alignItems: 'flex-start', gap: 12, border: '1px solid rgba(255,107,157,0.3)', background: 'rgba(255,107,157,0.05)' }}>
          <div style={{ background: 'rgba(255,107,157,0.15)', padding: 10, borderRadius: 10, color: '#ff6b9d' }}>
            <TestTube2 size={24} />
          </div>
          <div>
            <h3 style={{ fontSize: 14, fontWeight: 800, marginBottom: 4 }}>Experimental Paths</h3>
            <p style={{ fontSize: 12, color: 'var(--color-dim)', lineHeight: 1.4 }}>
              These signals bypass standard public flow. They are not sent to Telegram or Copy Trading.
            </p>
          </div>
        </div>

        {isLoading ? (
          <PageSpinner />
        ) : (
          <>
            <div className="card p-4 mb-4">
              <h3 style={{ fontSize: 13, fontWeight: 700, color: 'var(--color-dim)', textTransform: 'uppercase', marginBottom: 8 }}>Path Statistics</h3>
              {Object.keys(stats).length === 0 ? (
                <p style={{ fontSize: 12, color: 'var(--color-dim)' }}>No stats available.</p>
              ) : (
                Object.entries(stats).map(([k, v]) => <PathStatRow key={k} path={k} stat={v} />)
              )}
            </div>

            <div className="mb-2 flex items-center justify-between">
              <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--color-dim)', textTransform: 'uppercase' }}>Recent Lab Signals</span>
            </div>
            
            {signals.length === 0 ? (
              <p style={{ color: 'var(--color-dim)', fontSize: '13px', padding: '16px 0', textAlign: 'center' }}>No lab signals.</p>
            ) : (
              signals.map((s, i) => <LabSignalCard key={s.id ?? i} s={s} />)
            )}
          </>
        )}
      </div>
    </>
  )
}
