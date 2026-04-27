// ═══════════════════════════════════════════════════════════════
//  COPY-TRADING (Elite only)
//  Backend: /api/copy-trading/*
// ═══════════════════════════════════════════════════════════════

var _CT_TP_MODES = {
    tp1_only: {
        label: '🛡️ Conservative',
        sub: 'Exit 100% at TP1',
        desc: 'Lock profits immediately. Zero drawback risk after entry.',
        bars: [100, 0, 0],
        color: '#26a69a'
    },
    tp1_tp2: {
        label: '⚖️ Balanced',
        sub: 'Exit 65% TP1 · 35% TP2',
        desc: 'Secure base profit, hold a partial runner for TP2.',
        bars: [65, 35, 0],
        color: '#f0b429'
    },
    pyramid: {
        label: '🏛️ Pyramid Exit',
        sub: 'Exit 50% TP1 · 30% TP2 · 20% TP3+',
        desc: 'Institutional standard. Front-loaded exit with a runner.',
        bars: [50, 30, 20],
        color: '#7c4dff'
    },
    all_tps: {
        label: '🚀 Full Runner',
        sub: 'Equal split across all TPs',
        desc: 'Maximum upside potential. Highest drawback risk.',
        bars: [33, 33, 34],
        color: '#ef5350'
    }
};

var _ctBalTimer = null;
var _ctLivePnlTimer = null;

function stopCTBalancePolling() {
    if (_ctBalTimer) { clearInterval(_ctBalTimer); _ctBalTimer = null; }
    if (_ctLivePnlTimer) { clearInterval(_ctLivePnlTimer); _ctLivePnlTimer = null; }
}

// ── Real-time unrealized PnL (WS-sourced, zero REST) ───────────────────
// Polls /api/copy-trading/live-pnl every 1 s. The endpoint recomputes
// unrealized PnL from the UDS position state + PRICE_BROADCASTER mark
// snapshot — no Binance REST call — so it's safe to hit aggressively.
async function refreshCTLivePnl() {
    // Only run while the page is visible & the balance card is mounted
    if (document.hidden) return;
    if (!document.getElementById('ct-bal-unrealized')) { stopCTBalancePolling(); return; }
    try {
        var res = await fetch('/api/copy-trading/live-pnl', { headers: authHeaders() });
        if (!res.ok) return;
        var data = await res.json();
        if (!data || data.error) return;

        // Top-card unrealized PnL $ + %
        var el3 = document.getElementById('ct-bal-unrealized');
        var el3p = document.getElementById('ct-bal-unrealized-pct');
        if (el3)  { el3.textContent  = _fmtUsd(data.unrealized_pnl); el3.style.color = _pnlColor(data.unrealized_pnl); }
        if (el3p) { el3p.textContent = _fmtPct(data.unrealized_pnl_pct || 0); el3p.style.color = _pnlColor(data.unrealized_pnl_pct || 0); }
        var el4 = document.getElementById('ct-bal-invested');
        if (el4 && data.total_invested_usd != null) el4.textContent = '$' + (+data.total_invested_usd).toFixed(2);

        // Per-row PnL / PnL% cells in the open-trades table
        _ctPatchOpenRows(data.positions || {});
    } catch(e) { /* swallow — next tick retries */ }
}

async function loadCopyTradingPage() {
    var container = document.getElementById('copytrading-content');
    if (!container) return;
    if (!(window._hasTier ? window._hasTier('pro') : _tier === 'pro')) {
        container.innerHTML = '<div class="paywall-overlay"><div class="paywall-icon">🤖</div><div class="paywall-title">Copy-Trading — Pro Feature</div><div class="paywall-desc">Automatically mirror Aladdin signals to your Binance Futures account with institutional-grade exit management.</div><button class="btn btn-gold" onclick="switchPage(\'pricing\')">Upgrade to Pro — 109 USDT/mo</button></div>';
        return;
    }
    // ── Skeleton loader: users see the page shape instantly ──
    // 12 shimmer cards approximating the stats + balance grids,
    // plus placeholder blocks for the exchange selector and config
    // panels — eliminates the blank-spinner cold-start stall.
    const _sk = (w, h, r) => `<div style="height:${h}px;width:${w};background:var(--border);border-radius:${r||6}px;animation:sk-pulse 1.5s ease-in-out infinite"></div>`;
    container.innerHTML = '<style>@keyframes sk-pulse{0%,100%{opacity:.45}50%{opacity:.12}}</style>' +
        // Exchange selector strip
        '<div style="background:var(--surface);border:1px solid var(--border);border-radius:14px;padding:20px;margin-bottom:18px">' +
          _sk('40%', 10, 4) + '<div style="display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin-top:14px">' +
          [1,2,3,4,5].map(() => _sk('100%', 68, 10)).join('') + '</div></div>' +
        // Status bar
        '<div style="background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:14px 20px;margin-bottom:16px;display:flex;gap:12px;align-items:center">' +
          _sk('12px', 12, 50) + _sk('140px', 14, 4) + '</div>' +
        // Stats row 1 — 4 cards
        '<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:10px">' +
          [1,2,3,4].map(() => '<div style="background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:14px 16px;display:flex;flex-direction:column;gap:8px">' +
            _sk('60%', 9, 4) + _sk('80%', 22, 4) + _sk('55%', 9, 4) + '</div>').join('') + '</div>' +
        // Stats row 2 — 4 cards
        '<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:16px">' +
          [1,2,3,4].map(() => '<div style="background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:14px 16px;display:flex;flex-direction:column;gap:8px">' +
            _sk('50%', 9, 4) + _sk('70%', 22, 4) + _sk('45%', 9, 4) + '</div>').join('') + '</div>' +
        // Config panel placeholder
        '<div style="background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:20px;margin-bottom:16px;display:flex;flex-direction:column;gap:12px">' +
          _sk('35%', 12, 4) + _sk('100%', 40, 8) + _sk('100%', 40, 8) + '</div>';
    try {
        var results = await Promise.all([
            fetch('/api/copy-trading/config',  { headers: authHeaders() }),
            fetch('/api/copy-trading/history?limit=50', { headers: authHeaders() }),
            fetch('/api/copy-trading/balance', { headers: authHeaders() }),
        ]);
        var cfgData  = results[0].ok ? await results[0].json() : { config: null, stats: {} };
        var histData = results[1].ok ? await results[1].json() : { trades: [], stats: {} };
        var balData  = results[2].ok ? await results[2].json() : null;
        renderCopyTrading(cfgData.config, cfgData.stats || histData.stats || {}, histData.trades || [], balData);
        // Fetch server IP for the whitelist guide (non-blocking)
        fetchServerIP();
        // Fetch UDS stream health badge (non-blocking, shows WS Live vs REST fallback)
        fetchUDSHealth();
        // Auto-refresh balance every 5 s if user has a configured account
        stopCTBalancePolling();
        if (cfgData.config) {
            // Balance (total / available) refreshes every 5 s — changes rarely.
            _ctBalTimer = setInterval(refreshCTBalance, 5000);
            // Unrealized PnL refreshes every 1 s from WS caches — zero REST cost.
            _ctLivePnlTimer = setInterval(refreshCTLivePnl, 1000);
            // Kick off an immediate live-PnL refresh so numbers aren't stale
            // for the first second after page load.
            refreshCTLivePnl();
        }
    } catch(e) {
        container.innerHTML = '<div class="no-data">Failed to load copy-trading data.</div>';
    }
}

function _pnlColor(v) { return v > 0 ? 'var(--green)' : v < 0 ? 'var(--red)' : 'var(--text-dim)'; }
// Explicit sign: '+' for positive, '-' for negative, '' for zero. The old
// implementation returned '' for any v <= 0, so _fmtUsd(-1.85) lost the
// minus and rendered as "$1.85" in red — visually ambiguous.
function _pnlSign(v) { return v > 0 ? '+' : v < 0 ? '-' : ''; }
function _fmtUsd(v) { return _pnlSign(v) + '$' + Math.abs(Number(v) || 0).toFixed(2); }
// Format a percentage with an explicit leading sign. Zero renders as
// "0.00%" (no '+'), positive as "+1.23%", negative as "-1.23%".
function _fmtPct(v) {
    var n = Number(v) || 0;
    return (n > 0 ? '+' : n < 0 ? '-' : '') + Math.abs(n).toFixed(2) + '%';
}

