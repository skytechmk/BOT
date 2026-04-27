import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/services/api'
import { useAuthStore } from '@/store/useAuthStore'
import TopBar from '@/components/TopBar'
import { PageSpinner } from '@/components/ui/Spinner'
import { formatPnl, pnlColor, formatPrice, timeAgo, cleanPair } from '@/utils/helpers'
import { RefreshCw, ChevronDown, ChevronUp, TrendingUp, TrendingDown } from 'lucide-react'

const FILTERS = ['ALL', 'OPEN', 'LONG', 'SHORT', 'CLOSED']

const READINESS_COLORS = {
  IMMINENT: '#ff4444',
  HIGH: '#E4C375',
  MEDIUM: '#66ccff',
  LOW: '#94A3B8',
}

function sqiColor(sqi) {
  if (!sqi && sqi !== 0) return 'var(--color-dim)'
  if (sqi >= 80) return 'var(--color-green)'
  if (sqi >= 60) return '#E4C375'
  if (sqi >= 40) return '#ff9800'
  return 'var(--color-red)'
}

function TpRow({ label, value, hit }) {
  if (!value) return null
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '4px 0', borderBottom: '1px solid var(--color-border)' }}>
      <span style={{ fontSize: 11, color: hit ? 'var(--color-green)' : 'var(--color-dim)', fontWeight: 600 }}>
        {hit ? '✓ ' : ''}{label}
      </span>
      <span className="font-mono" style={{ fontSize: 12, fontWeight: 700, color: hit ? 'var(--color-green)' : 'var(--color-text)' }}>
        {formatPrice(value)}
      </span>
    </div>
  )
}

