// ═════════════════════════════════════════════════════════════════
//  CHARTS (Pro+) — LightweightCharts v5.1.0  ·  Multi-slot
//  Monitor up to 3 pairs simultaneously, each with its own timeframe.
//  Data: server REST (local DB + Binance fallback) + live Binance WS.
// ═════════════════════════════════════════════════════════════════
//
//  ARCHITECTURE
//  ────────────
//  Every chart lives in a self-contained "slot" with its own DOM
//  subtree, chart handles, series, WebSocket and refresh state. All
//  state is keyed by `slotId` (0 / 1 / 2). No global cross-talk.
//
//    _slots = Map<slotId, {
//        pair, interval, container,
//        priceChart, indChart,
//        candleSeries, volSeries, ceLineSeries, ceCloudSeries,
//        tsiSeries, linregSeries,
//        entryLine, slLine, tpLines, ceMarkers, markerPlugin,
//        liveWs, liveWsReconnect, liveLastBar, liveRefreshPending,
//        precFmt, syncingRange, zoneRedrawFns
//    }>
//
//  Backwards compatibility: slot 0 continues to populate the app-r7.js
//  globals (priceChart, indChart, _candleSeries, …) so any external
//  code referencing them keeps working unchanged.
// ═════════════════════════════════════════════════════════════════

const _TF_BARS         = { '5m': 300, '15m': 200, '1h': 500, '4h': 300, '1d': 200 };
const _MAX_CHART_SLOTS = 3;
const _CHART_QUICK_PAIRS = ['BTCUSDT','ETHUSDT','SOLUSDT','BNBUSDT','XRPUSDT','DOGEUSDT','ADAUSDT','AVAXUSDT'];
const _CHART_SLOTS_LS_KEY = 'aladdin_chart_slots_v1';

const _slots = new Map();                   // slotId → state
let _currentInterval = '1h';                // default TF for new slots

// ═════════════════════════════════════════════════════════════════
//  SLOT LIFECYCLE
// ═════════════════════════════════════════════════════════════════

function _newSlotState(slotId) {
    return {
        id: slotId,
        pair: null,
        interval: _currentInterval,
        priceChart: null,
        indChart: null,
        candleSeries: null,
        volSeries: null,
        ceLineSeries: null,
        ceCloudSeries: null,
        tsiSeries: null,
        linregSeries: null,
        entryLine: null,
        slLine: null,
        tpLines: [],
        ceMarkers: [],
        markerPlugin: null,
        zoneRedrawFns: [],
        liveWs: null,
        liveWsReconnect: null,
        liveLastBar: null,
        liveRefreshPending: false,
        precFmt: { precision: 4, minMove: 0.0001 },
        syncingRange: false,
        loadToken: 0,   // increments per _loadChartSlot call; stale fetches are dropped
    };
}

// Mirror slot 0 state into app-r7.js globals so legacy code keeps working.
function _syncPrimaryGlobals() {
    const s = _slots.get(0);
    if (!s) return;
    priceChart     = s.priceChart;
    indChart       = s.indChart;
    _candleSeries  = s.candleSeries;
    _volSeries     = s.volSeries;
    _ceLineSeries  = s.ceLineSeries;
    _ceCloudSeries = s.ceCloudSeries;
    _tsiSeries     = s.tsiSeries;
    _linregSeries  = s.linregSeries;
    _entryLine     = s.entryLine;
    _slLine        = s.slLine;
    _tpLines       = s.tpLines;
    _ceMarkers     = s.ceMarkers;
}

// ─── Persistence (localStorage) ─────────────────────────────────────
function _persistSlots() {
    try {
        const snap = [];
        for (const s of _slots.values()) {
            if (s.pair) snap.push({ id: s.id, pair: s.pair, interval: s.interval });
        }
        localStorage.setItem(_CHART_SLOTS_LS_KEY, JSON.stringify(snap));
    } catch(e) {}
}

function _loadPersistedSlots() {
    try {
        const raw = localStorage.getItem(_CHART_SLOTS_LS_KEY);
        if (!raw) return [];
        const arr = JSON.parse(raw);
        if (!Array.isArray(arr)) return [];
        return arr.filter(x => x && typeof x.pair === 'string').slice(0, _MAX_CHART_SLOTS);
    } catch(e) { return []; }
}

// ═════════════════════════════════════════════════════════════════
//  PAGE SHELL
// ═════════════════════════════════════════════════════════════════

