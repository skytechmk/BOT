import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/services/api'
import { useAuthStore } from '@/store/useAuthStore'
import TopBar from '@/components/TopBar'
import { PageSpinner } from '@/components/ui/Spinner'
import { hasTier, cleanPair } from '@/utils/helpers'
import { Lock, RefreshCw, Monitor } from 'lucide-react'

const FILTERS = ['All', 'LONG', 'SHORT', 'NEUTRAL']

function ScreenerRow({ row }) {
  const isLong = row.signal_bias === 'LONG' || row.bias === 'LONG'
  const isShort = row.signal_bias === 'SHORT' || row.bias === 'SHORT'
  
  return (
    <div className="flex items-center gap-2 py-3" style={{ borderBottom: '1px solid var(--color-border)' }}>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-1">
          <span className="font-mono font-bold text-sm">{cleanPair(row.pair)}</span>
          <span style={{
            fontSize: 9, fontWeight: 800, padding: '2px 6px', borderRadius: 4,
            background: isLong ? 'rgba(16,185,129,0.15)' : isShort ? 'rgba(239,68,68,0.15)' : 'rgba(255,255,255,0.05)',
            color: isLong ? 'var(--color-green)' : isShort ? 'var(--color-red)' : 'var(--color-dim)',
          }}>
            {row.signal_bias ?? row.bias ?? 'NEUTRAL'}
          </span>
        </div>
        <div style={{ display: 'flex', gap: 12, fontSize: 11, color: 'var(--color-dim)' }}>
          <span>RSI: <span style={{ fontWeight: 700, color: row.rsi < 30 ? 'var(--color-green)' : row.rsi > 70 ? 'var(--color-red)' : 'var(--color-text)' }}>{row.rsi?.toFixed(1) ?? '—'}</span></span>
          <span>Vol: <span style={{ fontWeight: 700, color: row.rel_vol > 1.5 ? 'var(--color-gold)' : 'var(--color-text)' }}>{row.rel_vol?.toFixed(2) ?? '—'}x</span></span>
        </div>
      </div>
      
      <div className="text-right">
        <div style={{ fontSize: 11, fontWeight: 700, marginBottom: 2 }}>
          {row.macd_hist > 0 ? (
            <span style={{ color: 'var(--color-green)' }}>MACD ↑</span>
          ) : row.macd_hist < 0 ? (
            <span style={{ color: 'var(--color-red)' }}>MACD ↓</span>
          ) : (
            <span style={{ color: 'var(--color-dim)' }}>MACD —</span>
          )}
        </div>
        <div style={{ fontSize: 10, color: 'var(--color-dimmer)' }}>
          {row.last_signal ? row.last_signal : 'No recent'}
        </div>
      </div>
    </div>
  )
}

export default function Screener() {
  const { user } = useAuthStore()
  const [filter, setFilter] = useState('All')

  const { data, isLoading, refetch, isFetching } = useQuery({
    queryKey: ['screener'],
    queryFn: () => api.get('/api/screener').then(r => r.data),
    enabled: hasTier(user, 'plus'),
    refetchInterval: 60_000,
  })

  if (!hasTier(user, 'plus')) {
    return (
      <>
        <TopBar title="Screener" />
        <div className="flex flex-col items-center justify-center px-6 pt-20 text-center gap-4">
          <Lock size={48} style={{ color: 'var(--color-gold)', opacity: 0.6 }} />
          <h2 style={{ fontSize: '20px', fontWeight: 800 }}>Plus Plan Required</h2>
          <p style={{ color: 'var(--color-dim)', fontSize: '14px', maxWidth: 280 }}>
            The TV Screener is available on Plus, Pro, and Elite plans.
          </p>
          <a href="/app" className="btn-gold" style={{ display: 'inline-block', width: 'auto', padding: '12px 32px' }}>
            Upgrade
          </a>
        </div>
      </>
    )
  }

  const items = data?.data ?? data ?? []
  const filtered = items.filter(row => {
    if (filter === 'All') return true
    const bias = row.signal_bias ?? row.bias ?? 'NEUTRAL'
    return bias === filter
  })

  return (
    <>
      <TopBar 
        title="Screener" 
        right={
          <button onClick={() => refetch()} style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 4, color: 'var(--color-dim)' }}>
            <RefreshCw size={18} className={isFetching ? 'animate-spin' : ''} />
          </button>
        }
      />
      
      <div className="px-4 pt-4 pb-20">
        <div className="card p-4 mb-4" style={{ display: 'flex', alignItems: 'flex-start', gap: 12 }}>
          <div style={{ background: 'rgba(80,180,255,0.15)', padding: 10, borderRadius: 10, color: '#50b4ff' }}>
            <Monitor size={24} />
          </div>
          <div>
            <h3 style={{ fontSize: 14, fontWeight: 800, marginBottom: 4 }}>TradingView Screener</h3>
            <p style={{ fontSize: 12, color: 'var(--color-dim)', lineHeight: 1.4 }}>
              Live crypto perpetuals ranked by signal strength. Pairs at the top are prioritised in the bot's scan cycle.
            </p>
          </div>
        </div>

        {/* Filters */}
        <div style={{ display: 'flex', gap: 8, overflowX: 'auto', scrollbarWidth: 'none', marginBottom: 16 }}>
          {FILTERS.map(f => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              style={{
                whiteSpace: 'nowrap', padding: '6px 14px', borderRadius: 20,
                border: '1px solid', fontSize: 12, fontWeight: 700, cursor: 'pointer',
                transition: 'all 0.15s',
                borderColor: filter === f ? 'var(--color-gold)' : 'var(--color-border)',
                background: filter === f ? 'rgba(228,195,117,0.15)' : 'rgba(255,255,255,0.02)',
                color: filter === f ? 'var(--color-gold)' : 'var(--color-dim)',
              }}
            >
              {f === 'LONG' ? '🟢 ' : f === 'SHORT' ? '🔴 ' : f === 'NEUTRAL' ? '⬜ ' : ''}{f}
            </button>
          ))}
        </div>

        <div className="card px-4 py-2">
          {isLoading ? (
            <PageSpinner />
          ) : filtered.length === 0 ? (
            <p style={{ color: 'var(--color-dim)', fontSize: '13px', padding: '16px 0', textAlign: 'center' }}>No pairs match filter.</p>
          ) : (
            filtered.map((row, i) => <ScreenerRow key={row.pair ?? i} row={row} />)
          )}
        </div>
      </div>
    </>
  )
}
