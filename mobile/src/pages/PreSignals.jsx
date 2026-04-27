import { useQuery } from '@tanstack/react-query'
import { api } from '@/services/api'
import { useAuthStore } from '@/store/useAuthStore'
import TopBar from '@/components/TopBar'
import { PageSpinner } from '@/components/ui/Spinner'
import { hasTier, cleanPair, timeAgo } from '@/utils/helpers'
import { Lock, RefreshCw, Target } from 'lucide-react'

const READINESS_COLORS = {
  IMMINENT: '#ff4444',
  HIGH: '#E4C375',
  MEDIUM: '#66ccff',
  LOW: '#94A3B8',
}

function PreSignalCard({ item }) {
  const isLong = item.direction === 'LONG' || item.signal_direction === 'LONG'
  const readiness = item.readiness_level ?? item.readiness ?? 'LOW'
  
  return (
    <div className="card mb-3 p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className="font-mono font-bold text-base">{cleanPair(item.pair)}</span>
          <span className={isLong ? 'badge-long' : 'badge-short'}>{isLong ? 'LONG' : 'SHORT'}</span>
        </div>
        <div style={{
          fontSize: 11, fontWeight: 800, padding: '3px 8px', borderRadius: 20,
          background: `${READINESS_COLORS[readiness]}22`,
          border: `1px solid ${READINESS_COLORS[readiness]}55`,
          color: READINESS_COLORS[readiness],
          letterSpacing: '0.04em',
        }}>
          {readiness}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 mb-3">
        <div>
          <div style={{ fontSize: 10, color: 'var(--color-dim)', fontWeight: 700, textTransform: 'uppercase', marginBottom: 2 }}>TSI Depth</div>
          <div className="font-mono" style={{ fontSize: 13, fontWeight: 700 }}>
            {item.tsi_depth ? item.tsi_depth.toFixed(1) : '—'}
          </div>
        </div>
        <div>
          <div style={{ fontSize: 10, color: 'var(--color-dim)', fontWeight: 700, textTransform: 'uppercase', marginBottom: 2 }}>Conviction</div>
          <div className="font-mono" style={{ fontSize: 13, fontWeight: 700 }}>
            {item.conviction_score ? `${item.conviction_score}/100` : '—'}
          </div>
        </div>
        <div>
          <div style={{ fontSize: 10, color: 'var(--color-dim)', fontWeight: 700, textTransform: 'uppercase', marginBottom: 2 }}>CE Status</div>
          <div style={{ fontSize: 12, fontWeight: 600, color: item.ce_flipped ? 'var(--color-green)' : 'var(--color-dim)' }}>
            {item.ce_flipped ? 'FLIPPED' : 'WAITING'}
          </div>
        </div>
        <div>
          <div style={{ fontSize: 10, color: 'var(--color-dim)', fontWeight: 700, textTransform: 'uppercase', marginBottom: 2 }}>L2 Alignment</div>
          <div style={{ fontSize: 12, fontWeight: 600, color: item.l2_aligned ? 'var(--color-gold)' : 'var(--color-dim)' }}>
            {item.l2_aligned ? 'ALIGNED' : 'PENDING'}
          </div>
        </div>
      </div>

      {item.triggers && item.triggers.length > 0 && (
        <div style={{ fontSize: 11, color: 'var(--color-dim)', background: 'var(--color-surface-2)', padding: '6px 10px', borderRadius: 6, marginBottom: 8 }}>
          <strong>Triggers:</strong> {item.triggers.join(', ')}
        </div>
      )}

      <div style={{ fontSize: 10, color: 'var(--color-dimmer)', textAlign: 'right' }}>
        Updated {timeAgo(item.timestamp || item.updated_at)}
      </div>
    </div>
  )
}

export default function PreSignals() {
  const { user } = useAuthStore()

  const { data, isLoading, refetch, isFetching } = useQuery({
    queryKey: ['presignals'],
    queryFn: () => api.get('/api/presignals').then(r => r.data),
    enabled: hasTier(user, 'pro'),
    refetchInterval: 30_000,
  })

  if (!hasTier(user, 'pro')) {
    return (
      <>
        <TopBar title="Pre-Signals" />
        <div className="flex flex-col items-center justify-center px-6 pt-20 text-center gap-4">
          <Lock size={48} style={{ color: 'var(--color-gold)', opacity: 0.6 }} />
          <h2 style={{ fontSize: '20px', fontWeight: 800 }}>Pro Plan Required</h2>
          <p style={{ color: 'var(--color-dim)', fontSize: '14px', maxWidth: 280 }}>
            Pre-signal alerts and early detection are available on Pro and Elite plans.
          </p>
          <a href="/app" className="btn-gold" style={{ display: 'inline-block', width: 'auto', padding: '12px 32px' }}>
            Upgrade
          </a>
        </div>
      </>
    )
  }

  const items = data?.alerts ?? data ?? []

  return (
    <>
      <TopBar 
        title="Pre-Signals" 
        right={
          <button onClick={() => refetch()} style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 4, color: 'var(--color-dim)' }}>
            <RefreshCw size={18} className={isFetching ? 'animate-spin' : ''} />
          </button>
        }
      />
      
      <div className="px-4 pt-4 pb-20">
        <div className="card p-4 mb-4" style={{ display: 'flex', alignItems: 'flex-start', gap: 12 }}>
          <div style={{ background: 'rgba(228,195,117,0.15)', padding: 10, borderRadius: 10, color: 'var(--color-gold)' }}>
            <Target size={24} />
          </div>
          <div>
            <h3 style={{ fontSize: 14, fontWeight: 800, marginBottom: 4 }}>Early Detection Radar</h3>
            <p style={{ fontSize: 12, color: 'var(--color-dim)', lineHeight: 1.4 }}>
              Pairs in extreme zones with hooked TSI momentum. Sorted by readiness.
            </p>
          </div>
        </div>

        {isLoading ? (
          <PageSpinner />
        ) : items.length === 0 ? (
          <p style={{ color: 'var(--color-dim)', fontSize: '13px', padding: '16px 0', textAlign: 'center' }}>No pre-signals currently active.</p>
        ) : (
          items.map((item, i) => <PreSignalCard key={item.pair ?? i} item={item} />)
        )}
      </div>
    </>
  )
}