function renderChartsPage() {
    // The shell is about to be wiped & rebuilt. Tear down any live slots
    // so we don't leak WS connections and so _slots can be re-mounted
    // into the freshly-created #chart-slots-container.
    for (const id of Array.from(_slots.keys())) {
        _disconnectLiveWsSlot(id);
        const s = _slots.get(id);
        if (s) {
            if (s.priceChart) { try { s.priceChart.remove(); } catch(e) {} }
            if (s.indChart)   { try { s.indChart.remove();   } catch(e) {} }
        }
        _slots.delete(id);
    }

    if (_tier === 'free') {
        document.getElementById('charts-content').innerHTML = `
            <div class="paywall-overlay">
                <div class="paywall-icon">📊</div>
                <div class="paywall-title">Interactive Charts — Pro Feature</div>
                <div class="paywall-desc">Access real-time charts with TSI, Chandelier Exit, and LinReg overlays.</div>
                <button class="btn btn-gold" onclick="switchPage('pricing')">Upgrade to Plus — 53 USDT/mo</button>
            </div>`;
        return;
    }

    document.getElementById('charts-content').innerHTML = `
        <!-- ═══ Pair picker + slot controls ═══ -->
        <div class="liq-card" style="margin-bottom:12px;padding:10px 14px;display:flex;align-items:center;gap:14px;flex-wrap:wrap">
            <div style="display:flex;align-items:center;gap:8px;flex-shrink:0">
                <span style="font-size:10px;font-weight:700;letter-spacing:.08em;color:var(--text-dim);text-transform:uppercase">Pair</span>
                <datalist id="chart-pairs-list"></datalist>
                <input id="chart-pair-input" type="text" placeholder="BTCUSDT" maxlength="24"
                    list="chart-pairs-list"
                    style="background:var(--surface3);border:1px solid var(--border);border-radius:8px;padding:7px 12px;color:var(--text);font-size:13px;font-weight:700;width:200px;text-transform:uppercase;outline:none"
                    oninput="this.value=this.value.toUpperCase()"
                    onkeydown="if(event.key==='Enter')loadChartFromInput()">
                <button class="btn btn-gold" onclick="loadChartFromInput()"
                    style="padding:7px 16px;font-size:12px;font-weight:700;border-radius:8px">Load</button>
                <button id="chart-add-slot-btn" onclick="addChartSlotFromInput()"
                    style="padding:7px 14px;font-size:12px;font-weight:700;border-radius:8px;background:transparent;color:var(--text);border:1px solid var(--border);cursor:pointer"
                    title="Add this pair as a second/third simultaneous chart">+ Add</button>
            </div>
            <div style="width:1px;height:22px;background:var(--border);flex-shrink:0"></div>
            <div id="chart-quick-pairs" style="display:flex;gap:5px;align-items:center;overflow-x:auto;-webkit-overflow-scrolling:touch;scrollbar-width:none;flex:1;min-width:0;flex-wrap:nowrap"></div>
            <div id="chart-slot-count" style="font-size:11px;color:var(--text-dim);font-weight:700;flex-shrink:0"></div>
        </div>

        <div id="chart-empty-state" style="padding:30px;text-align:center;color:var(--text-dim);font-size:13px">
            🔍 Type a pair (e.g. <strong style="color:var(--gold)">BTCUSDT</strong>) and press <strong>Load</strong>, or pick one from Quick. Use <strong>+ Add</strong> to compare up to <strong>${_MAX_CHART_SLOTS} pairs</strong> side-by-side with live CE, TSI &amp; Reverse Hunt indicators.
        </div>

        <div id="chart-slots-container" style="display:flex;flex-direction:column;gap:14px"></div>`;

    _initChartPairPicker();
}

// ═════════════════════════════════════════════════════════════════
//  PICKER + QUICK PAIRS
// ═════════════════════════════════════════════════════════════════

async function _initChartPairPicker() {
    // Quick-pick buttons
    const quick = document.getElementById('chart-quick-pairs');
    if (quick) {
        quick.innerHTML =
            '<span style="font-size:10px;font-weight:700;letter-spacing:.08em;color:var(--text-dim);text-transform:uppercase;flex-shrink:0;margin-right:2px">Quick</span>' +
            _CHART_QUICK_PAIRS.map(p =>
                `<button class="liq-win-btn" onclick="selectPairChart('${p}')"
                    style="flex-shrink:0;padding:4px 10px;font-size:11px;font-weight:700">${p.replace('USDT','')}</button>`
            ).join('');
    }

    // Populate autocomplete from /api/liq/pairs
    try {
        const r = await fetch('/api/liq/pairs', { headers: authHeaders() });
        if (r.ok) {
            const d = await r.json();
            const pairs = d.pairs || [];
            const dl = document.getElementById('chart-pairs-list');
            if (dl && pairs.length) {
                dl.innerHTML = pairs.map(p =>
                    `<option value="${p}">${p.replace('USDT','')}</option>`
                ).join('');
            }
        }
    } catch(e) {}

    // Decide what to load:
    //  1. If `_currentPair` is set (user clicked Chart on a signal, picked a
    //     pair on Overview, or pressed Load) → that's slot 0, always.
    //  2. Any OTHER persisted slots fill slots 1/2.
    //  3. Otherwise restore every persisted slot as-is.
    const persisted = _loadPersistedSlots();
    if (_currentPair) {
        await _ensureSlot(0, _currentPair, _currentInterval);
        const input = document.getElementById('chart-pair-input');
        if (input) input.value = _currentPair;
        for (const p of persisted) {
            if (!p.id || p.pair === _currentPair) continue;
            if (p.id >= _MAX_CHART_SLOTS) continue;
            await _ensureSlot(p.id, p.pair, p.interval || '1h');
        }
    } else if (persisted.length) {
        for (const p of persisted) await _ensureSlot(p.id, p.pair, p.interval || '1h');
        const first = persisted[0];
        _currentPair     = first.pair;
        _currentInterval = first.interval || '1h';
        const input = document.getElementById('chart-pair-input');
        if (input) input.value = first.pair;
    }

    _updateSlotCount();
}

// ─── Picker helpers ─────────────────────────────────────────────────

function loadChartFromInput() {
    const pair = _readPairInput();
    if (!pair) return;
    selectPairChart(pair);   // replaces slot 0 (primary)
}

function addChartSlotFromInput() {
    const pair = _readPairInput();
    if (!pair) return;
    // Find first unused slot id, append it; if all 3 used, replace the last.
    let targetId = -1;
    for (let i = 0; i < _MAX_CHART_SLOTS; i++) {
        if (!_slots.has(i)) { targetId = i; break; }
    }
    if (targetId === -1) {
        // All slots full — replace the most recently added one (highest id).
        targetId = _MAX_CHART_SLOTS - 1;
        _destroySlot(targetId);
    }
    _ensureSlot(targetId, pair, _currentInterval);
}

