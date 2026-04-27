import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/services/api'
import { useAuthStore } from '@/store/useAuthStore'
import TopBar from '@/components/TopBar'
import StatCard from '@/components/ui/StatCard'
import { PageSpinner } from '@/components/ui/Spinner'
import { formatPnl, pnlColor, formatPrice, cleanPair, timeAgo, hasTier } from '@/utils/helpers'
import { Power, PowerOff, AlertTriangle, Settings, History, Save, Trash2, ShieldAlert } from 'lucide-react'

// --- Components ---

function PositionRow({ pos, onClose }) {
  const isLong = pos.side === 'BUY' || pos.direction === 'LONG'
  return (
    <div className="flex items-center gap-3 py-3" style={{ borderBottom: '1px solid var(--color-border)' }}>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-0.5">
          <span className="font-mono font-bold text-sm">{cleanPair(pos.pair ?? pos.symbol)}</span>
          <span className={isLong ? 'badge-long' : 'badge-short'}>{isLong ? 'LONG' : 'SHORT'}</span>
        </div>
        <span style={{ fontSize: '11px', color: 'var(--color-dim)' }}>
          Entry {formatPrice(pos.entry_price)} · {pos.leverage ?? 1}x
        </span>
        {pos.sl_price > 0 && (
          <div style={{ fontSize: '10px', color: 'var(--color-red)', marginTop: 2, fontFamily: 'monospace' }}>
            SL: {formatPrice(pos.sl_price)}
          </div>
        )}
      </div>
      <div className="text-right">
        <div className="font-mono font-bold text-sm" style={{ color: pnlColor(pos.pnl) }}>
          {formatPnl(pos.pnl)}
        </div>
        <div style={{ fontSize: '11px', color: 'var(--color-dim)', marginBottom: 4 }}>
          {formatPrice(pos.mark_price ?? pos.current_price)}
        </div>
        <button
          onClick={() => onClose(pos.pair ?? pos.symbol)}
          style={{ fontSize: 9, fontWeight: 700, padding: '2px 8px', borderRadius: 4, background: 'transparent', border: '1px solid var(--color-red)', color: 'var(--color-red)', textTransform: 'uppercase' }}
        >
          Close
        </button>
      </div>
    </div>
  )
}

function TradeHistoryRow({ trade }) {
  const isLong = trade.direction === 'LONG'
  const pnlU = trade.pnl_usd ?? 0
  const pnlP = trade.pnl_pct ?? 0
  
  return (
    <div className="flex items-center gap-3 py-3" style={{ borderBottom: '1px solid var(--color-border)' }}>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-0.5">
          <span className="font-mono font-bold text-sm">{cleanPair(trade.pair)}</span>
          <span className={isLong ? 'badge-long' : 'badge-short'}>{trade.direction}</span>
          <span style={{ fontSize: 9, fontWeight: 700, padding: '2px 6px', borderRadius: 4, background: 'var(--color-surface-2)', border: '1px solid var(--color-border)', color: 'var(--color-text)', textTransform: 'uppercase' }}>
            {trade.status}
          </span>
        </div>
        <span style={{ fontSize: '11px', color: 'var(--color-dim)' }}>
          {new Date(trade.created_at * 1000).toLocaleDateString()} · {trade.leverage}x · ${Math.round(trade.size_usd ?? 0)}
        </span>
      </div>
      <div className="text-right">
        <div className="font-mono font-bold text-sm" style={{ color: pnlColor(pnlU) }}>
          {formatPnl(pnlU)}
        </div>
        <div style={{ fontSize: '11px', color: pnlColor(pnlP) }}>
          {pnlP > 0 ? '+' : ''}{pnlP.toFixed(2)}%
        </div>
      </div>
    </div>
  )
}

// --- Main Page ---

