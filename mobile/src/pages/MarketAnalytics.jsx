import { useQuery } from '@tanstack/react-query'
import { api } from '@/services/api'
import { useAuthStore } from '@/store/useAuthStore'
import TopBar from '@/components/TopBar'
import { PageSpinner } from '@/components/ui/Spinner'
import { Lock, TrendingUp, Activity, BarChart2 } from 'lucide-react'
import { hasTier } from '@/utils/helpers'

function MetricCard({ title, value, sub, color }) {
  return (
    <div className="card p-4">
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
  )
}

export default function MarketAnalytics() {
  const { user } = useAuthStore()

  const { data: analytics, isLoading } = useQuery({
    queryKey: ['market-analytics'],
    queryFn: () => api.get('/api/macro/analytics').then(r => r.data),
    enabled: hasTier(user, 'pro'),
    refetchInterval: 60_000,
  })

  if (!hasTier(user, 'pro')) {
    return (
      <>
        <TopBar title="Market Analytics" />
        <div className="flex flex-col items-center justify-center px-6 pt-20 text-center gap-4">
          <Lock size={48} style={{ color: 'var(--color-gold)', opacity: 0.6 }} />
          <h2 style={{ fontSize: '20px', fontWeight: 800 }}>Pro Plan Required</h2>
          <p style={{ color: 'var(--color-dim)', fontSize: '14px', maxWidth: 280 }}>
            Advanced market analytics including CVD, MFI, and deep liquidity data are available on Pro and Elite plans.
          </p>
          <a href="/app" className="btn-gold" style={{ display: 'inline-block', width: 'auto', padding: '12px 32px' }}>
            Upgrade
          </a>
        </div>
      </>
    )
  }

  const data = analytics || {}

  return (
    <>
      <TopBar title="Market Analytics" />
      
      <div className="px-4 pt-4 pb-20">
        
        <div className="card p-4 mb-4" style={{ display: 'flex', alignItems: 'flex-start', gap: 12 }}>
          <div style={{ background: 'rgba(228,195,117,0.15)', padding: 10, borderRadius: 10, color: 'var(--color-gold)' }}>
            <TrendingUp size={24} />
          </div>
          <div>
            <h3 style={{ fontSize: 14, fontWeight: 800, marginBottom: 4 }}>Volume & Liquidity</h3>
            <p style={{ fontSize: 12, color: 'var(--color-dim)', lineHeight: 1.4 }}>
              Real-time Cumulative Volume Delta and Money Flow analysis across all tracked pairs.
            </p>
          </div>
        </div>

        {isLoading ? (
          <PageSpinner />
        ) : (
          <>
            <h3 style={{ fontSize: 13, fontWeight: 700, color: 'var(--color-dim)', textTransform: 'uppercase', marginBottom: 12 }}>Cumulative Volume Delta</h3>
            <div className="grid grid-cols-2 gap-3 mb-5">
              <MetricCard 
                title="CVD (1h)" 
                value={data.cvd_1h ? `$${(data.cvd_1h / 1e6).toFixed(2)}M` : '—'} 
                sub={data.cvd_1h > 0 ? 'Net Buying' : 'Net Selling'}
                color={data.cvd_1h > 0 ? 'var(--color-green)' : 'var(--color-red)'}
              />
              <MetricCard 
                title="CVD (4h)" 
                value={data.cvd_4h ? `$${(data.cvd_4h / 1e6).toFixed(2)}M` : '—'} 
                sub={data.cvd_4h > 0 ? 'Net Buying' : 'Net Selling'}
                color={data.cvd_4h > 0 ? 'var(--color-green)' : 'var(--color-red)'}
              />
              <MetricCard 
                title="CVD (24h)" 
                value={data.cvd_24h ? `$${(data.cvd_24h / 1e6).toFixed(2)}M` : '—'} 
                sub={data.cvd_24h > 0 ? 'Net Buying' : 'Net Selling'}
                color={data.cvd_24h > 0 ? 'var(--color-green)' : 'var(--color-red)'}
              />
              <MetricCard 
                title="CVD Trend" 
                value={data.cvd_trend || 'NEUTRAL'} 
                sub="Overall momentum"
                color={data.cvd_trend === 'BULLISH' ? 'var(--color-green)' : data.cvd_trend === 'BEARISH' ? 'var(--color-red)' : 'var(--color-dim)'}
              />
            </div>

            <h3 style={{ fontSize: 13, fontWeight: 700, color: 'var(--color-dim)', textTransform: 'uppercase', marginBottom: 12 }}>Money Flow Index</h3>
            <div className="grid grid-cols-2 gap-3 mb-5">
              <MetricCard 
                title="Global MFI" 
                value={data.mfi_global?.toFixed(1) || '—'} 
                sub={data.mfi_global > 80 ? 'Overbought' : data.mfi_global < 20 ? 'Oversold' : 'Neutral'}
                color={data.mfi_global > 80 ? 'var(--color-red)' : data.mfi_global < 20 ? 'var(--color-green)' : 'var(--color-gold)'}
              />
              <MetricCard 
                title="BTC MFI" 
                value={data.mfi_btc?.toFixed(1) || '—'} 
                sub="Bitcoin specific flow"
              />
            </div>
            
            <h3 style={{ fontSize: 13, fontWeight: 700, color: 'var(--color-dim)', textTransform: 'uppercase', marginBottom: 12 }}>Market Breadth</h3>
            <div className="card p-4">
              <div className="flex justify-between items-center py-2" style={{ borderBottom: '1px solid var(--color-border)' }}>
                <span style={{ fontSize: 14 }}>Pairs Above VWAP</span>
                <span style={{ fontSize: 14, fontWeight: 700 }}>
                  {data.above_vwap_pct ? `${data.above_vwap_pct.toFixed(1)}%` : '—'}
                </span>
              </div>
              <div className="flex justify-between items-center py-2" style={{ borderBottom: '1px solid var(--color-border)' }}>
                <span style={{ fontSize: 14 }}>Pairs Above 200 EMA</span>
                <span style={{ fontSize: 14, fontWeight: 700 }}>
                  {data.above_200ema_pct ? `${data.above_200ema_pct.toFixed(1)}%` : '—'}
                </span>
              </div>
              <div className="flex justify-between items-center py-2">
                <span style={{ fontSize: 14 }}>Open Interest (24h Δ)</span>
                <span style={{ fontSize: 14, fontWeight: 700, color: data.oi_change_pct > 0 ? 'var(--color-green)' : 'var(--color-red)' }}>
                  {data.oi_change_pct > 0 ? '+' : ''}{data.oi_change_pct ? `${data.oi_change_pct.toFixed(2)}%` : '—'}
                </span>
              </div>
            </div>
          </>
        )}

      </div>
    </>
  )
}
