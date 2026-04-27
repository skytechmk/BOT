import { useQuery } from '@tanstack/react-query'
import { api } from '@/services/api'
import { useAuthStore } from '@/store/useAuthStore'
import TopBar from '@/components/TopBar'
import StatCard from '@/components/ui/StatCard'
import { PageSpinner } from '@/components/ui/Spinner'
import { formatPnl, pnlColor, timeAgo, cleanPair, tierLabel, tierColor } from '@/utils/helpers'
import { Bell, Send, ArrowRight } from 'lucide-react'
import { Link } from 'react-router-dom'

function SignalRow({ s }) {
  const isLong = s.direction === 'LONG'
  const isOpen = ['SENT', 'OPEN', 'ACTIVE'].includes(s.status)
  return (
    <Link to="/signals" className="flex items-center gap-3 py-3" style={{ borderBottom: '1px solid var(--color-border)' }}>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-0.5">
          <span className="font-mono font-bold text-sm">{cleanPair(s.pair)}</span>
          <span className={isLong ? 'badge-long' : 'badge-short'}>{s.direction}</span>
          {isOpen && <span className="badge-open">OPEN</span>}
        </div>
        <span style={{ fontSize: '11px', color: 'var(--color-dim)' }}>{timeAgo(s.created_at)}</span>
      </div>
      <div className="text-right flex items-center gap-2">
        <div>
          <div className="font-mono font-bold text-sm" style={{ color: s.pnl != null ? pnlColor(s.pnl) : 'var(--color-text)' }}>
            {s.pnl != null ? formatPnl(s.pnl) : '—'}
          </div>
          <div style={{ fontSize: '11px', color: 'var(--color-dim)' }}>{s.status}</div>
        </div>
        <ArrowRight size={14} style={{ color: 'var(--color-dimmer)' }} />
      </div>
    </Link>
  )
}

function PairRow({ p }) {
  const isLong = p.zone === 'LONG' || p.zone?.includes('LONG')
  const isShort = p.zone === 'SHORT' || p.zone?.includes('SHORT')
  const pnl = p.total_pnl ?? 0

  return (
    <div className="flex items-center gap-3 py-2" style={{ borderBottom: '1px solid var(--color-border)' }}>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-0.5">
          <span className="font-mono font-bold text-sm">{cleanPair(p.pair)}</span>
          {p.zone && (
            <span style={{ 
              fontSize: 9, fontWeight: 700, padding: '2px 6px', borderRadius: 4, 
              background: isLong ? 'rgba(16,185,129,0.15)' : isShort ? 'rgba(239,68,68,0.15)' : 'rgba(255,255,255,0.05)',
              color: isLong ? 'var(--color-green)' : isShort ? 'var(--color-red)' : 'var(--color-dim)',
              border: `1px solid ${isLong ? 'rgba(16,185,129,0.3)' : isShort ? 'rgba(239,68,68,0.3)' : 'var(--color-border)'}`
            }}>
              {p.zone}
            </span>
          )}
        </div>
        <span style={{ fontSize: '11px', color: 'var(--color-dim)' }}>{p.total_signals ?? 0} signals</span>
      </div>
      <div className="text-right">
        <div className="font-mono font-bold text-sm" style={{ color: pnlColor(pnl) }}>
          {formatPnl(pnl)}
        </div>
        <div style={{ fontSize: '11px', color: 'var(--color-dim)' }}>
          {p.win_rate != null ? `${p.win_rate.toFixed(0)}% WR` : '—'}
        </div>
      </div>
    </div>
  )
}

