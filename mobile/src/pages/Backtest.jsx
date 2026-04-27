import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/services/api'
import { useAuthStore } from '@/store/useAuthStore'
import TopBar from '@/components/TopBar'
import { PageSpinner } from '@/components/ui/Spinner'
import { formatPnl, pnlColor, timeAgo, hasTier } from '@/utils/helpers'
import { Play, ChevronDown, ChevronUp, Lock } from 'lucide-react'
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts'

const PAIRS = ['BTCUSDT','ETHUSDT','SOLUSDT','BNBUSDT','XRPUSDT','DOGEUSDT','ADAUSDT','AVAXUSDT']

function RunCard({ run, expanded, onToggle }) {
  const ok = run.status === 'completed' || run.sharpe != null
  return (
    <div className="card mx-4 mb-3 overflow-hidden">
      <div className="flex items-center justify-between p-4 cursor-pointer" onClick={onToggle}>
        <div>
          <div className="flex items-center gap-2 mb-0.5">
            <span className="font-mono font-bold text-sm">{run.pair?.replace('USDT','')}</span>
            <span style={{ fontSize: '11px', color: 'var(--color-dim)' }}>{run.days}d · {run.timeframe}</span>
          </div>
          <div className="flex gap-3 mt-1">
            {run.win_rate != null && (
              <span style={{ fontSize: '12px', color: 'var(--color-green)', fontWeight: 700 }}>WR {run.win_rate}%</span>
            )}
            {run.total_pnl != null && (
              <span style={{ fontSize: '12px', fontWeight: 700, color: pnlColor(run.total_pnl) }}>{formatPnl(run.total_pnl)}</span>
            )}
          </div>
        </div>
        {expanded ? <ChevronUp size={16} style={{ color: 'var(--color-dim)' }} /> : <ChevronDown size={16} style={{ color: 'var(--color-dim)' }} />}
      </div>

      {expanded && ok && (
        <div style={{ borderTop: '1px solid var(--color-border)', padding: '12px 16px' }}>
          <div className="grid grid-cols-2 gap-3 mb-4">
            {[
              { l: 'Sharpe', v: run.sharpe?.toFixed(2) ?? '—' },
              { l: 'Max DD', v: run.max_drawdown != null ? formatPnl(run.max_drawdown) : '—' },
              { l: 'Profit Factor', v: run.profit_factor?.toFixed(2) ?? '—' },
              { l: 'Total Trades', v: run.total_trades ?? '—' },
            ].map(({ l, v }) => (
              <div key={l} className="card p-3">
                <div style={{ fontSize: '10px', color: 'var(--color-dim)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 3 }}>{l}</div>
                <div className="font-mono font-bold text-sm">{v}</div>
              </div>
            ))}
          </div>

          {run.equity_curve?.length > 0 && (
            <ResponsiveContainer width="100%" height={120}>
              <AreaChart data={run.equity_curve} margin={{ top: 0, right: 0, left: -28, bottom: 0 }}>
                <defs>
                  <linearGradient id="btGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#E4C375" stopOpacity={0.2} />
                    <stop offset="95%" stopColor="#E4C375" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="rgba(255,255,255,0.04)" vertical={false} />
                <XAxis dataKey="date" hide />
                <YAxis tickFormatter={v => `${v}%`} style={{ fontSize: 9, fill: 'var(--color-dim)' }} />
                <Tooltip formatter={v => [`${v?.toFixed?.(2)}%`, 'PnL']} contentStyle={{ background: 'var(--color-surface-2)', border: '1px solid var(--color-border)', borderRadius: 8, fontSize: 11 }} />
                <Area type="monotone" dataKey="pnl" stroke="#E4C375" strokeWidth={1.5} fill="url(#btGrad)" dot={false} />
              </AreaChart>
            </ResponsiveContainer>
          )}
        </div>
      )}
    </div>
  )
}

export default function Backtest() {
  const { user } = useAuthStore()
  const qc = useQueryClient()
  const [expandedId, setExpandedId] = useState(null)
  const [form, setForm] = useState({ pair: 'BTCUSDT', days: 30, timeframe: '1h' })

  const { data: runs, isLoading } = useQuery({
    queryKey: ['backtest-list'],
    queryFn: () => api.get('/api/backtest/list').then(r => r.data),
  })

  const runMutation = useMutation({
    mutationFn: (params) => api.post('/api/backtest/run', params).then(r => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['backtest-list'] }),
  })

  const isTierOk = hasTier(user, 'pro')

  if (!isTierOk) {
    return (
      <>
        <TopBar title="Backtesting" />
        <div className="flex flex-col items-center justify-center px-6 pt-20 text-center gap-4">
          <Lock size={48} style={{ color: 'var(--color-gold)', opacity: 0.6 }} />
          <h2 style={{ fontSize: '20px', fontWeight: 800 }}>Pro Plan Required</h2>
          <p style={{ color: 'var(--color-dim)', fontSize: '14px', maxWidth: 280 }}>Backtesting is available on Pro and Elite plans.</p>
          <a href="/app" className="btn-gold" style={{ display: 'inline-block', width: 'auto', padding: '12px 32px' }}>Upgrade</a>
        </div>
      </>
    )
  }

  const list = Array.isArray(runs) ? runs : (runs?.runs ?? [])

  return (
    <>
      <TopBar title="Backtesting" />
      <div className="pt-4">
        <div className="card mx-4 mb-4 p-4">
          <div style={{ fontSize: '13px', fontWeight: 700, color: 'var(--color-dim)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 14 }}>
            New Backtest
          </div>
          <div className="grid grid-cols-2 gap-3 mb-3">
            <div>
              <label style={{ fontSize: '11px', color: 'var(--color-dim)', fontWeight: 600, display: 'block', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Pair</label>
              <select
                value={form.pair}
                onChange={e => setForm(p => ({ ...p, pair: e.target.value }))}
                className="input-field"
                style={{ paddingTop: 10, paddingBottom: 10, fontSize: 13 }}
              >
                {PAIRS.map(p => <option key={p} value={p}>{p.replace('USDT', '')}</option>)}
              </select>
            </div>
            <div>
              <label style={{ fontSize: '11px', color: 'var(--color-dim)', fontWeight: 600, display: 'block', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Timeframe</label>
              <select
                value={form.timeframe}
                onChange={e => setForm(p => ({ ...p, timeframe: e.target.value }))}
                className="input-field"
                style={{ paddingTop: 10, paddingBottom: 10, fontSize: 13 }}
              >
                {['15m','1h','4h','1d'].map(t => <option key={t} value={t}>{t}</option>)}
              </select>
            </div>
          </div>
          <div className="mb-3">
            <label style={{ fontSize: '11px', color: 'var(--color-dim)', fontWeight: 600, display: 'block', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Period</label>
            <div className="flex gap-2">
              {[7, 14, 30, 60, 90].map(d => (
                <button key={d} onClick={() => setForm(p => ({ ...p, days: d }))}
                  style={{
                    flex: 1, padding: '8px 0', borderRadius: 8, border: '1px solid',
                    fontSize: '12px', fontWeight: 700, cursor: 'pointer',
                    borderColor: form.days === d ? 'var(--color-gold)' : 'var(--color-border)',
                    background: form.days === d ? 'rgba(228,195,117,0.15)' : 'rgba(255,255,255,0.02)',
                    color: form.days === d ? 'var(--color-gold)' : 'var(--color-dim)',
                  }}
                >{d}d</button>
              ))}
            </div>
          </div>
          <button
            className="btn-gold"
            onClick={() => runMutation.mutate(form)}
            disabled={runMutation.isPending}
            style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8 }}
          >
            <Play size={16} />
            {runMutation.isPending ? 'Running…' : 'Run Backtest'}
          </button>
          {runMutation.isError && (
            <p style={{ fontSize: '12px', color: 'var(--color-red)', marginTop: 8 }}>
              {runMutation.error?.response?.data?.detail ?? 'Run failed.'}
            </p>
          )}
        </div>

        {isLoading ? <PageSpinner /> : list.length === 0 ? (
          <p style={{ color: 'var(--color-dim)', fontSize: '13px', textAlign: 'center', padding: '24px 0' }}>No backtests yet.</p>
        ) : (
          list.map((run, i) => (
            <RunCard key={run.id ?? i} run={run}
              expanded={expandedId === (run.id ?? i)}
              onToggle={() => setExpandedId(p => p === (run.id ?? i) ? null : (run.id ?? i))} />
          ))
        )}
      </div>
    </>
  )
}