function renderCopyTrading(cfg, stats, trades, bal) {
    var container = document.getElementById('copytrading-content');
    if (!container) return;
    var hasConfig = !!cfg;
    var isActive = hasConfig && cfg.is_active;
    var hasKeys = hasConfig && !!cfg.api_key_masked;
    var currentMode = (hasConfig && cfg.tp_mode) ? cfg.tp_mode : 'pyramid';
    var currentSlMode = (hasConfig && cfg.sl_mode) ? cfg.sl_mode : 'signal';
    var currentSlPct  = (hasConfig && cfg.sl_pct)  ? parseFloat(cfg.sl_pct) : 3.0;

    var html = '<div class="section-header"><h2>🤖 Copy-Trading</h2></div>';

    // ── Exchange Selector ────────────────────────────────────────
    html += '<div style="background:var(--surface);border:1px solid var(--border);border-radius:14px;padding:20px;margin-bottom:18px">';
    html += '<div style="font-size:11px;font-weight:700;letter-spacing:.08em;color:var(--text-dim);margin-bottom:14px">EXCHANGE</div>';
    html += '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px">';

    // Binance — Active
    html += '<div style="border:2px solid var(--gold);border-radius:10px;padding:14px 16px;cursor:default;background:#f0b42912;position:relative">';
    html += '<div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">';
    html += '<img src="https://cryptologos.cc/logos/binance-bnb-logo.png" style="width:20px;height:20px;border-radius:50%;object-fit:cover" onerror="this.style.display=\'none\'">';
    html += '<span style="font-size:13px;font-weight:800">Binance</span></div>';
    html += '<div style="font-size:10px;color:var(--text-dim)">Futures · USDT-M</div>';
    html += '<div style="position:absolute;top:8px;right:8px;background:var(--gold);color:#000;font-size:9px;font-weight:800;padding:2px 7px;border-radius:4px;letter-spacing:.05em">ACTIVE</div>';
    html += '</div>';

    // Bybit — Beta this week
    html += '<div style="border:2px solid #f7931a55;border-radius:10px;padding:14px 16px;cursor:not-allowed;background:#f7931a08;position:relative;opacity:.9">';
    html += '<div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">';
    html += '<img src="https://cryptologos.cc/logos/bybit-logo.png" style="width:20px;height:20px;border-radius:50%;object-fit:cover" onerror="this.style.display=\'none\'">';
    html += '<span style="font-size:13px;font-weight:800">Bybit</span></div>';
    html += '<div style="font-size:10px;color:var(--text-dim)">Futures · USDT-M</div>';
    html += '<div style="position:absolute;top:8px;right:8px;background:#f7931a;color:#000;font-size:9px;font-weight:800;padding:2px 7px;border-radius:4px;letter-spacing:.05em">THIS WEEK</div>';
    html += '</div>';

    // KuCoin — Beta this week
    html += '<div style="border:2px solid #00c85355;border-radius:10px;padding:14px 16px;cursor:not-allowed;background:#00c85308;position:relative;opacity:.9">';
    html += '<div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">';
    html += '<img src="https://cryptologos.cc/logos/kucoin-kcs-logo.png" style="width:20px;height:20px;border-radius:50%;object-fit:cover" onerror="this.style.display=\'none\'">';
    html += '<span style="font-size:13px;font-weight:800">KuCoin</span></div>';
    html += '<div style="font-size:10px;color:var(--text-dim)">Futures · USDT-M</div>';
    html += '<div style="position:absolute;top:8px;right:8px;background:#00c853;color:#000;font-size:9px;font-weight:800;padding:2px 7px;border-radius:4px;letter-spacing:.05em">THIS WEEK</div>';
    html += '</div>';

    // OKX — Coming soon
    html += '<div style="border:2px solid var(--border);border-radius:10px;padding:14px 16px;cursor:not-allowed;background:var(--bg);position:relative;opacity:.55">';
    html += '<div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">';
    html += '<img src="https://cryptologos.cc/logos/okb-okb-logo.png" style="width:20px;height:20px;border-radius:50%;object-fit:cover;filter:grayscale(1)" onerror="this.style.display=\'none\'">';
    html += '<span style="font-size:13px;font-weight:800">OKX</span></div>';
    html += '<div style="font-size:10px;color:var(--text-dim)">Futures · USDT-M</div>';
    html += '<div style="position:absolute;top:8px;right:8px;background:var(--surface);border:1px solid var(--border);color:var(--text-dim);font-size:9px;font-weight:700;padding:2px 7px;border-radius:4px;letter-spacing:.05em">Q3</div>';
    html += '</div>';

    // Gate.io — Coming soon
    html += '<div style="border:2px solid var(--border);border-radius:10px;padding:14px 16px;cursor:not-allowed;background:var(--bg);position:relative;opacity:.55">';
    html += '<div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">';
    html += '<span style="font-size:18px">🔷</span>';
    html += '<span style="font-size:13px;font-weight:800">Gate.io</span></div>';
    html += '<div style="font-size:10px;color:var(--text-dim)">Futures · USDT-M</div>';
    html += '<div style="position:absolute;top:8px;right:8px;background:var(--surface);border:1px solid var(--border);color:var(--text-dim);font-size:9px;font-weight:700;padding:2px 7px;border-radius:4px;letter-spacing:.05em">Q3</div>';
    html += '</div>';

    html += '</div>';
    html += '<div style="margin-top:10px;font-size:11px;color:var(--text-dim)">🔥 <strong style="color:#f7931a">Bybit</strong> and <strong style="color:#00c853">KuCoin</strong> integrations are in final testing — launching this week. Configure your Binance account now while you wait.</div>';
    html += '</div>';

    // ── Status Bar ──────────────────────────────────────────────
    html += '<div style="display:flex;align-items:center;justify-content:space-between;background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:14px 20px;margin-bottom:16px;gap:16px;flex-wrap:wrap">';
    html += '<div style="display:flex;align-items:center;gap:12px">';
    html += '<div style="width:10px;height:10px;border-radius:50%;background:' + (isActive ? 'var(--green)' : '#555') + ';box-shadow:' + (isActive ? '0 0 8px var(--green)' : 'none') + '"></div>';
    html += '<span style="font-weight:700;font-size:15px">' + (isActive ? 'Copy-Trading Active' : 'Copy-Trading Inactive') + '</span>';
    if (hasKeys) html += '<span style="font-size:11px;color:var(--text-dim);font-family:monospace;background:var(--bg);padding:2px 8px;border-radius:4px">🔑 ' + cfg.api_key_masked + '</span>';
    // UDS health badge — populated after render by fetchUDSHealth()
    html += '<span id="ct-uds-badge" style="display:none;font-size:10px;font-weight:700;padding:2px 9px;border-radius:10px;letter-spacing:.04em;font-family:monospace"></span>';
    html += '</div>';
    html += '<div style="display:flex;gap:8px">';
    if (hasConfig) {
        html += '<button class="btn" style="padding:6px 16px;font-size:12px;background:' + (isActive ? 'var(--red)' : 'var(--green)') + ';color:#000;font-weight:700" onclick="toggleCopyTrading(' + !isActive + ')">' + (isActive ? '⏹ Disable' : '▶ Enable') + '</button>';
        if (isActive) {
            html += '<button class="btn" onclick="closeAllCTPositions()" title="Close ALL open positions at market price" style="padding:6px 14px;font-size:12px;font-weight:700;background:transparent;border:1px solid #f44336;color:#f44336">⚡ Close All Positions</button>';
        }
    }
    html += '</div></div>';

    // ── PP4 · API-key rotation nudge ─────────────────────────────
    // Soft at 90 d, stronger at 180 d. Purely informational — users
    // stay fully operational; we simply recommend generating a fresh
    // key with the same permissions (Futures only, no withdrawal).
    if (hasKeys && cfg.api_key_rotation_needed) {
        var urgent = !!cfg.api_key_rotation_urgent;
        var ageDays = cfg.api_key_age_days != null ? Math.round(cfg.api_key_age_days) : '—';
        var borderColor = urgent ? '#f87171' : '#f0b429';
        var textColor   = urgent ? '#fecaca' : '#f0b429';
        var bg          = urgent ? '#1a0a0a' : '#1a1200';
        var title = urgent
            ? 'API key is older than 180 days'
            : 'Consider rotating your Binance API key';
        var body = urgent
            ? 'For account hygiene, generate a fresh Futures-only key (no withdrawal permission) and replace the one in use. Your existing key still works — this is a recommendation, not a forced expiry.'
            : 'Your Binance API key is ' + ageDays + ' days old. Best practice is to rotate keys every 90–180 days. Generate a new Futures-only key and paste it below when convenient.';
        html += '<div style="display:flex;gap:14px;align-items:flex-start;background:' + bg + ';border:1.5px solid ' + borderColor + ';border-radius:12px;padding:16px 20px;margin-bottom:16px">';
        html += '<div style="font-size:24px;flex-shrink:0;line-height:1">🔑</div>';
        html += '<div style="flex:1">';
        html += '<div style="font-size:13px;font-weight:800;color:' + textColor + ';margin-bottom:4px">' + title + ' (' + ageDays + ' days)</div>';
        html += '<div style="font-size:12px;color:var(--text);line-height:1.55">' + body + '</div>';
        html += '</div></div>';
    }

    // ── TradFi Agreement Warning ─────────────────────────────────
    var showTradFi = cfg && cfg.has_tradefi_errors && !cfg.tradefi_signed;
    if (showTradFi) {
        html += '<div id="ct-tradefi-banner" style="display:flex;gap:14px;align-items:flex-start;background:#1a1200;border:1.5px solid #f0b429;border-radius:12px;padding:18px 20px;margin-bottom:16px">';
        html += '<div style="font-size:28px;flex-shrink:0;line-height:1">⚠️</div>';
        html += '<div style="flex:1">';
        html += '<div style="font-size:14px;font-weight:800;color:#f0b429;margin-bottom:6px">Binance TradFi-Perps Agreement Required</div>';
        html += '<div style="font-size:12px;color:#e8d5a3;margin-bottom:12px">Some signals (stock/RWA perpetuals like <strong>INTCUSDT, AAPLUSDT, HOODUSDT</strong>) failed because your Binance account hasn\'t signed the TradFi-Perps agreement. This is a one-time requirement by Binance — once signed, all future trades will execute normally.</div>';
        html += '<div style="font-size:12px;font-weight:700;color:#f0b429;margin-bottom:8px;letter-spacing:.04em">HOW TO SIGN THE AGREEMENT:</div>';
        html += '<ol style="margin:0 0 14px 0;padding-left:20px;color:#e8d5a3;font-size:12px;line-height:1.9">';
        html += '<li>Open <a href="https://www.binance.com/en/futures/INTCUSDT" target="_blank" rel="noopener" style="color:#f0b429;font-weight:600">Binance Futures → INTCUSDT</a> (or any stock perp pair)</li>';
        html += '<li>Click <strong style="color:#fff">Buy / Long</strong> — a popup will appear asking you to sign the TradFi-Perps agreement</li>';
        html += '<li>Read and <strong style="color:#fff">Accept the agreement</strong> — you don\'t need to actually place an order</li>';
        html += '<li>Once signed, return here and click <strong style="color:#f0b429">Mark as Signed</strong> below</li>';
        html += '</ol>';
        html += '<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">';
        html += '<button onclick="ctMarkTradefiSigned()" style="padding:8px 20px;border-radius:8px;font-size:12px;font-weight:700;cursor:pointer;background:#f0b429;border:none;color:#000">✅ Mark as Signed</button>';
        html += '<a href="https://www.binance.com/en/futures/INTCUSDT" target="_blank" rel="noopener" style="padding:8px 18px;border-radius:8px;font-size:12px;font-weight:700;background:transparent;border:1.5px solid #f0b429;color:#f0b429;text-decoration:none">Open Binance Futures →</a>';
        html += '<span style="font-size:11px;color:#7a6a3a">This banner will disappear once you mark it as signed.</span>';
        html += '</div>';
        html += '</div></div>';
    }

    // ── Analytics Panel ─────────────────────────────────────────
    var hasTrades = stats.total > 0;
    html += '<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:16px">';

    // Row 1: core stats
    var pnl = stats.total_pnl_usd || 0;
    var wr = stats.win_rate || 0;
    html += _ctCard('Total PnL', _fmtUsd(pnl), 'Realized closed trades', _pnlColor(pnl));
    html += _ctCard('Win Rate', wr + '%', (stats.won||0) + 'W / ' + (stats.lost||0) + 'L', wr >= 55 ? 'var(--green)' : wr >= 45 ? 'var(--gold)' : 'var(--red)');
    html += _ctCard('Profit Factor', hasTrades ? (stats.profit_factor === 999 ? '∞' : (stats.profit_factor||0).toFixed(2)) : '—', 'Gross profit ÷ gross loss', (stats.profit_factor||0) >= 1.5 ? 'var(--green)' : 'var(--text-dim)');
    html += _ctCard('ROI', hasTrades ? _fmtPct(stats.roi_pct||0) : '—', 'Return on invested margin', _pnlColor(stats.roi_pct||0));
    html += '</div>';

    html += '<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:16px">';
    html += _ctCard('Open / Total', (stats.open||0) + ' / ' + (stats.total||0), 'Active positions', 'var(--text-dim)');
    html += _ctCard('Avg Win', hasTrades ? '+$' + (stats.avg_win_usd||0).toFixed(2) : '—', 'Average winning trade', 'var(--green)');
    html += _ctCard('Avg Loss', hasTrades ? '-$' + (stats.avg_loss_usd||0).toFixed(2) : '—', 'Average losing trade', 'var(--red)');
    html += _ctCard('Best / Worst', hasTrades ? ('+$' + Math.abs(stats.best_trade_usd||0).toFixed(0) + ' / -$' + Math.abs(stats.worst_trade_usd||0).toFixed(0)) : '—', 'Single trade extremes', 'var(--text-dim)');
    html += '</div>';

    // ── Balance Row ─────────────────────────────────────────────
    var hasBalance = bal && !bal.error;
    var totalBal = hasBalance ? bal.balance_usdt : null;
    var availBal = hasBalance ? bal.available_usdt : null;
    var unrealPnl = hasBalance ? bal.unrealized_pnl : null;
    var totalInv = stats.total_invested_usd || 0;

    // When the live-balance call fails, surface the *reason* so the user
    // can act (IP not whitelisted, futures permission missing, keys wrong,
    // TradFi agreement unsigned, timeout, etc.) — instead of silent dashes.
    if (bal && bal.error && hasKeys) {
        var ec = bal.error_code || 'unknown';
        var hint = bal.error || 'Binance API call failed.';
        var detail = bal.error_detail || '';
        var emoji = ({
            invalid_key_or_ip: '🔑', bad_key_format: '🔑', bad_signature: '🔏',
            clock_skew: '⏱', tradfi_unsigned: '📝', timeout: '⏳', network: '🌐',
            no_keys: '🔌', unknown: '⚠'
        })[ec] || '⚠';
        html += '<div style="display:flex;gap:12px;align-items:flex-start;background:#1a0e0e;border:1px solid #dc262666;border-radius:12px;padding:14px 18px;margin-bottom:12px">';
        html += '<div style="font-size:22px;line-height:1;flex-shrink:0">' + emoji + '</div>';
        html += '<div style="flex:1;min-width:0">';
        html += '<div style="font-size:13px;font-weight:800;color:#fca5a5;margin-bottom:4px;letter-spacing:.02em">Live Binance balance unavailable <span style="color:#6b7280;font-weight:500;font-family:monospace;font-size:11px;margin-left:6px">[' + ec + ']</span></div>';
        html += '<div style="font-size:12px;color:#e5a5a5;line-height:1.55">' + hint + '</div>';
        if (detail && detail !== hint) {
            html += '<details style="margin-top:6px"><summary style="font-size:11px;color:#6b7280;cursor:pointer">Raw error (for support)</summary><div style="font-family:monospace;font-size:11px;color:#9a6060;margin-top:4px;word-break:break-all">' + detail + '</div></details>';
        }
        html += '<div style="margin-top:8px"><button onclick="refreshCTBalance()" style="padding:5px 12px;border-radius:6px;font-size:11px;font-weight:700;background:#dc2626;color:#fff;border:none;cursor:pointer">⟳ Retry</button></div>';
        html += '</div></div>';
    }

    html += '<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:20px" id="ct-balance-row">';
    // Futures Balance card (with refresh button)
    html += '<div style="background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:14px 16px;position:relative">';
    html += '<div style="font-size:10px;font-weight:600;color:var(--text-dim);letter-spacing:.07em;margin-bottom:6px">FUTURES BALANCE</div>';
    html += '<div style="font-size:20px;font-weight:800;color:var(--gold);line-height:1.1" id="ct-bal-total">' + (hasBalance ? '$' + totalBal.toFixed(2) : '—') + '</div>';
    html += '<div style="font-size:11px;color:var(--text-dim);margin-top:4px">Total USDT in account</div>';
    html += '<button onclick="refreshCTBalance()" title="Refresh" style="position:absolute;top:10px;right:10px;background:none;border:none;color:var(--text-dim);cursor:pointer;font-size:14px">⟳</button>';
    html += '</div>';
    // Available Balance
    html += '<div style="background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:14px 16px">';
    html += '<div style="font-size:10px;font-weight:600;color:var(--text-dim);letter-spacing:.07em;margin-bottom:6px">AVAILABLE MARGIN</div>';
    html += '<div style="font-size:20px;font-weight:800;color:' + (hasBalance && availBal > 0 ? 'var(--green)' : 'var(--text-dim)') + ';line-height:1.1" id="ct-bal-avail">' + (hasBalance ? '$' + availBal.toFixed(2) : '—') + '</div>';
    html += '<div style="font-size:11px;color:var(--text-dim);margin-top:4px">Free margin for new trades</div>';
    html += '</div>';
    // Total Invested
    html += '<div style="background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:14px 16px">';
    html += '<div style="font-size:10px;font-weight:600;color:var(--text-dim);letter-spacing:.07em;margin-bottom:6px">TOTAL INVESTED</div>';
    html += '<div style="font-size:20px;font-weight:800;color:var(--text);line-height:1.1" id="ct-bal-invested">$' + totalInv.toFixed(2) + '</div>';
    html += '<div style="font-size:11px;color:var(--text-dim);margin-top:4px">Cumulative position margin</div>';
    html += '</div>';
    // Unrealized PnL + Add Funds
    var unrealPct = hasBalance ? (bal.unrealized_pnl_pct || 0) : 0;
    var unrealPctStr = hasBalance ? _fmtPct(unrealPct) : '—';
    html += '<div style="background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:14px 16px">';
    html += '<div style="font-size:10px;font-weight:600;color:var(--text-dim);letter-spacing:.07em;margin-bottom:6px">UNREALIZED PnL</div>';
    html += '<div style="font-size:20px;font-weight:800;color:' + (hasBalance ? _pnlColor(unrealPnl) : 'var(--text-dim)') + ';line-height:1.1" id="ct-bal-unrealized">' + (hasBalance ? _fmtUsd(unrealPnl) : '—') + '</div>';
    html += '<div style="font-size:12px;font-weight:700;margin-top:2px;color:' + (hasBalance ? _pnlColor(unrealPct) : 'var(--text-dim)') + '" id="ct-bal-unrealized-pct">' + unrealPctStr + '</div>';
    html += '<div style="margin-top:6px"><a href="https://www.binance.com/en/my/wallet/account/futures" target="_blank" rel="noopener" style="font-size:11px;color:var(--gold);text-decoration:none;font-weight:600">+ Add Funds → Binance Futures</a></div>';
    html += '</div>';
    html += '</div>';

    // ── PnL Sparkline (last 20 closed trades) ──────────────────
    var closed = trades.filter(function(t) { return t.status === 'closed' && t.pnl_usd != null; }).slice(0, 20);
    if (closed.length > 1) {
        var maxAbs = Math.max.apply(null, closed.map(function(t) { return Math.abs(t.pnl_usd); })) || 1;
        html += '<div style="background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:16px 20px;margin-bottom:16px">';
        html += '<div style="font-size:12px;font-weight:600;color:var(--text-dim);margin-bottom:10px;letter-spacing:.05em">PnL PER TRADE (last ' + closed.length + ' closed)</div>';
        html += '<div style="display:flex;align-items:flex-end;gap:3px;height:48px">';
        closed.slice().reverse().forEach(function(t) {
            var h = Math.round(Math.abs(t.pnl_usd) / maxAbs * 44) + 4;
            var col = t.pnl_usd > 0 ? 'var(--green)' : 'var(--red)';
            html += '<div title="' + t.pair + ' ' + _fmtUsd(t.pnl_usd) + '" style="flex:1;height:' + h + 'px;background:' + col + ';border-radius:2px 2px 0 0;opacity:0.85;cursor:default"></div>';
        });
        html += '</div></div>';
    }

    // ── TP Strategy Selector ─────────────────────────────────────
    html += '<div style="background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:20px;margin-bottom:16px">';
    html += '<div style="font-size:13px;font-weight:700;margin-bottom:4px">🎯 Exit Strategy (Take-Profit Mode)</div>';
    html += '<div style="font-size:11px;color:var(--text-dim);margin-bottom:14px">Defines how your position quantity is split across signal take-profit targets.</div>';
    html += '<div style="display:grid;grid-template-columns:repeat(2,1fr);gap:10px" id="ct-tp-grid">';
    Object.keys(_CT_TP_MODES).forEach(function(key) {
        var m = _CT_TP_MODES[key];
        var sel = key === currentMode;
        html += '<div onclick="ctSelectTpMode(\'' + key + '\')" id="ct-tp-' + key + '" style="border:2px solid ' + (sel ? m.color : 'var(--border)') + ';border-radius:10px;padding:14px;cursor:pointer;background:' + (sel ? m.color + '18' : 'var(--bg)') + ';transition:all .15s">';
        html += '<div style="font-weight:700;font-size:13px;margin-bottom:2px">' + m.label + '</div>';
        html += '<div style="font-size:11px;color:' + m.color + ';font-weight:600;margin-bottom:6px">' + m.sub + '</div>';
        // mini bar chart showing allocation
        html += '<div style="display:flex;gap:2px;height:6px;border-radius:3px;overflow:hidden;margin-bottom:6px">';
        m.bars.forEach(function(b) {
            if (b > 0) html += '<div style="flex:' + b + ';background:' + m.color + ';opacity:' + (b === m.bars[0] ? '1' : b === m.bars[1] ? '.6' : '.35') + '"></div>';
        });
        html += '</div>';
        html += '<div style="font-size:11px;color:var(--text-dim)">' + m.desc + '</div>';
        html += '</div>';
    });
    html += '</div>';
    html += '<input type="hidden" id="ct-tp-mode" value="' + currentMode + '">';
    html += '</div>';

    // ── SL Mode Selector ────────────────────────────────────────────────
    var _SL_MODES = {
        signal: { label: '📡 Signal SL', sub: 'Use exact SL from signal', desc: 'Software monitor enforces it at market price.', color: '#26a69a' },
        pct:    { label: '📐 Custom %', sub: 'Set your own SL distance', desc: 'Computed from actual fill price × your %.', color: '#f0b429' },
        none:   { label: '🚫 No SL', sub: 'Manual management only', desc: 'No stop-loss placed. Use with caution.', color: '#ef5350' }
    };
    html += '<div style="background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:20px;margin-bottom:16px">';
    html += '<div style="font-size:13px;font-weight:700;margin-bottom:4px">🛡️ Stop-Loss Mode</div>';
    html += '<div style="font-size:11px;color:var(--text-dim);margin-bottom:14px">How your stop-loss level is determined for each copied position.</div>';
    html += '<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:10px" id="ct-sl-grid">';
    Object.keys(_SL_MODES).forEach(function(key) {
        var m = _SL_MODES[key];
        var sel = key === currentSlMode;
        html += '<div onclick="ctSelectSlMode(\'' + key + '\')" id="ct-sl-' + key + '" style="border:2px solid ' + (sel ? m.color : 'var(--border)') + ';border-radius:10px;padding:12px;cursor:pointer;background:' + (sel ? m.color + '18' : 'var(--bg)') + ';transition:all .15s">';
        html += '<div style="font-weight:700;font-size:12px;margin-bottom:2px">' + m.label + '</div>';
        html += '<div style="font-size:11px;color:' + m.color + ';font-weight:600;margin-bottom:4px">' + m.sub + '</div>';
        html += '<div style="font-size:10px;color:var(--text-dim)">' + m.desc + '</div>';
        html += '</div>';
    });
    html += '</div>';
    html += '<input type="hidden" id="ct-sl-mode" value="' + currentSlMode + '">';
    // Custom % input — shown only when pct mode selected
    html += '<div id="ct-sl-pct-row" style="margin-top:12px;display:' + (currentSlMode === 'pct' ? 'flex' : 'none') + ';align-items:center;gap:10px">';
    html += '<label style="font-size:12px;color:var(--text-dim);white-space:nowrap">SL Distance %</label>';
    html += '<input type="number" id="ct-sl-pct" min="0.1" max="50" step="0.1" value="' + currentSlPct + '" style="width:80px;background:var(--bg);border:1px solid var(--border);border-radius:6px;padding:6px 8px;color:var(--text);font-size:13px">';
    html += '<span style="font-size:11px;color:var(--text-dim)">below entry (LONG) / above entry (SHORT)</span>';
    html += '</div>';
    html += '</div>';

    // ── IP Whitelist Setup Guide ──────────────────────────────────
    html += '<div style="background:var(--surface);border:2px solid var(--green);border-radius:12px;padding:20px;margin-bottom:16px">';
    html += '<div style="display:flex;align-items:center;gap:10px;margin-bottom:14px">';
    html += '<span style="font-size:22px;flex-shrink:0">🛡️</span>';
    html += '<div><div style="font-size:14px;font-weight:800;color:var(--green)">Step 1 — Whitelist This Server\'s IP on Your Binance API Key</div>';
    html += '<div style="font-size:11px;color:var(--text-dim);margin-top:2px">Copy-trading calls Binance <strong>directly from our server</strong> using your API key. Binance requires the server\'s IP to be whitelisted — otherwise every trade will fail with <code style="background:var(--bg);padding:1px 5px;border-radius:3px;color:var(--red)">-2015 Invalid API key</code>.</div>';
    html += '</div></div>';

    // IP display row
    html += '<div style="display:flex;align-items:center;gap:10px;margin-bottom:16px;flex-wrap:wrap">';
    html += '<div style="font-size:11px;font-weight:600;color:var(--text-dim);letter-spacing:.06em;white-space:nowrap">SERVER IP TO WHITELIST:</div>';
    html += '<div style="display:flex;align-items:center;gap:8px;background:var(--bg);border:1.5px solid var(--green);border-radius:8px;padding:8px 14px;flex:1;min-width:200px">';
    html += '<code id="ct-server-ip" style="font-size:15px;font-weight:700;color:var(--green);letter-spacing:.05em;font-family:monospace">Fetching…</code>';
    html += '<span id="ct-server-ip-stale" style="display:none;font-size:10px;color:var(--gold);background:var(--bg);border:1px solid var(--gold);padding:2px 6px;border-radius:4px">⚠ stale</span>';
    html += '</div>';
    html += '<button onclick="copyServerIP()" title="Copy IP to clipboard" style="padding:8px 14px;border-radius:8px;font-size:12px;font-weight:700;cursor:pointer;background:var(--green);border:none;color:#fff;white-space:nowrap" id="ct-copy-ip-btn">📋 Copy IP</button>';
    html += '<button onclick="refreshServerIP()" title="Refresh IP (runs every 30 min automatically)" style="padding:8px 14px;border-radius:8px;font-size:12px;cursor:pointer;background:transparent;border:1.5px solid var(--green);color:var(--green);white-space:nowrap" id="ct-refresh-ip-btn">⟳ Refresh</button>';
    html += '</div>';

    // Step-by-step guide
    html += '<div style="background:var(--bg);border-radius:8px;padding:14px 16px;margin-bottom:14px">';
    html += '<div style="font-size:11px;font-weight:700;color:var(--green);letter-spacing:.07em;margin-bottom:10px">HOW TO WHITELIST ON BINANCE:</div>';
    html += '<ol style="margin:0;padding-left:20px;color:var(--text);font-size:12px;line-height:2.0">';
    html += '<li>Go to <a href="https://www.binance.com/en/my/settings/api-management" target="_blank" rel="noopener" style="color:var(--green);font-weight:600">Binance → Profile → API Management</a></li>';
    html += '<li>Click <strong>Create API</strong> → choose <strong>System-generated</strong></li>';
    html += '<li>Under <strong>API restrictions</strong> — enable <strong style="color:var(--green)">✓ Enable Futures</strong> only<br><span style="color:var(--red);font-size:11px">⚠ Do NOT enable Withdrawals or Transfers — they will be rejected by our system</span></li>';
    html += '<li>Under <strong>IP access restriction</strong> → select <strong>Restrict access to trusted IPs only</strong></li>';
    html += '<li>Enter the IP shown above and click <strong>Add</strong></li>';
    html += '<li>Confirm via email 2FA, then copy your <strong>API Key</strong> and <strong>Secret Key</strong> below</li>';
    html += '</ol>';
    html += '</div>';

    // Dynamic IP warning
    html += '<div style="display:flex;gap:10px;align-items:flex-start;background:var(--surface);border:1.5px solid var(--gold);border-radius:8px;padding:10px 14px">';
    html += '<span style="font-size:16px;flex-shrink:0">⚠️</span>';
    html += '<div style="font-size:11px;color:var(--text-dim)"><strong style="color:var(--gold)">Dynamic IP Warning:</strong> This server\'s IP address can change after restarts or ISP reassignment. ';
    html += 'If your copy-trading suddenly stops working with an API error, come back here, copy the new IP, and update your Binance API whitelist. ';
    html += 'The IP is automatically refreshed every 30 minutes.</div>';
    html += '</div>';
    html += '</div>';

    // ── API Keys + Risk Settings ────────────────────────────────
    html += '<div style="background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:20px;margin-bottom:16px">';
    html += '<div style="font-size:13px;font-weight:700;margin-bottom:4px">🔑 Binance API Keys</div>';
    html += '<div style="font-size:11px;color:var(--text-dim);margin-bottom:12px">Encrypted at rest (AES-256). <span style="color:var(--gold)">Required:</span> Futures trading permission. <span style="color:var(--red)">Forbidden:</span> Withdrawal / Transfer (rejected for security).</div>';
    html += '<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:14px">';
    html += _ctInput('ct-api-key', 'text', 'API Key', '', 'monospace');
    html += _ctInput('ct-api-secret', 'password', 'API Secret', '', 'monospace');
    html += '</div>';

    var sizePct      = hasConfig ? cfg.size_pct        : 2.0;
    var maxSizePct   = hasConfig ? cfg.max_size_pct     : 5.0;
    var maxLev       = hasConfig ? cfg.max_leverage     : 20;
    var scaleSqi     = hasConfig ? cfg.scale_with_sqi   : true;
    var sizeMode     = (hasConfig && cfg.size_mode)      ? cfg.size_mode                   : 'pct';
    var fixedSizeUsd = (hasConfig && cfg.fixed_size_usd) ? parseFloat(cfg.fixed_size_usd)  : 5.0;
    var leverageMode = (hasConfig && cfg.leverage_mode)  ? cfg.leverage_mode               : 'auto';
    var allowedTiers = (hasConfig && cfg.allowed_tiers)  ? cfg.allowed_tiers.split(',')    : ['blue_chip','large_cap','mid_cap','small_cap','high_risk'];
    var allowedSectors = (hasConfig && cfg.allowed_sectors && cfg.allowed_sectors !== 'all') ? cfg.allowed_sectors.split(',') : [];
    var hotOnly      = hasConfig ? !!cfg.hot_only : false;
    var copyExperimental = hasConfig ? !!cfg.copy_experimental : false;

    html += '<div style="font-size:12px;font-weight:600;color:var(--text-dim);margin-bottom:14px;letter-spacing:.05em">RISK PARAMETERS</div>';

    // ── Position Size Mode ──────────────────────────────────────
    html += '<div style="margin-bottom:18px">';
    html += '<div style="font-size:11px;font-weight:600;color:var(--text-dim);letter-spacing:.06em;margin-bottom:8px">POSITION SIZE</div>';
    html += '<div style="display:flex;gap:8px;margin-bottom:12px">';
    var _smA = sizeMode === 'pct', _smB = sizeMode === 'fixed_usd';
    html += '<button id="ct-sm-btn-pct" onclick="ctSwitchSizeMode(\'pct\')" style="padding:7px 18px;border-radius:7px;font-size:12px;font-weight:700;cursor:pointer;border:2px solid ' + (_smA ? 'var(--gold)' : 'var(--border)') + ';background:' + (_smA ? '#f0b4291a' : 'var(--bg)') + ';color:' + (_smA ? 'var(--gold)' : 'var(--text-dim)') + '">% of Balance</button>';
    html += '<button id="ct-sm-btn-fixed" onclick="ctSwitchSizeMode(\'fixed_usd\')" style="padding:7px 18px;border-radius:7px;font-size:12px;font-weight:700;cursor:pointer;border:2px solid ' + (_smB ? 'var(--gold)' : 'var(--border)') + ';background:' + (_smB ? '#f0b4291a' : 'var(--bg)') + ';color:' + (_smB ? 'var(--gold)' : 'var(--text-dim)') + '">Fixed USDT</button>';
    html += '</div>';
    html += '<input type="hidden" id="ct-size-mode" value="' + sizeMode + '">';
    html += '<div id="ct-size-pct-section" style="display:' + (_smA ? 'grid' : 'none') + ';grid-template-columns:1fr 1fr;gap:10px">';
    html += _ctNumInput('ct-size-pct', 'Base Size % of Balance', sizePct, 0.5, 0.5, 25, 'Per-trade allocation as % of available futures balance');
    html += _ctNumInput('ct-max-size-pct', 'Max Size % Cap', maxSizePct, 0.5, 0.5, 50, 'Hard ceiling — no single trade exceeds this % of balance');
    html += '</div>';
    html += '<div id="ct-size-fixed-section" style="display:' + (_smB ? 'block' : 'none') + '">';
    html += '<div style="font-size:11px;color:var(--text-dim);margin-bottom:6px">Quick presets (USDT per trade)</div>';
    html += '<div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:10px">';
    [0.50, 1, 2, 5, 10, 15, 20].forEach(function(v) {
        var _pa = Math.abs(fixedSizeUsd - v) < 0.01;
        html += '<button onclick="ctSetFixedSize(' + v + ')" style="padding:5px 12px;border-radius:6px;font-size:12px;font-weight:700;cursor:pointer;border:2px solid ' + (_pa ? 'var(--gold)' : 'var(--border)') + ';background:' + (_pa ? '#f0b4291a' : 'var(--bg)') + ';color:' + (_pa ? 'var(--gold)' : 'var(--text)') + '">' + (v < 1 ? '$' + v.toFixed(2) : '$' + v) + '</button>';
    });
    html += '</div>';
    html += '<div><label style="font-size:11px;color:var(--text-dim);display:block;margin-bottom:4px">Custom amount (USDT)</label>';
    html += '<input type="number" id="ct-fixed-size-usd" step="0.5" min="0.5" max="9999" value="' + fixedSizeUsd + '" oninput="ctCheckHighStake(this.value)" style="width:200px;padding:10px;background:var(--bg);border:1px solid var(--border);border-radius:8px;color:var(--text);font-size:13px"></div>';
    var _hs = fixedSizeUsd > 20;
    html += '<div id="ct-high-stake-warning" style="display:' + (_hs ? 'flex' : 'none') + ';align-items:flex-start;gap:10px;background:#b71c1c22;border:1px solid #f44336;border-radius:8px;padding:10px 14px;margin-top:10px;font-size:12px"><span style="font-size:20px;flex-shrink:0">\u26a0\ufe0f</span><div><strong style="color:#f44336">High-Stakes Warning</strong><div style="color:#ef9a9a;margin-top:3px">Positions above $20 carry significant risk. Losses can be substantial. Ensure you have calibrated risk management before proceeding.</div></div></div>';
    html += '</div></div>';

    // ── Leverage Mode ───────────────────────────────────────────
    html += '<div style="margin-bottom:18px">';
    html += '<div style="font-size:11px;font-weight:600;color:var(--text-dim);letter-spacing:.06em;margin-bottom:8px">LEVERAGE MODE</div>';
    html += '<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:10px">';
    var _lmDefs = [
        ['auto',     '\ud83e\udd16', 'Automatic', 'Signal leverage, capped at your max'],
        ['fixed',    '\ud83d\udd12', 'Fixed',     'Always use your exact set leverage'],
        ['max_pair', '\ud83d\udd1d', 'Pair Max',  'Binance maximum for each pair (e.g. 125\xd7)'],
    ];
    _lmDefs.forEach(function(_lm) {
        var _sel = _lm[0] === leverageMode;
        html += '<div onclick="ctSelectLeverageMode(\'' + _lm[0] + '\')" id="ct-lm-' + _lm[0] + '" style="border:2px solid ' + (_sel ? '#7c4dff' : 'var(--border)') + ';border-radius:8px;padding:10px;cursor:pointer;background:' + (_sel ? '#7c4dff18' : 'var(--bg)') + ';text-align:center;transition:all .15s">';
        html += '<div style="font-size:18px;margin-bottom:3px">' + _lm[1] + '</div>';
        html += '<div style="font-size:12px;font-weight:700">' + _lm[2] + '</div>';
        html += '<div style="font-size:10px;color:var(--text-dim);margin-top:2px">' + _lm[3] + '</div>';
        html += '</div>';
    });
    html += '</div>';
    html += '<input type="hidden" id="ct-leverage-mode" value="' + leverageMode + '">';
    html += '<div id="ct-lev-input-section" style="display:' + (leverageMode === 'max_pair' ? 'none' : 'block') + '">';
    var _lvLbl = leverageMode === 'fixed' ? 'Fixed Leverage (\xd7)' : 'Max Leverage Cap (\xd7)';
    html += _ctNumInput('ct-max-lev', _lvLbl, maxLev, 1, 1, 125, 'Exact leverage to use (Fixed) or maximum cap on signal leverage (Auto)');
    html += '</div></div>';

    // ── SQI Scaling ─────────────────────────────────────────────
    html += '<div style="margin-bottom:14px"><label style="display:flex;align-items:center;gap:8px;font-size:12px;color:var(--text-dim);cursor:pointer"><input type="checkbox" id="ct-scale-sqi" ' + (scaleSqi ? 'checked' : '') + ' style="width:14px;height:14px"> Scale position size with signal SQI quality score (\xb125% of base)</label></div>';

    html += '<div style="margin-bottom:14px;padding:12px 14px;border:1px solid #f0b42955;background:#f0b42910;border-radius:10px"><label style="display:flex;align-items:flex-start;gap:8px;font-size:12px;color:var(--text);cursor:pointer"><input type="checkbox" id="ct-copy-experimental" ' + (copyExperimental ? 'checked' : '') + ' style="width:14px;height:14px;margin-top:2px"><span><strong style="color:#f0b429">🧪 Copy experimental signals</strong><br><span style="color:var(--text-dim);font-size:11px">Disabled by default. Enables copy-trading for signals marked EXPERIMENTAL in Telegram/dashboard.</span></span></label></div>';

    // ── Signal Filters ───────────────────────────────────────────
    if (hasConfig) {
        var _tierDefs = [
            ['blue_chip', '🔵', 'Blue Chip', '#2196f3'],
            ['large_cap', '🟢', 'Large Cap', '#4caf50'],
            ['mid_cap',   '🟡', 'Mid Cap',   '#f0b429'],
            ['small_cap', '🟠', 'Small Cap', '#ff9800'],
            ['high_risk', '🔴', 'High Risk', '#f44336'],
        ];
        var _sectorDefs = [
            ['layer1',  '⛓️',  'Layer 1'],
            ['layer2',  '🔗',  'Layer 2'],
            ['defi',    '🏦',  'DeFi'],
            ['gaming',  '🎮',  'Gaming'],
            ['ai',      '🤖',  'AI'],
            ['tradefi', '📈',  'TradFi'],
            ['meme',    '🐸',  'Meme'],
            ['infra',   '⚙️',  'Infra'],
            ['other',   '🔷',  'Other'],
        ];

        html += '<div style="margin-bottom:18px;padding-top:14px;border-top:1px solid var(--border)">';
        html += '<div style="font-size:11px;font-weight:600;color:var(--text-dim);letter-spacing:.06em;margin-bottom:6px">SIGNAL FILTERS <span style="font-size:10px;font-weight:400;color:var(--text-dim)">(only copy signals matching these filters)</span></div>';

        // Tier toggles
        html += '<div style="font-size:11px;color:var(--text-dim);margin-bottom:6px;margin-top:10px">Market Cap Tier</div>';
        html += '<div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:12px">';
        _tierDefs.forEach(function(td) {
            var key = td[0], col = td[3], lbl = td[1] + ' ' + td[2];
            var active = allowedTiers.indexOf(key) >= 0;
            html += '<button id="ct-tier-' + key + '" onclick="ctToggleTier(\'' + key + '\')" style="padding:6px 14px;border-radius:20px;font-size:11px;font-weight:700;cursor:pointer;border:2px solid ' + (active ? col : 'var(--border)') + ';background:' + (active ? col + '22' : 'var(--bg)') + ';color:' + (active ? col : 'var(--text-dim)') + ';transition:all .15s">' + lbl + '</button>';
        });
        html += '</div>';

        // Sector toggles
        html += '<div style="font-size:11px;color:var(--text-dim);margin-bottom:6px">Sector <span style="font-size:10px">(all = no filter)</span></div>';
        html += '<div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:12px">';
        var _allSectorsActive = allowedSectors.length === 0;
        html += '<button id="ct-sec-all" onclick="ctToggleSector(\'all\')" style="padding:6px 14px;border-radius:20px;font-size:11px;font-weight:700;cursor:pointer;border:2px solid ' + (_allSectorsActive ? 'var(--gold)' : 'var(--border)') + ';background:' + (_allSectorsActive ? '#f0b4291a' : 'var(--bg)') + ';color:' + (_allSectorsActive ? 'var(--gold)' : 'var(--text-dim)') + '">All Sectors</button>';
        _sectorDefs.forEach(function(sd) {
            var key = sd[0], lbl = sd[1] + ' ' + sd[2];
            var active = !_allSectorsActive && allowedSectors.indexOf(key) >= 0;
            html += '<button id="ct-sec-' + key + '" onclick="ctToggleSector(\'' + key + '\')" style="padding:6px 14px;border-radius:20px;font-size:11px;font-weight:700;cursor:pointer;border:2px solid ' + (active ? 'var(--gold)' : 'var(--border)') + ';background:' + (active ? '#f0b4291a' : 'var(--bg)') + ';color:' + (active ? 'var(--gold)' : 'var(--text-dim)') + ';transition:all .15s">' + lbl + '</button>';
        });
        html += '</div>';

        // HOT only
        html += '<label style="display:flex;align-items:center;gap:8px;font-size:12px;color:var(--text-dim);cursor:pointer;margin-bottom:14px"><input type="checkbox" id="ct-hot-only" ' + (hotOnly ? 'checked' : '') + ' style="width:14px;height:14px"> 🔥 Only copy <strong style="color:var(--gold)">&nbsp;HOT tokens</strong>&nbsp;— coins with market-cap rank rising fast (≥15 positions in 24h)</label>';

        html += '<input type="hidden" id="ct-allowed-tiers" value="' + allowedTiers.join(',') + '">';
        html += '<input type="hidden" id="ct-allowed-sectors" value="' + (allowedSectors.length ? allowedSectors.join(',') : 'all') + '">';
        html += '</div>';
    }

    html += '<div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center">';
    if (hasConfig) {
        html += '<button class="btn btn-gold" onclick="saveCopyTradingSettings()" style="font-weight:700;padding:10px 24px">💾 Save Settings</button>';
        html += '<button class="btn" onclick="saveCopyTradingKeys()" style="background:transparent;border:1px solid var(--border);color:var(--text-dim);font-size:12px">🔑 Update API Keys</button>';
        html += '<button class="btn" style="background:transparent;border:1px solid var(--red);color:var(--red);font-size:12px" onclick="deleteCopyTradingKeys()">🗑 Delete Keys</button>';
    } else {
        html += '<button class="btn btn-gold" onclick="saveCopyTradingKeys()" style="font-weight:700;padding:10px 24px">🔑 Save Keys + Settings</button>';
    }
    html += '</div></div>';

    // ── Trade History ───────────────────────────────────────────
    html += '<div style="background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:20px">';
    html += '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px">';
    html += '<div style="font-size:13px;font-weight:700">📋 Trade History</div>';
    html += '<button onclick="ctRecalcPnl()" title="Recompute realized PnL for every closed trade (last 90 days) — pulls USD from Binance income history and derives ROI% from the leverage actually used" ' +
            'style="padding:4px 12px;font-size:11px;font-weight:700;border-radius:6px;cursor:pointer;' +
            'background:transparent;border:1px solid var(--border);color:var(--text-dim)">⟳ Recalculate PnL</button>';
    html += '</div>';
    if (!trades.length) {
        html += '<div style="text-align:center;color:var(--text-dim);font-size:13px;padding:24px 0">No copy-trades yet. Enable copy-trading and the next signal will be mirrored to your account.</div>';
    } else {
        // Stash for sort callbacks — survives re-renders of just the tbody.
        window._ctTrades = trades.slice();
        if (!window._ctSort) window._ctSort = { key: 'date', dir: 'desc' };

        // Mobile card container (populated after render by renderMobileTradeCards)
        html += '<div id="ct-history-cards"></div>';

        html += '<div id="ct-history-table-wrap" style="overflow-x:auto">';
        html += '<table class="signal-table" id="ct-history-table"><thead><tr>' +
            _ctSortableTh('date',   'Date')   +
            _ctSortableTh('pair',   'Pair')   +
            _ctSortableTh('dir',    'Dir')    +
            _ctSortableTh('size',   'Size')   +
            _ctSortableTh('lev',    'Lev')    +
            _ctSortableTh('entry',  'Entry')  +
            _ctSortableTh('pnl_usd','PnL $')  +
            _ctSortableTh('pnl_pct','PnL %')  +
            _ctSortableTh('status', 'Status') +
            '</tr></thead><tbody id="ct-history-tbody">' +
            _ctRenderTradeRows(_ctSortedTrades()) +
            '</tbody></table></div>';
    }
    html += '</div>';

    container.innerHTML = html;

    // Populate mobile trade cards (no-op on desktop; CSS hides #ct-history-cards there)
    if (trades.length && typeof renderMobileTradeCards === 'function') {
        renderMobileTradeCards(trades);
    }
}

