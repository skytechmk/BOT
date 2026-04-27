import { useQuery } from '@tanstack/react-query'
import { api } from '@/services/api'
import { useAuthStore } from '@/store/useAuthStore'
import TopBar from '@/components/TopBar'
import StatCard from '@/components/ui/StatCard'
import { PageSpinner } from '@/components/ui/Spinner'
import { formatPnl, pnlColor, cleanPair, hasTier } from '@/utils/helpers'
import {
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
} from 'recharts'
import { Lock } from 'lucide-react'

function CustomTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null
  return (
    <div style={{
      background: 'var(--color-surface-2)',
      border: '1px solid var(--color-border)',
      borderRadius: 8,
      padding: '8px 12px',
      fontSize: 12,
    }}>
      <div style={{ color: 'var(--color-dim)', marginBottom: 4 }}>{label}</div>
      <div style={{ color: 'var(--color-gold)', fontWeight: 700 }}>
        {formatPnl(payload[0]?.value)}
      </div>
    </div>
  )
}

export default function Analytics() {
  const { user } = useAuthStore()
  const isPlusTier = hasTier(user, 'plus')

  const { data: summary, isLoading } = useQuery({
    queryKey: ['analytics-summary'],
    queryFn: () => api.get('/api/analytics/summary?days=30').then(r => r.data),
    enabled: isPlusTier,
  })

  const { data: equity } = useQuery({
    queryKey: ['analytics-equity'],
    queryFn: () => api.get('/api/analytics/equity?days=30').then(r => r.data),
    enabled: isPlusTier,
  })

  const { data: pairs } = useQuery({
    queryKey: ['analytics-pairs'],
    queryFn: () => api.get('/api/analytics/pairs?days=30').then(r => r.data),
    enabled: isPlusTier,
  })

  if (!isPlusTier) {
    return (
      <>
        <TopBar title="Analytics" />
        <div className="flex flex-col items-center justify-center px-6 pt-20 text-center gap-4">
          <Lock size={48} style={{ color: 'var(--color-gold)', opacity: 0.6 }} />
          <h2 style={{ fontSize: '20px', fontWeight: 800 }}>Plus Plan Required</h2>
          <p style={{ color: 'var(--color-dim)', fontSize: '14px', maxWidth: 280 }}>
            Detailed analytics are available on Plus and above.
          </p>
          <a href="/app" className="btn-gold" style={{ display: 'inline-block', width: 'auto', padding: '12px 32px' }}>
            Upgrade
          </a>
        </div>
      </>
    )
  }

  if (isLoading) return <><TopBar title="Analytics" /><PageSpinner /></>

  const equityPoints = equity?.data ?? equity?.equity ?? []
  const topPairs = Array.isArray(pairs) ? pairs.slice(0, 8) : (pairs?.pairs ?? []).slice(0, 8)

  return (
    <>
      <TopBar title="Analytics" />
      <div className="px-4 pt-4">
        <div className="grid grid-cols-2 gap-3 mb-5">
          <StatCard
            label="Win Rate"
            value={summary?.win_rate ? `${summary.win_rate}%` : '—'}
            sub="30 days"
            valueStyle={{ color: 'var(--color-green)' }}
          />
          <StatCard
            label="Total PnL"
            value={summary?.total_pnl != null ? formatPnl(summary.total_pnl) : '—'}
            sub="30 days"
            valueStyle={{ color: pnlColor(summary?.total_pnl) }}
          />
          <StatCard
            label="Total Signals"
            value={summary?.total_signals ?? '—'}
            sub="closed"
          />
          <StatCard
            label="Avg PnL"
            value={summary?.avg_pnl != null ? formatPnl(summary.avg_pnl) : '—'}
            sub="per signal"
            valueStyle={{ color: pnlColor(summary?.avg_pnl) }}
          />
        </div>

        {equityPoints.length > 0 && (
          <div className="card p-4 mb-5">
            <span style={{ fontSize: '13px', fontWeight: 700, color: 'var(--color-dim)', letterSpacing: '0.05em', textTransform: 'uppercase', display: 'block', marginBottom: 16 }}>
              Equity Curve (30d)
            </span>
            <ResponsiveContainer width="100%" height={160}>
              <AreaChart data={equityPoints} margin={{ top: 0, right: 0, left: -24, bottom: 0 }}>
                <defs>
                  <linearGradient id="goldGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#E4C375" stopOpacity={0.25} />
                    <stop offset="95%" stopColor="#E4C375" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="rgba(255,255,255,0.04)" vertical={false} />
                <XAxis dataKey="date" hide />
                <YAxis tickFormatter={v => `${v}%`} style={{ fontSize: 10, fill: 'var(--color-dim)' }} />
                <Tooltip content={<CustomTooltip />} />
                <Area
                  type="monotone"
                  dataKey="cumulative_pnl"
                  stroke="#E4C375"
                  strokeWidth={2}
                  fill="url(#goldGrad)"
                  dot={false}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        )}

        {topPairs.length > 0 && (
          <div className="card px-4 py-3 mb-5">
            <span style={{ fontSize: '13px', fontWeight: 700, color: 'var(--color-dim)', letterSpacing: '0.05em', textTransform: 'uppercase', display: 'block', marginBottom: 12 }}>
              Top Pairs
            </span>
            {topPairs.map((p, i) => (
              <div key={i} className="flex items-center justify-between py-2" style={{ borderBottom: '1px solid var(--color-border)' }}>
                <div className="flex items-center gap-2">
                  <span style={{ fontSize: '11px', color: 'var(--color-dimmer)', width: 16 }}>{i + 1}</span>
                  <span className="font-mono font-bold text-sm">{cleanPair(p.pair)}</span>
                </div>
                <div className="flex items-center gap-4">
                  <span style={{ fontSize: '11px', color: 'var(--color-dim)' }}>{p.count ?? p.signals} signals</span>
                  <span className="font-mono font-bold text-sm" style={{ color: pnlColor(p.avg_pnl ?? p.pnl) }}>
                    {formatPnl(p.avg_pnl ?? p.pnl)}
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </>
  )
}
