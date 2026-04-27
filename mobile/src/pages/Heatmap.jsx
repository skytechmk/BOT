import { useState, useEffect, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/services/api'
import { useAuthStore } from '@/store/useAuthStore'
import TopBar from '@/components/TopBar'
import { PageSpinner } from '@/components/ui/Spinner'
import { hasTier } from '@/utils/helpers'
import { Lock } from 'lucide-react'

// Canvas rendering logic adapted for mobile
function drawHeatmap(canvas, data, vpData, markPrice, zoomRange) {
  if (!canvas || !data?.buckets?.length) return
  const ctx = canvas.getContext('2d')
  
  const dpr = Math.min(window.devicePixelRatio || 1, 3)
  const W = canvas.offsetWidth || window.innerWidth - 32
  const H = 320
  
  canvas.width = Math.round(W * dpr)
  canvas.height = Math.round(H * dpr)
  ctx.scale(dpr, dpr)
  ctx.clearRect(0, 0, W, H)

  const padL = 60, padR = 80, padT = 20, padB = 25
  const chartW = W - padL - padR, chartH = H - padT - padB
  const centerX = padL + chartW / 2, halfW = chartW / 2 - 4
  const vpX = W - padR + 4, vpW = padR - 8

  // Calculate prices
  let bPrices = data.buckets.map(b => b.price).filter(p => p > 0)
  if (vpData?.buckets) vpData.buckets.forEach(b => { if (b.price > 0) bPrices.push(b.price) })
  if (markPrice > 0) bPrices.push(markPrice)
  if (!bPrices.length) bPrices = [1, 2]

  let minP, maxP
  if (markPrice > 0) {
    minP = markPrice * (1 - zoomRange)
    maxP = markPrice * (1 + zoomRange)
  } else {
    const rawMin = Math.min(...bPrices)
    const rawMax = Math.max(...bPrices)
    const pad = (rawMax - rawMin) * 0.05 || rawMax * 0.02
    minP = rawMin - pad
    maxP = rawMax + pad
  }
  const priceRange = maxP - minP || 1
  const priceToY = (p) => padT + chartH - ((p - minP) / priceRange) * chartH

  // Filter buckets in view
  const visBuckets = data.buckets.filter(b => b.price >= minP && b.price <= maxP)
  const maxLong = Math.max(...visBuckets.map(b => b.long_liq_usd), 1)
  const maxShort = Math.max(...visBuckets.map(b => b.short_liq_usd), 1)
  const maxUsd = Math.max(maxLong, maxShort)

  // Draw VA background
  if (vpData?.vah && vpData?.val) {
    const yVah = priceToY(vpData.vah)
    const yVal = priceToY(vpData.val)
    ctx.fillStyle = 'rgba(80,180,255,0.06)'
    ctx.fillRect(padL, Math.min(yVah, yVal), chartW + padR - 8, Math.abs(yVal - yVah))
  }

  // Draw center divider
  ctx.strokeStyle = 'rgba(255,255,255,0.08)'; ctx.lineWidth = 1
  ctx.beginPath(); ctx.moveTo(centerX, padT); ctx.lineTo(centerX, padT + chartH); ctx.stroke()

  // Draw Liquidation bars
  const rowH = Math.max(2, chartH / Math.max(1, data.buckets.length) - 0.5)
  visBuckets.forEach(b => {
    const y = priceToY(b.price)
    const longW2 = (b.long_liq_usd / maxUsd) * halfW
    const shortW2 = (b.short_liq_usd / maxUsd) * halfW
    const intensity = Math.min(1, (b.long_liq_usd + b.short_liq_usd) / maxUsd)
    const alpha = 0.3 + intensity * 0.7
    
    if (longW2 > 0.5) {
      ctx.fillStyle = `rgba(255,77,106,${alpha})`
      ctx.fillRect(centerX - longW2, y - rowH/2, longW2, rowH)
    }
    if (shortW2 > 0.5) {
      ctx.fillStyle = `rgba(0,214,143,${alpha})`
      ctx.fillRect(centerX, y - rowH/2, shortW2, rowH)
    }
  })

  // Draw VPVR bars
  if (vpData?.buckets?.length) {
    const maxRatio = Math.max(...vpData.buckets.map(b => b.ratio), 0.01)
    vpData.buckets.forEach(b => {
      const y = priceToY(b.price)
      const barW = (b.ratio / maxRatio) * vpW
      const isPoc = Math.abs(b.price - vpData.poc) < 1e-9
      const alpha = 0.25 + b.ratio * 0.65
      ctx.fillStyle = isPoc ? 'rgba(160,120,255,0.9)' : `rgba(100,160,255,${alpha})`
      ctx.fillRect(vpX, y - 2, barW, 4)
    })

    // POC Line
    if (vpData.poc) {
      const yPoc = priceToY(vpData.poc)
      ctx.strokeStyle = 'rgba(160,120,255,0.85)'; ctx.lineWidth = 1.5; ctx.setLineDash([6, 4])
      ctx.beginPath(); ctx.moveTo(padL, yPoc); ctx.lineTo(W - 6, yPoc); ctx.stroke(); ctx.setLineDash([])
    }
  }

  // Left axis separator
  ctx.strokeStyle = 'rgba(255,255,255,0.15)'; ctx.lineWidth = 1
  ctx.beginPath(); ctx.moveTo(padL, padT); ctx.lineTo(padL, padT + chartH); ctx.stroke()

  // Y-Axis labels
  ctx.font = 'bold 9px monospace'; ctx.textAlign = 'right'
  for (let i = 0; i <= 6; i++) {
    const ratio = i / 6
    const price = minP + ratio * priceRange
    const y = padT + chartH - ratio * chartH
    
    ctx.strokeStyle = 'rgba(255,255,255,0.2)'; ctx.lineWidth = 1
    ctx.beginPath(); ctx.moveTo(padL - 4, y); ctx.lineTo(padL, y); ctx.stroke()
    ctx.strokeStyle = 'rgba(255,255,255,0.06)'
    ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(padL + chartW, y); ctx.stroke()
    
    ctx.fillStyle = 'rgba(210,220,235,0.92)'
    const pStr = price >= 1000 ? Math.round(price).toString() : price.toFixed(2)
    ctx.fillText(pStr, padL - 6, y + 3)
  }

  // Footer labels
  const footerY = padT + chartH + 16
  ctx.font = '9px sans-serif'
  ctx.textAlign = 'left'; ctx.fillStyle = 'rgba(255,77,106,0.8)'; ctx.fillText('◀ Longs', padL + 2, footerY)
  ctx.textAlign = 'right'; ctx.fillStyle = 'rgba(0,214,143,0.8)'; ctx.fillText('Shorts ▶', centerX + halfW - 2, footerY)
  ctx.textAlign = 'center'; ctx.fillStyle = 'rgba(100,160,255,0.7)'; ctx.fillText('VP', vpX + vpW / 2, footerY)

  // Draw Mark Price Line
  if (markPrice > 0) {
    const yMark = priceToY(markPrice)
    const yClamped = Math.max(padT + 2, Math.min(padT + chartH - 2, yMark))
    
    ctx.strokeStyle = 'rgba(240,185,11,0.9)'; ctx.lineWidth = 1.5; ctx.setLineDash([5, 3])
    ctx.beginPath(); ctx.moveTo(padL, yClamped); ctx.lineTo(W - padR + 8, yClamped); ctx.stroke(); ctx.setLineDash([])
    
    const label = markPrice >= 1000 ? Math.round(markPrice).toString() : markPrice.toFixed(2)
    ctx.font = 'bold 10px monospace'
    const tw = ctx.measureText(label).width
    ctx.fillStyle = 'rgba(240,185,11,0.15)'
    ctx.fillRect(W - padR + 10, yClamped - 8, tw + 8, 14)
    ctx.strokeStyle = 'rgba(240,185,11,0.5)'; ctx.lineWidth = 1
    ctx.strokeRect(W - padR + 10, yClamped - 8, tw + 8, 14)
    ctx.fillStyle = 'rgba(240,185,11,1)'; ctx.textAlign = 'left'
    ctx.fillText(label, W - padR + 14, yClamped + 3)
  }
}

export default function Heatmap() {
  const { user } = useAuthStore()
  const canvasRef = useRef(null)
  
  const [pair, setPair] = useState('BTCUSDT')
  const [inputVal, setInputVal] = useState('BTCUSDT')
  const [windowHr, setWindowHr] = useState(24)
  const [zoomRange, setZoomRange] = useState(0.35)

  const { data: summary } = useQuery({
    queryKey: ['liq-summary'],
    queryFn: () => api.get('/api/liq/summary?top_n=5').then(r => r.data),
    enabled: hasTier(user, 'plus'),
    refetchInterval: 30000,
  })

  const { data: heatData, isLoading: heatLoading } = useQuery({
    queryKey: ['liq-heatmap', pair, windowHr],
    queryFn: () => api.get(`/api/liq/heatmap/${pair}?window=${windowHr}`).then(r => r.data),
    enabled: hasTier(user, 'plus'),
  })

  const { data: vpData } = useQuery({
    queryKey: ['liq-vp', pair, windowHr],
    queryFn: () => api.get(`/api/liq/vp/${pair}?window=${windowHr}`).then(r => r.data),
    enabled: hasTier(user, 'plus'),
  })

  const { data: context } = useQuery({
    queryKey: ['liq-context', pair],
    queryFn: () => api.get(`/api/liq/context/${pair}`).then(r => r.data),
    enabled: hasTier(user, 'plus'),
    refetchInterval: 15000,
  })

  const { data: suggest, refetch: refetchSuggest } = useQuery({
    queryKey: ['liq-suggest', pair],
    queryFn: () => api.get(`/api/liq/suggest/${pair}?direction=auto`).then(r => r.data),
    enabled: hasTier(user, 'plus'),
  })

  useEffect(() => {
    if (canvasRef.current && heatData) {
      drawHeatmap(canvasRef.current, heatData, vpData, context?.mark_price || 0, zoomRange)
    }
  }, [heatData, vpData, context?.mark_price, zoomRange])

  const handlePairSubmit = (e) => {
    e.preventDefault()
    if (inputVal.trim()) setPair(inputVal.trim().toUpperCase())
  }

  if (!hasTier(user, 'plus')) {
    return (
      <>
        <TopBar title="Heatmap" />
        <div className="flex flex-col items-center justify-center px-6 pt-20 text-center gap-4">
          <Lock size={48} style={{ color: 'var(--color-gold)', opacity: 0.6 }} />
          <h2 style={{ fontSize: '20px', fontWeight: 800 }}>Plus Plan Required</h2>
          <p style={{ color: 'var(--color-dim)', fontSize: '14px', maxWidth: 280 }}>
            Liquidation Heatmap is available on Plus, Pro, and Elite plans.
          </p>
          <a href="/app" className="btn-gold" style={{ display: 'inline-block', width: 'auto', padding: '12px 32px' }}>
            Upgrade
          </a>
        </div>
      </>
    )
  }

  const quickPairs = summary?.summary?.slice(0, 5) || []

  return (
    <>
      <TopBar title="Liquidation Heatmap" />
      <div className="px-4 pt-4 pb-20">
        
        {/* Controls */}
        <div className="card p-3 mb-4">
          <form onSubmit={handlePairSubmit} className="flex gap-2 mb-3">
            <input 
              type="text" 
              value={inputVal}
              onChange={e => setInputVal(e.target.value)}
              className="input-field flex-1"
              style={{ padding: '8px 12px', fontSize: 14, textTransform: 'uppercase' }}
              placeholder="e.g. BTCUSDT"
            />
            <button type="submit" className="btn-gold" style={{ padding: '8px 16px' }}>Load</button>
          </form>

          <div className="flex gap-2 overflow-x-auto mb-3 pb-1" style={{ scrollbarWidth: 'none' }}>
            {[4, 12, 24, 72, 168].map(w => (
              <button
                key={w}
                onClick={() => setWindowHr(w)}
                style={{
                  flexShrink: 0, padding: '4px 10px', borderRadius: 8, fontSize: 11, fontWeight: 700,
                  background: windowHr === w ? 'var(--color-gold)' : 'var(--color-surface-3)',
                  color: windowHr === w ? '#000' : 'var(--color-dim)',
                  border: 'none'
                }}
              >
                {w < 24 ? `${w}h` : `${w/24}d`}
              </button>
            ))}
          </div>

          <div className="flex gap-2 overflow-x-auto" style={{ scrollbarWidth: 'none' }}>
            {quickPairs.map((p, i) => {
              const dom = p.dominant === 'LONG' ? 'var(--color-red)' : 'var(--color-green)'
              return (
                <button
                  key={i}
                  onClick={() => { setPair(p.symbol); setInputVal(p.symbol); }}
                  style={{
                    flexShrink: 0, padding: '4px 10px', borderRadius: 12, fontSize: 11, fontWeight: 700,
                    background: 'var(--color-surface-2)', border: `1px solid ${dom}`, color: dom,
                  }}
                >
                  {p.symbol.replace('USDT', '')}
                </button>
              )
            })}
          </div>
        </div>

        {/* Heatmap Canvas */}
        <div className="card p-3 mb-4 relative" style={{ overflow: 'hidden' }}>
          <div className="flex justify-between items-center mb-3">
            <div>
              <span style={{ fontSize: 14, fontWeight: 800 }}>{pair}</span>
              <div style={{ fontSize: 10, color: 'var(--color-dim)' }}>
                {heatData?.has_data ? `${heatData.total_events_24h} events` : 'Loading...'}
              </div>
            </div>
            <div className="flex gap-2">
              <button onClick={() => setZoomRange(r => Math.max(0.02, r - 0.1))} style={{ background: 'var(--color-surface-3)', border: 'none', color: 'var(--color-text)', width: 24, height: 24, borderRadius: 4, fontWeight: 800 }}>-</button>
              <button onClick={() => setZoomRange(r => Math.min(0.8, r + 0.1))} style={{ background: 'var(--color-surface-3)', border: 'none', color: 'var(--color-text)', width: 24, height: 24, borderRadius: 4, fontWeight: 800 }}>+</button>
            </div>
          </div>

          {heatLoading && (
            <div style={{ position: 'absolute', top: 50, left: 0, right: 0, bottom: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(0,0,0,0.5)', zIndex: 10 }}>
              <PageSpinner />
            </div>
          )}
          
          <canvas ref={canvasRef} style={{ width: '100%', height: 320, display: 'block' }} />
        </div>

        {/* Context Stats */}
        {context && (
          <div className="grid grid-cols-2 gap-3 mb-4">
            <div className="card p-3">
              <div style={{ fontSize: 10, color: 'var(--color-dim)', fontWeight: 700, textTransform: 'uppercase', marginBottom: 4 }}>Funding / 8h</div>
              <div style={{ fontSize: 13, fontWeight: 800, color: context.funding_rate > 0.0005 ? 'var(--color-red)' : context.funding_rate < -0.0005 ? 'var(--color-green)' : 'var(--color-gold)' }}>
                {context.funding_rate ? `${(context.funding_rate * 100).toFixed(4)}%` : '—'}
              </div>
            </div>
            <div className="card p-3">
              <div style={{ fontSize: 10, color: 'var(--color-dim)', fontWeight: 700, textTransform: 'uppercase', marginBottom: 4 }}>Bias</div>
              <div style={{ fontSize: 13, fontWeight: 800, color: context.funding_bias === 'LONG_HEAVY' ? 'var(--color-red)' : context.funding_bias === 'SHORT_HEAVY' ? 'var(--color-green)' : 'var(--color-gold)' }}>
                {context.funding_bias?.replace('_', ' ') || '—'}
              </div>
            </div>
          </div>
        )}

        {/* Suggestion Card */}
        <div className="card p-3">
          <div className="flex justify-between items-center mb-3">
            <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--color-text)' }}>🎯 TP/SL Suggestion</span>
            <button onClick={() => refetchSuggest()} style={{ fontSize: 11, background: 'var(--color-surface-3)', border: 'none', color: 'var(--color-dim)', padding: '2px 8px', borderRadius: 4 }}>↻ Refresh</button>
          </div>
          
          {!suggest ? (
            <div style={{ fontSize: 12, color: 'var(--color-dim)' }}>Loading...</div>
          ) : !suggest.has_data ? (
            <div style={{ fontSize: 12, color: 'var(--color-red)' }}>{suggest.error || 'No suggestion available'}</div>
          ) : (
            <div>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 8 }}>
                <span className={suggest.direction === 'LONG' ? 'badge-long' : 'badge-short'}>{suggest.direction}</span>
                <span style={{ fontSize: 12, fontWeight: 600 }}>R/R: {suggest.risk_reward?.toFixed(2)}</span>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                {suggest.tp_levels?.map((tp, i) => (
                  <div key={i} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, background: 'rgba(0,214,143,0.06)', padding: '6px 10px', borderRadius: 6 }}>
                    <span style={{ color: 'var(--color-green)' }}>TP{i+1} ({tp.type})</span>
                    <span className="font-mono font-bold">{tp.price?.toFixed(2)}</span>
                  </div>
                ))}
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, background: 'rgba(239,68,68,0.06)', padding: '6px 10px', borderRadius: 6, marginTop: 4 }}>
                  <span style={{ color: 'var(--color-red)' }}>Stop Loss</span>
                  <span className="font-mono font-bold">{suggest.sl_price?.toFixed(2)}</span>
                </div>
              </div>
            </div>
          )}
        </div>

      </div>
    </>
  )
}