function _ctCard(label, value, sub, col) {
    return '<div style="background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:14px 16px">' +
        '<div style="font-size:10px;font-weight:600;color:var(--text-dim);letter-spacing:.07em;margin-bottom:6px">' + label.toUpperCase() + '</div>' +
        '<div style="font-size:20px;font-weight:800;color:' + (col||'var(--text)') + ';line-height:1.1">' + value + '</div>' +
        '<div style="font-size:11px;color:var(--text-dim);margin-top:4px">' + sub + '</div>' +
        '</div>';
}

function _ctInput(id, type, label, val, family) {
    return '<div><label style="font-size:11px;color:var(--text-dim);display:block;margin-bottom:4px">' + label + '</label>' +
        '<input type="' + type + '" id="' + id + '" value="' + (val||'') + '" placeholder="Enter ' + label + '" ' +
        'style="width:100%;padding:10px;background:var(--bg);border:1px solid var(--border);border-radius:8px;color:var(--text);font-size:13px' + (family ? ';font-family:' + family : '') + '"></div>';
}

function _ctNumInput(id, label, val, step, min, max, title) {
    return '<div><label style="font-size:11px;color:var(--text-dim);display:block;margin-bottom:4px" title="' + title + '">' + label + '</label>' +
        '<input type="number" id="' + id + '" step="' + step + '" min="' + min + '" max="' + max + '" value="' + val + '" title="' + title + '" ' +
        'style="width:100%;padding:10px;background:var(--bg);border:1px solid var(--border);border-radius:8px;color:var(--text);font-size:13px"></div>';
}