function _readPairInput() {
    const input = document.getElementById('chart-pair-input');
    if (!input) return null;
    let v = (input.value || '').trim().toUpperCase();
    if (!v) return null;
    if (!v.endsWith('USDT') && !v.endsWith('USD') && !v.endsWith('BUSD')) {
        v += 'USDT';
        input.value = v;
    }
    return v;
}

// ═════════════════════════════════════════════════════════════════
//  PUBLIC ENTRY POINTS (also called from Overview and elsewhere)
// ═════════════════════════════════════════════════════════════════

async function selectPairChart(pair) {
    if (_tier === 'free') { switchPage('pricing'); return; }
    _currentPair = pair;
    const input = document.getElementById('chart-pair-input');
    if (input) input.value = pair;
    const empty = document.getElementById('chart-empty-state');
    if (empty) empty.style.display = 'none';

    if (_currentPage !== 'charts') {
        switchPage('charts');                                  // triggers renderChartsPage → _ensureSlot(0)
        return;
    }
    await _ensureSlot(0, pair, _currentInterval);              // already on tab → load slot 0
}

// Switch TF for a specific slot (invoked from TF buttons in slot header)
async function switchChartIntervalSlot(slotId, tf) {
    const s = _slots.get(slotId);
    if (!s || !s.pair) return;
    s.interval = tf;
    if (slotId === 0) _currentInterval = tf;
    _updateTFButtons(slotId, tf);
    await _loadChartSlot(slotId, s.pair, tf);
    _persistSlots();
}

// Backwards-compat shim — old code may still call switchChartInterval(tf)
// targeting the primary slot.
async function switchChartInterval(tf) {
    return switchChartIntervalSlot(0, tf);
}

// Close a slot
function closeChartSlot(slotId) {
    _destroySlot(slotId);
    _persistSlots();
    _updateSlotCount();
    if (_slots.size === 0) {
        const empty = document.getElementById('chart-empty-state');
        if (empty) empty.style.display = '';
    }
}

// ═════════════════════════════════════════════════════════════════
//  SLOT ENSURE / CREATE / DESTROY
// ═════════════════════════════════════════════════════════════════

async function _ensureSlot(slotId, pair, interval) {
    const container = document.getElementById('chart-slots-container');
    if (!container) return;

    let s = _slots.get(slotId);
    if (!s) {
        s = _newSlotState(slotId);
        _slots.set(slotId, s);
        _mountSlotDom(s);
    }

    s.pair     = pair;
    s.interval = interval || s.interval || '1h';

    const empty = document.getElementById('chart-empty-state');
    if (empty) empty.style.display = 'none';

    _updateSlotHeader(s);
    _updateTFButtons(slotId, s.interval);
    _updateSlotCount();
    _persistSlots();

    await _loadChartSlot(slotId, s.pair, s.interval);
}

function _mountSlotDom(slot) {
    const container = document.getElementById('chart-slots-container');
    if (!container) return;
    const el = document.createElement('div');
    el.className = 'chart-section';
    el.id = `chart-section-${slot.id}`;
    el.dataset.slotId = String(slot.id);
    el.style.cssText = 'background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:14px';
    el.innerHTML = `
        <div class="chart-header" style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px">
            <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
                <h3 id="chart-title-${slot.id}" style="margin:0;font-size:15px;font-weight:700">Loading…</h3>
                <span id="live-stream-badge-${slot.id}" style="display:none;align-items:center;gap:4px;font-size:11px;color:#00d68f;font-weight:600">
                    <span style="width:6px;height:6px;border-radius:50%;background:#00d68f;box-shadow:0 0 6px #00d68f;display:inline-block"></span>LIVE
                </span>
            </div>
            <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">
                <div id="tf-selector-${slot.id}" style="display:flex;gap:4px;background:var(--surface2);border:1px solid var(--border);border-radius:8px;padding:3px">
                    ${['5m','15m','1h','4h','1d'].map(tf =>
                        `<button id="tf-btn-${slot.id}-${tf}" onclick="switchChartIntervalSlot(${slot.id},'${tf}')"
                            style="padding:4px 11px;border-radius:6px;border:none;cursor:pointer;font-size:11px;font-weight:700;background:transparent;color:var(--text-dim);transition:all .15s">
                            ${tf.toUpperCase()}
                        </button>`
                    ).join('')}
                </div>
                <div class="chart-legend" style="display:flex;gap:10px;flex-wrap:wrap;font-size:11px">
                    <div class="leg"><div class="leg-line" style="background:#00d68f"></div>CE Long</div>
                    <div class="leg"><div class="leg-line" style="background:#ff4d6a"></div>CE Short</div>
                    <div class="leg"><div class="leg-area" style="background:rgba(0,214,143,0.3)"></div>Cloud</div>
                    <div class="leg"><div class="leg-line" style="background:#a78bfa"></div>TSI</div>
                </div>
                <button onclick="closeChartSlot(${slot.id})"
                    title="Close this chart"
                    style="background:transparent;border:1px solid var(--border);color:var(--text-dim);border-radius:6px;width:28px;height:28px;cursor:pointer;font-size:14px;font-weight:700">×</button>
            </div>
        </div>
        <div id="price-chart-${slot.id}" style="position:relative;margin-top:10px;height:420px"></div>
        <div id="chart-resize-handle-${slot.id}"
             style="height:8px;cursor:ns-resize;display:flex;align-items:center;justify-content:center;user-select:none">
             <div class="resize-grip" style="width:52px;height:3px;background:#1e2d40;border-radius:2px;transition:background .2s"></div>
        </div>
        <div id="indicator-chart-${slot.id}" style="height:160px"></div>
        <div class="rh-status" id="rh-status-${slot.id}"></div>
    `;
    container.appendChild(el);
}