export default function CopyTrading() {
  const { user } = useAuthStore()
  const qc = useQueryClient()
  const [tab, setTab] = useState('positions') // positions, history, settings

  // Form state
  const [form, setForm] = useState({
    api_key: '', api_secret: '',
    size_mode: 'pct', size_pct: 2.0, fixed_size_usd: 5.0, max_size_pct: 5.0,
    leverage_mode: 'auto', max_leverage: 20,
    tp_mode: 'pyramid', sl_mode: 'signal', sl_pct: 3.0,
    scale_with_sqi: false, copy_experimental: false,
    allowed_tiers: ['blue_chip', 'large_cap', 'mid_cap', 'small_cap', 'high_risk'],
    allowed_sectors: [], hot_only: false
  })

  // Queries
  const { data: config, isLoading: cfgLoading } = useQuery({
    queryKey: ['ct-config'],
    queryFn: () => api.get('/api/copy-trading/config').then(r => r.data),
  })

  const { data: balance } = useQuery({
    queryKey: ['ct-balance'],
    queryFn: () => api.get('/api/copy-trading/balance').then(r => r.data),
    enabled: config?.is_active,
    refetchInterval: 15_000,
  })

  const { data: livePnl } = useQuery({
    queryKey: ['ct-live-pnl'],
    queryFn: () => api.get('/api/copy-trading/live-pnl').then(r => r.data),
    enabled: config?.is_active,
    refetchInterval: 10_000,
  })

  const { data: history } = useQuery({
    queryKey: ['ct-history'],
    queryFn: () => api.get('/api/copy-trading/history?limit=20').then(r => r.data),
    enabled: tab === 'history',
  })
  
  const { data: udsStatus } = useQuery({
    queryKey: ['ct-uds'],
    queryFn: () => api.get('/api/copy-trading/uds-status').then(r => r.data),
    enabled: config?.is_active,
    refetchInterval: 30_000,
  })

  // Mutations
  const toggleMutation = useMutation({
    mutationFn: (enable) => api.post('/api/copy-trading/toggle', { active: enable }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['ct-config'] }),
  })

  const closePosMutation = useMutation({
    mutationFn: (pair) => api.post(`/api/copy-trading/close-position/${pair}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['ct-live-pnl'] })
      qc.invalidateQueries({ queryKey: ['ct-balance'] })
    },
  })
  
  const closeAllMutation = useMutation({
    mutationFn: () => api.post('/api/copy-trading/close-all'),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['ct-live-pnl'] })
      qc.invalidateQueries({ queryKey: ['ct-balance'] })
    },
  })

  const saveKeysMutation = useMutation({
    mutationFn: (data) => api.post('/api/copy-trading/keys', data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['ct-config'] }),
  })
  
  const saveSettingsMutation = useMutation({
    mutationFn: (data) => api.post('/api/copy-trading/settings', data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['ct-config'] }),
  })
  
  const deleteKeysMutation = useMutation({
    mutationFn: () => api.delete('/api/copy-trading/keys'),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['ct-config'] })
      setForm(prev => ({ ...prev, api_key: '', api_secret: '' }))
    },
  })

  // Sync config to form
  useEffect(() => {
    if (config) {
      setForm(prev => ({
        ...prev,
        size_mode: config.size_mode || 'pct',
        size_pct: config.size_pct || 2.0,
        fixed_size_usd: config.fixed_size_usd || 5.0,
        max_size_pct: config.max_size_pct || 5.0,
        leverage_mode: config.leverage_mode || 'auto',
        max_leverage: config.max_leverage || 20,
        tp_mode: config.tp_mode || 'pyramid',
        sl_mode: config.sl_mode || 'signal',
        sl_pct: config.sl_pct || 3.0,
        scale_with_sqi: config.scale_with_sqi || false,
        copy_experimental: config.copy_experimental || false,
        allowed_tiers: config.filters?.allowed_tiers?.split(',').filter(Boolean) || ['blue_chip', 'large_cap', 'mid_cap', 'small_cap', 'high_risk'],
        allowed_sectors: config.filters?.allowed_sectors === 'all' ? [] : (config.filters?.allowed_sectors?.split(',').filter(Boolean) || []),
        hot_only: config.filters?.hot_only || false,
      }))
    }
  }, [config])

  const handleSave = () => {
    const payload = { ...form }
    if (config?.has_keys) {
      saveSettingsMutation.mutate(payload)
      // also save filters
      api.post('/api/copy-trading/filters', {
        allowed_tiers: form.allowed_tiers.join(','),
        allowed_sectors: form.allowed_sectors.length ? form.allowed_sectors.join(',') : 'all',
        hot_only: form.hot_only
      })
    } else {
      if (!form.api_key || !form.api_secret) return alert('API keys required')
      saveKeysMutation.mutate(payload)
    }
  }

  const isTierOk = hasTier(user, 'plus')
  const positions = livePnl?.positions ? Object.values(livePnl.positions) : []
  const totalPnl = positions.reduce((sum, p) => sum + (parseFloat(p.pnl_usd ?? p.pnl) || 0), 0)

  if (!isTierOk) {
    return (
      <>
        <TopBar title="Copy Trading" />
        <div className="flex flex-col items-center justify-center px-6 pt-20 text-center gap-4">
          <AlertTriangle size={48} style={{ color: 'var(--color-gold)', opacity: 0.6 }} />
          <h2 style={{ fontSize: '20px', fontWeight: 800 }}>Plus Plan Required</h2>
          <p style={{ color: 'var(--color-dim)', fontSize: '14px', maxWidth: 280 }}>
            Copy trading is available on Plus, Pro, and Elite plans.
          </p>
          <a href="/app" className="btn-gold" style={{ display: 'inline-block', width: 'auto', padding: '12px 32px' }}>
            Upgrade
          </a>
        </div>
      </>
    )
  }

  if (cfgLoading) return <><TopBar title="Copy Trading" /><PageSpinner /></>

  const hasKeys = config?.has_keys
  const isActive = config?.is_active
  const udsLive = udsStatus?.connected

  if (!hasKeys && tab !== 'settings') {
    setTab('settings')
  }

  return (
    <>
      <TopBar title="Copy Trading" />
      
      {/* Tabs */}
      {hasKeys && (
        <div style={{ display: 'flex', borderBottom: '1px solid var(--color-border)', padding: '0 16px' }}>
          {[
            { id: 'positions', label: 'Positions' },
            { id: 'history', label: 'History' },
            { id: 'settings', label: 'Settings' }
          ].map(t => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              style={{
                flex: 1, padding: '14px 0', fontSize: 13, fontWeight: 700,
                background: 'transparent', border: 'none',
                color: tab === t.id ? 'var(--color-gold)' : 'var(--color-dim)',
                borderBottom: tab === t.id ? '2px solid var(--color-gold)' : '2px solid transparent',
              }}
            >
              {t.label}
            </button>
          ))}
        </div>
      )}

      <div className="px-4 pt-4 pb-20">
        
        {/* --- POSITIONS TAB --- */}
        {tab === 'positions' && hasKeys && (
          <>
            <div className="flex items-center justify-between mb-4">
              <div>
                <span style={{ fontSize: '12px', color: 'var(--color-dim)', fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase' }}>
                  Status
                </span>
                <div className="flex items-center gap-2 mt-1">
                  <div style={{
                    width: 8, height: 8, borderRadius: '50%',
                    background: isActive ? 'var(--color-green)' : 'var(--color-dimmer)',
                    boxShadow: isActive ? '0 0 6px var(--color-green)' : 'none',
                  }} />
                  <span style={{ fontWeight: 700, fontSize: '15px' }}>{isActive ? 'Active' : 'Inactive'}</span>
                  {udsLive !== undefined && isActive && (
                    <span style={{ 
                      fontSize: 10, padding: '2px 6px', borderRadius: 10, fontWeight: 700, marginLeft: 4,
                      background: udsLive ? 'rgba(16,185,129,0.15)' : 'rgba(240,185,11,0.15)',
                      color: udsLive ? 'var(--color-green)' : 'var(--color-gold)',
                      border: `1px solid ${udsLive ? 'rgba(16,185,129,0.3)' : 'rgba(240,185,11,0.3)'}`
                    }}>
                      {udsLive ? '🟢 WS Live' : '🟡 REST Fallback'}
                    </span>
                  )}
                </div>
              </div>
              <button
                onClick={() => toggleMutation.mutate(!isActive)}
                disabled={toggleMutation.isPending}
                style={{
                  display: 'flex', alignItems: 'center', gap: 8,
                  padding: '10px 18px', borderRadius: 10, border: 'none', cursor: 'pointer',
                  fontWeight: 700, fontSize: '14px', transition: 'all 0.15s',
                  background: isActive ? 'rgba(239,68,68,0.15)' : 'rgba(16,185,129,0.15)',
                  color: isActive ? 'var(--color-red)' : 'var(--color-green)',
                  opacity: toggleMutation.isPending ? 0.5 : 1,
                }}
              >
                {isActive ? <PowerOff size={16} /> : <Power size={16} />}
                {isActive ? 'Stop' : 'Start'}
              </button>
            </div>

            <div className="grid grid-cols-2 gap-3 mb-5">
              <StatCard
                label="Balance"
                value={balance?.total_usdt != null ? `$${parseFloat(balance.total_usdt).toFixed(2)}` : '—'}
                sub="USDT"
              />
              <StatCard
                label="Open PnL"
                value={positions.length > 0 ? formatPnl(totalPnl) : '—'}
                sub={`${positions.length} positions`}
                valueStyle={{ color: pnlColor(totalPnl) }}
              />
            </div>

            <div className="card px-4 py-3">
              <div className="flex items-center justify-between mb-2">
                <span style={{ fontSize: '13px', fontWeight: 700, color: 'var(--color-dim)', letterSpacing: '0.05em', textTransform: 'uppercase' }}>
                  Open Positions
                </span>
                {positions.length > 0 && (
                  <button 
                    onClick={() => {
                      if (confirm('Close ALL positions immediately at market price?')) {
                        closeAllMutation.mutate()
                      }
                    }}
                    style={{ fontSize: 11, fontWeight: 700, color: 'var(--color-red)', background: 'transparent', border: 'none', cursor: 'pointer' }}
                  >
                    Close All
                  </button>
                )}
              </div>
              {positions.length === 0 ? (
                <p style={{ color: 'var(--color-dim)', fontSize: '13px', padding: '12px 0' }}>
                  No open positions.
                </p>
              ) : (
                positions.map((p, i) => (
                  <PositionRow 
                    key={p.pair ?? p.symbol ?? i} 
                    pos={p} 
                    onClose={(pair) => {
                      if (confirm(`Close ${pair} position immediately at market price?`)) {
                        closePosMutation.mutate(pair)
                      }
                    }} 
                  />
                ))
              )}
            </div>
          </>
        )}

        {/* --- HISTORY TAB --- */}
        {tab === 'history' && hasKeys && (
          <div className="card px-4 py-3">
            <div className="flex items-center justify-between mb-2">
              <span style={{ fontSize: '13px', fontWeight: 700, color: 'var(--color-dim)', letterSpacing: '0.05em', textTransform: 'uppercase' }}>
                Trade History
              </span>
            </div>
            {!history ? (
              <PageSpinner />
            ) : history.trades?.length === 0 ? (
              <p style={{ color: 'var(--color-dim)', fontSize: '13px', padding: '12px 0' }}>
                No past trades found.
              </p>
            ) : (
              history.trades?.map((t, i) => <TradeHistoryRow key={t.id ?? i} trade={t} />)
            )}
          </div>
        )}

        {/* --- SETTINGS TAB --- */}
        {tab === 'settings' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
            
            {!hasKeys && (
              <div style={{ background: 'rgba(228,195,117,0.08)', border: '1px solid rgba(228,195,117,0.2)', padding: 16, borderRadius: 12 }}>
                <h3 style={{ fontSize: 16, fontWeight: 800, color: 'var(--color-gold)', marginBottom: 8 }}>Connect Binance</h3>
                <p style={{ fontSize: 13, color: 'var(--color-text)', marginBottom: 12 }}>Enter your Binance API keys with Futures enabled. IP Restriction is highly recommended (configure in full dashboard).</p>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                  <input type="text" placeholder="API Key" className="input-field" value={form.api_key} onChange={e => setForm({...form, api_key: e.target.value})} />
                  <input type="password" placeholder="API Secret" className="input-field" value={form.api_secret} onChange={e => setForm({...form, api_secret: e.target.value})} />
                </div>
              </div>
            )}

            <div className="card p-4">
              <h3 style={{ fontSize: 14, fontWeight: 700, marginBottom: 12, color: 'var(--color-dim)' }}>Position Sizing</h3>
              
              <div style={{ display: 'flex', gap: 10, marginBottom: 16 }}>
                <button onClick={() => setForm({...form, size_mode: 'pct'})} style={{ flex: 1, padding: 10, borderRadius: 8, border: '1px solid', borderColor: form.size_mode === 'pct' ? 'var(--color-gold)' : 'var(--color-border)', background: form.size_mode === 'pct' ? 'rgba(228,195,117,0.1)' : 'transparent', color: form.size_mode === 'pct' ? 'var(--color-gold)' : 'var(--color-dim)', fontWeight: 700, fontSize: 13 }}>% of Balance</button>
                <button onClick={() => setForm({...form, size_mode: 'fixed_usd'})} style={{ flex: 1, padding: 10, borderRadius: 8, border: '1px solid', borderColor: form.size_mode === 'fixed_usd' ? 'var(--color-gold)' : 'var(--color-border)', background: form.size_mode === 'fixed_usd' ? 'rgba(228,195,117,0.1)' : 'transparent', color: form.size_mode === 'fixed_usd' ? 'var(--color-gold)' : 'var(--color-dim)', fontWeight: 700, fontSize: 13 }}>Fixed USD</button>
              </div>

              {form.size_mode === 'pct' ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                  <div>
                    <label style={{ fontSize: 11, color: 'var(--color-dim)', display: 'block', marginBottom: 4 }}>Size per trade (%)</label>
                    <input type="number" step="0.1" className="input-field" value={form.size_pct} onChange={e => setForm({...form, size_pct: parseFloat(e.target.value) || 0})} />
                  </div>
                  <div>
                    <label style={{ fontSize: 11, color: 'var(--color-dim)', display: 'block', marginBottom: 4 }}>Max Risk Cap (%)</label>
                    <input type="number" step="0.1" className="input-field" value={form.max_size_pct} onChange={e => setForm({...form, max_size_pct: parseFloat(e.target.value) || 0})} />
                  </div>
                </div>
              ) : (
                <div>
                  <label style={{ fontSize: 11, color: 'var(--color-dim)', display: 'block', marginBottom: 4 }}>Fixed Amount (USDT)</label>
                  <input type="number" step="1" className="input-field" value={form.fixed_size_usd} onChange={e => setForm({...form, fixed_size_usd: parseFloat(e.target.value) || 0})} />
                </div>
              )}
            </div>

            <div className="card p-4">
              <h3 style={{ fontSize: 14, fontWeight: 700, marginBottom: 12, color: 'var(--color-dim)' }}>Leverage Mode</h3>
              <div style={{ display: 'flex', gap: 8, marginBottom: 16, overflowX: 'auto', scrollbarWidth: 'none', paddingBottom: 4 }}>
                {[
                  { id: 'auto', label: 'Auto (Signal)' },
                  { id: 'fixed', label: 'Fixed' },
                  { id: 'max_pair', label: 'Max Pair' }
                ].map(l => (
                  <button key={l.id} onClick={() => setForm({...form, leverage_mode: l.id})} style={{ flexShrink: 0, padding: '8px 14px', borderRadius: 8, border: '1px solid', borderColor: form.leverage_mode === l.id ? '#a78bfa' : 'var(--color-border)', background: form.leverage_mode === l.id ? 'rgba(167,139,250,0.1)' : 'transparent', color: form.leverage_mode === l.id ? '#a78bfa' : 'var(--color-dim)', fontWeight: 700, fontSize: 12 }}>{l.label}</button>
                ))}
              </div>
              {form.leverage_mode !== 'max_pair' && (
                <div>
                  <label style={{ fontSize: 11, color: 'var(--color-dim)', display: 'block', marginBottom: 4 }}>{form.leverage_mode === 'fixed' ? 'Fixed Leverage (x)' : 'Max Leverage Cap (x)'}</label>
                  <input type="number" step="1" min="1" max="125" className="input-field" value={form.max_leverage} onChange={e => setForm({...form, max_leverage: parseInt(e.target.value) || 1})} />
                </div>
              )}
            </div>

            <div className="card p-4">
              <h3 style={{ fontSize: 14, fontWeight: 700, marginBottom: 12, color: 'var(--color-dim)' }}>Take Profit & Stop Loss</h3>
              <label style={{ fontSize: 11, color: 'var(--color-dim)', display: 'block', marginBottom: 6 }}>Take Profit Mode</label>
              <select className="input-field" value={form.tp_mode} onChange={e => setForm({...form, tp_mode: e.target.value})} style={{ padding: '12px 16px', marginBottom: 16 }}>
                <option value="pyramid">Pyramid (30/30/20/20 at TP1-4)</option>
                <option value="tp1_100">100% at TP1</option>
                <option value="tp2_100">100% at TP2</option>
                <option value="tp3_100">100% at TP3</option>
                <option value="half_half">50% TP1 / 50% TP2</option>
                <option value="none">No Take Profit (Manual)</option>
              </select>

              <label style={{ fontSize: 11, color: 'var(--color-dim)', display: 'block', marginBottom: 6 }}>Stop Loss Mode</label>
              <select className="input-field" value={form.sl_mode} onChange={e => setForm({...form, sl_mode: e.target.value})} style={{ padding: '12px 16px', marginBottom: form.sl_mode === 'pct' ? 10 : 0 }}>
                <option value="signal">Signal SL (Recommended)</option>
                <option value="pct">Fixed Percentage</option>
                <option value="none">No Stop Loss (Dangerous)</option>
              </select>

              {form.sl_mode === 'pct' && (
                <div>
                  <label style={{ fontSize: 11, color: 'var(--color-dim)', display: 'block', marginBottom: 4 }}>Fixed SL (%)</label>
                  <input type="number" step="0.1" className="input-field" value={form.sl_pct} onChange={e => setForm({...form, sl_pct: parseFloat(e.target.value) || 0})} />
                </div>
              )}
            </div>

            <button 
              className="btn-gold" 
              onClick={handleSave}
              disabled={saveKeysMutation.isPending || saveSettingsMutation.isPending}
              style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: 8 }}
            >
              <Save size={18} /> Save Settings
            </button>

            {hasKeys && (
              <button 
                onClick={() => {
                  if (confirm('Delete API keys and all settings? This cannot be undone.')) {
                    deleteKeysMutation.mutate()
                  }
                }}
                disabled={deleteKeysMutation.isPending}
                style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: 8, padding: 14, borderRadius: 10, border: '1px solid rgba(239,68,68,0.3)', background: 'transparent', color: 'var(--color-red)', fontWeight: 700, fontSize: 14 }}
              >
                <Trash2 size={18} /> Delete API Keys
              </button>
            )}

          </div>
        )}

      </div>
    </>
  )
}