// ── Trade-history sorting ────────────────────────────────────────
// Clickable header cell. Shows an arrow on the currently-sorted column.
function _ctSortableTh(key, label) {
    var s = window._ctSort || { key: 'date', dir: 'desc' };
    var active = s.key === key;
    var arrow = active ? (s.dir === 'asc' ? ' ▲' : ' ▼') : '';
    var color = active ? 'var(--gold)' : 'inherit';
    return '<th data-sort-key="' + key + '" onclick="ctSortTrades(\'' + key + '\')" ' +
        'style="cursor:pointer;user-select:none;color:' + color + '" ' +
        'title="Sort by ' + label + '">' + label + arrow + '</th>';
}

// Pull a comparable value out of a trade row for the given sort key.
function _ctSortValue(t, key) {
    switch (key) {
        case 'date':    return t.created_at || 0;
        case 'pair':    return (t.pair || '').toUpperCase();
        case 'dir':     return t.direction || '';
        case 'size':    return t.size_usd || 0;
        case 'lev':     return t.leverage || 0;
        case 'entry':   return t.entry_price || 0;
        case 'pnl_usd': return t.pnl_usd || 0;
        case 'pnl_pct': return t.pnl_pct || 0;
        case 'status':  return t.status || '';
        default:        return 0;
    }
}

