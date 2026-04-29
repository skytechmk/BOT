// ═══════════════════════════════════════════════════════════════
//  SCREENER (Pro/Elite)
// ═══════════════════════════════════════════════════════════════
let _screenerData = [];
let _screenerFilter = 'all';

async function loadScreener(force = false) {
    const el = document.getElementById('screener-container');
    if (!el) return;
    // Sk1 · Skeleton shimmer grid — maintains final layout so the user
    // sees structure instantly instead of a solitary spinner. 12 cards
    // matching the final screener-grid dimensions; staggered animation
    // delays make the shimmer feel organic rather than mechanical.
    const skeletonCards = Array(12).fill(
        '<div class="screener-card" style="border:1px solid var(--border);background:var(--surface);padding:16px;border-radius:10px">' +
        '<div style="height:18px;width:40%;background:var(--border);border-radius:4px;margin-bottom:14px;animation:sk-pulse 1.5s ease-in-out infinite"></div>' +
        '<div style="height:12px;width:100%;background:var(--border);border-radius:4px;margin-bottom:10px;animation:sk-pulse 1.5s ease-in-out infinite .1s"></div>' +
        '<div style="height:12px;width:80%;background:var(--border);border-radius:4px;margin-bottom:10px;animation:sk-pulse 1.5s ease-in-out infinite .2s"></div>' +
        '<div style="height:12px;width:60%;background:var(--border);border-radius:4px;animation:sk-pulse 1.5s ease-in-out infinite .3s"></div>' +
        '</div>'
    ).join('');
    el.innerHTML = '<style>@keyframes sk-pulse{0%,100%{opacity:.45}50%{opacity:.12}}</style>' +
                   '<div class="screener-grid" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:14px">' + skeletonCards + '</div>';
    try {
        const res = await fetch('/api/screener', { headers: authHeaders() });
        if (!res.ok) { el.innerHTML = `<p style="color:var(--red)">Error: ${res.status}</p>`; return; }
        const data = await res.json();
        if (data.error) { el.innerHTML = `<p style="color:var(--red)">${data.error}</p>`; return; }
        _screenerData = data.pairs || [];
        const ts = data.fetched_at ? new Date(data.fetched_at * 1000).toLocaleTimeString() : '—';
        document.getElementById('screener-cache-info').textContent = `${data.total} pairs · fetched ${ts}`;
        renderScreener();
    } catch(e) {
        el.innerHTML = `<p style="color:var(--red)">Failed to load screener: ${e.message}</p>`;
    }
}