function _destroySlot(slotId) {
    const s = _slots.get(slotId);
    if (!s) return;
    // Invalidate any in-flight fetches
    s.loadToken = -1;
    _disconnectLiveWsSlot(slotId);
    if (s.priceChart) { try { s.priceChart.remove(); } catch(e) {} }
    if (s.indChart)   { try { s.indChart.remove();   } catch(e) {} }
    const el = document.getElementById(`chart-section-${slotId}`);
    if (el && el.parentNode) el.parentNode.removeChild(el);
    _slots.delete(slotId);
    if (slotId === 0) _syncPrimaryGlobals();    // clears globals since slot 0 gone
}

function _updateSlotHeader(s) {
    const title = document.getElementById(`chart-title-${s.id}`);
    if (title) {
        title.textContent = s.pair.replace('USDT','/USDT') + ' Perp · ' + s.interval.toUpperCase();
    }
}

function _updateTFButtons(slotId, tf) {
    ['5m','15m','1h','4h','1d'].forEach(t => {
        const b = document.getElementById(`tf-btn-${slotId}-${t}`);
        if (!b) return;
        b.style.background = t === tf ? 'var(--gold)' : 'transparent';
        b.style.color      = t === tf ? '#000'       : 'var(--text-dim)';
    });
}

function _updateSlotCount() {
    const el = document.getElementById('chart-slot-count');
    if (el) el.textContent = `${_slots.size}/${_MAX_CHART_SLOTS} chart${_slots.size === 1 ? '' : 's'}`;
    const addBtn = document.getElementById('chart-add-slot-btn');
    if (addBtn) addBtn.disabled = _slots.size >= _MAX_CHART_SLOTS && false;  // allow replace of last
}

// ═════════════════════════════════════════════════════════════════
//  LOAD CHART (per slot)
// ═════════════════════════════════════════════════════════════════

async function _loadChartSlot(slotId, pair, interval) {
    const s = _slots.get(slotId);
    if (!s) return;

    _disconnectLiveWsSlot(slotId);

    // Invalidate previous in-flight fetches for this slot
    const myToken = ++s.loadToken;

    _updateSlotHeader(s);

    // Destroy existing charts + series refs
    if (s.priceChart) { try { s.priceChart.remove(); } catch(e) {} s.priceChart = null; }
    if (s.indChart)   { try { s.indChart.remove();   } catch(e) {} s.indChart   = null; }
    s.candleSeries = s.volSeries = s.ceLineSeries = s.ceCloudSeries = null;
    s.tsiSeries = s.linregSeries = s.entryLine = s.slLine = null;
    s.tpLines = []; s.ceMarkers = []; s.markerPlugin = null;
    s.liveLastBar = null;

    const priceEl = document.getElementById(`price-chart-${slotId}`);
    const indEl   = document.getElementById(`indicator-chart-${slotId}`);
    if (!priceEl || !indEl) return;
    priceEl.innerHTML =
        '<div class="loading" style="padding:40px"><div class="spinner"></div>Loading ' + interval.toUpperCase() + ' data…</div>';
    indEl.innerHTML = '';
    const rh = document.getElementById(`rh-status-${slotId}`);
    if (rh) rh.innerHTML = '';
    const badge = document.getElementById(`live-stream-badge-${slotId}`);
    if (badge) badge.style.display = 'none';

    const bars = _TF_BARS[interval] || 500;
    try {
        const res = await fetch(`/api/chart/${pair}?interval=${interval}&bars=${bars}`, { headers: authHeaders() });
        const d   = await res.json();
        if (myToken !== s.loadToken) return;    // stale fetch, slot was reloaded/destroyed
        if (d.error) throw new Error(d.error);
        renderChartSlot(slotId, d);
        renderChartStatusSlot(slotId, d);
        _connectLiveWsSlot(slotId, pair, interval);
        if (slotId === 0) _syncPrimaryGlobals();
    } catch(e) {
        if (myToken !== s.loadToken) return;
        priceEl.innerHTML =
            '<div class="no-data">Failed to load ' + interval.toUpperCase() + ' data — ' + (e.message || 'server error') + '</div>';
    }
}

// ── Price precision: matches Binance tick sizes by magnitude ───────
function _pricePrecision(price) {
    if (!price || price <= 0) return { precision: 4, minMove: 0.0001 };
    if (price < 0.00001)  return { precision: 8, minMove: 0.00000001 };
    if (price < 0.0001)   return { precision: 7, minMove: 0.0000001 };
    if (price < 0.01)     return { precision: 6, minMove: 0.000001 };
    if (price < 0.1)      return { precision: 5, minMove: 0.00001 };
    if (price < 1)        return { precision: 4, minMove: 0.0001 };
    if (price < 10)       return { precision: 3, minMove: 0.001 };
    if (price < 100)      return { precision: 2, minMove: 0.01 };
    if (price < 10000)    return { precision: 1, minMove: 0.1 };
    return { precision: 0, minMove: 1 };
}

function _createChartOptions(height) {
    const w = Math.min(document.querySelector('.main-content')?.clientWidth || 1200, 1560) - 30;
    return {
        width:  Math.max(320, w),
        height,
        layout: { background: { color: '#080c14' }, textColor: '#8899aa', fontSize: 11, fontFamily: "'Inter', sans-serif" },
        grid:   { vertLines: { color: '#111827' }, horzLines: { color: '#111827' } },
        crosshair: { mode: LightweightCharts.CrosshairMode.Normal,
            vertLine: { color: '#3a4a5e', width: 1, style: LightweightCharts.LineStyle.Solid, labelBackgroundColor: '#1e2d40' },
            horzLine: { color: '#3a4a5e', width: 1, style: LightweightCharts.LineStyle.Solid, labelBackgroundColor: '#1e2d40' } },
        rightPriceScale: { borderColor: '#1a2536', scaleMargins: { top: 0.05, bottom: 0.05 } },
        timeScale: { borderColor: '#1a2536', timeVisible: true, secondsVisible: false, rightOffset: 8 },
        handleScale: { mouseWheel: true, pinch: true, axisPressedMouseMove: { time: true, price: true } },
        handleScroll: { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false },
        attributionLogo: false,
    };
}