function _ctSortedTrades() {
    var s = window._ctSort || { key: 'date', dir: 'desc' };
    var arr = (window._ctTrades || []).slice();
    arr.sort(function(a, b) {
        var va = _ctSortValue(a, s.key), vb = _ctSortValue(b, s.key);
        if (va < vb) return s.dir === 'asc' ? -1 : 1;
        if (va > vb) return s.dir === 'asc' ?  1 : -1;
        // stable tiebreaker: newest first
        return (b.created_at || 0) - (a.created_at || 0);
    });
    return arr;
}

// Click handler: toggle asc/desc on same column, otherwise switch key.
// Numeric columns default to descending (biggest first) on first click;
// text columns default to ascending.
function ctSortTrades(key) {
    var s = window._ctSort || { key: 'date', dir: 'desc' };
    var numericDefaults = ['date','size','lev','entry','pnl_usd','pnl_pct'];
    if (s.key === key) {
        s.dir = s.dir === 'asc' ? 'desc' : 'asc';
    } else {
        s.key = key;
        s.dir = numericDefaults.indexOf(key) !== -1 ? 'desc' : 'asc';
    }
    window._ctSort = s;
    // Re-render the header row (to update arrows) + tbody only.
    var tbl = document.getElementById('ct-history-table');
    var tbody = document.getElementById('ct-history-tbody');
    if (tbl) {
        var headRow = tbl.querySelector('thead tr');
        if (headRow) {
            headRow.innerHTML =
                _ctSortableTh('date',   'Date')   +
                _ctSortableTh('pair',   'Pair')   +
                _ctSortableTh('dir',    'Dir')    +
                _ctSortableTh('size',   'Size')   +
                _ctSortableTh('lev',    'Lev')    +
                _ctSortableTh('entry',  'Entry')  +
                _ctSortableTh('pnl_usd','PnL $')  +
                _ctSortableTh('pnl_pct','PnL %')  +
                _ctSortableTh('status', 'Status') +
                '<th style="font-size:10px;color:var(--text-dim)">Stop Loss</th>';
        }
    }
    if (tbody) tbody.innerHTML = _ctRenderTradeRows(_ctSortedTrades());
}