function screenerFilter(f, btn) {
    _screenerFilter = f;
    document.querySelectorAll('.screener-filters .filter-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    renderScreener();
}

function renderScreener() {
    const el = document.getElementById('screener-container');
    if (!el) return;
    const pairs = _screenerFilter === 'all'
        ? _screenerData
        : _screenerData.filter(p => p.bias === _screenerFilter);

    if (!pairs.length) {
        el.innerHTML = '<p style="color:var(--text-dim);text-align:center;padding:40px 0">No pairs match the selected filter.</p>';
        return;
    }

    const cards = pairs.map(p => {
        const biasClass = p.bias === 'LONG' ? 'long' : p.bias === 'SHORT' ? 'short' : 'neutral';
        const biasLabel = p.bias === 'LONG' ? '▲ LONG' : p.bias === 'SHORT' ? '▼ SHORT' : '— NEUTRAL';
        const rsiPct = Math.round(p.rsi);
        const rsiColor = p.rsi <= 38 ? 'var(--green)' : p.rsi >= 62 ? 'var(--red)' : '#888';
        const rsiWidth = `${p.rsi}%`;
        const changeColor = p.change >= 0 ? 'var(--green)' : 'var(--red)';
        const changeStr = (p.change >= 0 ? '+' : '') + p.change.toFixed(2) + '%';
        const macdIcon = p.macd_cross === 'bullish' ? '↑' : '↓';
        const macdColor = p.macd_cross === 'bullish' ? 'var(--green)' : 'var(--red)';
        const volColor = p.rel_vol >= 2 ? 'var(--gold)' : p.rel_vol >= 1.5 ? '#aaa' : 'var(--text-dim)';
        const sym = p.symbol.replace('USDT', '');
        return `
        <div class="screener-card bias-${biasClass}" onclick="selectPairChart('${p.symbol}')" style="cursor:pointer">
            <div class="sc-header">
                <span class="sc-pair">${sym}<span style="font-size:11px;color:var(--text-dim);font-weight:400">/USDT</span></span>
                <div style="display:flex;flex-direction:column;align-items:flex-end;gap:3px">
                    <span class="sc-score">#${_screenerData.indexOf(p)+1} · ${p.score}</span>
                    <span class="sc-bias ${biasClass}">${biasLabel}</span>
                </div>
            </div>
            <div class="sc-row">
                <span class="sc-label">RSI (14)</span>
                <span class="sc-val" style="color:${rsiColor}">${p.rsi}</span>
            </div>
            <div class="sc-rsi-bar"><div class="sc-rsi-fill" style="width:${rsiWidth};background:${rsiColor}"></div></div>
            <div class="sc-row" style="margin-top:8px">
                <span class="sc-label">Rel. Volume</span>
                <span class="sc-val" style="color:${volColor}">${p.rel_vol}×</span>
            </div>
            <div class="sc-row">
                <span class="sc-label">MACD</span>
                <span class="sc-val" style="color:${macdColor}">${macdIcon} ${p.macd_cross}</span>
            </div>
            <div class="sc-row">
                <span class="sc-label">24h Change</span>
                <span class="sc-val" style="color:${changeColor}">${changeStr}</span>
            </div>
        </div>`;
    }).join('');

    el.innerHTML = `<div class="screener-grid">${cards}</div>`;
}

//  PRE-SIGNALS (Elite)
// ═══════════════════════════════════════════════════════════════
async function loadPreSignals() {
    if (!(window._hasTier ? window._hasTier('pro') : _tier === 'pro')) {
        document.getElementById('presignals-container').innerHTML = `
            <div class="paywall-overlay">
                <div class="paywall-icon">🎯</div>
                <div class="paywall-title">Pre-Signal Alerts — Pro Feature</div>
                <div class="paywall-desc">Get early alerts on pairs about to trigger a signal. Hooked TSI in extreme zones = imminent reversal.</div>
                <button class="btn btn-gold" onclick="switchPage('pricing')">Upgrade to Pro — 109 USDT/mo</button>
            </div>`;
        return;
    }
    try {
        const res = await fetch('/api/presignals', { headers: authHeaders() });
        const data = await res.json();
        renderPreSignals(data.presignals || []);
    } catch(e) {
        document.getElementById('presignals-container').innerHTML = '<div class="no-data">Failed to load pre-signals</div>';
    }
}

// ── Helper: compute SL/TP from presignal CE data ──────────────────
function _calcQuickEntryTargets(p) {
    const entry     = p.price;
    const isLong    = p.expected_signal === 'LONG';
    let ceDistRaw   = p.ce_distance_pct != null ? p.ce_distance_pct : (p.ce_dist || 3);
    let ceDist      = Math.abs(ceDistRaw);
    if (ceDist < 0.25) ceDist = 0.5; // Enforce minimum 0.5% risk to prevent SL=Entry errors
    const riskAmt   = entry * (ceDist / 100);
    // SL = CE level (natural stop)
    const sl        = isLong ? entry - riskAmt : entry + riskAmt;
    // TP targets at 1.5R, 2.5R, 4R
    const tp1 = isLong ? entry + riskAmt * 1.5 : entry - riskAmt * 1.5;
    const tp2 = isLong ? entry + riskAmt * 2.5 : entry - riskAmt * 2.5;
    const tp3 = isLong ? entry + riskAmt * 4.0 : entry - riskAmt * 4.0;
    return { sl, tp1, tp2, tp3, riskPct: ceDist };
}

// ── Quick Entry Modal ─────────────────────────────────────────────
function openQuickEntryModal(p) {
    const existing = document.getElementById('qe-modal-overlay');
    if (existing) existing.remove();

    const isLong  = p.expected_signal === 'LONG';
    const dirColor = isLong ? 'var(--green)' : 'var(--red)';
    const dirIcon  = isLong ? '🚀' : '📉';
    const t        = _calcQuickEntryTargets(p);
    const fmt      = (n) => typeof formatPrice === 'function' ? formatPrice(n) : n.toPrecision(6);
    const sym      = p.pair.replace('USDT', '');

    const overlay = document.createElement('div');
    overlay.id = 'qe-modal-overlay';
    overlay.style.cssText = `
        position:fixed;inset:0;background:rgba(0,0,0,.75);z-index:9999;
        display:flex;align-items:center;justify-content:center;padding:16px`;
    overlay.innerHTML = `
    <div id="qe-modal" style="
        background:var(--card,#1a1d23);border:1px solid var(--border,#2a2d35);
        border-radius:14px;width:100%;max-width:420px;padding:24px;
        box-shadow:0 24px 64px rgba(0,0,0,.6);position:relative">

      <!-- Header -->
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:18px">
        <div>
          <div style="font-size:11px;font-weight:700;letter-spacing:.1em;color:var(--text-dim)">⚡ QUICK ENTRY</div>
          <div style="font-size:22px;font-weight:800;margin-top:2px">
            ${sym}<span style="color:var(--text-dim);font-weight:400;font-size:14px">/USDT</span>
          </div>
        </div>
        <div style="text-align:right">
          <div style="font-size:20px;font-weight:800;color:${dirColor}">${dirIcon} ${p.expected_signal}</div>
          <div style="font-size:11px;color:var(--text-dim);margin-top:2px">${p.readiness} · ${p.zone}</div>
        </div>
      </div>

      <!-- Price grid -->
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:16px">
        <div style="background:var(--surface,#12151a);border-radius:8px;padding:10px 12px">
          <div style="font-size:10px;color:var(--text-dim);margin-bottom:3px">ENTRY (MARK)</div>
          <div style="font-size:14px;font-weight:700">${fmt(p.price)}</div>
        </div>
        <div style="background:rgba(239,68,68,.1);border:1px solid rgba(239,68,68,.25);border-radius:8px;padding:10px 12px">
          <div style="font-size:10px;color:#f87171;margin-bottom:3px">STOP LOSS</div>
          <div style="font-size:14px;font-weight:700;color:#f87171">${fmt(t.sl)}</div>
          <div style="font-size:10px;color:var(--text-dim)">${t.riskPct.toFixed(2)}% risk</div>
        </div>
      </div>

      <!-- TP targets -->
      <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin-bottom:18px">
        ${[['TP1','1.5R',t.tp1],['TP2','2.5R',t.tp2],['TP3','4.0R',t.tp3]].map(([lbl,rr,price])=>`
        <div style="background:rgba(16,185,129,.08);border:1px solid rgba(16,185,129,.2);border-radius:8px;padding:8px 10px;text-align:center">
          <div style="font-size:10px;color:#6ee7b7;font-weight:700">${lbl} <span style="opacity:.6">${rr}</span></div>
          <div style="font-size:12px;font-weight:700;color:#6ee7b7;margin-top:3px">${fmt(price)}</div>
        </div>`).join('')}
      </div>

      <!-- Leverage override -->
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:18px">
        <label style="font-size:12px;color:var(--text-dim);white-space:nowrap">Leverage override</label>
        <input id="qe-leverage" type="number" min="1" max="125" value="0" placeholder="0 = use config"
          style="flex:1;background:var(--surface,#12151a);border:1px solid var(--border);border-radius:6px;
                 padding:6px 10px;color:var(--text);font-size:13px;outline:none">
        <span style="font-size:11px;color:var(--text-dim)">0 = config default</span>
      </div>

      <!-- Warning -->
      <div style="background:rgba(251,191,36,.08);border:1px solid rgba(251,191,36,.2);border-radius:8px;
                  padding:10px 12px;font-size:11px;color:#fcd34d;margin-bottom:18px;line-height:1.5">
        ⚠️ This will immediately execute a <strong>${p.expected_signal}</strong> market order on your connected exchange account
        using your copy-trading size settings.
      </div>

      <!-- Buttons -->
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px">
        <button onclick="document.getElementById('qe-modal-overlay').remove()"
          style="padding:12px;border-radius:8px;background:var(--surface);border:1px solid var(--border);
                 color:var(--text-dim);font-size:13px;font-weight:600;cursor:pointer">
          Cancel
        </button>
        <button id="qe-confirm-btn"
          onclick="executeQuickEntry('${p.pair}','${p.expected_signal}',${t.sl},[${t.tp1},${t.tp2},${t.tp3}])"
          style="padding:12px;border-radius:8px;background:${dirColor};border:none;
                 color:#000;font-size:13px;font-weight:800;cursor:pointer;
                 display:flex;align-items:center;justify-content:center;gap:6px">
          ${dirIcon} Execute Entry
        </button>
      </div>
    </div>`;

    // Close on backdrop click
    overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.remove(); });
    document.body.appendChild(overlay);
}

