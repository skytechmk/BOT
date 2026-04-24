/**
 * order-flow.js — Market Analytics widget.
 * Renders /api/flow/snapshot/{symbol}:
 *   CVD (aggTrade) | MFI gauge + history | L/S ratio | OI sparkline | Funding pill | Taker ratio
 * All market data from Binance public APIs — no external key needed.
 */

(function () {
  'use strict';

  /* ── helpers ─────────────────────────────────────────── */

  const $ = id => document.getElementById(id);

  function fmtDelta(v) {
    if (v === null || v === undefined) return '—';
    const sign = v >= 0 ? '+' : '';
    const abs  = Math.abs(v);
    if (abs >= 1e6) return sign + (v / 1e6).toFixed(2) + 'M';
    if (abs >= 1e3) return sign + (v / 1e3).toFixed(1) + 'K';
    return sign + v.toFixed(2);
  }

  function fmtPct(v, factor = 100) {
    if (v === null || v === undefined) return '—';
    const pct = v * factor;
    return (pct >= 0 ? '+' : '') + pct.toFixed(2) + '%';
  }

  function fmtUsd(v) {
    if (!v && v !== 0) return '—';
    if (Math.abs(v) >= 1e9) return '$' + (v / 1e9).toFixed(2) + 'B';
    if (Math.abs(v) >= 1e6) return '$' + (v / 1e6).toFixed(2) + 'M';
    if (Math.abs(v) >= 1e3) return '$' + (v / 1e3).toFixed(1) + 'K';
    return '$' + v.toFixed(0);
  }

  function colD(val) {
    if (val >  0.05) return 'var(--green)';
    if (val < -0.05) return 'var(--red)';
    return 'var(--text-dim)';
  }

  function setHTML(id, html) { const el = $(id); if (el) el.innerHTML = html; }

  /* ── MFI gauge (canvas arc) ───────────────────────────── */

  function drawMfiGauge(value) {
    const c = $('flow-mfi-gauge');
    if (!c) return;
    const ctx = c.getContext('2d');
    const W = c.width, H = c.height;
    const cx = W / 2, cy = H * 0.78;
    const r  = W * 0.38;
    ctx.clearRect(0, 0, W, H);

    /* background arc */
    ctx.beginPath();
    ctx.arc(cx, cy, r, Math.PI, 0, false);
    ctx.strokeStyle = 'rgba(255,255,255,.07)';
    ctx.lineWidth   = 10;
    ctx.stroke();

    /* coloured fill */
    const norm  = Math.max(0, Math.min(100, value ?? 50)) / 100;
    const start = Math.PI;
    const end   = Math.PI + norm * Math.PI;
    const grad  = ctx.createLinearGradient(cx - r, 0, cx + r, 0);
    grad.addColorStop(0,   'rgba(0,210,100,.9)');
    grad.addColorStop(0.5, 'rgba(240,185,11,.9)');
    grad.addColorStop(1,   'rgba(255,77,106,.9)');
    ctx.beginPath();
    ctx.arc(cx, cy, r, start, end, false);
    ctx.strokeStyle = grad;
    ctx.lineWidth   = 10;
    ctx.stroke();

    /* value text */
    ctx.fillStyle   = value !== null ? (value <= 20 ? '#00d264' : value >= 80 ? '#ff4d6a' : '#fff') : 'rgba(255,255,255,.4)';
    ctx.font        = `bold ${W * 0.20}px Inter,sans-serif`;
    ctx.textAlign   = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(value !== null ? value.toFixed(1) : '—', cx, cy - r * 0.18);

    /* zone labels */
    ctx.fillStyle   = 'rgba(0,210,100,.7)';
    ctx.font        = `${W * 0.09}px Inter,sans-serif`;
    ctx.fillText('OS', cx - r * 0.95, cy + 4);
    ctx.fillStyle   = 'rgba(255,77,106,.7)';
    ctx.fillText('OB', cx + r * 0.88, cy + 4);
  }

  /* ── MFI history bars ─────────────────────────────────── */

  function drawMfiHistory(history) {
    const c = $('flow-mfi-chart');
    if (!c) return;
    const ctx = c.getContext('2d');
    const W = c.width, H = c.height;
    ctx.clearRect(0, 0, W, H);
    if (!history?.length) return;
    const bw = W / history.length;
    history.forEach((v, i) => {
      if (v === null) return;
      const bh  = (v / 100) * H;
      const col = v <= 20 ? 'rgba(0,210,100,.85)'
                : v >= 80 ? 'rgba(255,77,106,.85)'
                : 'rgba(80,180,255,.6)';
      ctx.fillStyle = col;
      ctx.fillRect(i * bw + 1, H - bh, bw - 2, bh);
    });
    [20, 80].forEach(level => {
      ctx.strokeStyle = level === 20 ? 'rgba(0,210,100,.3)' : 'rgba(255,77,106,.3)';
      ctx.lineWidth   = 1;
      ctx.beginPath();
      ctx.moveTo(0, H - (level / 100) * H);
      ctx.lineTo(W, H - (level / 100) * H);
      ctx.stroke();
    });
  }

  /* ── OI sparkline ─────────────────────────────────────── */

  function drawOiChart(history) {
    const c = $('flow-oi-chart');
    if (!c || !history?.length) return;
    const ctx = c.getContext('2d');
    const W = c.width, H = c.height;
    ctx.clearRect(0, 0, W, H);
    const vals = history.map(h => h.oi_usd).filter(v => v > 0);
    if (vals.length < 2) return;
    const min = Math.min(...vals), max = Math.max(...vals);
    const range = max - min || 1;
    const stepX = W / (vals.length - 1);
    const grad  = ctx.createLinearGradient(0, 0, 0, H);
    grad.addColorStop(0, 'rgba(80,180,255,.25)');
    grad.addColorStop(1, 'rgba(80,180,255,0)');

    ctx.beginPath();
    vals.forEach((v, i) => {
      const x = i * stepX;
      const y = H - ((v - min) / range) * (H - 4) - 2;
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    });
    ctx.strokeStyle = 'rgba(80,180,255,.9)';
    ctx.lineWidth   = 2;
    ctx.stroke();

    /* fill area */
    ctx.lineTo(W, H); ctx.lineTo(0, H); ctx.closePath();
    ctx.fillStyle = grad;
    ctx.fill();
  }

  /* ── Taker ratio bar ──────────────────────────────────── */

  function drawTakerBar(ratio) {
    const fill = $('flow-taker-fill');
    if (!fill) return;
    const pct = ratio ? Math.min(100, Math.max(0, (ratio / (ratio + 1)) * 100)) : 50;
    fill.style.width = pct.toFixed(1) + '%';
  }

  /* ── CVD render ───────────────────────────────────────── */

  function renderCVD(cvd) {
    const biasEl = $('flow-cvd-bias');
    if (!cvd) {
      ['flow-cvd-1m','flow-cvd-5m','flow-cvd-15m','flow-cvd-1h'].forEach(id => {
        const el = $(id); if (el) el.innerHTML = `${id.split('-')[2].replace('cvd','').replace('-','')} <span style="font-weight:700;color:var(--text-dim)">—</span>`;
      });
      if (biasEl) { biasEl.textContent = '— no stream data'; biasEl.style.background = 'var(--surface3)'; biasEl.style.color = 'var(--text-dim)'; biasEl.style.borderColor = 'var(--border)'; }
      return;
    }
    [['flow-cvd-1m','1m',cvd.cvd_1m,cvd.delta_pct_1m],
     ['flow-cvd-5m','5m',cvd.cvd_5m,cvd.delta_pct_5m],
     ['flow-cvd-15m','15m',cvd.cvd_15m,cvd.delta_pct_15m],
     ['flow-cvd-1h','1h',cvd.cvd_1h,cvd.delta_pct_1h]].forEach(([id,label,delta,dp]) => {
      const el = $(id); if (!el) return;
      const col = colD(dp ?? 0);
      el.innerHTML = `${label}: <span style="font-weight:700;color:${col}">${fmtDelta(delta)} <small style="font-size:10px;opacity:.7">(${((dp ?? 0) * 100).toFixed(1)}%)</small></span>`;
    });
    const dp5 = cvd.delta_pct_5m ?? 0;
    const bias = dp5 > 0.05 ? 'BUY PRESSURE' : dp5 < -0.05 ? 'SELL PRESSURE' : 'NEUTRAL';
    if (biasEl) {
      biasEl.textContent = bias;
      biasEl.style.background   = dp5 > 0.05 ? 'rgba(0,210,100,.15)' : dp5 < -0.05 ? 'rgba(255,77,106,.15)' : 'var(--surface3)';
      biasEl.style.borderColor  = dp5 > 0.05 ? 'rgba(0,210,100,.4)'  : dp5 < -0.05 ? 'rgba(255,77,106,.4)'  : 'var(--border)';
      biasEl.style.color        = dp5 > 0.05 ? 'var(--green)'         : dp5 < -0.05 ? 'var(--red)'            : 'var(--text-dim)';
    }
  }

  /* ── MFI render ───────────────────────────────────────── */

  function renderMFI(mfi) {
    if (!mfi) { drawMfiGauge(null); return; }
    const v     = mfi.value;
    const state = mfi.state ?? 'neutral';
    const col   = state === 'oversold' ? 'var(--green)' : state === 'overbought' ? 'var(--red)' : 'var(--text-dim)';
    drawMfiGauge(v);
    setHTML('flow-mfi-state', `<span style="color:${col};font-weight:800">${state.toUpperCase()}</span>`);
    const obv = mfi.obv_dir ?? '—';
    const ad  = mfi.ad_dir  ?? '—';
    setHTML('flow-mfi-obv', `OBV: <strong style="color:${obv === 'rising' ? 'var(--green)' : 'var(--red)'}">${obv} ${obv === 'rising' ? '↑' : '↓'}</strong>`);
    setHTML('flow-mfi-ad',  `A/D: <strong style="color:${ad === 'accumulation' ? 'var(--green)' : 'var(--red)'}">${ad} ${ad === 'accumulation' ? '↑' : '↓'}</strong>`);
    drawMfiHistory(mfi.history || []);
  }

  /* ── Market data render (L/S, OI, funding, taker) ────── */

  function renderMarket(m) {
    if (!m) {
      setHTML('flow-ls-long',   'Long <strong>—</strong>');
      setHTML('flow-ls-short',  'Short <strong>—</strong>');
      setHTML('flow-oi-value',  'OI: <strong>—</strong>');
      setHTML('flow-oi-change', 'OI Δ 24h: <strong>—</strong>');
      setHTML('flow-funding-val', '—');
      setHTML('flow-taker-ratio', '—');
      return;
    }

    /* L/S */
    const lp = m.long_pct  ?? 50;
    const sp = m.short_pct ?? 50;
    const fill = $('flow-ls-fill');
    if (fill) fill.style.width = lp.toFixed(1) + '%';
    setHTML('flow-ls-long',  `Long <strong style="color:var(--green)">${lp.toFixed(1)}%</strong>`);
    setHTML('flow-ls-short', `Short <strong style="color:var(--red)">${sp.toFixed(1)}%</strong>`);

    /* Top trader L/S (if available) */
    if (m.top_long_pct != null) {
      const tlp = m.top_long_pct, tsp = m.top_short_pct ?? (100 - tlp);
      setHTML('flow-ls-top', `Top traders: <strong style="color:var(--green)">${tlp.toFixed(1)}%</strong> L / <strong style="color:var(--red)">${tsp.toFixed(1)}%</strong> S`);
    }

    /* OI */
    const oc = m.oi_change ?? 0;
    const ocCol = oc >= 0 ? 'var(--green)' : 'var(--red)';
    setHTML('flow-oi-value',  `OI: <strong>${fmtUsd(m.oi_usd)}</strong>`);
    setHTML('flow-oi-change', `OI Δ 24h: <strong style="color:${ocCol}">${oc >= 0 ? '+' : ''}${oc.toFixed(2)}%</strong>`);
    drawOiChart(m.oi_history || []);

    /* Funding rate */
    const fr  = m.funding_rate ?? 0;
    const frCol = fr > 0.01 ? 'var(--red)' : fr < -0.01 ? 'var(--green)' : 'var(--text-dim)';
    const frLabel = fr > 0.01 ? 'Longs pay' : fr < -0.01 ? 'Shorts pay' : 'Neutral';
    const nextFund = m.next_funding_time
      ? new Date(m.next_funding_time).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'})
      : '';
    const frEl = $('flow-funding-val');
    if (frEl) {
      frEl.style.color = frCol;
      frEl.textContent = `${fr >= 0 ? '+' : ''}${fr.toFixed(4)}%`;
    }
    setHTML('flow-funding-label', `<span style="color:${frCol}">${frLabel}</span>${nextFund ? ` · next ${nextFund}` : ''}`);

    /* Taker ratio */
    const tr    = m.taker_ratio ?? 1;
    const tbias = m.taker_bias  ?? 'neutral';
    const trCol = tbias === 'buy_dominant' ? 'var(--green)' : tbias === 'sell_dominant' ? 'var(--red)' : 'var(--text-dim)';
    setHTML('flow-taker-ratio', `<strong style="color:${trCol}">${tr.toFixed(3)}×</strong> <span style="font-size:10px;color:${trCol}">${tbias.replace('_', ' ').toUpperCase()}</span>`);
    drawTakerBar(tr);
  }

  /* ── main fetch ───────────────────────────────────────── */

  async function loadFlowSnapshot() {
    const token  = (typeof _token !== 'undefined' && _token)
                 || localStorage.getItem('aladdin_token');
    const maEl   = $('flow-pair-input');
    const hmEl   = $('liq-pair-input');
    const raw    = (maEl && maEl.value.trim()) || (hmEl && hmEl.value.trim()) || 'BTCUSDT';
    const symbol = raw.toUpperCase();
    if (!symbol) return;

    try {
      const headers = token ? { 'Authorization': `Bearer ${token}` } : {};
      const resp = await fetch(`/api/flow/snapshot/${symbol}`, { headers });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();

      renderCVD(data.cvd);
      renderMFI(data.mfi);
      renderMarket(data.market);

      const note = $('flow-unavail-note');
      if (note) note.style.display = 'none';

      const tsEl = $('flow-last-update');
      if (tsEl) tsEl.textContent = 'Updated ' + new Date().toLocaleTimeString();
    } catch (err) {
      console.warn('[order-flow] fetch failed:', err.message);
      const note = $('flow-unavail-note');
      if (note) {
        note.style.display = 'block';
        note.textContent   = err.message.includes('401')
          ? 'Authentication required — please log in with a Pro account.'
          : `Flow data unavailable: ${err.message}`;
      }
    }
  }

  /* ── auto-refresh every 30 s when page is visible ─────── */

  let _flowTimer = null;
  function _startFlowTimer() {
    if (_flowTimer) clearInterval(_flowTimer);
    _flowTimer = setInterval(() => {
      const page = document.getElementById('page-market-analytics');
      if (page && page.style.display !== 'none' && !page.classList.contains('hidden')) {
        loadFlowSnapshot();
      }
    }, 30_000);
  }

  /* ── public API ───────────────────────────────────────── */

  window.loadFlowSnapshot = loadFlowSnapshot;

  /* hook into heatmap load */
  const _origLoad = window.loadLiqHeatmap;
  if (typeof _origLoad === 'function') {
    window.loadLiqHeatmap = function (...args) {
      const r = _origLoad.apply(this, args);
      setTimeout(loadFlowSnapshot, 800);
      return r;
    };
  }

  document.addEventListener('DOMContentLoaded', () => {
    _startFlowTimer();
    /* fire when user switches to market-analytics tab */
    document.querySelectorAll('[data-page="market-analytics"]').forEach(el => {
      el.addEventListener('click', () => setTimeout(loadFlowSnapshot, 400));
    });
  });

})();
