import { useState, useEffect, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/services/api'
import { useAuthStore } from '@/store/useAuthStore'
import TopBar from '@/components/TopBar'
import { PageSpinner } from '@/components/ui/Spinner'
import { hasTier } from '@/utils/helpers'
import { createChart, CrosshairMode, LineStyle } from 'lightweight-charts'
import { Lock } from 'lucide-react'

const INTERVALS = ['1m', '5m', '15m', '1h', '4h', '1d']
const QUICK_PAIRS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT']

export default function Charts() {
  const { user } = useAuthStore()
  const priceContainerRef = useRef(null)
  const indContainerRef = useRef(null)
  
  const [pair, setPair] = useState('BTCUSDT')
  const [interval, setInterval] = useState('1h')
  const [inputVal, setInputVal] = useState('BTCUSDT')

  // Refs to hold charts and series for updating
  const chartsRef = useRef({ priceChart: null, indChart: null })

  // We request enough bars to show a decent chart on mobile
  const { data, isLoading, isError } = useQuery({
    queryKey: ['chart-data', pair, interval],
    queryFn: () => api.get(`/api/chart/${pair}?interval=${interval}&bars=300`).then(r => r.data),
    enabled: hasTier(user, 'plus'),
    refetchInterval: 30_000,
  })

  // Initialize and update charts
  useEffect(() => {
    if (!hasTier(user, 'plus') || !priceContainerRef.current || !indContainerRef.current) return
    if (!data || data.error || !data.timestamps) return

    const d = data

    // Destroy existing charts if any
    if (chartsRef.current.priceChart) {
      chartsRef.current.priceChart.remove()
      chartsRef.current.priceChart = null
    }
    if (chartsRef.current.indChart) {
      chartsRef.current.indChart.remove()
      chartsRef.current.indChart = null
    }

    const priceEl = priceContainerRef.current
    const indEl = indContainerRef.current

    // Helper for precision
    const getPrecision = (price) => {
      if (!price || price <= 0) return { precision: 4, minMove: 0.0001 }
      if (price < 0.00001) return { precision: 8, minMove: 0.00000001 }
      if (price < 0.0001) return { precision: 7, minMove: 0.0000001 }
      if (price < 0.01) return { precision: 6, minMove: 0.000001 }
      if (price < 0.1) return { precision: 5, minMove: 0.00001 }
      if (price < 1) return { precision: 4, minMove: 0.0001 }
      if (price < 10) return { precision: 3, minMove: 0.001 }
      if (price < 100) return { precision: 2, minMove: 0.01 }
      if (price < 10000) return { precision: 1, minMove: 0.1 }
      return { precision: 0, minMove: 1 }
    }

    const lastClose = d.close && d.close.length ? d.close[d.close.length - 1] : 1
    const precFmt = getPrecision(lastClose)
    const pf = { type: 'price', ...precFmt }

    const createChartOptions = (height) => ({
      width: priceEl.clientWidth,
      height,
      layout: { background: { color: 'transparent' }, textColor: '#8899aa', fontSize: 10, fontFamily: "'Inter', sans-serif" },
      grid: { vertLines: { color: 'rgba(255,255,255,0.04)' }, horzLines: { color: 'rgba(255,255,255,0.04)' } },
      crosshair: { mode: CrosshairMode.Normal,
        vertLine: { color: '#3a4a5e', width: 1, style: LineStyle.Solid, labelBackgroundColor: '#1e2d40' },
        horzLine: { color: '#3a4a5e', width: 1, style: LineStyle.Solid, labelBackgroundColor: '#1e2d40' } },
      rightPriceScale: { borderColor: '#1a2536', scaleMargins: { top: 0.05, bottom: 0.05 } },
      timeScale: { borderColor: '#1a2536', timeVisible: true, secondsVisible: false, rightOffset: 3 },
      handleScale: { mouseWheel: true, pinch: true, axisPressedMouseMove: { time: true, price: true } },
      handleScroll: { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false },
      attributionLogo: false,
    })

    const toUnix = (ts) => Math.floor(new Date(ts).getTime() / 1000)

    const priceH = Math.max(260, priceEl.clientHeight || 300)
    const indH = Math.max(120, indEl.clientHeight || 120)

    const priceChart = createChart(priceEl, createChartOptions(priceH))
    const indChart = createChart(indEl, createChartOptions(indH))

    chartsRef.current = { priceChart, indChart }

    // --- PRICE CHART ---
    // Candles
    const candleSeries = priceChart.addCandlestickSeries({
      upColor: '#00d68f', downColor: '#ff4d6a',
      borderUpColor: '#00d68f', borderDownColor: '#ff4d6a',
      wickUpColor: '#4fffb8', wickDownColor: '#ff6b85',
      priceFormat: pf,
    })
    candleSeries.setData(d.timestamps.map((t, i) => ({ time: toUnix(t), open: d.open[i], high: d.high[i], low: d.low[i], close: d.close[i] })))

    // Volume
    const volSeries = priceChart.addHistogramSeries({ priceFormat: { type: 'volume' }, priceScaleId: 'vol' })
    priceChart.priceScale('vol').applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } })
    volSeries.setData(d.timestamps.map((t, i) => ({
      time: toUnix(t), value: d.volume[i],
      color: d.close[i] >= d.open[i] ? 'rgba(0,214,143,0.12)' : 'rgba(255,77,106,0.12)'
    })))

    // CE Line
    if (d.ce_line_dir) {
      const ceLineSeries = priceChart.addLineSeries({
        lineWidth: 2, priceLineVisible: false, lastValueVisible: false,
        crosshairMarkerVisible: false, priceFormat: pf
      })
      ceLineSeries.setData(d.timestamps.map((t, i) => ({
        time: toUnix(t),
        value: d.ce_line_dir[i] === 1 ? d.ce_line_long_stop[i] : d.ce_line_short_stop[i],
        color: d.ce_line_dir[i] === 1 ? '#00d68f' : '#ff4d6a'
      })))
    }

    // CE Cloud
    if (d.ce_cloud_dir) {
      const ceCloudSeries = priceChart.addLineSeries({
        lineWidth: 2, priceLineVisible: false, lastValueVisible: false,
        crosshairMarkerVisible: false, lineStyle: LineStyle.Dotted, priceFormat: pf
      })
      ceCloudSeries.setData(d.timestamps.map((t, i) => ({
        time: toUnix(t),
        value: d.ce_cloud_dir[i] === 1 ? d.ce_cloud_long_stop[i] : d.ce_cloud_short_stop[i],
        color: d.ce_cloud_dir[i] === 1 ? 'rgba(0,214,143,0.45)' : 'rgba(255,77,106,0.45)'
      })))
    }

    // --- INDICATOR CHART ---
    // LinReg Histogram
    if (d.linreg) {
      const linregSeries = indChart.addHistogramSeries({ priceLineVisible: false, lastValueVisible: false, priceScaleId: 'lr' })
      indChart.priceScale('lr').applyOptions({ scaleMargins: { top: 0.08, bottom: 0.08 } })
      linregSeries.setData(d.timestamps.map((t, i) => ({
        time: toUnix(t), value: d.linreg[i],
        color: d.linreg[i] >= 0 ? 'rgba(0,214,143,0.28)' : 'rgba(255,77,106,0.28)'
      })))
    }

    // TSI Line
    if (d.tsi) {
      const tsiSeries = indChart.addLineSeries({ color: '#a78bfa', lineWidth: 2, priceLineVisible: false, lastValueVisible: true })
      tsiSeries.setData(d.timestamps.map((t, i) => ({ time: toUnix(t), value: d.tsi[i] })))
    }

    // Adaptive thresholds
    if (d.adapt_l1 && d.adapt_l2) {
      const addThresh = (val, col) => {
        [val, -val].forEach(v => {
          const l = indChart.addLineSeries({ color: col, lineWidth: 1, lineStyle: LineStyle.Dotted, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false })
          l.setData(d.timestamps.map(t => ({ time: toUnix(t), value: v })))
        })
      }
      addThresh(d.adapt_l1, 'rgba(244,162,54,0.6)')
      addThresh(d.adapt_l2, 'rgba(255,77,106,0.6)')
      
      const zeroS = indChart.addLineSeries({ color: 'rgba(255,255,255,0.1)', lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false })
      zeroS.setData(d.timestamps.map(t => ({ time: toUnix(t), value: 0 })))
    }

    // Sync timelines
    let syncingRange = false
    priceChart.timeScale().subscribeVisibleLogicalRangeChange(r => {
      if (syncingRange || !r) return
      syncingRange = true
      try { indChart.timeScale().setVisibleLogicalRange(r) } catch(_) {}
      syncingRange = false
    })
    indChart.timeScale().subscribeVisibleLogicalRangeChange(r => {
      if (syncingRange || !r) return
      syncingRange = true
      try { priceChart.timeScale().setVisibleLogicalRange(r) } catch(_) {}
      syncingRange = false
    })

    priceChart.priceScale('right').applyOptions({ autoScale: true, scaleMargins: { top: 0.06, bottom: 0.20 } })

    const handleResize = () => {
      if (priceContainerRef.current) priceChart.applyOptions({ width: priceContainerRef.current.clientWidth })
      if (indContainerRef.current) indChart.applyOptions({ width: indContainerRef.current.clientWidth })
    }

    window.addEventListener('resize', handleResize)

    return () => {
      window.removeEventListener('resize', handleResize)
      priceChart.remove()
      indChart.remove()
    }
  }, [data, user])

  const handlePairSubmit = (e) => {
    e.preventDefault()
    if (inputVal.trim()) {
      setPair(inputVal.trim().toUpperCase())
    }
  }

  if (!hasTier(user, 'plus')) {
    return (
      <>
        <TopBar title="Interactive Charts" />
        <div className="flex flex-col items-center justify-center px-6 pt-20 text-center gap-4">
          <Lock size={48} style={{ color: 'var(--color-gold)', opacity: 0.6 }} />
          <h2 style={{ fontSize: '20px', fontWeight: 800 }}>Plus Plan Required</h2>
          <p style={{ color: 'var(--color-dim)', fontSize: '14px', maxWidth: 280 }}>
            Interactive charts are available on Plus, Pro, and Elite plans.
          </p>
          <a href="/app" className="btn-gold" style={{ display: 'inline-block', width: 'auto', padding: '12px 32px' }}>
            Upgrade
          </a>
        </div>
      </>
    )
  }

  // Determine current TSI zone
  let tsiZone = 'Neutral', tsiColor = 'var(--color-dim)'
  let tsiVal = 0, lrVal = 0, ceLineDir = 1, ceCloudDir = 1
  if (data?.timestamps?.length) {
    const last = data.timestamps.length - 1
    tsiVal = data.tsi?.[last] || 0
    lrVal = data.linreg?.[last] || 0
    ceLineDir = data.ce_line_dir?.[last] || 1
    ceCloudDir = data.ce_cloud_dir?.[last] || 1
    if (tsiVal >= data.adapt_l2) { tsiZone = 'OB L2'; tsiColor = 'var(--color-red)' }
    else if (tsiVal >= data.adapt_l1) { tsiZone = 'OB L1'; tsiColor = 'var(--color-red)' }
    else if (tsiVal <= -data.adapt_l2) { tsiZone = 'OS L2'; tsiColor = 'var(--color-green)' }
    else if (tsiVal <= -data.adapt_l1) { tsiZone = 'OS L1'; tsiColor = 'var(--color-green)' }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', paddingBottom: 60 }}>
      <TopBar title="Interactive Charts" />
      
      <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--color-border)' }}>
        <form onSubmit={handlePairSubmit} style={{ display: 'flex', gap: 8, marginBottom: 10 }}>
          <input 
            type="text" 
            value={inputVal}
            onChange={e => setInputVal(e.target.value)}
            className="input-field"
            style={{ padding: '8px 12px', fontSize: 14, textTransform: 'uppercase' }}
            placeholder="e.g. BTCUSDT"
          />
          <button type="submit" className="btn-gold" style={{ padding: '8px 16px' }}>Load</button>
        </form>

        <div style={{ display: 'flex', gap: 6, overflowX: 'auto', scrollbarWidth: 'none', marginBottom: 12 }}>
          {QUICK_PAIRS.map(p => (
            <button
              key={p}
              onClick={() => { setPair(p); setInputVal(p); }}
              style={{
                flexShrink: 0, padding: '4px 10px', borderRadius: 12, fontSize: 11, fontWeight: 700,
                background: pair === p ? 'var(--color-surface-3)' : 'var(--color-surface-2)',
                border: `1px solid ${pair === p ? 'var(--color-gold)' : 'var(--color-border)'}`,
                color: pair === p ? 'var(--color-gold)' : 'var(--color-text)',
              }}
            >
              {p.replace('USDT', '')}
            </button>
          ))}
        </div>

        <div style={{ display: 'flex', gap: 6, overflowX: 'auto', scrollbarWidth: 'none' }}>
          {INTERVALS.map(i => (
            <button
              key={i}
              onClick={() => setInterval(i)}
              style={{
                flexShrink: 0, padding: '4px 12px', borderRadius: 6, fontSize: 12, fontWeight: 700,
                background: interval === i ? 'var(--color-gold)' : 'transparent',
                color: interval === i ? '#000' : 'var(--color-dim)',
              }}
            >
              {i}
            </button>
          ))}
        </div>
      </div>

      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', position: 'relative' }}>
        {isLoading && (
          <div style={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 10 }}>
            <PageSpinner />
          </div>
        )}
        {isError && (
          <div style={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 10, color: 'var(--color-red)' }}>
            Error loading chart data.
          </div>
        )}

        {/* Legend */}
        {data && !isLoading && (
          <div style={{ padding: '8px 16px', display: 'flex', flexWrap: 'wrap', gap: '8px 16px', fontSize: 10, fontWeight: 600, background: 'var(--color-surface)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}><div style={{ width: 8, height: 2, background: '#00d68f' }}></div>CE Long</div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}><div style={{ width: 8, height: 2, background: '#ff4d6a' }}></div>CE Short</div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}><div style={{ width: 8, height: 8, background: 'rgba(0,214,143,0.3)', borderRadius: 2 }}></div>Cloud</div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}><div style={{ width: 8, height: 2, background: '#a78bfa' }}></div>TSI</div>
          </div>
        )}

        {/* Charts */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
          <div ref={priceContainerRef} style={{ width: '100%', minHeight: '260px', flex: 1 }} />
          <div style={{ height: 1, background: 'var(--color-border)', width: '100%' }}></div>
          <div ref={indContainerRef} style={{ width: '100%', minHeight: '120px', height: '120px' }} />
        </div>

        {/* Status Row */}
        {data && !isLoading && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 8px', padding: '8px 12px', borderTop: '1px solid var(--color-border)', background: 'var(--color-surface)', fontSize: 10 }}>
            <div style={{ display: 'flex', gap: 4, background: 'var(--color-surface-2)', padding: '2px 6px', borderRadius: 4 }}>
              <span style={{ color: 'var(--color-dim)' }}>TSI Zone:</span>
              <span style={{ fontWeight: 700, color: tsiColor }}>{tsiZone}</span>
            </div>
            <div style={{ display: 'flex', gap: 4, background: 'var(--color-surface-2)', padding: '2px 6px', borderRadius: 4 }}>
              <span style={{ color: 'var(--color-dim)' }}>TSI:</span>
              <span style={{ fontWeight: 700, color: tsiVal > 0 ? 'var(--color-red)' : 'var(--color-green)' }}>{tsiVal.toFixed(3)}</span>
            </div>
            <div style={{ display: 'flex', gap: 4, background: 'var(--color-surface-2)', padding: '2px 6px', borderRadius: 4 }}>
              <span style={{ color: 'var(--color-dim)' }}>LinReg:</span>
              <span style={{ fontWeight: 700, color: lrVal > 0 ? 'var(--color-green)' : lrVal < 0 ? 'var(--color-red)' : 'var(--color-text)' }}>{lrVal.toFixed(3)}</span>
            </div>
            <div style={{ display: 'flex', gap: 4, background: 'var(--color-surface-2)', padding: '2px 6px', borderRadius: 4 }}>
              <span style={{ color: 'var(--color-dim)' }}>CE Line:</span>
              <span style={{ fontWeight: 700, color: ceLineDir === 1 ? 'var(--color-green)' : 'var(--color-red)' }}>{ceLineDir === 1 ? 'LONG' : 'SHORT'}</span>
            </div>
            <div style={{ display: 'flex', gap: 4, background: 'var(--color-surface-2)', padding: '2px 6px', borderRadius: 4 }}>
              <span style={{ color: 'var(--color-dim)' }}>CE Cloud:</span>
              <span style={{ fontWeight: 700, color: ceCloudDir === 1 ? 'var(--color-green)' : 'var(--color-red)' }}>{ceCloudDir === 1 ? 'LONG' : 'SHORT'}</span>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