async function executeQuickEntry(pair, direction, slPrice, tpPrices) {
    const btn = document.getElementById('qe-confirm-btn');
    if (!btn) return;
    const leverage = parseInt(document.getElementById('qe-leverage')?.value || '0', 10);

    btn.disabled = true;
    btn.innerHTML = '<span style="opacity:.6">Executing…</span>';

    try {
        const res = await fetch('/api/presignals/quick-entry', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...authHeaders() },
            body: JSON.stringify({ pair, direction, sl_price: slPrice, tp_prices: tpPrices, leverage }),
        });
        const data = await res.json();

        const overlay = document.getElementById('qe-modal-overlay');
        if (overlay) overlay.remove();

        if (data.error) {
            _qeShowToast(`❌ Quick Entry failed: ${data.error}`, 'error');
        } else {
            _qeShowToast(
                `✅ ${direction} ${pair.replace('USDT','')} entered @ ${typeof formatPrice === 'function' ? formatPrice(data.entry_price_used) : data.entry_price_used}`,
                'success'
            );
        }
    } catch (e) {
        const overlay = document.getElementById('qe-modal-overlay');
        if (overlay) overlay.remove();
        _qeShowToast(`❌ Network error: ${e.message}`, 'error');
    }
}

// Upgrade prompt shown when a non-ultra tier clicks the locked Quick Entry button.
function _qeShowUpgradePrompt() {
    const existing = document.getElementById('qe-upgrade-overlay');
    if (existing) existing.remove();
    const overlay = document.createElement('div');
    overlay.id = 'qe-upgrade-overlay';
    overlay.style.cssText = `
        position:fixed;inset:0;background:rgba(5,8,14,.82);z-index:9999;
        display:flex;align-items:center;justify-content:center;padding:20px;
        backdrop-filter:blur(6px)`;
    overlay.onclick = (e) => { if (e.target === overlay) overlay.remove(); };
    overlay.innerHTML = `
      <div style="background:var(--card);border:1px solid var(--border);border-radius:14px;
                  padding:28px 32px;max-width:420px;width:100%;text-align:center;
                  box-shadow:0 24px 60px rgba(0,0,0,.5)">
        <div style="font-size:36px;margin-bottom:10px">⚡</div>
        <div style="font-size:18px;font-weight:800;margin-bottom:6px">Quick Entry — Ultra Exclusive</div>
        <div style="font-size:13px;color:var(--text-dim);line-height:1.55;margin-bottom:20px">
          One-click order execution from pre-signal alerts. Upgrade to <b>Ultra</b>
          to unlock instant trade entry with your configured copy-trading API keys.
        </div>
        <div style="display:flex;gap:10px;justify-content:center">
          <button onclick="document.getElementById('qe-upgrade-overlay').remove()"
            style="padding:10px 18px;border-radius:8px;border:1px solid var(--border);
                   background:transparent;color:var(--text);font-size:13px;cursor:pointer">
            Close
          </button>
          <button onclick="document.getElementById('qe-upgrade-overlay').remove();switchPage('pricing');"
            style="padding:10px 18px;border-radius:8px;border:none;
                   background:var(--gold);color:#000;font-size:13px;font-weight:800;cursor:pointer">
            View Pricing →
          </button>
        </div>
      </div>`;
    document.body.appendChild(overlay);
}