const _add = (chart, Type, opts) => chart.addSeries(Type, opts);

// ═════════════════════════════════════════════════════════════════
//  RENDER CHART (per slot)
// ═════════════════════════════════════════════════════════════════

function renderChartSlot(slotId, d) {
    const s = _slots.get(slotId);
    if (!s) return;
    const LC = LightweightCharts;
    const priceEl = document.getElementById(`price-chart-${slotId}`);
    const indEl   = document.getElementById(`indicator-chart-${slotId}`);
    if (!priceEl || !indEl) return;
    priceEl.innerHTML = '';
    indEl.innerHTML   = '';
    priceEl.style.position = 'relative';

    const _lastClose = d.close && d.close.length ? d.close[d.close.length - 1] : 1;
    s.precFmt = _pricePrecision(_lastClose);
    const _pf = { type: 'price', ...s.precFmt };

    const priceH = Math.max(240, priceEl.clientHeight || 420);
    const indH   = Math.max(100, indEl.clientHeight   || 160);

    s.priceChart = LC.createChart(priceEl, _createChartOptions(priceH));

    // Candles
    s.candleSeries = _add(s.priceChart, LC.CandlestickSeries, {
        upColor: '#00d68f', downColor: '#ff4d6a',
        borderUpColor: '#00d68f', borderDownColor: '#ff4d6a',
        wickUpColor: '#4fffb8', wickDownColor: '#ff6b85',
        priceFormat: _pf,
    });
    s.candleSeries.setData(d.timestamps.map((t,i) => ({ time: toUnix(t), open: d.open[i], high: d.high[i], low: d.low[i], close: d.close[i] })));

    // Volume
    s.volSeries = _add(s.priceChart, LC.HistogramSeries, { priceFormat: { type: 'volume' }, priceScaleId: 'vol' });
    s.priceChart.priceScale('vol').applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    s.volSeries.setData(d.timestamps.map((t,i) => ({
        time: toUnix(t), value: d.volume[i],
        color: d.close[i] >= d.open[i] ? 'rgba(0,214,143,0.12)' : 'rgba(255,77,106,0.12)'
    })));

    // CE Line
    s.ceLineSeries = _add(s.priceChart, LC.LineSeries, {
        lineWidth: 2, priceLineVisible: false, lastValueVisible: false,
        crosshairMarkerVisible: false, priceFormat: _pf });
    s.ceLineSeries.setData(d.timestamps.map((t,i) => ({
        time: toUnix(t),
        value: d.ce_line_dir[i] === 1 ? d.ce_line_long_stop[i] : d.ce_line_short_stop[i],
        color: d.ce_line_dir[i] === 1 ? '#00d68f' : '#ff4d6a'
    })));

    // CE Cloud
    s.ceCloudSeries = _add(s.priceChart, LC.LineSeries, {
        lineWidth: 2, priceLineVisible: false, lastValueVisible: false,
        crosshairMarkerVisible: false, lineStyle: LC.LineStyle.Dotted, priceFormat: _pf });
    s.ceCloudSeries.setData(d.timestamps.map((t,i) => ({
        time: toUnix(t),
        value: d.ce_cloud_dir[i] === 1 ? d.ce_cloud_long_stop[i] : d.ce_cloud_short_stop[i],
        color: d.ce_cloud_dir[i] === 1 ? 'rgba(0,214,143,0.45)' : 'rgba(255,77,106,0.45)'
    })));

    // CE markers
    s.ceMarkers = [];
    for (let i = 1; i < d.timestamps.length; i++) {
        if (d.ce_line_dir[i] === 1 && d.ce_line_dir[i-1] === -1)
            s.ceMarkers.push({ time: toUnix(d.timestamps[i]), position: 'belowBar', color: '#00d68f', shape: 'arrowUp',   text: 'CE Buy',  size: 1 });
        else if (d.ce_line_dir[i] === -1 && d.ce_line_dir[i-1] === 1)
            s.ceMarkers.push({ time: toUnix(d.timestamps[i]), position: 'aboveBar', color: '#ff4d6a', shape: 'arrowDown', text: 'CE Sell', size: 1 });
    }
    try {
        s.markerPlugin = LC.createSeriesMarkers(s.candleSeries, s.ceMarkers);
    } catch(e) {
        try { s.candleSeries.setMarkers(s.ceMarkers); } catch(_) {}
    }

    // Indicator pane
    s.indChart = LC.createChart(indEl, _createChartOptions(indH));
    s.linregSeries = _add(s.indChart, LC.HistogramSeries, { priceLineVisible: false, lastValueVisible: false, priceScaleId: 'lr' });
    s.indChart.priceScale('lr').applyOptions({ scaleMargins: { top: 0.08, bottom: 0.08 } });
    s.linregSeries.setData(d.timestamps.map((t,i) => ({
        time: toUnix(t), value: d.linreg[i],
        color: d.linreg[i] >= 0 ? 'rgba(0,214,143,0.28)' : 'rgba(255,77,106,0.28)'
    })));

    s.tsiSeries = _add(s.indChart, LC.LineSeries, { color: '#a78bfa', lineWidth: 2, priceLineVisible: false, lastValueVisible: true });
    s.tsiSeries.setData(d.timestamps.map((t,i) => ({ time: toUnix(t), value: d.tsi[i] })));

    [{ val: d.adapt_l1, col: 'rgba(244,162,54,0.6)' }, { val: d.adapt_l2, col: 'rgba(255,77,106,0.6)' }].forEach(({val, col}) => {
        [val, -val].forEach(v => {
            const l = _add(s.indChart, LC.LineSeries, { color: col, lineWidth: 1, lineStyle: LC.LineStyle.Dotted, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
            l.setData(d.timestamps.map(t => ({ time: toUnix(t), value: v })));
        });
    });
    const zeroS = _add(s.indChart, LC.LineSeries, { color: '#1e2d40', lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
    zeroS.setData(d.timestamps.map(t => ({ time: toUnix(t), value: 0 })));

    // Sync time scales per-slot (flag prevents infinite loop)
    s.priceChart.timeScale().subscribeVisibleLogicalRangeChange(r => {
        if (s.syncingRange || !r) return;
        s.syncingRange = true;
        try { s.indChart.timeScale().setVisibleLogicalRange(r); } catch(_) {}
        s.syncingRange = false;
    });
    s.indChart.timeScale().subscribeVisibleLogicalRangeChange(r => {
        if (s.syncingRange || !r) return;
        s.syncingRange = true;
        try { s.priceChart.timeScale().setVisibleLogicalRange(r); } catch(_) {}
        s.syncingRange = false;
    });

    // Signal overlay (only if there's a matching signal in the cache)
    overlaySignalLinesSlot(slotId, d);

    s.priceChart.priceScale('right').applyOptions({ autoScale: true, scaleMargins: { top: 0.06, bottom: 0.20 } });

    _addVerticalZoom(priceEl, s.priceChart, 'right', { top: 0.06, bottom: 0.20 });
    _addVerticalZoom(indEl,   s.indChart,   'right', { top: 0.08, bottom: 0.08 });

    _setupResizeHandleSlot(slotId);

    if (slotId === 0) _syncPrimaryGlobals();
}

// ═════════════════════════════════════════════════════════════════
//  VERTICAL ZOOM (wheel over the price axis)
// ═════════════════════════════════════════════════════════════════

function _addVerticalZoom(containerEl, chart, scaleId, initMargins) {
    if (!containerEl || !chart) return;
    let _m = { ...(initMargins || { top: 0.06, bottom: 0.06 }) };
    containerEl.addEventListener('wheel', e => {
        const rect = containerEl.getBoundingClientRect();
        if (!rect.width) return;
        const priceAxisW = 68;
        if (e.clientX < rect.right - priceAxisW) return;
        e.preventDefault();
        e.stopImmediatePropagation();
        const step = 0.018;
        const dir  = e.deltaY > 0 ? 1 : -1;
        _m.top    = Math.max(0.01, Math.min(0.45, _m.top    + dir * step));
        _m.bottom = Math.max(0.01, Math.min(0.45, _m.bottom + dir * step));
        chart.priceScale(scaleId).applyOptions({ autoScale: false, scaleMargins: { ..._m } });
    }, { passive: false, capture: true });
}

// ═════════════════════════════════════════════════════════════════
//  DRAG RESIZE (per slot)
// ═════════════════════════════════════════════════════════════════

function _setupResizeHandleSlot(slotId) {
    const s       = _slots.get(slotId);
    const handle  = document.getElementById(`chart-resize-handle-${slotId}`);
    const priceEl = document.getElementById(`price-chart-${slotId}`);
    const indEl   = document.getElementById(`indicator-chart-${slotId}`);
    if (!s || !handle || !priceEl || !indEl) return;

    const MIN_PH = 180, MIN_IH = 60;
    handle.onmousedown = e => {
        e.preventDefault();
        const startY  = e.clientY;
        const startPH = priceEl.clientHeight;
        const startIH = indEl.clientHeight;
        handle.querySelector('.resize-grip').style.background = '#4a6080';
        const onMove = ev => {
            const dy    = ev.clientY - startY;
            const newPH = Math.max(MIN_PH, startPH + dy);
            const newIH = Math.max(MIN_IH, startIH - dy);
            priceEl.style.height = newPH + 'px';
            indEl.style.height   = newIH + 'px';
            if (s.priceChart) s.priceChart.applyOptions({ height: newPH });
            if (s.indChart)   s.indChart.applyOptions({ height: newIH });
        };
        const onUp = () => {
            handle.querySelector('.resize-grip').style.background = '#1e2d40';
            document.removeEventListener('mousemove', onMove);
            document.removeEventListener('mouseup', onUp);
        };
        document.addEventListener('mousemove', onMove);
        document.addEventListener('mouseup', onUp);
    };
}

// ═════════════════════════════════════════════════════════════════
//  SIGNAL OVERLAY (per slot) — entry / SL / TP + signal info bar
// ═════════════════════════════════════════════════════════════════

function overlaySignalLinesSlot(slotId, d) {
    const s  = _slots.get(slotId);
    if (!s || !s.priceChart) return;
    const LC = LightweightCharts;
    const total = d.timestamps.length;
    const sig = (typeof _signalCache !== 'undefined' && _signalCache)
        ? _signalCache.find(x => x.pair === d.pair && x.price && x.stop_loss)
        : null;

    if (!sig) {
        s.priceChart.timeScale().setVisibleLogicalRange({ from: Math.max(0, total - 80), to: total });
        s.indChart && s.indChart.timeScale().setVisibleLogicalRange({ from: Math.max(0, total - 80), to: total });
        return;
    }

    const tFirst = toUnix(d.timestamps[0]);
    const tLast  = toUnix(d.timestamps[total - 1]);
    const mkLine = v => [{ time: tFirst, value: v }, { time: tLast, value: v }];
    const isLong = (sig.direction || '').toUpperCase() !== 'SHORT';

    const sigDispUnix = sig.timestamp + _SERVER_TZ_OFFSET;
    let sigIdx = -1;
    for (let i = 0; i < total; i++) { if (toUnix(d.timestamps[i]) >= sigDispUnix) { sigIdx = i; break; } }
    const from = sigIdx >= 0 ? Math.max(0, sigIdx - 24) : Math.max(0, total - 80);
    s.priceChart.timeScale().setVisibleLogicalRange({ from, to: total });
    s.indChart   && s.indChart.timeScale().setVisibleLogicalRange({ from, to: total });

    const pctFmt = (price) => {
        const p = (price - sig.price) / sig.price * 100;
        return (p >= 0 ? '+' : '') + p.toFixed(2) + '%';
    };
    const slPct = pctFmt(sig.stop_loss);
    const _spf  = { type: 'price', ...s.precFmt };

    s.entryLine = _add(s.priceChart, LC.LineSeries, {
        color: '#f4a236', lineWidth: 2, lineStyle: LC.LineStyle.Dashed,
        priceLineVisible: false, lastValueVisible: true, crosshairMarkerVisible: false,
        priceFormat: _spf, title: '─ Entry' });
    s.entryLine.setData(mkLine(sig.price));

    s.slLine = _add(s.priceChart, LC.LineSeries, {
        color: '#ff4d6a', lineWidth: 2, lineStyle: LC.LineStyle.Dashed,
        priceLineVisible: false, lastValueVisible: true, crosshairMarkerVisible: false,
        priceFormat: _spf, title: `─ SL ${slPct}` });
    s.slLine.setData(mkLine(sig.stop_loss));

    const tpGreen = ['#00c47a', '#00d68f', '#4fffb8'];
    s.tpLines = [];
    (sig.targets || []).forEach((tp, i) => {
        const pct = pctFmt(tp);
        const line = _add(s.priceChart, LC.LineSeries, {
            color: tpGreen[Math.min(i, 2)], lineWidth: 1 + i * 0.5,
            lineStyle: LC.LineStyle.Dashed,
            priceLineVisible: false, lastValueVisible: true, crosshairMarkerVisible: false,
            priceFormat: _spf, title: `─ TP${i+1} ${pct}` });
        line.setData(mkLine(tp));
        s.tpLines.push(line);
    });

    // Signal-bar marker merged with CE markers
    if (sigIdx >= 0 && s.candleSeries) {
        const sigM = {
            time: toUnix(d.timestamps[sigIdx]),
            position: isLong ? 'belowBar' : 'aboveBar',
            color: '#f4a236', shape: isLong ? 'arrowUp' : 'arrowDown',
            text: `📍 ${sig.direction} @${formatPrice(sig.price)}`, size: 2,
        };
        const all = [...(s.ceMarkers || []), sigM].sort((a, b) => a.time - b.time);
        try {
            if (s.markerPlugin && s.markerPlugin.setMarkers) s.markerPlugin.setMarkers(all);
            else LC.createSeriesMarkers(s.candleSeries, all);
        } catch(_) {
            try { s.candleSeries.setMarkers(all); } catch(__) {}
        }
    }
}

// ═════════════════════════════════════════════════════════════════
//  STATUS ROW (per slot)
// ═════════════════════════════════════════════════════════════════

function renderChartStatusSlot(slotId, d) {
    const last = d.tsi.length - 1;
    const tsi = d.tsi[last], lr = d.linreg[last], ceL = d.ce_line_dir[last], ceC = d.ce_cloud_dir[last];
    let zone = 'Neutral', zc = 'neutral';
    if      (tsi >=  d.adapt_l2) { zone = 'OB L2'; zc = 'down'; }
    else if (tsi >=  d.adapt_l1) { zone = 'OB L1'; zc = 'down'; }
    else if (tsi <= -d.adapt_l2) { zone = 'OS L2'; zc = 'up';   }
    else if (tsi <= -d.adapt_l1) { zone = 'OS L1'; zc = 'up';   }
    const el = document.getElementById(`rh-status-${slotId}`);
    if (!el) return;
    el.innerHTML = `
        <div class="rh-stat"><span class="stat-label">TSI Zone:</span><span class="stat-val ${zc}">${zone}</span></div>
        <div class="rh-stat"><span class="stat-label">TSI:</span><span class="stat-val ${tsi > 0 ? 'down' : 'up'}">${tsi.toFixed(3)}</span></div>
        <div class="rh-stat"><span class="stat-label">L1/L2:</span><span class="stat-val neutral">±${d.adapt_l1} / ±${d.adapt_l2}</span></div>
        <div class="rh-stat"><span class="stat-label">LinReg:</span><span class="stat-val ${lr > 0 ? 'up' : lr < 0 ? 'down' : 'neutral'}">${lr.toFixed(3)}</span></div>
        <div class="rh-stat"><span class="stat-label">CE Line:</span><span class="stat-val ${ceL === 1 ? 'up' : 'down'}">${ceL === 1 ? 'LONG' : 'SHORT'}</span></div>
        <div class="rh-stat"><span class="stat-label">CE Cloud:</span><span class="stat-val ${ceC === 1 ? 'up' : 'down'}">${ceC === 1 ? 'LONG' : 'SHORT'}</span></div>`;
}

// ═════════════════════════════════════════════════════════════════
//  RESIZE — propagate to every slot
// ═════════════════════════════════════════════════════════════════

window.addEventListener('resize', () => {
    const w = Math.max(320, Math.min(document.querySelector('.main-content')?.clientWidth || 1200, 1560) - 30);
    for (const s of _slots.values()) {
        if (s.priceChart) s.priceChart.applyOptions({ width: w });
        if (s.indChart)   s.indChart.applyOptions({ width: w });
    }
});

// ═════════════════════════════════════════════════════════════════
//  LIVE BINANCE WEBSOCKET — per slot
// ═════════════════════════════════════════════════════════════════

function _connectLiveWsSlot(slotId, pair, interval) {
    const s = _slots.get(slotId);
    if (!s) return;
    _disconnectLiveWsSlot(slotId);

    const stream = `${pair.toLowerCase()}@kline_${interval}`;
    const wsUrl  = `wss://fstream.binance.com/stream?streams=${stream}`;
    const ctx = { active: true, socket: null };

    function connect() {
        if (!ctx.active) return;
        const ws = new WebSocket(wsUrl);
        ctx.socket = ws;
        ws.onopen = () => {
            const badge = document.getElementById(`live-stream-badge-${slotId}`);
            if (badge) badge.style.display = 'flex';
        };
        ws.onmessage = (evt) => {
            try {
                const msg = JSON.parse(evt.data);
                const k   = (msg.data || msg).k;
                if (k) _onLiveTickSlot(slotId, pair, interval, k);
            } catch(_) {}
        };
        ws.onerror = () => {};
        ws.onclose = () => {
            const badge = document.getElementById(`live-stream-badge-${slotId}`);
            if (badge) badge.style.display = 'none';
            if (ctx.active) s.liveWsReconnect = setTimeout(connect, 3000);
        };
    }
    connect();

    s.liveWs = { _teardown: () => { ctx.active = false; if (ctx.socket) try { ctx.socket.close(); } catch(_) {} ctx.socket = null; } };
}

function _disconnectLiveWsSlot(slotId) {
    const s = _slots.get(slotId);
    if (!s) return;
    if (s.liveWsReconnect) { clearTimeout(s.liveWsReconnect); s.liveWsReconnect = null; }
    if (s.liveWs && s.liveWs._teardown) s.liveWs._teardown();
    s.liveWs = null;
    s.liveLastBar = null;
    const badge = document.getElementById(`live-stream-badge-${slotId}`);
    if (badge) badge.style.display = 'none';
}

function _disconnectAllLiveWs() {
    for (const id of _slots.keys()) _disconnectLiveWsSlot(id);
}

async function _onLiveTickSlot(slotId, pair, interval, k) {
    const s = _slots.get(slotId);
    if (!s || !s.candleSeries || !s.priceChart) return;

    const barTime = Math.floor(parseInt(k.t) / 1000) + (_SERVER_TZ_OFFSET || 0);
    const o = parseFloat(k.o), h = parseFloat(k.h),
          l = parseFloat(k.l), c = parseFloat(k.c),
          v = parseFloat(k.v);
    const bar = { time: barTime, open: o, high: h, low: l, close: c };

    try {
        s.candleSeries.update(bar);
        if (s.volSeries) s.volSeries.update({
            time: barTime, value: v,
            color: c >= o ? 'rgba(0,214,143,0.15)' : 'rgba(255,77,106,0.15)'
        });
    } catch(_) {}
    s.liveLastBar = bar;

    if (k.x && !s.liveRefreshPending) {
        s.liveRefreshPending = true;
        setTimeout(async () => {
            try {
                const bars = _TF_BARS[interval] || 500;
                const res  = await fetch(`/api/chart/${pair}?interval=${interval}&bars=${bars}`, { headers: authHeaders() });
                const d    = await res.json();
                if (!d.error && s.candleSeries) {
                    if (s.tsiSeries && d.tsi) {
                        s.tsiSeries.setData(d.timestamps.map((t,i) => ({ time: toUnix(t), value: d.tsi[i] })));
                    }
                    if (s.linregSeries && d.linreg) {
                        s.linregSeries.setData(d.timestamps.map((t,i) => ({
                            time: toUnix(t), value: d.linreg[i],
                            color: d.linreg[i] >= 0 ? 'rgba(0,214,143,0.28)' : 'rgba(255,77,106,0.28)'
                        })));
                    }
                    if (s.ceLineSeries && d.ce_line_dir) {
                        s.ceLineSeries.setData(d.timestamps.map((t,i) => ({
                            time: toUnix(t),
                            value: d.ce_line_dir[i] === 1 ? d.ce_line_long_stop[i] : d.ce_line_short_stop[i],
                            color: d.ce_line_dir[i] === 1 ? '#00d68f' : '#ff4d6a'
                        })));
                    }
                    if (s.ceCloudSeries && d.ce_cloud_dir) {
                        s.ceCloudSeries.setData(d.timestamps.map((t,i) => ({
                            time: toUnix(t),
                            value: d.ce_cloud_dir[i] === 1 ? d.ce_cloud_long_stop[i] : d.ce_cloud_short_stop[i],
                            color: d.ce_cloud_dir[i] === 1 ? 'rgba(0,214,143,0.45)' : 'rgba(255,77,106,0.45)'
                        })));
                    }
                    renderChartStatusSlot(slotId, d);
                }
            } catch(_) {}
            s.liveRefreshPending = false;
        }, 1500);
    }
}

// ═════════════════════════════════════════════════════════════════
//  PAGE-CHANGE TEARDOWN — disconnect every slot's WS when leaving
// ═════════════════════════════════════════════════════════════════

(function () {
    const orig = window.switchPage;
    if (typeof orig !== 'function') return;
    window.switchPage = function (page) {
        if (page !== 'charts') _disconnectAllLiveWs();
        return orig.apply(this, arguments);
    };
})();