function SignalCard({ s }) {
  const isLong = s.direction === 'LONG'
  const isOpen = ['SENT', 'OPEN', 'ACTIVE'].includes(s.status)
  const [expanded, setExpanded] = useState(false)
  const sqi = s.sqi ?? s.quality_score ?? s.conviction_score
  const readiness = s.readiness_level
  const sector = s.sector
  const marketType = s.market_type
  const leverage = s.leverage

  return (
    <div
      className="card mx-4 mb-3 overflow-hidden"
      onClick={() => setExpanded(p => !p)}
      style={{ cursor: 'pointer' }}
    >
      {/* Header */}
      <div style={{ padding: '12px 16px' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8 }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            {/* Pair + badges row */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap', marginBottom: 4 }}>
              <span className="font-mono font-black" style={{ fontSize: 15 }}>{cleanPair(s.pair)}</span>
              <span className={isLong ? 'badge-long' : 'badge-short'}>{s.direction}</span>
              {isOpen && <span className="badge-open">LIVE</span>}
              {readiness && (
                <span style={{
                  fontSize: 10, fontWeight: 800, padding: '2px 7px', borderRadius: 20,
                  background: `${READINESS_COLORS[readiness] ?? '#666'}22`,
                  border: `1px solid ${READINESS_COLORS[readiness] ?? '#666'}55`,
                  color: READINESS_COLORS[readiness] ?? 'var(--color-dim)',
                  letterSpacing: '0.04em',
                }}>{readiness}</span>
              )}
            </div>
            {/* Meta row */}
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
              <span style={{ fontSize: 11, color: 'var(--color-dim)' }}>{s.status} · {timeAgo(s.created_at)}</span>
              {leverage && <span style={{ fontSize: 10, fontWeight: 700, color: '#a78bfa', background: 'rgba(167,139,250,0.12)', padding: '1px 6px', borderRadius: 4 }}>{leverage}x</span>}
              {sector && <span style={{ fontSize: 10, color: 'var(--color-dimmer)', background: 'rgba(255,255,255,0.05)', padding: '1px 6px', borderRadius: 4 }}>{sector}</span>}
              {marketType && marketType !== sector && <span style={{ fontSize: 10, color: 'var(--color-dimmer)', background: 'rgba(255,255,255,0.05)', padding: '1px 6px', borderRadius: 4 }}>{marketType}</span>}
            </div>
          </div>

          <div style={{ textAlign: 'right', flexShrink: 0 }}>
            <div className="font-mono font-black" style={{ fontSize: 17, color: s.pnl != null ? pnlColor(s.pnl) : 'var(--color-dim)' }}>
              {s.pnl != null ? formatPnl(s.pnl) : '—'}
            </div>
            {s.entry_price && (
              <div style={{ fontSize: 11, color: 'var(--color-dim)' }}>
                @ {formatPrice(s.entry_price)}
              </div>
            )}
            {sqi != null && (
              <div style={{ fontSize: 10, fontWeight: 800, color: sqiColor(sqi), marginTop: 2 }}>
                SQI {sqi}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Expanded detail */}
      {expanded && (
        <div style={{ borderTop: '1px solid var(--color-border)', padding: '12px 16px' }}>
          {/* Prices grid */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0 12px', marginBottom: 10 }}>
            <div>
              <div style={{ fontSize: 10, color: 'var(--color-dim)', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 2 }}>Entry</div>
              <div className="font-mono" style={{ fontSize: 13, fontWeight: 800 }}>{formatPrice(s.entry_price)}</div>
            </div>
            <div>
              <div style={{ fontSize: 10, color: 'var(--color-red)', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 2 }}>Stop Loss</div>
              <div className="font-mono" style={{ fontSize: 13, fontWeight: 800, color: 'var(--color-red)' }}>{formatPrice(s.stop_loss)}</div>
            </div>
          </div>

          {/* TP rows */}
          <div style={{ marginBottom: 10 }}>
            <div style={{ fontSize: 10, color: 'var(--color-dim)', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 6 }}>Take Profits</div>
            <TpRow label="TP1" value={s.tp1} hit={s.tp1_hit} />
            <TpRow label="TP2" value={s.tp2} hit={s.tp2_hit} />
            <TpRow label="TP3" value={s.tp3} hit={s.tp3_hit} />
            <TpRow label="TP4" value={s.tp4} hit={s.tp4_hit} />
          </div>

          {/* Commentary */}
          {(s.commentary ?? s.ai_analysis) && (
            <div style={{ marginTop: 6, padding: '8px 10px', background: 'rgba(80,180,255,0.06)', border: '1px solid rgba(80,180,255,0.15)', borderRadius: 8, fontSize: 11, color: 'var(--color-dim)', lineHeight: 1.6 }}>
              {s.commentary ?? s.ai_analysis}
            </div>
          )}

          {/* Regime / zone */}
          {(s.regime || s.zone) && (
            <div style={{ marginTop: 8, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              {s.regime && <span style={{ fontSize: 11, background: 'rgba(255,255,255,0.05)', borderRadius: 6, padding: '2px 8px', color: 'var(--color-dim)' }}>{s.regime}</span>}
              {s.zone && <span style={{ fontSize: 11, background: 'rgba(255,255,255,0.05)', borderRadius: 6, padding: '2px 8px', color: 'var(--color-dim)' }}>{s.zone}</span>}
            </div>
          )}
        </div>
      )}

      {/* Expand toggle hint */}
      <div style={{ display: 'flex', justifyContent: 'center', padding: '4px 0', borderTop: '1px solid var(--color-border)' }}>
        {expanded
          ? <ChevronUp size={14} style={{ color: 'var(--color-dimmer)' }} />
          : <ChevronDown size={14} style={{ color: 'var(--color-dimmer)' }} />}
      </div>
    </div>
  )
}

export default function Signals() {
  const { user } = useAuthStore()
  const [filter, setFilter] = useState('ALL')

  const { data, isLoading, refetch, isFetching } = useQuery({
    queryKey: ['signals'],
    queryFn: () => api.get('/api/signals').then(r => r.data),
    refetchInterval: 30_000,
  })

  const all = data?.signals ?? []
  const filtered = all.filter(s => {
    if (filter === 'ALL') return true
    if (filter === 'OPEN') return ['SENT', 'OPEN', 'ACTIVE'].includes(s.status)
    if (filter === 'CLOSED') return ['CLOSED', 'COMPLETED', 'HIT_TP', 'HIT_SL'].includes(s.status)
    return s.direction === filter
  })

  return (
    <>
      <TopBar
        title="Signals"
        right={
          <button onClick={() => refetch()} style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 4, color: 'var(--color-dim)' }}>
            <RefreshCw size={18} className={isFetching ? 'animate-spin' : ''} />
          </button>
        }
      />

      {/* Summary bar */}
      {data && (
        <div style={{ display: 'flex', gap: 10, padding: '10px 16px 0', fontSize: 12 }}>
          <span style={{ color: 'var(--color-dim)' }}>
            <span style={{ color: 'var(--color-gold)', fontWeight: 800 }}>{data.open_count ?? 0}</span> open ·{' '}
            <span style={{ fontWeight: 700 }}>{data.total ?? all.length}</span> total
          </span>
          {data.win_rate && (
            <span style={{ marginLeft: 'auto', color: 'var(--color-green)', fontWeight: 700 }}>
              WR {data.win_rate}%
            </span>
          )}
        </div>
      )}

      {/* Filter chips */}
      <div style={{ display: 'flex', gap: 8, padding: '10px 16px', overflowX: 'auto', scrollbarWidth: 'none' }}>
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
            {f === 'LONG' ? '🟢 ' : f === 'SHORT' ? '🔴 ' : ''}{f}
          </button>
        ))}
      </div>

      {data?.tier === 'free' && !user?.is_admin && (
        <div style={{ margin: '0 16px 12px', padding: '10px 14px', borderRadius: 10, background: 'rgba(228,195,117,0.07)', border: '1px solid rgba(228,195,117,0.2)' }}>
          <p style={{ fontSize: 12, color: 'var(--color-gold)', fontWeight: 600 }}>
            Free tier: signals delayed 24h. <a href="/app" style={{ textDecoration: 'underline' }}>Upgrade for live.</a>
          </p>
        </div>
      )}

      {isLoading ? (
        <PageSpinner />
      ) : filtered.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '48px 16px', color: 'var(--color-dim)' }}>
          <div style={{ fontSize: 32, marginBottom: 12 }}>📡</div>
          <p>No signals match this filter.</p>
        </div>
      ) : (
        <div style={{ paddingBottom: 16 }}>
          {filtered.map((s, i) => <SignalCard key={s.id ?? i} s={s} />)}
        </div>
      )}
    </>
  )
}