// Build <tr> rows for an (already-sorted) list of trades.
function _ctRenderTradeRows(trades) {
    var out = '';
    trades.forEach(function(t) {
        var pnlU = t.pnl_usd != null ? t.pnl_usd : 0;
        var pnlP = t.pnl_pct != null ? t.pnl_pct : 0;
        var isOpen = t.status === 'open';
        var pnlCol = _pnlColor(pnlU);
        var dir = t.direction || '—';
        var dirCol = dir === 'LONG' ? 'var(--green)' : dir === 'SHORT' ? 'var(--red)' : 'var(--text-dim)';
        var ts = t.created_at ? new Date(t.created_at * 1000).toLocaleDateString('en-GB', {day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'}) : '—';
        var statusBadge = _ctStatusBadge(t.status);
        var closeBtn = isOpen ? ' <button onclick="ctClosePosition(\'' + t.pair + '\')" style="margin-left:8px;padding:2px 8px;font-size:9px;font-weight:700;border-radius:4px;background:transparent;border:1px solid #f44336;color:#f44336;cursor:pointer;text-transform:uppercase">Close</button>' : '';

        var pnlUsdCell, pnlPctCell;
        if (isOpen) {
            var sign = pnlU >= 0 ? '+' : '';
            pnlUsdCell = '<span style="color:' + pnlCol + ';font-weight:700">' + _pnlSign(pnlU) + Math.abs(pnlU).toFixed(2) + ' USDT</span>' +
                '<div style="font-size:9px;color:var(--text-dim);margin-top:1px;letter-spacing:.04em">UNREALIZED</div>';
            pnlPctCell = '<span style="color:' + pnlCol + ';font-weight:600">' + _fmtPct(pnlP) + '</span>';
        } else {
            pnlUsdCell = '<span style="color:' + pnlCol + ';font-weight:700">' + _fmtUsd(pnlU) + '</span>';
            pnlPctCell = '<span style="color:' + pnlCol + '">' + _fmtPct(pnlP) + '</span>';
        }

        // Tag open-trade rows so refreshCTBalance() can patch live PnL
        // cells in-place without re-rendering (and losing sort state).
        var rowAttrs = isOpen
            ? ' data-ct-open="1" data-ct-pair="' + (t.pair||'') + '"'
            : '';
        var pnlUsdAttrs = isOpen ? ' class="ct-pnl-usd"' : '';
        var pnlPctAttrs = isOpen ? ' class="ct-pnl-pct"' : '';

        // Trailing SL: show the live stop-loss price (sl_price column from DB).
        // For open trades: green if far from price, red if close. Closed trades show static value.
        var slPx = t.sl_price ? parseFloat(t.sl_price) : 0;
        var slCell;
        if (slPx > 0) {
            var slStr = formatPrice(slPx);
            if (isOpen) {
                slCell = '<span style="font-family:monospace;font-size:10px;color:var(--red);font-weight:600" class="ct-sl-price" title="Active stop-loss">' + slStr + '</span>';
            } else {
                slCell = '<span style="font-family:monospace;font-size:10px;color:var(--text-dim)">' + slStr + '</span>';
            }
        } else {
            slCell = '<span style="color:var(--text-dim)">—</span>';
        }

        out += '<tr' + rowAttrs + '>' +
            '<td style="font-size:11px;white-space:nowrap">' + ts + '</td>' +
            '<td style="font-weight:700">' + (t.pair||'—') + '</td>' +
            '<td style="color:' + dirCol + ';font-weight:700;font-size:11px">' + dir + '</td>' +
            '<td>$' + (t.size_usd||0).toFixed(0) + '</td>' +
            '<td>' + (t.leverage||'—') + 'x</td>' +
            '<td style="font-family:monospace;font-size:11px">' + (t.entry_price ? formatPrice(t.entry_price) : '—') + '</td>' +
            '<td' + pnlUsdAttrs + '>' + pnlUsdCell + '</td>' +
            '<td' + pnlPctAttrs + '>' + pnlPctCell + '</td>' +
            '<td>' + statusBadge + closeBtn + '</td>' +
            '<td>' + slCell + '</td>' +
            '</tr>';
    });
    return out;
}

function _ctStatusBadge(s) {
    var map = { open:'#1565c0', closed:'#2e7d32', skipped:'#5d4037', error:'#b71c1c', pending:'#37474f' };
    var col = map[s] || '#333';
    return '<span style="background:' + col + ';color:#fff;font-size:10px;font-weight:700;padding:2px 7px;border-radius:4px;text-transform:uppercase">' + (s||'—') + '</span>';
}

function ctSelectTpMode(mode) {
    document.getElementById('ct-tp-mode').value = mode;
    Object.keys(_CT_TP_MODES).forEach(function(key) {
        var el = document.getElementById('ct-tp-' + key);
        if (!el) return;
        var m = _CT_TP_MODES[key];
        if (key === mode) {
            el.style.borderColor = m.color;
            el.style.background = m.color + '18';
        } else {
            el.style.borderColor = 'var(--border)';
            el.style.background = 'var(--bg)';
        }
    });
}

var _CT_SL_COLORS = { signal: '#26a69a', pct: '#f0b429', none: '#ef5350' };
function ctSelectSlMode(mode) {
    document.getElementById('ct-sl-mode').value = mode;
    ['signal','pct','none'].forEach(function(key) {
        var el = document.getElementById('ct-sl-' + key);
        if (!el) return;
        var c = _CT_SL_COLORS[key];
        if (key === mode) { el.style.borderColor = c; el.style.background = c + '18'; }
        else { el.style.borderColor = 'var(--border)'; el.style.background = 'var(--bg)'; }
    });
    var pctRow = document.getElementById('ct-sl-pct-row');
    if (pctRow) pctRow.style.display = mode === 'pct' ? 'flex' : 'none';
}

function _ctGetEl(id) { return document.getElementById(id); }
function _ctVal(id, fb) { var e = _ctGetEl(id); return e ? e.value : fb; }

async function saveCopyTradingKeys() {
    var apiKey = _ctVal('ct-api-key', '').trim();
    var apiSecret = _ctVal('ct-api-secret', '').trim();
    if (!apiKey || !apiSecret) {
        // Keys blank but config already exists — just save settings
        var hasCfg = !!document.querySelector('[onclick="deleteCopyTradingKeys()"]');
        if (hasCfg) { return saveCopyTradingSettings(); }
        alert('Enter both API Key and API Secret.');
        return;
    }
    var body = {
        api_key:          apiKey,
        api_secret:       apiSecret,
        size_pct:         parseFloat(_ctVal('ct-size-pct', 2.0))      || 2.0,
        max_size_pct:     parseFloat(_ctVal('ct-max-size-pct', 5.0))   || 5.0,
        max_leverage:     parseInt(_ctVal('ct-max-lev', 20))           || 20,
        scale_with_sqi:   (_ctGetEl('ct-scale-sqi') || {}).checked     || false,
        tp_mode:          _ctVal('ct-tp-mode', 'pyramid'),
        sl_mode:          _ctVal('ct-sl-mode', 'signal'),
        sl_pct:           parseFloat(_ctVal('ct-sl-pct', 3.0)) || 3.0,
        size_mode:        _ctVal('ct-size-mode', 'pct'),
        fixed_size_usd:   parseFloat(_ctVal('ct-fixed-size-usd', 5.0)) || 5.0,
        leverage_mode:    _ctVal('ct-leverage-mode', 'auto'),
        copy_experimental: (_ctGetEl('ct-copy-experimental') || {}).checked || false,
    };
    try {
        var res = await fetch('/api/copy-trading/keys', {
            method: 'POST',
            headers: Object.assign({}, authHeaders(), {'Content-Type':'application/json'}),
            body: JSON.stringify(body)
        });
        var data = await res.json();
        if (data.error) { alert('Error: ' + data.error); return; }
        var msg = '✅ API keys and settings saved.';
        if (data.warning) msg += '\n\n⚠️ Note: ' + data.warning;
        if (data.balance_usdt !== undefined) msg += '\n\nFutures USDT balance: $' + data.balance_usdt.toFixed(2);
        alert(msg);
        loadCopyTradingPage();
    } catch(e) { alert('Failed to save keys.'); }
}

async function toggleCopyTrading(active) {
    try {
        var res = await fetch('/api/copy-trading/toggle', {
            method: 'POST',
            headers: Object.assign({}, authHeaders(), {'Content-Type':'application/json'}),
            body: JSON.stringify({ active: active })
        });
        var data = await res.json();
        if (data.error) { alert(data.error); return; }
        if (data.warning) {
            // Show non-blocking banner instead of alert — maintenance mode warning
            var wb = document.getElementById('ct-maint-warn');
            if (!wb) {
                wb = document.createElement('div');
                wb.id = 'ct-maint-warn';
                wb.style.cssText = 'margin:10px 0;padding:10px 14px;background:rgba(255,107,133,0.12);border:1px solid #ff6b85;border-radius:8px;font-size:13px;color:#ff6b85;line-height:1.5';
                var root = document.getElementById('copytrading-content');
                if (root) root.insertBefore(wb, root.firstChild);
            }
            wb.innerHTML = '🛠️ ' + data.warning;
            wb.style.display = 'block';
        }
        loadCopyTradingPage();
    } catch(e) { alert('Failed to toggle copy-trading.'); }
}

async function saveCopyTradingSettings() {
    var body = {
        size_pct:         parseFloat(_ctVal('ct-size-pct', 2.0))      || 2.0,
        max_size_pct:     parseFloat(_ctVal('ct-max-size-pct', 5.0))   || 5.0,
        max_leverage:     parseInt(_ctVal('ct-max-lev', 20))           || 20,
        scale_with_sqi:   (_ctGetEl('ct-scale-sqi') || {}).checked     || false,
        tp_mode:          _ctVal('ct-tp-mode', 'pyramid'),
        sl_mode:          _ctVal('ct-sl-mode', 'signal'),
        sl_pct:           parseFloat(_ctVal('ct-sl-pct', 3.0)) || 3.0,
        size_mode:        _ctVal('ct-size-mode', 'pct'),
        fixed_size_usd:   parseFloat(_ctVal('ct-fixed-size-usd', 5.0)) || 5.0,
        leverage_mode:    _ctVal('ct-leverage-mode', 'auto'),
        copy_experimental: (_ctGetEl('ct-copy-experimental') || {}).checked || false,
    };
    try {
        var res = await fetch('/api/copy-trading/settings', {
            method: 'POST',
            headers: Object.assign({}, authHeaders(), {'Content-Type':'application/json'}),
            body: JSON.stringify(body)
        });
        var data = await res.json();
        if (data.error) { alert(data.error); return; }
        await saveCopyTradingFilters();
        loadCopyTradingPage();
    } catch(e) { alert('Failed to save settings.'); }
}

async function refreshCTBalance() {
    // If balance elements are gone (user navigated away), stop polling
    if (!document.getElementById('ct-bal-total')) { stopCTBalancePolling(); return; }
    var btn = document.querySelector('[onclick="refreshCTBalance()"]');
    if (btn) btn.style.opacity = '0.4';
    try {
        var res = await fetch('/api/copy-trading/balance', { headers: authHeaders() });
        var data = res.ok ? await res.json() : null;
        if (data && !data.error) {
            var el = document.getElementById('ct-bal-total');
            var el2 = document.getElementById('ct-bal-avail');
            var el3 = document.getElementById('ct-bal-unrealized');
            var el4 = document.getElementById('ct-bal-invested');
            if (el)  el.textContent  = '$' + data.balance_usdt.toFixed(2);
            if (el2) { el2.textContent = '$' + data.available_usdt.toFixed(2); el2.style.color = data.available_usdt > 0 ? 'var(--green)' : 'var(--text-dim)'; }
            if (el3) { el3.textContent = _fmtUsd(data.unrealized_pnl); el3.style.color = _pnlColor(data.unrealized_pnl); }
            var el3p = document.getElementById('ct-bal-unrealized-pct');
            if (el3p && data.unrealized_pnl_pct !== undefined) {
                var p = data.unrealized_pnl_pct || 0;
                el3p.textContent = _fmtPct(p);
                el3p.style.color = _pnlColor(p);
            }
            if (el4 && data.total_invested_usd !== undefined) el4.textContent = '$' + data.total_invested_usd.toFixed(2);

            // Live-patch every open-trade row with fresh per-position PnL
            // straight from Binance — no re-render, no lost sort state.
            _ctPatchOpenRows(data.positions || {});
        }
    } catch(e) {}
    if (btn) btn.style.opacity = '1';
}

// Update PnL $ / PnL % cells in-place for every open-trade row. The values
// come straight from Binance's futures_account() positions array, so they
// already reflect leverage (Binance computes unrealizedProfit and ROI%
// exactly the same way for open & closed positions).
function _ctPatchOpenRows(positions) {
    var rows = document.querySelectorAll('tr[data-ct-open="1"]');
    rows.forEach(function(row) {
        var pair = row.getAttribute('data-ct-pair') || '';
        var p    = positions[pair];
        var usdCell = row.querySelector('td.ct-pnl-usd');
        var pctCell = row.querySelector('td.ct-pnl-pct');
        if (!usdCell || !pctCell) return;

        if (!p) {
            // Position no longer on Binance (closed externally or not yet
            // filled). Show a neutral placeholder rather than stale data.
            usdCell.innerHTML = '<span style="color:var(--text-dim);font-weight:700">—</span>' +
                '<div style="font-size:9px;color:var(--text-dim);margin-top:1px;letter-spacing:.04em">NO POSITION</div>';
            pctCell.innerHTML = '<span style="color:var(--text-dim);font-weight:600">—</span>';
            // Keep the stashed trade in sync so sorting by PnL doesn't
            // float these to the top/bottom with stale numbers.
            var stash = (window._ctTrades || []).find(function(t){return t.pair === pair;});
            if (stash) { stash.pnl_usd = 0; stash.pnl_pct = 0; }
            return;
        }

        var pnlU = +p.pnl_usd || 0;
        var pnlP = +p.pnl_pct || 0;
        var col  = _pnlColor(pnlU);
        var sign = pnlU >= 0 ? '+' : '';

        usdCell.innerHTML = '<span style="color:' + col + ';font-weight:700">' +
            _pnlSign(pnlU) + Math.abs(pnlU).toFixed(2) + ' USDT</span>' +
            '<div style="font-size:9px;color:var(--text-dim);margin-top:1px;letter-spacing:.04em">UNREALIZED</div>';
        pctCell.innerHTML = '<span style="color:' + col + ';font-weight:600">' + _fmtPct(pnlP) + '</span>';

        // Keep the stashed trade object fresh so sort-by-PnL reflects live
        // numbers, not the snapshot from the last full page load.
        var stash = (window._ctTrades || []).find(function(t){return t.pair === pair;});
        if (stash) { stash.pnl_usd = pnlU; stash.pnl_pct = pnlP; }
    });
}

function ctSwitchSizeMode(mode) {
    _ctGetEl('ct-size-mode').value = mode;
    var pctSec = _ctGetEl('ct-size-pct-section');
    var fixSec = _ctGetEl('ct-size-fixed-section');
    if (pctSec) pctSec.style.display = mode === 'pct' ? 'grid' : 'none';
    if (fixSec) fixSec.style.display = mode === 'fixed_usd' ? 'block' : 'none';
    var pctBtn = _ctGetEl('ct-sm-btn-pct');
    var fixBtn = _ctGetEl('ct-sm-btn-fixed');
    if (pctBtn) { pctBtn.style.borderColor = mode==='pct' ? 'var(--gold)' : 'var(--border)'; pctBtn.style.color = mode==='pct' ? 'var(--gold)' : 'var(--text-dim)'; pctBtn.style.background = mode==='pct' ? '#f0b4291a' : 'var(--bg)'; }
    if (fixBtn) { fixBtn.style.borderColor = mode==='fixed_usd' ? 'var(--gold)' : 'var(--border)'; fixBtn.style.color = mode==='fixed_usd' ? 'var(--gold)' : 'var(--text-dim)'; fixBtn.style.background = mode==='fixed_usd' ? '#f0b4291a' : 'var(--bg)'; }
}

function ctSetFixedSize(v) {
    var el = _ctGetEl('ct-fixed-size-usd');
    if (el) { el.value = v; ctCheckHighStake(v); }
    document.querySelectorAll('[onclick^="ctSetFixedSize"]').forEach(function(btn) {
        var m = btn.getAttribute('onclick').match(/[\d.]+/);
        if (!m) return;
        var bv = parseFloat(m[0]);
        var active = Math.abs(bv - v) < 0.01;
        btn.style.borderColor = active ? 'var(--gold)' : 'var(--border)';
        btn.style.color       = active ? 'var(--gold)' : 'var(--text)';
        btn.style.background  = active ? '#f0b4291a'   : 'var(--bg)';
    });
}

function ctCheckHighStake(v) {
    var warn = _ctGetEl('ct-high-stake-warning');
    if (warn) warn.style.display = parseFloat(v) > 20 ? 'flex' : 'none';
}

function ctSelectLeverageMode(mode) {
    _ctGetEl('ct-leverage-mode').value = mode;
    ['auto', 'fixed', 'max_pair'].forEach(function(k) {
        var el = _ctGetEl('ct-lm-' + k);
        if (!el) return;
        el.style.borderColor = k === mode ? '#7c4dff' : 'var(--border)';
        el.style.background  = k === mode ? '#7c4dff18' : 'var(--bg)';
    });
    var levSec = _ctGetEl('ct-lev-input-section');
    if (levSec) levSec.style.display = mode === 'max_pair' ? 'none' : 'block';
}

async function closeAllCTPositions() {
    if (!confirm('⚡ CLOSE ALL POSITIONS\n\nThis will immediately close ALL open Binance Futures positions at market price and cancel all SL/TP orders.\n\nThis cannot be undone. Proceed?')) return;
    try {
        var res = await fetch('/api/copy-trading/close-all', { method: 'POST', headers: authHeaders() });
        var data = await res.json();
        if (data.error) { alert('Error: ' + data.error); return; }
        var msg = '\u2705 Closed ' + data.count + ' position(s).';
        if (data.closed && data.closed.length) msg += '\n\nPairs: ' + data.closed.join(', ');
        if (data.errors && data.errors.length)  msg += '\n\n\u26a0\ufe0f Errors:\n' + data.errors.join('\n');
        alert(msg);
        loadCopyTradingPage();
    } catch(e) { alert('Failed to close positions.'); }
}

async function ctRecalcPnl() {
    try {
        var btn = event.target;
        btn.disabled = true;
        btn.textContent = '⟳ Fetching…';
        var res = await fetch('/api/copy-trading/recalc-pnl', { method: 'POST', headers: authHeaders() });
        var data = await res.json();
        btn.disabled = false;
        btn.textContent = '⟳ Recalculate PnL';
        if (data.error) { alert('Error: ' + data.error); return; }
        alert('✅ PnL Recalculation complete.\n\nUpdated: ' + data.updated + ' trade(s)\nSkipped: ' + data.skipped + ' (no income found)' + (data.errors && data.errors.length ? '\nErrors: ' + data.errors.join(', ') : ''));
        loadCopyTradingPage();
    } catch(e) { alert('Failed to recalculate PnL.'); }
}

async function ctClosePosition(pair) {
    if (!confirm('⚡ CLOSE POSITION: ' + pair + '\n\nThis will immediately close your open position for ' + pair + ' at Binance market price and cancel its SL/TP orders.\n\nProceed?')) return;
    try {
        var res = await fetch('/api/copy-trading/close-position/' + pair, { method: 'POST', headers: authHeaders() });
        var data = await res.json();
        if (data.error) { alert('Error: ' + data.error); return; }
        var pnlUsd = typeof data.pnl_usd === 'number' ? data.pnl_usd : null;
        var pnlPct = typeof data.pnl_pct === 'number' ? data.pnl_pct : null;
        var pnlStr = (pnlUsd !== null)
            ? '\n\nRealized PnL: ' + (pnlUsd >= 0 ? '+' : '') + pnlUsd.toFixed(4) + ' USDT  (' + (pnlPct >= 0 ? '+' : '') + pnlPct.toFixed(2) + '%)'
            : '';
        alert('✅ Position ' + pair + ' closed.' + pnlStr);
        loadCopyTradingPage();
    } catch(e) { alert('Failed to close position.'); }
}

var _CT_TIER_COLORS = { blue_chip:'#2196f3', large_cap:'#4caf50', mid_cap:'#f0b429', small_cap:'#ff9800', high_risk:'#f44336' };

function ctToggleTier(key) {
    var el = document.getElementById('ct-allowed-tiers');
    if (!el) return;
    var tiers = el.value ? el.value.split(',').filter(Boolean) : [];
    var idx = tiers.indexOf(key);
    if (idx >= 0) {
        if (tiers.length === 1) { alert('At least one tier must be selected.'); return; }
        tiers.splice(idx, 1);
    } else {
        tiers.push(key);
    }
    el.value = tiers.join(',');
    var btn = document.getElementById('ct-tier-' + key);
    if (btn) {
        var active = tiers.indexOf(key) >= 0;
        var col = _CT_TIER_COLORS[key] || 'var(--gold)';
        btn.style.borderColor = active ? col : 'var(--border)';
        btn.style.background  = active ? col + '22' : 'var(--bg)';
        btn.style.color       = active ? col : 'var(--text-dim)';
    }
}

function ctToggleSector(key) {
    var el = document.getElementById('ct-allowed-sectors');
    if (!el) return;
    var allBtn = document.getElementById('ct-sec-all');
    var _setAllActive = function(a) {
        if (!allBtn) return;
        allBtn.style.borderColor = a ? 'var(--gold)' : 'var(--border)';
        allBtn.style.background  = a ? '#f0b4291a' : 'var(--bg)';
        allBtn.style.color       = a ? 'var(--gold)' : 'var(--text-dim)';
    };
    var _setSectorActive = function(k, a) {
        var sb = document.getElementById('ct-sec-' + k);
        if (!sb) return;
        sb.style.borderColor = a ? 'var(--gold)' : 'var(--border)';
        sb.style.background  = a ? '#f0b4291a' : 'var(--bg)';
        sb.style.color       = a ? 'var(--gold)' : 'var(--text-dim)';
    };
    if (key === 'all') {
        el.value = 'all';
        _setAllActive(true);
        ['layer1','layer2','defi','gaming','ai','tradefi','meme','infra','other'].forEach(function(k) { _setSectorActive(k, false); });
        return;
    }
    var sectors = (el.value === 'all' || !el.value) ? [] : el.value.split(',').filter(Boolean);
    var idx = sectors.indexOf(key);
    if (idx >= 0) {
        sectors.splice(idx, 1);
    } else {
        sectors.push(key);
    }
    if (sectors.length === 0) {
        el.value = 'all';
        _setAllActive(true);
        _setSectorActive(key, false);
    } else {
        el.value = sectors.join(',');
        _setAllActive(false);
        _setSectorActive(key, sectors.indexOf(key) >= 0);
    }
}

async function saveCopyTradingFilters() {
    var tiersEl   = document.getElementById('ct-allowed-tiers');
    var sectorsEl = document.getElementById('ct-allowed-sectors');
    var hotEl     = document.getElementById('ct-hot-only');
    if (!tiersEl) return;
    var body = {
        allowed_tiers:   tiersEl.value   || 'blue_chip,large_cap,mid_cap,small_cap,high_risk',
        allowed_sectors: sectorsEl ? sectorsEl.value : 'all',
        hot_only:        hotEl ? hotEl.checked : false,
    };
    try {
        var res = await fetch('/api/copy-trading/filters', {
            method: 'POST',
            headers: Object.assign({}, authHeaders(), {'Content-Type':'application/json'}),
            body: JSON.stringify(body)
        });
        var data = await res.json();
        if (data.error) alert('Filter save error: ' + data.error);
    } catch(e) { alert('Failed to save filters.'); }
}

async function ctMarkTradefiSigned() {
    try {
        var res = await fetch('/api/copy-trading/tradefi-signed', { method: 'POST', headers: authHeaders() });
        var data = await res.json();
        if (data.error) { alert('Error: ' + data.error); return; }
        var banner = document.getElementById('ct-tradefi-banner');
        if (banner) {
            banner.style.transition = 'opacity .4s';
            banner.style.opacity = '0';
            setTimeout(function() { banner.style.display = 'none'; }, 400);
        }
    } catch(e) { alert('Failed to mark as signed. Please try again.'); }
}

async function deleteCopyTradingKeys() {
    if (!confirm('Delete your Binance API keys and all copy-trading configuration?\n\nThis cannot be undone. Active positions on Binance will NOT be closed automatically.')) return;
    try {
        var res = await fetch('/api/copy-trading/keys', {
            method: 'DELETE', headers: authHeaders()
        });
        var data = await res.json();
        if (data.error) { alert(data.error); return; }
        loadCopyTradingPage();
    } catch(e) { alert('Failed to delete keys.'); }
}

// ── Server IP helpers ────────────────────────────────────────────────────────

async function fetchServerIP() {
    var el = document.getElementById('ct-server-ip');
    var staleEl = document.getElementById('ct-server-ip-stale');
    if (!el) return;
    try {
        var res = await fetch('/api/copy-trading/server-ip', { headers: authHeaders() });
        if (!res.ok) { el.textContent = 'Unavailable'; return; }
        var data = await res.json();
        if (data.ip) {
            el.textContent = data.ip;
            if (staleEl) staleEl.style.display = data.stale ? 'inline' : 'none';
        } else {
            el.textContent = data.error || 'Unavailable';
        }
    } catch(e) {
        if (el) el.textContent = 'Error fetching IP';
    }
}

async function refreshServerIP() {
    var btn = document.getElementById('ct-refresh-ip-btn');
    var el  = document.getElementById('ct-server-ip');
    if (!el) return;
    el.textContent = 'Refreshing…';
    if (btn) { btn.disabled = true; btn.style.opacity = '0.5'; }
    try {
        var res = await fetch('/api/copy-trading/server-ip?refresh=true', { headers: authHeaders() });
        var data = res.ok ? await res.json() : {};
        el.textContent = data.ip || data.error || 'Unavailable';
        var staleEl = document.getElementById('ct-server-ip-stale');
        if (staleEl) staleEl.style.display = data.stale ? 'inline' : 'none';
    } catch(e) {
        el.textContent = 'Error';
    }
    if (btn) { btn.disabled = false; btn.style.opacity = '1'; }
}

function copyServerIP() {
    var el = document.getElementById('ct-server-ip');
    var ip = el ? el.textContent.trim() : '';
    if (!ip || ip === 'Fetching…' || ip === 'Unavailable') {
        alert('IP not loaded yet. Please wait a moment.');
        return;
    }
    navigator.clipboard.writeText(ip).then(function() {
        var btn = document.getElementById('ct-copy-ip-btn');
        if (btn) {
            var orig = btn.textContent;
            btn.textContent = '✅ Copied!';
            btn.style.background = '#388e3c';
            setTimeout(function() { btn.textContent = orig; btn.style.background = '#2e7d32'; }, 2000);
        }
    }).catch(function() {
        prompt('Copy this IP and paste it into Binance API whitelist:', ip);
    });
}

// ── UDS Health Badge ──────────────────────────────────────────────
// Fetches /api/copy-trading/uds-status and renders a small badge in
// the status bar telling users whether the zero-cost WebSocket balance
// path is live or falling back to REST. Silent on any network failure.
async function fetchUDSHealth() {
    var badge = document.getElementById('ct-uds-badge');
    if (!badge) return;
    try {
        var res = await fetch('/api/copy-trading/uds-status', { headers: authHeaders() });
        if (!res.ok) return;
        var d = await res.json();
        var isLive = d.connected === true;
        var label  = isLive ? '🟢 WS Live' : '🟡 REST fallback';
        var bg     = isLive ? 'rgba(0,214,143,0.12)' : 'rgba(240,185,11,0.12)';
        var color  = isLive ? 'var(--green)' : 'var(--gold)';
        var border = isLive ? '1px solid rgba(0,214,143,0.35)' : '1px solid rgba(240,185,11,0.35)';
        badge.textContent = label;
        badge.style.cssText = 'display:inline-block;font-size:10px;font-weight:700;padding:2px 9px;' +
            'border-radius:10px;letter-spacing:.04em;font-family:monospace;' +
            'background:' + bg + ';color:' + color + ';border:' + border;
        if (d.staleness_sec != null) {
            badge.title = 'WebSocket User Data Stream · last update ' + Math.round(d.staleness_sec) + 's ago';
        } else {
            badge.title = 'Balance source: ' + (isLive ? 'WebSocket (zero REST cost)' : 'REST API (rate-limit budget used)');
        }
    } catch(_) {
        // Silent — network failure should not surface an error on a badge
    }
}
