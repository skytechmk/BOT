// ═══════════════════════════════════════════════════════════════
//  MACRO INDICATORS PANEL — USDT.D + per-pair REVERSE HUNT state
//  Multi-timeframe ready (default 1H — matches bot main loop).
// ═══════════════════════════════════════════════════════════════
(function () {
    let _macroTF = '1h';
    let _macroPollTimer = null;
    let _macroClockTimer = null;

    const STATE_COLORS = {
        // USDT.D
        'GREED_MAX_PAIN':  '#ef4444',  // red — alts overheated, block LONGs
        'GREED_PAIN':      '#f59e0b',  // amber
        'NEUTRAL':         '#6b7280',  // grey
        'FEAR_PAIN':       '#3b82f6',  // blue
        'FEAR_MAX_PAIN':   '#10cab8',  // teal — capitulation, block SHORTs
        // Per-pair
        'SHORT_MAX_PAIN':  '#ef4444',
        'SHORT_PAIN':      '#f59e0b',
        'LONG_PAIN':       '#3b82f6',
        'LONG_MAX_PAIN':   '#10cab8',
    };
    const STATE_LABELS = {
        // TOTAL MARKET card reads USDT.D directly:
        //   USDT.D rising  (greed side) → USDT.D itself is OVERBOUGHT
        //   USDT.D falling (fear side)  → USDT.D itself is OVERSOLD
        'GREED_MAX_PAIN': '⚡ OVERBOUGHT EXTREME', // USDT.D in extreme greed
        'GREED_PAIN':     '⚠ OVERBOUGHT',          // USDT.D rising into greed
        'NEUTRAL':        '— NEUTRAL',
        'FEAR_PAIN':      '� OVERSOLD',           // USDT.D falling into fear
        'FEAR_MAX_PAIN':  '🧊 OVERSOLD EXTREME',   // USDT.D in extreme fear
        // Per-pair
        'SHORT_MAX_PAIN': '🔻 SHORT MAX',
        'SHORT_PAIN':     '🔻 SHORT',
        'LONG_MAX_PAIN':  '🔺 LONG MAX',
        'LONG_PAIN':      '🔺 LONG',
    };

    function tsiBarPos(tsi, min = -3, max = 3) {
        if (tsi === null || tsi === undefined || isNaN(tsi)) return 50;
        const clamped = Math.max(min, Math.min(max, tsi));
        return ((clamped - min) / (max - min)) * 100;
    }

    function regimeDot(regime) {
        const map = { 'BULLISH': '#10cab8', 'BEARISH': '#ef4444', 'NEUTRAL': '#6b7280', 'UNKNOWN': '#475569' };
        return `<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${map[regime] || '#475569'};margin-right:5px"></span>${regime || 'UNKNOWN'}`;
    }

    function fmt(n, digits = 2) {
        if (n === null || n === undefined || isNaN(n)) return '—';
        return (typeof n === 'number' ? n.toFixed(digits) : String(n));
    }

    function renderUSDTD(u) {
        if (!u || u.error) {
            return `<div class="macro-card macro-usdtd error">
                <div class="macro-card-title">TOTAL MARKET</div>
                <div class="macro-err">${u && u.error ? u.error : 'unavailable'}</div>
            </div>`;
        }
        const color = STATE_COLORS[u.state] || '#6b7280';
        const label = STATE_LABELS[u.state] || u.state || '—';
        const tsiPos = tsiBarPos(u.tsi_scaled);
        const ready = u.is_ready;
        const readyBadge = ready
            ? `<span class="macro-ready ok">READY</span>`
            : `<span class="macro-ready warm">WARM-UP ${u.bars_available}/400</span>`;
        return `
        <div class="macro-card macro-usdtd" style="border-color:${color}">
            <div class="macro-card-title">
                <span>TOTAL MARKET</span>
                ${readyBadge}
            </div>
            <div class="macro-state" style="color:${color};font-size:1.25em;font-weight:800;letter-spacing:.02em;margin:8px 0 4px">${label}</div>
            <div class="macro-gauge">
                <div class="macro-gauge-wrapper">
                    <div class="macro-gauge-track">
                        <div class="macro-gauge-zone fear-max"></div>
                        <div class="macro-gauge-zone fear"></div>
                        <div class="macro-gauge-zone neutral"></div>
                        <div class="macro-gauge-zone greed"></div>
                        <div class="macro-gauge-zone greed-max"></div>
                    </div>
                    <div class="macro-gauge-arrow" style="left:${tsiPos}%;border-bottom-color:${color}"></div>
                </div>
                <div class="macro-gauge-labels">
                    <span>−3</span><span>−1.8</span><span>−1.4</span><span>0</span><span>+1.4</span><span>+2.1</span><span>+3</span>
                </div>
            </div>
            <div class="macro-metrics">
                <div><span class="mm-lbl">TSI</span><span class="mm-val" style="color:${color}">${fmt(u.tsi_scaled, 2)}</span></div>
                <div><span class="mm-lbl">PREV</span><span class="mm-val">${fmt(u.tsi_prev, 2)}</span></div>
                <div><span class="mm-lbl">LINREG</span><span class="mm-val">${fmt(u.linreg, 2)}</span></div>
                <div><span class="mm-lbl">REGIME</span><span class="mm-val">${(u.linreg || 0) > 0 ? '🐻 alts bearish' : '🐂 alts bullish'}</span></div>
            </div>
            <div class="macro-gates-note">
                Gates: LONG blocks at TSI ≥ +2.1 · SHORT blocks at TSI ≤ −1.8
            </div>
        </div>`;
    }

    // ── Fear & Greed Index ────────────────────────────────────────
    const FNG_ZONES = [
        { max: 24,  color: '#ef4444', label: 'Extreme Fear' },
        { max: 49,  color: '#f59e0b', label: 'Fear'         },
        { max: 55,  color: '#6b7280', label: 'Neutral'      },
        { max: 74,  color: '#84cc16', label: 'Greed'        },
        { max: 100, color: '#22c55e', label: 'Extreme Greed'},
    ];

    function fngColor(val) {
        return (FNG_ZONES.find(z => val <= z.max) || FNG_ZONES[FNG_ZONES.length-1]).color;
    }

    // ── TradingView Economic Calendar (official widget) ──────────────
    // High-importance events only, filtered to the top-impact economies:
    // US, Eurozone, UK, Japan, China, Germany, Canada, Switzerland.
    // Uses TradingView's script-based widget loader (no iframe whitelist issues).
    function renderEconCalendar() {
        // NOTE: re-rendering the macro block will re-inject this container.
        // Attach a 1-shot effect to insert the TV widget <script> after the DOM
        // lands. We do this via requestAnimationFrame + MutationObserver guard
        // inside loadEconCalendarWidget(), invoked from loadMacro's .then.
        return `
        <div class="macro-card" style="margin-top:10px;padding:10px 12px">
            <div class="macro-card-title" style="margin-bottom:8px;display:flex;align-items:center;justify-content:space-between">
                <span>📅 ECONOMIC CALENDAR</span>
                <a href="https://www.tradingview.com/economic-calendar/" target="_blank" rel="noopener nofollow"
                   style="font-size:10px;color:var(--text-dim);font-weight:600;text-decoration:none">tradingview ↗</a>
            </div>
            <div id="tv-econ-calendar"
                 style="position:relative;width:100%;height:520px;border-radius:8px;overflow:hidden;background:#0b1220;border:1px solid var(--border)">
                <div class="tradingview-widget-container" style="height:100%">
                    <div class="tradingview-widget-container__widget" style="height:100%"></div>
                </div>
            </div>
            <div style="font-size:9px;color:var(--aw-silver);margin-top:6px;line-height:1.4">
                High-impact events · US / Eurozone / Japan ·
                powered by
                <a href="https://www.tradingview.com/" target="_blank" rel="noopener nofollow" style="color:var(--text-dim)">TradingView</a>.
            </div>
        </div>`;
    }

    // Inject the TradingView widget script after the calendar container mounts.
    // The widget reads its config from the *immediately preceding* <script>
    // element, so we must append to the container, not write inline HTML.
    function _currentAppTheme() {
        return (document.documentElement.getAttribute('data-theme') === 'light') ? 'light' : 'dark';
    }

    function mountEconCalendarWidget() {
        const wrapper = document.getElementById('tv-econ-calendar');
        const container = wrapper && wrapper.querySelector('.tradingview-widget-container');
        if (!wrapper || !container) return;

        const theme = _currentAppTheme();
        // Match wrapper background to the target theme so there's no flash of
        // dark while the widget is loading under light mode (or vice-versa).
        wrapper.style.background = theme === 'light' ? '#ffffff' : '#0b1220';

        // Clear any previous widget mounted into this container.
        // TradingView's embed script can replace the inner div between mounts,
        // so we null-guard and lazily recreate it if missing (fixes the
        // "Cannot set properties of null (setting 'innerHTML')" crash that
        // fired on theme toggle → remount).
        let inner = container.querySelector('.tradingview-widget-container__widget');
        if (!inner) {
            inner = document.createElement('div');
            inner.className = 'tradingview-widget-container__widget';
            container.appendChild(inner);
        } else {
            inner.innerHTML = '';
        }
        const existing = container.querySelector('script[data-tv-econcal]');
        if (existing) existing.remove();

        const s = document.createElement('script');
        s.type  = 'text/javascript';
        s.src   = 'https://s3.tradingview.com/external-embedding/embed-widget-events.js';
        s.async = true;
        s.setAttribute('data-tv-econcal', '1');
        s.text  = JSON.stringify({
            colorTheme:       theme,
            isTransparent:    false,                   // let colorTheme paint the bg
            width:            '100%',
            height:           '100%',
            locale:           'en',
            importanceFilter: '0,1',                   // 0 = medium, 1 = high (drop lows)
            countryFilter:    'us,eu,jp',
        });
        container.appendChild(s);

        _ensureThemeObserver();
    }

    // Watch <html data-theme> and re-mount the widget whenever the app theme
    // flips, so the calendar always matches the surrounding UI.
    let _tvThemeObserver = null;
    let _tvThemeLast     = null;
    function _ensureThemeObserver() {
        if (_tvThemeObserver) return;
        _tvThemeLast    = _currentAppTheme();
        _tvThemeObserver = new MutationObserver(() => {
            const next = _currentAppTheme();
            if (next === _tvThemeLast) return;
            _tvThemeLast = next;
            // Debounce: theme toggles can fire multiple attribute writes.
            clearTimeout(_ensureThemeObserver._t);
            _ensureThemeObserver._t = setTimeout(() => {
                if (document.getElementById('tv-econ-calendar')) mountEconCalendarWidget();
            }, 120);
        });
        _tvThemeObserver.observe(document.documentElement, {
            attributes: true,
            attributeFilter: ['data-theme'],
        });
    }

    function renderFearGreed(fg) {
        if (!fg || fg.error) {
            return `<div class="macro-card fg-card">
                <div class="macro-card-title">FEAR &amp; GREED INDEX</div>
                <div class="macro-err">${fg && fg.error ? fg.error : 'unavailable'}</div>
            </div>`;
        }
        const val   = Math.max(0, Math.min(100, fg.value));
        const color = fngColor(val);
        const label = fg.classification || '';
        const pct   = val;
        const agoSec = fg.cached_at ? Math.round(Date.now()/1000 - fg.cached_at) : null;
        const agoStr = agoSec !== null
            ? (agoSec < 120 ? `${agoSec}s ago` : agoSec < 3600 ? `${Math.round(agoSec/60)}m ago` : `${Math.round(agoSec/3600)}h ago`)
            : '';
        const staleNote = fg.stale ? ' (cached)' : '';
        return `
        <div class="macro-card fg-card" style="margin-top:10px;border-left:3px solid ${color}">
            <div class="macro-card-title">
                <span>🌡 FEAR &amp; GREED INDEX</span>
                <span style="color:${color};font-size:12px;font-weight:800">${val}</span>
            </div>
            <div class="macro-state" style="color:${color};font-size:1.15em;font-weight:800;letter-spacing:.02em;margin:6px 0 4px">${label.toUpperCase()}</div>
            <div class="macro-gauge">
                <div class="fg-gauge-wrapper" style="position:relative;padding-bottom:18px">
                    <div style="height:18px;border-radius:9px;overflow:hidden;background:linear-gradient(to right,
                        #ef4444 0%,#ef4444 24%,
                        #f59e0b 24%,#f59e0b 49%,
                        #6b7280 49%,#6b7280 55%,
                        #84cc16 55%,#84cc16 75%,
                        #22c55e 75%,#22c55e 100%);box-shadow:inset 0 1px 4px rgba(0,0,0,.4)"></div>
                    <div style="position:absolute;bottom:0;left:${pct}%;transform:translateX(-50%);
                        width:0;height:0;border-left:9px solid transparent;border-right:9px solid transparent;
                        border-bottom:14px solid ${color};
                        filter:drop-shadow(0 2px 4px rgba(0,0,0,.55))"></div>
                </div>
                <div style="display:flex;justify-content:space-between;font-size:10px;color:var(--aw-silver);margin-top:4px">
                    <span>0</span><span>Extreme Fear</span><span>Fear</span><span>Greed</span><span>100</span>
                </div>
            </div>
            <div style="font-size:9px;color:var(--aw-silver);margin-top:6px">${fg.source || 'coinmarketcap'}${agoStr ? ` · updated ${agoStr}` : ''}${staleNote}</div>
        </div>`;
    }

    async function loadFearGreed() {
        const el = document.getElementById('macro-fg-slot');
        if (!el) return;
        try {
            const r = await fetch('/api/macro/fear-greed');
            const fg = r.ok ? await r.json() : { error: `HTTP ${r.status}` };
            el.innerHTML = renderFearGreed(fg);
        } catch (e) {
            el.innerHTML = renderFearGreed({ error: e.message });
        }
    }

    function renderPairsTable(pairs) {
        if (!pairs || !pairs.length) return '<div class="macro-err">No pair data</div>';
        const rows = pairs.map(p => {
            if (p.error) {
                return `<tr><td>${p.pair}</td><td colspan="5" class="macro-err">${p.error}</td></tr>`;
            }
            const color = STATE_COLORS[p.state] || '#6b7280';
            const label = STATE_LABELS[p.state] || p.state || '—';
            const readyBadge = p.is_ready ? '' : `<span class="warm-dot" title="warmup ${p.bars_available}/400"></span>`;
            return `<tr>
                <td><strong>${p.pair}</strong> ${readyBadge}</td>
                <td style="color:${color}">${fmt(p.tsi_scaled, 2)}</td>
                <td>${fmt(p.linreg, 2)}</td>
                <td style="color:${color};font-weight:600">${label}</td>
                <td>${regimeDot(p.lr_regime)}</td>
                <td><div class="tsi-bar">
                    <div class="tsi-bar-fill" style="width:${tsiBarPos(p.tsi_scaled)}%;background:${color}"></div>
                </div></td>
            </tr>`;
        }).join('');
        return `<table class="macro-pairs-table">
            <thead><tr>
                <th>Pair</th><th>TSI</th><th>LinReg</th><th>State</th><th>Regime</th><th>TSI ±2.2</th>
            </tr></thead>
            <tbody>${rows}</tbody>
        </table>
        <div class="macro-gates-note">
            Per-pair gate: LONG blocks at TSI ≥ +2.2 · SHORT blocks at TSI ≤ −2.2
        </div>`;
    }

    // ── TSI Zone Alert Grid ───────────────────────────────────────────────
    const ZONE_META = {
        OB_L2: { label: '🔴 OB Extreme (SHORT setup)',  color: '#ef4444', ce: 'SHORT' },
        OB_L1: { label: '🟠 OB Watch (SHORT watch)',    color: '#f59e0b', ce: 'SHORT' },
        OS_L2: { label: '🟢 OS Extreme (LONG setup)',   color: '#10b981', ce: 'LONG'  },
        OS_L1: { label: '🔵 OS Watch (LONG watch)',     color: '#3b82f6', ce: 'LONG'  },
    };

    function renderZoneAlerts(monitoredPairs) {
        if (!monitoredPairs || !monitoredPairs.length) {
            return '<div style="color:var(--text-dim);font-size:12px;padding:8px 0">No pairs in extreme zones</div>';
        }
        const grouped = {};
        ['OB_L2','OS_L2','OB_L1','OS_L1'].forEach(z => { grouped[z] = []; });
        monitoredPairs.forEach(p => { if (grouped[p.zone]) grouped[p.zone].push(p); });

        return ['OB_L2','OS_L2','OB_L1','OS_L1'].map(zone => {
            const list = grouped[zone];
            if (!list.length) return '';
            const { label, color, ce: expectedCE } = ZONE_META[zone];
            const chips = list.map(p => {
                const ceMatch  = p.ce_line === expectedCE;
                const sym = p.pair.replace('USDT','');
                return `<span style="
                    display:inline-flex;align-items:center;gap:4px;
                    padding:3px 9px;border-radius:6px;font-size:11px;font-weight:700;
                    background:${ceMatch ? color + '22' : 'rgba(255,255,255,0.04)'};
                    border:1px solid ${ceMatch ? color + '66' : 'rgba(255,255,255,0.08)'};
                    color:${ceMatch ? color : 'var(--text-dim)'};
                    cursor:pointer" onclick="selectPairChart('${p.pair}')" title="TSI:${p.tsi} CE:${p.ce_line||'?'}">
                    ${sym}
                    <span style="font-size:9px;opacity:.7">${p.tsi > 0 ? '+' : ''}${p.tsi}</span>
                    ${ceMatch ? '<span style="font-size:9px">✔</span>' : ''}
                </span>`;
            }).join('');
            return `<div style="margin-bottom:8px">
                <div style="font-size:10px;font-weight:700;letter-spacing:.06em;color:${color};margin-bottom:4px">
                    ${label} <span style="opacity:.6;font-weight:400">(${list.length})</span>
                </div>
                <div style="display:flex;flex-wrap:wrap;gap:4px">${chips}</div>
            </div>`;
        }).join('');
    }

    async function loadMacro() {
        const mc = document.getElementById('macro-content');
        if (!mc) return;
        try {
            const pairs = window._macroPairList || 'BTCUSDT,ETHUSDT,SOLUSDT,DOGEUSDT,XRPUSDT,BNBUSDT,AVAXUSDT,LINKUSDT';
            const _ah = typeof authHeaders === 'function' ? authHeaders() : {};
            const [macroResp, monResp] = await Promise.all([
                fetch(`/api/macro/state?pairs=${pairs}&timeframe=${_macroTF}`, { headers: _ah }),
                fetch('/api/monitored', { headers: _ah }),
            ]);
            if (!macroResp.ok) { mc.innerHTML = `<div class="macro-err">API error ${macroResp.status}</div>`; return; }
            const data    = await macroResp.json();
            const monData = monResp.ok ? await monResp.json() : {};
            const monPairs = (monData.pairs || []).filter(p => p.zone);
            mc.innerHTML = `
                <div class="macro-grid">
                    <div class="macro-left">
                        ${renderUSDTD(data.usdt_d)}
                        <div id="macro-fg-slot"><div class="macro-card fg-card" style="margin-top:10px"><div class="macro-card-title">🌡 FEAR &amp; GREED INDEX</div><div class="macro-err" style="font-size:10px">Loading…</div></div></div>
                        ${renderEconCalendar()}
                    </div>
                    <div class="macro-right">
                        <div class="macro-card" style="padding:12px 14px;margin-bottom:10px">
                            <div class="macro-card-title" style="margin-bottom:10px">⚡ TSI Zone Alerts — All Pairs</div>
                            ${renderZoneAlerts(monPairs)}
                        </div>
                        <div class="macro-card-title" style="margin-bottom:8px">Per-Pair REV HUNT (${data.timeframe || _macroTF})</div>
                        ${renderPairsTable(data.pairs)}
                    </div>
                </div>`;
            loadFearGreed();
            mountEconCalendarWidget();
            const upd = document.getElementById('macro-updated');
            if (upd) {
                upd.dataset.fetchedAt = (data.updated_at || Date.now() / 1000) * 1000;
            }
        } catch (e) {
            mc.innerHTML = `<div class="macro-err">Failed to load: ${e.message || e}</div>`;
        }
    }

    window.setMacroTF = function (tf) {
        if (!['15m', '30m', '1h', '2h', '4h'].includes(tf)) return;
        _macroTF = tf;
        document.querySelectorAll('.macro-tf-btn').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.tf === tf);
        });
        const badge = document.getElementById('macro-tf-badge');
        if (badge) badge.textContent = tf.toUpperCase();
        loadMacro();
    };

    function _startClock() {
        if (_macroClockTimer) clearInterval(_macroClockTimer);
        _macroClockTimer = setInterval(() => {
            const upd = document.getElementById('macro-updated');
            if (!upd) return;
            const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
            const now = new Date();
            const timeStr = now.toLocaleTimeString(undefined, {
                hour: '2-digit', minute: '2-digit', second: '2-digit',
                timeZone: tz
            });
            const tzShort = now.toLocaleTimeString(undefined, {
                timeZoneName: 'short', hour: '2-digit', minute: '2-digit',
                timeZone: tz
            }).split(' ').slice(-1)[0];
            const fetchedAt = parseFloat(upd.dataset.fetchedAt || 0);
            const agoSec = fetchedAt ? Math.round((Date.now() - fetchedAt) / 1000) : null;
            const agoStr = fetchedAt
                ? (agoSec < 60 ? `${agoSec}s ago` : `${Math.round(agoSec / 60)}m ago`)
                : '';
            upd.innerHTML = `<span class="macro-clock">${timeStr} <span class="macro-tz">${tzShort}</span></span>${agoStr ? ` <span class="macro-fetch-age">&bull; data ${agoStr}</span>` : ''}`;
        }, 1000);
    }

    window.initMacroPanel = function () {
        loadMacro();
        _startClock();
        // Refresh data every 60s while overview page is open
        if (_macroPollTimer) clearInterval(_macroPollTimer);
        _macroPollTimer = setInterval(() => {
            // Only refresh if overview is the current page
            const ov = document.getElementById('page-overview');
            if (ov && ov.classList.contains('active')) {
                loadMacro();
            }
        }, 60000);
    };

    // Auto-start on DOM ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => window.initMacroPanel && window.initMacroPanel());
    } else {
        window.initMacroPanel && window.initMacroPanel();
    }
})();
