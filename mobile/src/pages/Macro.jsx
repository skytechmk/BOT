import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/services/api'
import TopBar from '@/components/TopBar'
import { PageSpinner } from '@/components/ui/Spinner'
import { Globe, TrendingDown, TrendingUp, AlertTriangle } from 'lucide-react'
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'

function MetricCard({ title, value, sub, trend, chartData, color }) {
  return (
    <div className="card p-4 mb-4">
      <div className="flex justify-between items-start mb-2">
        <div>
          <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--color-dim)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 4 }}>
            {title}
          </div>
          <div style={{ fontSize: 24, fontWeight: 800, color: color || 'var(--color-text)' }}>
            {value}
          </div>
          {sub && (
            <div style={{ fontSize: 12, color: 'var(--color-dim)', marginTop: 2 }}>
              {sub}
            </div>
          )}
        </div>
        {trend && (
          <div style={{ 
            display: 'flex', alignItems: 'center', gap: 4, fontSize: 12, fontWeight: 700,
            color: trend > 0 ? 'var(--color-green)' : trend < 0 ? 'var(--color-red)' : 'var(--color-dim)',
            background: trend > 0 ? 'rgba(16,185,129,0.1)' : trend < 0 ? 'rgba(239,68,68,0.1)' : 'transparent',
            padding: '2px 8px', borderRadius: 12
          }}>
            {trend > 0 ? <TrendingUp size={14} /> : trend < 0 ? <TrendingDown size={14} /> : null}
            {trend > 0 ? '+' : ''}{trend}%
          </div>
        )}
      </div>

      {chartData && chartData.length > 0 && (
        <div style={{ height: 60, marginTop: 12 }}>
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={chartData} margin={{ top: 0, right: 0, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id={`grad-${title}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor={color || '#a78bfa'} stopOpacity={0.3} />
                  <stop offset="95%" stopColor={color || '#a78bfa'} stopOpacity={0} />
                </linearGradient>
              </defs>
              <Area 
                type="monotone" 
                dataKey="value" 
                stroke={color || '#a78bfa'} 
                fill={`url(#grad-${title})`} 
                strokeWidth={2} 
                isAnimationActive={false} 
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  )
}

export default function Macro() {
  const [tf, setTf] = useState('1h')

  const { data: state, isLoading: stateLoading } = useQuery({
    queryKey: ['macro-state', tf],
    queryFn: () => api.get(`/api/macro/state?tf=${tf}`).then(r => r.data),
    refetchInterval: 60_000,
  })

  const { data: fg, isLoading: fgLoading } = useQuery({
    queryKey: ['macro-fear-greed'],
    queryFn: () => api.get('/api/macro/fear-greed').then(r => r.data),
    staleTime: 3600_000, // 1 hour
  })

  return (
    <>
      <TopBar title="Macro Environment" />
      
      <div className="px-4 pt-4 pb-20">
        <div className="card p-4 mb-4" style={{ display: 'flex', alignItems: 'flex-start', gap: 12 }}>
          <div style={{ background: 'rgba(167,139,250,0.15)', padding: 10, borderRadius: 10, color: '#a78bfa' }}>
            <Globe size={24} />
          </div>
          <div>
            <h3 style={{ fontSize: 14, fontWeight: 800, marginBottom: 4 }}>Macro State</h3>
            <p style={{ fontSize: 12, color: 'var(--color-dim)', lineHeight: 1.4 }}>
              Global market indicators that drive the bot's risk appetite and position sizing.
            </p>
          </div>
        </div>

        <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
          {['15m', '1h', '4h'].map(t => (
            <button
              key={t}
              onClick={() => setTf(t)}
              style={{
                flex: 1, padding: '8px 0', borderRadius: 8, fontSize: 12, fontWeight: 700,
                background: tf === t ? 'rgba(167,139,250,0.15)' : 'var(--color-surface-2)',
                color: tf === t ? '#a78bfa' : 'var(--color-dim)',
                border: `1px solid ${tf === t ? '#a78bfa' : 'var(--color-border)'}`
              }}
            >
              {t}
            </button>
          ))}
        </div>

        {stateLoading || fgLoading ? (
          <PageSpinner />
        ) : (
          <>
            {/* Market Regime */}
            <div className="card p-4 mb-4 text-center">
              <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--color-dim)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 8 }}>
                Current Market Regime
              </div>
              <div style={{ 
                display: 'inline-flex', alignItems: 'center', gap: 8, padding: '8px 16px', borderRadius: 12,
                background: state?.regime === 'RISK_ON' ? 'rgba(16,185,129,0.15)' : state?.regime === 'RISK_OFF' ? 'rgba(239,68,68,0.15)' : 'rgba(255,255,255,0.05)',
                color: state?.regime === 'RISK_ON' ? 'var(--color-green)' : state?.regime === 'RISK_OFF' ? 'var(--color-red)' : 'var(--color-text)',
                fontSize: 18, fontWeight: 800
              }}>
                {state?.regime === 'RISK_OFF' && <AlertTriangle size={20} />}
                {state?.regime?.replace('_', ' ') ?? 'NEUTRAL'}
              </div>
              {state?.regime === 'RISK_OFF' && (
                <p style={{ fontSize: 12, color: 'var(--color-red)', marginTop: 8 }}>
                  Bot is operating with reduced risk parameters.
                </p>
              )}
            </div>

            {/* Metrics */}
            <MetricCard 
              title="USDT Dominance" 
              value={`${state?.usdt_dom?.toFixed(2) ?? '—'}%`} 
              sub="Money flowing in/out of crypto"
              trend={state?.usdt_dom_roc_pct}
              chartData={state?.usdt_dom_history?.map((v, i) => ({ i, value: v }))}
              color={state?.usdt_dom_roc_pct > 0 ? 'var(--color-red)' : 'var(--color-green)'} // USDT.D up = crypto down
            />

            <MetricCard 
              title="BTC Dominance" 
              value={`${state?.btc_dom?.toFixed(2) ?? '—'}%`} 
              sub="Altcoin season indicator"
              trend={state?.btc_dom_roc_pct}
              chartData={state?.btc_dom_history?.map((v, i) => ({ i, value: v }))}
              color="#F7931A"
            />

            {fg && fg.data && fg.data[0] && (
              <MetricCard 
                title="Fear & Greed Index" 
                value={fg.data[0].value} 
                sub={fg.data[0].value_classification}
                color={fg.data[0].value < 40 ? 'var(--color-red)' : fg.data[0].value > 60 ? 'var(--color-green)' : 'var(--color-gold)'}
              />
            )}
          </>
        )}
      </div>
    </>
  )
}