export default function Dashboard() {
  const { user } = useAuthStore()
  
  const { data: statsLive } = useQuery({
    queryKey: ['public-stats'],
    queryFn: () => api.get('/api/public/stats').then(r => r.data),
    staleTime: 120_000,
    refetchInterval: 120_000,
  })

  const { data: signals, isLoading: sigLoading } = useQuery({
    queryKey: ['signals'],
    queryFn: () => api.get('/api/signals').then(r => r.data),
    refetchInterval: 60_000,
  })

  const { data: site } = useQuery({
    queryKey: ['site'],
    queryFn: () => api.get('/api/public/site').then(r => r.data),
    staleTime: 300_000,
  })

  const { data: macroState } = useQuery({
    queryKey: ['macro-state-1h'],
    queryFn: () => api.get('/api/macro/state?tf=1h').then(r => r.data),
    refetchInterval: 60_000,
  })

  const { data: pairsData, isLoading: pairsLoading } = useQuery({
    queryKey: ['monitored-pairs'],
    queryFn: () => api.get('/api/monitored').then(r => r.data),
    refetchInterval: 120_000,
  })

  const stats = statsLive ?? {}
  const recentSignals = signals?.signals?.slice(0, 5) ?? []
  const openCount = signals?.open_count ?? 0
  const topPairs = pairsData?.monitored?.slice(0, 5) ?? []

  return (
    <>
      <TopBar right={
        <Link to="/signals">
          <div style={{ position: 'relative', padding: 4 }}>
            <Bell size={20} style={{ color: 'var(--color-dim)' }} />
            {openCount > 0 && (
              <span style={{
                position: 'absolute', top: 0, right: 0,
                background: 'var(--color-gold)', color: '#000',
                borderRadius: '50%', width: 16, height: 16,
                fontSize: 9, fontWeight: 800,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
              }}>{openCount}</span>
            )}
          </div>
        </Link>
      } />

      <div className="px-4 pt-4 pb-20">
        
        {/* Welcome */}
        <div style={{ marginBottom: 16 }}>
          <p style={{ color: 'var(--color-dim)', fontSize: '13px', marginBottom: 2 }}>Welcome back</p>
          <h2 style={{ fontSize: '20px', fontWeight: 800 }}>{user?.username ?? user?.email}</h2>
          <span
            className="inline-block text-xs font-bold px-2 py-0.5 rounded-full mt-1"
            style={{ background: 'rgba(255,255,255,0.06)', color: tierColor(user?.tier) }}
          >
            {user?.is_admin ? 'Admin' : `${tierLabel(user?.tier)} Plan`}
          </span>
        </div>

        {/* Telegram Banner */}
        {(user?.tier === 'pro' || user?.tier === 'elite') && site?.telegram_invite_link && (
          <a href={site.telegram_invite_link} target="_blank" rel="noopener noreferrer" className="card mb-5 p-4" style={{ display: 'flex', alignItems: 'center', gap: 14, background: 'linear-gradient(135deg, rgba(80,180,255,0.15) 0%, rgba(80,180,255,0.02) 100%)', borderColor: 'rgba(80,180,255,0.3)', textDecoration: 'none' }}>
            <div style={{ width: 44, height: 44, borderRadius: '50%', background: 'rgba(80,180,255,0.2)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#50b4ff', flexShrink: 0 }}>
              <Send size={20} style={{ marginLeft: -2 }} />
            </div>
            <div>
              <div style={{ fontWeight: 800, fontSize: 15, color: '#50b4ff', marginBottom: 2 }}>Pro Telegram Channel</div>
              <div style={{ fontSize: 12, color: 'var(--color-dim)', lineHeight: 1.4 }}>Get real-time entry and TP/SL alerts</div>
            </div>
          </a>
        )}

        {/* Macro Card */}
        {macroState && (
          <div className="card mb-5 p-4" style={{ background: 'rgba(167,139,250,0.05)', borderColor: 'rgba(167,139,250,0.2)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
              <span style={{ fontSize: 12, fontWeight: 700, color: '#a78bfa', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Macro Status · 1H</span>
            </div>
            <div style={{ display: 'flex', gap: 16 }}>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 11, color: 'var(--color-dim)', marginBottom: 2 }}>Market Regime</div>
                <div style={{ fontSize: 15, fontWeight: 800, color: macroState.regime === 'RISK_ON' ? 'var(--color-green)' : macroState.regime === 'RISK_OFF' ? 'var(--color-red)' : 'var(--color-text)' }}>
                  {macroState.regime?.replace('_', ' ') ?? '—'}
                </div>
              </div>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 11, color: 'var(--color-dim)', marginBottom: 2 }}>USDT Dominance</div>
                <div style={{ fontSize: 15, fontWeight: 800, color: 'var(--color-text)' }}>
                  {macroState.usdt_dom ? `${macroState.usdt_dom.toFixed(2)}%` : '—'}
                </div>
              </div>
            </div>
          </div>
        )}

        <div className="grid grid-cols-2 gap-3 mb-5">
          <StatCard
            label="Open Signals"
            value={openCount}
            sub="active now"
            valueStyle={{ color: openCount > 0 ? 'var(--color-gold)' : 'var(--color-text)' }}
          />
          <StatCard
            label="Win Rate"
            value={site?.win_rate ? `${site.win_rate}%` : stats?.win_rate ? `${stats.win_rate}%` : '—'}
            sub="all time"
            valueStyle={{ color: 'var(--color-green)' }}
          />
          <StatCard
            label="Total Signals"
            value={signals?.total ?? '—'}
            sub="last 50"
          />
          <StatCard
            label="Pairs Tracked"
            value={stats?.monitored_count ?? site?.pairs_tracked ?? '—'}
            sub="live scanning"
          />
        </div>

        {/* Signals Preview */}
        <div className="card px-4 py-3 mb-5">
          <div className="flex items-center justify-between mb-2">
            <span style={{ fontSize: '13px', fontWeight: 700, color: 'var(--color-dim)', letterSpacing: '0.05em', textTransform: 'uppercase' }}>
              Recent Signals
            </span>
            <Link to="/signals" style={{ fontSize: '13px', color: 'var(--color-gold)', fontWeight: 600 }}>
              View All
            </Link>
          </div>
          {sigLoading ? (
            <PageSpinner />
          ) : recentSignals.length === 0 ? (
            <p style={{ color: 'var(--color-dim)', fontSize: '13px', padding: '12px 0' }}>No signals yet.</p>
          ) : (
            recentSignals.map((s, i) => <SignalRow key={i} s={s} />)
          )}
        </div>

        {/* Top Pairs Preview */}
        <div className="card px-4 py-3 mb-5">
          <div className="flex items-center justify-between mb-2">
            <span style={{ fontSize: '13px', fontWeight: 700, color: 'var(--color-dim)', letterSpacing: '0.05em', textTransform: 'uppercase' }}>
              Top Monitored Pairs
            </span>
          </div>
          {pairsLoading ? (
            <PageSpinner />
          ) : topPairs.length === 0 ? (
            <p style={{ color: 'var(--color-dim)', fontSize: '13px', padding: '12px 0' }}>No pairs tracked.</p>
          ) : (
            topPairs.map((p, i) => <PairRow key={i} p={p} />)
          )}
        </div>

        {/* Upgrade CTA */}
        {user?.tier === 'free' && !user?.is_admin && (
          <div className="card p-4 text-center" style={{ borderColor: 'rgba(228,195,117,0.2)', background: 'rgba(228,195,117,0.04)' }}>
            <p style={{ fontWeight: 700, marginBottom: 6 }}>Upgrade to Plus or Pro</p>
            <p style={{ fontSize: '13px', color: 'var(--color-dim)', marginBottom: 12 }}>
              Get live signals, copy trading, and full analytics.
            </p>
            <a href="/app" className="btn-gold" style={{ display: 'inline-block', width: 'auto', padding: '10px 24px' }}>
              Upgrade Now
            </a>
          </div>
        )}
      </div>
    </>
  )
}