function _qeShowToast(msg, type) {
    const t = document.createElement('div');
    t.style.cssText = `
        position:fixed;bottom:24px;left:50%;transform:translateX(-50%);z-index:10000;
        padding:12px 20px;border-radius:10px;font-size:13px;font-weight:600;
        background:${type === 'success' ? 'rgba(16,185,129,.95)' : 'rgba(239,68,68,.95)'};
        color:#fff;box-shadow:0 8px 24px rgba(0,0,0,.4);
        animation:fadeInUp .25s ease`;
    t.textContent = msg;
    document.body.appendChild(t);
    setTimeout(() => t.remove(), 5000);
}

function renderPreSignals(items) {
    if (!items.length) {
        document.getElementById('presignals-container').innerHTML = '<div class="no-data">No pre-signals right now. Pairs will appear here when they show hooked momentum in extreme zones.</div>';
        return;
    }
    const readinessColors = {IMMINENT:'#ff4444',HIGH:'var(--gold)',MEDIUM:'#66ccff',LOW:'var(--text-dim)'};
    // Quick Entry is an ULTRA-tier feature (admins always pass).
    // For non-ultra tiers we still render the button but in a locked state:
    // clicking shows an upgrade prompt instead of opening the modal.
    const canQuickEntry = (_user && _user.is_admin) || (_tier === 'ultra');

    document.getElementById('presignals-container').innerHTML = `<div class="presignal-grid">${items.map(p => {
        const rc  = readinessColors[p.readiness] || 'var(--text-dim)';
        const chg = p.change_24h != null ? `<span style="color:${p.change_24h >= 0 ? 'var(--green)' : 'var(--red)'}">${p.change_24h >= 0 ? '+' : ''}${p.change_24h}%</span>` : '';
        const isLong = p.expected_signal === 'LONG';

        const qeBtn = canQuickEntry ? `
            <button onclick="event.stopPropagation();openQuickEntryModal(${JSON.stringify(p).replace(/"/g,'&quot;')})"
              style="display:flex;align-items:center;gap:5px;padding:7px 12px;border-radius:7px;cursor:pointer;
                     font-size:11px;font-weight:800;letter-spacing:.04em;border:none;
                     background:${isLong ? 'rgba(16,185,129,.15)' : 'rgba(239,68,68,.15)'};
                     color:${isLong ? 'var(--green)' : 'var(--red)'};
                     border:1px solid ${isLong ? 'rgba(16,185,129,.3)' : 'rgba(239,68,68,.3)'};
                     transition:all .15s">
              ⚡ Quick Entry
            </button>`
          : `
            <button onclick="event.stopPropagation();_qeShowUpgradePrompt()"
              title="Quick Entry is an Ultra-tier feature — upgrade to unlock"
              style="display:flex;align-items:center;gap:5px;padding:7px 12px;border-radius:7px;cursor:pointer;
                     font-size:11px;font-weight:800;letter-spacing:.04em;
                     background:rgba(255,255,255,.04);
                     color:var(--text-dim);
                     border:1px solid rgba(255,255,255,.1);
                     opacity:.7;transition:all .15s">
              🔒 Quick Entry
            </button>`;

        const _exBadge = p.exchanges === 'both'
            ? '<span style="font-size:9px;font-weight:800;color:#7dd3fc;background:#7dd3fc18;border:1px solid #7dd3fc44;border-radius:8px;padding:1px 6px;margin-left:6px">🔵🟡 Both</span>'
            : p.exchanges === 'mexc'
            ? '<span style="font-size:9px;font-weight:800;color:#f0b429;background:#f0b42918;border:1px solid #f0b42944;border-radius:8px;padding:1px 6px;margin-left:6px">🟡 MEXC</span>'
            : '';

        return `<div class="presignal-card" style="border-color:${rc}40">
            <div class="readiness" style="color:${rc};border-color:${rc}">${p.readiness}</div>
            <div class="pair-name" style="font-size:16px;font-weight:700;margin-bottom:4px">${p.pair.replace('USDT','')}<span style="color:var(--text-dim);font-weight:400">/USDT</span>${_exBadge} ${chg}</div>
            <div class="expected ${p.expected_signal.toLowerCase()}">Expected: ${isLong ? '🚀' : '📉'} ${p.expected_signal}</div>
            <div class="pair-meta" style="margin-top:10px">
                <div class="meta-item"><span>Zone</span><span class="meta-val">${p.zone}</span></div>
                <div class="meta-item"><span>TSI</span><span class="meta-val">${typeof p.tsi === 'number' ? p.tsi.toFixed(2) : p.tsi}</span></div>
                <div class="meta-item"><span>CE Line</span><span class="meta-val ${(p.ce_line||'').toLowerCase()}">${p.ce_line || '—'}</span></div>
                <div class="meta-item"><span>CE Cloud</span><span class="meta-val ${(p.ce_cloud||'').toLowerCase()}">${p.ce_cloud || '—'}</span></div>
                <div class="meta-item"><span>CE Dist</span><span class="meta-val">${p.ce_dist != null ? p.ce_dist.toFixed(1) + '%' : '—'}</span></div>
                <div class="meta-item"><span>LinReg</span><span class="meta-val">${p.linreg != null ? p.linreg.toFixed(2) : '—'}</span></div>
            </div>
            <div style="margin-top:10px;font-size:12px;color:var(--text-dim)">Price: <span style="color:var(--text);font-weight:600">${formatPrice(p.price)}</span></div>
            <div style="margin-top:10px;display:flex;align-items:center;justify-content:space-between">
                <a href="#" onclick="event.preventDefault();selectPairChart('${p.pair}')" style="font-size:11px;color:var(--gold)">📊 Chart</a>
                ${qeBtn}
            </div>
        </div>`;
    }).join('')}</div>`;
}
