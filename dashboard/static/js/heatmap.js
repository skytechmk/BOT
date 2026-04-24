// ═══════════════════════════════════════════════════════════════
//  LIQUIDATION HEATMAP
// ═══════════════════════════════════════════════════════════════
let _liqFastTimer  = null;
let _liqSlowTimer  = null;
let _liqCurrentPair = 'BTCUSDT';
let _liqWindow = 24;  // default 24h (1h removed)
let _liqCachedVp   = null;
let _liqMarkPrice  = null;
let _liqMarkWs     = null;
let _liqLastLayout    = null;
let _liqCrosshairEl   = null;
let _liqCachedHeatData = null;
let _liqNoiseThreshold = 0;

const _LIQ_NOISE_STEPS  = [0, 1e3, 5e3, 1e4, 2.5e4, 5e4, 1e5, 2.5e5, 5e5, 1e6];
const _LIQ_NOISE_LABELS = ['All','$1K','$5K','$10K','$25K','$50K','$100K','$250K','$500K','$1M'];

// Y-axis zoom — fraction of mark price shown on each side (0.02 = ±2%, 0.80 = ±80%)
let _liqZoomRange = 0.35;
const _LIQ_ZOOM_STEPS = [0.02, 0.05, 0.08, 0.12, 0.18, 0.25, 0.35, 0.50, 0.65, 0.80];

function _liqZoomLabelStr(r) {
    return '\u00b1' + Math.round(r * 100) + '%';
}

function _liqApplyZoom(newRange) {
    _liqZoomRange = Math.max(0.02, Math.min(0.80, newRange));
    var lbl = document.getElementById('liq-zoom-label');
    if (lbl) lbl.textContent = _liqZoomLabelStr(_liqZoomRange);
    if (_liqCachedHeatData) renderLiqHeatmap(_liqCachedHeatData, _liqCachedVp);
}

function liqZoomIn() {
    // Tighten range: find the next smaller step
    var cur = _liqZoomRange;
    var next = _LIQ_ZOOM_STEPS.slice().reverse().find(function(s){ return s < cur - 0.001; });
    _liqApplyZoom(next !== undefined ? next : _LIQ_ZOOM_STEPS[0]);
}

function liqZoomOut() {
    // Widen range: find the next larger step
    var cur = _liqZoomRange;
    var next = _LIQ_ZOOM_STEPS.find(function(s){ return s > cur + 0.001; });
    _liqApplyZoom(next !== undefined ? next : _LIQ_ZOOM_STEPS[_LIQ_ZOOM_STEPS.length - 1]);
}

function liqZoomReset() {
    _liqApplyZoom(0.35);
}

function setLiqNoiseFilter(idx) {
    idx = Math.max(0, Math.min(9, parseInt(idx) || 0));
    _liqNoiseThreshold = _LIQ_NOISE_STEPS[idx];
    var lbl = document.getElementById('liq-noise-label');
    if (lbl) lbl.textContent = _LIQ_NOISE_LABELS[idx];
    if (_liqCachedHeatData) renderLiqHeatmap(_liqCachedHeatData, _liqCachedVp);
}

// Module-level price formatter (mirrored from renderLiqHeatmap so crosshair can use it)
function _liqFmtPrice(p) {
    if (p >= 10000) return Math.round(p).toLocaleString();
    if (p >= 1000)  return p.toFixed(1);
    if (p >= 100)   return p.toFixed(2);
    if (p >= 10)    return p.toFixed(3);
    if (p >= 1)     return p.toFixed(4);
    if (p >= 0.1)   return p.toFixed(5);
    return p.toPrecision(4);
}

function initLiqCrosshair() {
    var wrapper = document.getElementById('liq-canvas');
    if (!wrapper) return;
    var parent = wrapper.parentElement;
    if (!parent) return;
    var ch = document.getElementById('liq-crosshair-canvas');
    if (!ch) {
        ch = document.createElement('canvas');
        ch.id = 'liq-crosshair-canvas';
        ch.style.cssText = 'position:absolute;top:0;left:0;pointer-events:none;z-index:11';
        parent.appendChild(ch);
    }
    _liqCrosshairEl = ch;
    // Sync size to main canvas
    ch.style.width  = wrapper.style.width  || wrapper.offsetWidth  + 'px';
    ch.style.height = wrapper.style.height || wrapper.offsetHeight + 'px';
    parent.removeEventListener('mousemove',  _liqOnMouseMove);
    parent.removeEventListener('mouseleave', _liqOnMouseLeave);
    parent.removeEventListener('wheel',       _liqOnWheel);
    parent.addEventListener('mousemove',  _liqOnMouseMove);
    parent.addEventListener('mouseleave', _liqOnMouseLeave);
    parent.addEventListener('wheel',       _liqOnWheel, { passive: false });
}

function _liqOnWheel(e) {
    e.preventDefault();
    if (e.deltaY < 0) liqZoomIn();   // scroll up = zoom in (tighter)
    else              liqZoomOut();  // scroll down = zoom out (wider)
}

function _liqOnMouseMove(e) {
    var rect = e.currentTarget.getBoundingClientRect();
    _liqDrawCrosshair(e.clientX - rect.left, e.clientY - rect.top);
}
function _liqOnMouseLeave() {
    if (!_liqCrosshairEl) return;
    var ctx = _liqCrosshairEl.getContext('2d');
    ctx.clearRect(0, 0, _liqCrosshairEl.width, _liqCrosshairEl.height);
}

function _liqDrawCrosshair(mx, my) {
    if (!_liqCrosshairEl || !_liqLastLayout) return;
    var lo  = _liqLastLayout;
    var mainC = document.getElementById('liq-canvas');
    var W = mainC ? (parseFloat(mainC.style.width)  || mainC.offsetWidth  || 900) : 900;
    var H = mainC ? (parseFloat(mainC.style.height) || mainC.offsetHeight || 560) : 560;
    var dpr = Math.min(window.devicePixelRatio || 1, 3);
    _liqCrosshairEl.width  = Math.round(W * dpr);
    _liqCrosshairEl.height = Math.round(H * dpr);
    _liqCrosshairEl.style.width  = W + 'px';
    _liqCrosshairEl.style.height = H + 'px';
    var ctx = _liqCrosshairEl.getContext('2d');
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, W, H);
    // Only draw inside chart area
    if (mx < lo.padL || mx > W - lo.padR || my < lo.padT || my > lo.padT + lo.chartH) return;
    var priceRange = lo.maxP - lo.minP || 1;
    var price = lo.minP + ((lo.padT + lo.chartH - my) / lo.chartH) * priceRange;
    // Horizontal crosshair (Y-axis line)
    ctx.save();
    ctx.strokeStyle = 'rgba(255,255,255,0.55)';
    ctx.lineWidth = 1;
    ctx.setLineDash([5, 4]);
    ctx.beginPath(); ctx.moveTo(lo.padL, my); ctx.lineTo(W - lo.padR, my); ctx.stroke();
    ctx.restore();
    // Vertical crosshair (X-axis line)
    ctx.save();
    ctx.strokeStyle = 'rgba(255,255,255,0.30)';
    ctx.lineWidth = 1;
    ctx.setLineDash([5, 4]);
    ctx.beginPath(); ctx.moveTo(mx, lo.padT); ctx.lineTo(mx, lo.padT + lo.chartH); ctx.stroke();
    ctx.restore();
    // Price badge on Y-axis
    var label = _liqFmtPrice(price);
    ctx.font = 'bold 11px monospace';
    var tw = ctx.measureText(label).width;
    var bw = tw + 12, bh = 16;
    var bx = lo.padL - bw - 4, by = my - bh / 2;
    ctx.fillStyle = 'rgba(0,10,20,0.92)';
    ctx.fillRect(bx, by, bw, bh);
    ctx.strokeStyle = 'rgba(255,255,255,0.45)';
    ctx.lineWidth = 0.8;
    ctx.strokeRect(bx, by, bw, bh);
    ctx.fillStyle = '#ffffff';
    ctx.textAlign = 'center';
    ctx.fillText(label, bx + bw / 2, my + 4);
    // Nearest bucket tooltip
    if (lo.buckets && lo.buckets.length) {
        var near = null, minD = Infinity;
        lo.buckets.forEach(function(b) {
            var by2 = lo.padT + lo.chartH - ((b.price - lo.minP) / priceRange) * lo.chartH;
            var d = Math.abs(by2 - my);
            if (d < minD) { minD = d; near = b; }
        });
        if (near && minD < 28) {
            var longM  = near.long_liq_usd  >= 1e6 ? '$' + (near.long_liq_usd  / 1e6).toFixed(2) + 'M' : '$' + (near.long_liq_usd  / 1e3).toFixed(0) + 'K';
            var shortM = near.short_liq_usd >= 1e6 ? '$' + (near.short_liq_usd / 1e6).toFixed(2) + 'M' : '$' + (near.short_liq_usd / 1e3).toFixed(0) + 'K';
            var tipLines = [
                _liqFmtPrice(near.price),
                '\u25C4 Long: ' + longM,
                'Short: ' + shortM + ' \u25BA',
            ];
            ctx.font = 'bold 11px monospace';
            var tipW = Math.max.apply(null, tipLines.map(function(l){ return ctx.measureText(l).width; })) + 20;
            var tipH = tipLines.length * 16 + 10;
            var tx = Math.min(mx + 12, W - lo.padR - tipW - 4);
            var ty = Math.max(lo.padT + 4, Math.min(my - tipH / 2, lo.padT + lo.chartH - tipH - 4));
            ctx.fillStyle = 'rgba(0,10,20,0.90)';
            ctx.fillRect(tx, ty, tipW, tipH);
            ctx.strokeStyle = 'rgba(255,255,255,0.25)';
            ctx.lineWidth = 0.8;
            ctx.strokeRect(tx, ty, tipW, tipH);
            ctx.textAlign = 'left';
            ctx.fillStyle = 'rgba(240,220,180,1)';   ctx.fillText(tipLines[0], tx + 10, ty + 14);
            ctx.fillStyle = 'rgba(255,100,120,0.95)'; ctx.fillText(tipLines[1], tx + 10, ty + 29);
            ctx.fillStyle = 'rgba(0,214,143,0.95)';   ctx.fillText(tipLines[2], tx + 10, ty + 44);
        }
    }
}

function connectLiqMarkWs(symbol) {
    if (_liqMarkWs) { try { _liqMarkWs.close(); } catch(e){} _liqMarkWs = null; }
    const url = 'wss://fstream.binance.com/ws/' + symbol.toLowerCase() + '@markPrice';
    let ws;
    try { ws = new WebSocket(url); } catch(e) { return; }
    ws.onopen  = function() { _liqMarkWs = ws; };
    ws.onmessage = function(e) {
        try {
            var d = JSON.parse(e.data);
            var newPrice = parseFloat(d.p);
            if (!isNaN(newPrice) && newPrice > 0) {
                _liqMarkPrice = newPrice;
                drawMarkPriceLine();
                var markEl = document.getElementById('liq-live-mark');
                if (markEl) markEl.textContent = 'Mark: ' + newPrice;
                var fr = parseFloat(d.r);
                if (!isNaN(fr)) {
                    var frEl = document.getElementById('liq-live-fr');
                    if (frEl) {
                        var frPct = (fr * 100).toFixed(4);
                        frEl.textContent = (frPct >= 0 ? '+' : '') + frPct + '% / 8h';
                        frEl.style.color = fr > 0.0005 ? 'var(--red)' : fr < -0.0005 ? 'var(--green)' : 'var(--gold)';
                    }
                }
            }
        } catch(ex) {}
    };
    ws.onerror = function() {};
    ws.onclose = function() {
        _liqMarkWs = null;
        setTimeout(function() {
            if (document.getElementById('page-heatmap').classList.contains('active') &&
                _liqCurrentPair === symbol) {
                connectLiqMarkWs(symbol);
            }
        }, 3000);
    };
}

function drawMarkPriceLine() {
    var priceCanvas = document.getElementById('liq-price-canvas');
    var mainCanvas  = document.getElementById('liq-canvas');
    if (!priceCanvas || !mainCanvas || !_liqMarkPrice || !_liqLastLayout) return;
    var lo  = _liqLastLayout;
    var dpr = Math.min(window.devicePixelRatio || 1, 3);
    var W   = parseFloat(mainCanvas.style.width)  || mainCanvas.offsetWidth  || 900;
    var H   = parseFloat(mainCanvas.style.height) || mainCanvas.offsetHeight || 560;
    priceCanvas.width  = Math.round(W * dpr);
    priceCanvas.height = Math.round(H * dpr);
    priceCanvas.style.width  = W + 'px';
    priceCanvas.style.height = H + 'px';
    var priceRange = lo.maxP - lo.minP || 1;
    var y = lo.padT + lo.chartH - ((_liqMarkPrice - lo.minP) / priceRange) * lo.chartH;
    var ctx = priceCanvas.getContext('2d');
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, W, H);
    var yClamped = Math.max(lo.padT + 2, Math.min(lo.padT + lo.chartH - 2, y));
    ctx.save();
    ctx.shadowColor = 'rgba(240,185,11,0.4)';
    ctx.shadowBlur  = 4;
    ctx.strokeStyle = 'rgba(240,185,11,0.9)';
    ctx.lineWidth   = 1.5;
    ctx.setLineDash([5, 3]);
    ctx.beginPath();
    ctx.moveTo(lo.padL, yClamped);
    ctx.lineTo(W - lo.padR + 8, yClamped);  // W is logical width
    ctx.stroke();
    ctx.restore();
    ctx.setLineDash([]);
    var isMob = window.innerWidth <= 480;
    var label = isMob ? String(Math.round(_liqMarkPrice)) : _liqMarkPrice.toPrecision(6);
    ctx.font = 'bold 11px monospace';
    var tw  = ctx.measureText(label).width;
    ctx.fillStyle = 'rgba(240,185,11,0.15)';
    ctx.fillRect(W - lo.padR + 10, yClamped - 9, tw + 10, 16);
    ctx.strokeStyle = 'rgba(240,185,11,0.5)';
    ctx.lineWidth = 1;
    ctx.strokeRect(W - lo.padR + 10, yClamped - 9, tw + 10, 16);
    ctx.fillStyle = 'rgba(240,185,11,1)';
    ctx.textAlign = 'left';
    ctx.fillText(label, W - lo.padR + 15, yClamped + 3);
    if (_liqLastLayout && (_liqTopBids.length || _liqTopAsks.length)) {
        var lPriceRange = lo.maxP - lo.minP || 1;
        var lPriceToY  = function(p) { return lo.padT + lo.chartH - ((p - lo.minP) / lPriceRange) * lo.chartH; };
        var maxBidQty  = Math.max.apply(null, _liqTopBids.map(function(b){return b.qty}).concat([1]));
        var maxAskQty  = Math.max.apply(null, _liqTopAsks.map(function(a){return a.qty}).concat([1]));
        _liqTopBids.forEach(function(b) {
            var y2  = lPriceToY(b.price);
            if (y2 < lo.padT || y2 > lo.padT + lo.chartH) return;
            var len = Math.min(50, Math.max(8, (b.qty / maxBidQty) * 50));
            ctx.fillStyle = 'rgba(80,180,255,' + (0.3 + (b.qty / maxBidQty) * 0.55) + ')';
            ctx.fillRect(lo.padL, y2 - 2, len, 4);
        });
        var axStart = lo.padL + (lo.maxP - lo.minP > 0 ? (lo.chartW / 2 + 4) : 60);
        _liqTopAsks.forEach(function(a) {
            var y2  = lPriceToY(a.price);
            if (y2 < lo.padT || y2 > lo.padT + lo.chartH) return;
            var len = Math.min(50, Math.max(8, (a.qty / maxAskQty) * 50));
            ctx.fillStyle = 'rgba(255,140,80,' + (0.3 + (a.qty / maxAskQty) * 0.55) + ')';
            ctx.fillRect(axStart, y2 - 2, len, 4);
        });
    }
}

function setLiqWindow(w) {
    _liqWindow = w;
    document.querySelectorAll('.liq-win-btn').forEach(function(b) {
        b.classList.toggle('active', parseInt(b.dataset.w) === w);
    });
    loadLiqHeatmap(_liqCurrentPair);
}

async function initLiqHeatmap() {
    await loadLiqSummary();
    await loadLiqHeatmap();
    initLiqWatchlist();
    initLiqPairSuggest();
    if (_liqFastTimer) clearInterval(_liqFastTimer);
    _liqFastTimer = setInterval(async function() {
        if (!document.getElementById('page-heatmap').classList.contains('active')) return;
        await loadLiqSummary();
        await _loadLiqBarsOnly();
        await loadLiqVelocity(_liqCurrentPair);
        updatePocBiasCard();
    }, 5000);
    if (_liqSlowTimer) clearInterval(_liqSlowTimer);
    _liqSlowTimer = setInterval(async function() {
        if (!document.getElementById('page-heatmap').classList.contains('active')) return;
        await _loadLiqVpAndContext();
    }, 60000);
}

async function _loadLiqBarsOnly() {
    try {
        var res = await fetch('/api/liq/heatmap/' + _liqCurrentPair + '?window=' + _liqWindow, { headers: authHeaders() });
        if (!res.ok) return;
        var data = await res.json();
        renderLiqHeatmap(data, _liqCachedVp);
    } catch(e) {}
}

async function _loadLiqVpAndContext() {
    try {
        var results = await Promise.all([
            fetch('/api/liq/vp/' + _liqCurrentPair + '?window=' + _liqWindow, { headers: authHeaders() }),
            loadLiqContext(_liqCurrentPair),
        ]);
        if (results[0].ok) { _liqCachedVp = await results[0].json(); }
    } catch(e) {}
}

async function loadLiqSummary() {
    try {
        var res = await fetch('/api/liq/summary?top_n=20', { headers: authHeaders() });
        if (!res.ok) return;
        var data = await res.json();
        var stats = data.stats || {};
        var badge = document.getElementById('liq-conn-badge');
        var statsBadge = document.getElementById('liq-stats-badge');
        if (badge) {
            badge.textContent = stats.connected ? '🟢 Live' : '🔴 Reconnecting';
            badge.style.background = stats.connected ? 'rgba(0,214,143,0.15)' : 'rgba(255,77,106,0.15)';
            badge.style.color = stats.connected ? 'var(--green)' : 'var(--red)';
        }
        if (statsBadge) {
            var usdM = (stats.total_usd || 0) / 1e6;
            statsBadge.textContent = (stats.total_events||0).toLocaleString() + ' events | $' + usdM.toFixed(1) + 'M | ' + (stats.symbols_tracked||0) + ' pairs';
        }
        var summary = data.summary || [];

        // Build top-12: top 10 by volume + guarantee BTC + ETH
        var top12 = summary.slice(0, 10);
        var inTop12 = function(sym) { return top12.some(function(x){return x.symbol === sym;}); };
        if (!inTop12('BTCUSDT')) {
            var btcEntry = summary.find(function(x){return x.symbol==='BTCUSDT';});
            top12.push(btcEntry || {symbol:'BTCUSDT', total_usd:0, long_liq_usd:0, short_liq_usd:0, dominant:'LONG'});
        }
        if (!inTop12('ETHUSDT')) {
            var ethEntry = summary.find(function(x){return x.symbol==='ETHUSDT';});
            top12.push(ethEntry || {symbol:'ETHUSDT', total_usd:0, long_liq_usd:0, short_liq_usd:0, dominant:'LONG'});
        }

        var qpEl = document.getElementById('liq-quick-pairs');
        if (qpEl && top12.length) {
            qpEl.innerHTML = top12.map(function(s, idx) {
                var dom = s.dominant === 'LONG' ? 'var(--red)' : 'var(--green)';
                var bg  = s.dominant === 'LONG' ? 'rgba(255,77,106,0.1)' : 'rgba(0,214,143,0.1)';
                var bdr = s.dominant === 'LONG' ? 'rgba(255,77,106,0.3)' : 'rgba(0,214,143,0.3)';
                var usd = s.total_usd >= 1e6 ? '$' + (s.total_usd/1e6).toFixed(1)+'M' : '$' + (s.total_usd/1e3).toFixed(0)+'K';
                var rank = idx < 10 ? '<span style="font-size:9px;opacity:.5;margin-right:2px">#'+(idx+1)+'</span>' : '';
                return '<span class="liq-pair-chip" onclick="loadLiqHeatmap(\'' + s.symbol + '\')" style="background:' + bg + ';border-color:' + bdr + ';color:' + dom + '">' +
                    rank + s.symbol.replace('USDT','') + ' <span style="color:var(--text-dim);font-weight:400">' + usd + '</span></span>';
            }).join('');
        }
        var barEl = document.getElementById('liq-summary-bar');
        if (barEl && summary.length) {
            var topLong = summary.slice().sort(function(a,b){return b.long_liq_usd - a.long_liq_usd}).slice(0,3);
            var topShort = summary.slice().sort(function(a,b){return b.short_liq_usd - a.short_liq_usd}).slice(0,3);
            function mkChip(s, val, color, bg, border) {
                return '<span class="liq-pair-chip" onclick="loadLiqHeatmap(\'' + s.symbol + '\')" style="background:' + bg + ';border-color:' + border + ';color:' + color + '">' +
                    '<span style="font-weight:800">' + s.symbol.replace('USDT','') + '</span>' +
                    '<span style="opacity:.85">$' + (val/1e6).toFixed(1) + 'M</span></span>';
            }
            barEl.innerHTML =
                '<div style="display:flex;align-items:center;gap:6px;padding:8px 14px;background:rgba(255,77,106,0.07);border:1px solid rgba(255,77,106,0.25);border-radius:8px">' +
                    '<span style="font-size:10px;font-weight:700;letter-spacing:.08em;color:rgba(255,77,106,0.8);text-transform:uppercase;white-space:nowrap">&#9660; Long Liqs</span>' +
                    '<div style="display:flex;gap:5px;flex-wrap:wrap">' + topLong.map(function(s){return mkChip(s,s.long_liq_usd,'var(--red)','rgba(255,77,106,0.12)','rgba(255,77,106,0.35)')}).join('') + '</div>' +
                '</div>' +
                '<div style="display:flex;align-items:center;gap:6px;padding:8px 14px;background:rgba(0,214,143,0.07);border:1px solid rgba(0,214,143,0.25);border-radius:8px">' +
                    '<span style="font-size:10px;font-weight:700;letter-spacing:.08em;color:rgba(0,214,143,0.8);text-transform:uppercase;white-space:nowrap">&#9650; Short Liqs</span>' +
                    '<div style="display:flex;gap:5px;flex-wrap:wrap">' + topShort.map(function(s){return mkChip(s,s.short_liq_usd,'var(--green)','rgba(0,214,143,0.12)','rgba(0,214,143,0.35)')}).join('') + '</div>' +
                '</div>';
        }
    } catch(e) {}
}

async function loadLiqContext(pair) {
    var bar = document.getElementById('liq-context-bar');
    if (!bar) return;
    try {
        var res = await fetch('/api/liq/context/' + pair, { headers: authHeaders() });
        if (!res.ok) { bar.innerHTML = '<span style="color:var(--text-dim)">Context unavailable</span>'; return; }
        var d = await res.json();
        if (!d.has_data) { bar.innerHTML = '<span style="color:var(--text-dim)">No context data</span>'; return; }
        var fr = d.funding_rate != null ? d.funding_rate : null;
        var frColor = fr === null ? 'var(--text-dim)' : fr > 0.05 ? 'var(--red)' : fr < -0.05 ? 'var(--green)' : 'var(--gold)';
        var frLabel = fr === null ? '\u2014' : (fr >= 0 ? '+' : '') + fr.toFixed(4) + '% / 8h';
        var biasLabel = d.funding_bias || '\u2014';
        var biasColor = biasLabel === 'LONG_HEAVY' ? 'var(--red)' : biasLabel === 'SHORT_HEAVY' ? 'var(--green)' : 'var(--gold)';
        var oiStr = d.oi_usd ? '$' + (d.oi_usd / 1e6).toFixed(1) + 'M OI' : '';
        var lsStr = d.ls_ratio != null ? 'L/S: ' + d.long_ratio + '% / ' + d.short_ratio + '%' : '';
        bar.innerHTML =
            '<div class="liq-ctx-pill"><span class="liq-ctx-pill-label">Funding / 8h</span><span id="liq-live-fr" class="liq-ctx-pill-val" style="color:' + frColor + '">' + frLabel + '</span></div>' +
            '<div class="liq-ctx-pill"><span class="liq-ctx-pill-label">Bias</span><span class="liq-ctx-pill-val" style="color:' + biasColor + '">' + biasLabel + '</span></div>' +
            (oiStr ? '<div class="liq-ctx-pill"><span class="liq-ctx-pill-label">Open Interest</span><span class="liq-ctx-pill-val">' + oiStr + '</span></div>' : '') +
            (lsStr ? '<div class="liq-ctx-pill"><span class="liq-ctx-pill-label">Long / Short</span><span class="liq-ctx-pill-val">' + d.long_ratio + '% <span style="color:var(--text-dim);font-weight:400">/</span> ' + d.short_ratio + '%</span></div>' : '') +
            '<div class="liq-ctx-pill"><span class="liq-ctx-pill-label">Mark Price</span><span id="liq-live-mark" class="liq-ctx-pill-val" style="color:var(--gold)">' + (d.mark_price || '\u2014') + '</span></div>';
    } catch(e) { bar.innerHTML = '<span style="color:var(--text-dim)">Context error</span>'; }
}

async function loadLiqHeatmap(pair) {
    pair = (pair || document.getElementById('liq-pair-input').value || 'BTCUSDT').toUpperCase();
    if (!pair.endsWith('USDT')) pair += 'USDT';
    _liqCurrentPair = pair;
    document.getElementById('liq-pair-input').value = pair;
    document.getElementById('liq-chart-title').textContent = pair;
    document.getElementById('liq-chart-sub').textContent = 'Loading snapshot…';
    // Non-blocking parallel side-loads (ctx, velocity, suggest) — don't
    // wait for them to render the primary heatmap.
    loadLiqContext(pair);
    loadLiqVelocity(pair);
    loadLiqSuggest(pair);
    // ═══ SNAPSHOT-FIRST (F2) ═══════════════════════════════════════════
    // Render the REST snapshot immediately. Only AFTER the user sees the
    // heatmap do we establish the live WebSocket connections — this
    // eliminates the cold-start "Connecting…" stall that plagued older
    // builds, and lets the user orient themselves while streams come up.
    try {
        var results = await Promise.all([
            fetch('/api/liq/heatmap/' + pair + '?window=' + _liqWindow, { headers: authHeaders() }),
            fetch('/api/liq/vp/' + pair + '?window=' + _liqWindow, { headers: authHeaders() }),
        ]);
        var heatData = results[0].ok ? await results[0].json() : null;
        var vpData   = results[1].ok ? await results[1].json() : null;
        if (!heatData) { document.getElementById('liq-chart-sub').textContent = 'Error loading data'; return; }
        if (vpData && vpData.has_data) { _liqCachedVp = vpData; updatePocBiasCard(); }
        renderLiqHeatmap(heatData, _liqCachedVp);
    } catch(e) {
        document.getElementById('liq-chart-sub').textContent = 'Failed to load';
        return;
    }
    // Snapshot is now painted. Hook the live streams on the next tick
    // so they don't compete with the initial canvas render.
    setTimeout(function() {
        connectLiqMarkWs(pair);
        connectOrderBookWs(pair);
    }, 0);
}

function renderLiqHeatmap(data, vpData) {
    _liqCachedHeatData = data;  // cache for noise-filter re-renders
    var canvas = document.getElementById('liq-canvas');
    var noData = document.getElementById('liq-no-data');
    var sub    = document.getElementById('liq-chart-sub');
    if (!data.has_data || !data.buckets || !data.buckets.length) {
        canvas.style.display = 'none'; noData.style.display = '';
        sub.textContent = '0 events in last ' + data.window_hours + 'h \u2014 accumulating...';
        return;
    }
    canvas.style.display = 'block'; noData.style.display = 'none';
    var longM  = (data.total_long_24h  / 1e6).toFixed(2);
    var shortM = (data.total_short_24h / 1e6).toFixed(2);
    var isMobile = window.innerWidth <= 768;
    sub.textContent = isMobile
        ? data.total_events_24h + ' events · L:$' + longM + 'M S:$' + shortM + 'M'
        : data.total_events_24h + ' events | Long liqs: $' + longM + 'M | Short liqs: $' + shortM + 'M | ' + data.window_hours + 'h window';
    // ── Responsive sizing ──────────────────────────────────────────
    var isMob  = window.innerWidth <= 480;
    var isTab  = window.innerWidth <= 768;
    var W      = canvas.offsetWidth || 900;
    var H      = isMob ? 320 : isTab ? 420 : 560;
    var dpr    = Math.min(window.devicePixelRatio || 1, 3); // cap at 3× for perf

    // Adaptive layout constants
    var padL   = isMob ? 65  : isTab ? 80  : 100;
    var padR   = isMob ? 90  : isTab ? 115 : 150;
    var padT   = isMob ? 18  : 28;
    var padB   = isMob ? 28  : 32;
    var labelCount = isMob ? 5 : isTab ? 10 : 14;
    var fontSize   = isMob ? 9  : 11;
    var footerSize = isMob ? 9  : 11;

    // Price formatter — clean, no scientific notation
    function fmtPrice(p) {
        if (p >= 10000) return Math.round(p).toString();
        if (p >= 1000)  return p.toFixed(1);
        if (p >= 100)   return p.toFixed(2);
        if (p >= 10)    return p.toFixed(3);
        if (p >= 1)     return p.toFixed(4);
        if (p >= 0.1)   return p.toFixed(5);
        return p.toPrecision(4);
    }

    // ── DPR-aware offscreen canvas ─────────────────────────────────
    var offscreen = document.createElement('canvas');
    offscreen.width  = Math.round(W * dpr);
    offscreen.height = Math.round(H * dpr);
    var ctx = offscreen.getContext('2d');
    ctx.scale(dpr, dpr);           // all drawing in logical px from here
    ctx.clearRect(0, 0, W, H);

    var buckets = data.buckets, n = buckets.length;
    if (n === 0) return;
    var vpBuckets = (vpData && vpData.has_data) ? vpData.buckets : [];
    // Only use positive bucket prices; clamp around mark price to prevent empty Y-axis
    var bPrices = buckets.map(function(b){return b.price}).filter(function(p){return p > 0});
    if (vpBuckets.length) vpBuckets.forEach(function(b){ if (b.price > 0) bPrices.push(b.price); });
    if (_liqMarkPrice && _liqMarkPrice > 0) bPrices.push(_liqMarkPrice);
    if (!bPrices.length) bPrices = [1, 2];
    var rawMin = Math.min.apply(null, bPrices);
    var rawMax = Math.max.apply(null, bPrices);
    var minP, maxP;
    if (_liqMarkPrice && _liqMarkPrice > 0) {
        // Y-axis is driven purely by zoom — not clamped to data extent.
        // This guarantees the axis always moves when the user zooms.
        minP = _liqMarkPrice * (1 - _liqZoomRange);
        maxP = _liqMarkPrice * (1 + _liqZoomRange);
    } else {
        // No mark price yet: fall back to data extent with a small pad
        var _pad0 = (rawMax - rawMin) * 0.05 || rawMax * 0.02;
        minP = rawMin - _pad0;
        maxP = rawMax + _pad0;
    }
    var priceRange = maxP - minP || 1;
    // Only draw buckets whose price falls within the visible range
    var visBuckets = buckets.filter(function(b) {
        return b.price >= minP && b.price <= maxP &&
               (b.long_liq_usd + b.short_liq_usd) >= _liqNoiseThreshold;
    });
    var maxLong  = Math.max.apply(null, visBuckets.map(function(b){return b.long_liq_usd}).concat([1]));
    var maxShort = Math.max.apply(null, visBuckets.map(function(b){return b.short_liq_usd}).concat([1]));
    var maxUsd   = Math.max(maxLong, maxShort);
    var chartW = W - padL - padR, chartH = H - padT - padB;
    var centerX = padL + chartW / 2, halfW = chartW / 2 - 4;
    var vpX = W - padR + 6, vpW = padR - 12;
    _liqLastLayout = { minP: minP, maxP: maxP, padL: padL, padR: padR, padT: padT, padB: padB, chartH: chartH, chartW: chartW, buckets: visBuckets };
    function priceToY(p) { return padT + chartH - ((p - minP) / priceRange) * chartH; }

    // VA background band
    if (vpData && vpData.has_data && vpData.vah && vpData.val) {
        var yVah = priceToY(vpData.vah), yVal = priceToY(vpData.val);
        ctx.fillStyle = 'rgba(80,180,255,0.06)';
        ctx.fillRect(padL, Math.min(yVah, yVal), chartW + padR - 8, Math.abs(yVal - yVah));
    }

    // Center divider
    ctx.strokeStyle = 'rgba(255,255,255,0.08)'; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(centerX, padT); ctx.lineTo(centerX, padT + chartH); ctx.stroke();

    // Liquidation bars
    var rowH = Math.max(2, chartH / n - 0.5);
    visBuckets.forEach(function(b) {
        var yCenter = priceToY(b.price);
        var longW2  = (b.long_liq_usd  / maxUsd) * halfW;
        var shortW2 = (b.short_liq_usd / maxUsd) * halfW;
        var intensity = Math.min(1, (b.long_liq_usd + b.short_liq_usd) / maxUsd);
        var alpha = 0.3 + intensity * 0.7;
        if (longW2  > 0.5) { ctx.fillStyle = 'rgba(255,77,106,' + alpha + ')';  ctx.fillRect(centerX - longW2,  yCenter - rowH/2, longW2,  rowH); }
        if (shortW2 > 0.5) { ctx.fillStyle = 'rgba(0,214,143,'  + alpha + ')';  ctx.fillRect(centerX,           yCenter - rowH/2, shortW2, rowH); }
    });

    // Helper: draw a right-side price badge (background box + label)
    function drawRightBadge(label, price, lineColor, bgAlpha) {
        var y = priceToY(price);
        var text = label + ' ' + fmtPrice(price);
        ctx.font = 'bold ' + fontSize + 'px monospace';
        var tw = ctx.measureText(text).width;
        var bx = vpX, bw = tw + 10, bh = 15;
        ctx.fillStyle = 'rgba(10,15,25,' + bgAlpha + ')';
        ctx.fillRect(bx, y - 9, bw, bh);
        ctx.strokeStyle = lineColor;
        ctx.lineWidth = 0.8;
        ctx.strokeRect(bx, y - 9, bw, bh);
        ctx.fillStyle = lineColor;
        ctx.textAlign = 'left';
        ctx.fillText(text, bx + 5, y + 3);
    }

    // VPVR bars
    if (vpBuckets.length) {
        var maxRatio = Math.max.apply(null, vpBuckets.map(function(b){return b.ratio}).concat([0.01]));
        vpBuckets.forEach(function(b) {
            var yCenter = priceToY(b.price);
            var barW    = (b.ratio / maxRatio) * vpW;
            var isPoc   = Math.abs(b.price - vpData.poc) < 1e-9;
            var alpha   = 0.25 + b.ratio * 0.65;
            ctx.fillStyle = isPoc ? 'rgba(160,120,255,0.9)' : 'rgba(100,160,255,' + alpha + ')';
            ctx.fillRect(vpX, yCenter - 3, barW, 6);
        });
        // POC line + badge
        if (vpData.poc) {
            var yPoc = priceToY(vpData.poc);
            ctx.strokeStyle = 'rgba(160,120,255,0.85)'; ctx.lineWidth = 1.5; ctx.setLineDash([6, 4]);
            ctx.beginPath(); ctx.moveTo(padL, yPoc); ctx.lineTo(W - 6, yPoc); ctx.stroke(); ctx.setLineDash([]);
            drawRightBadge('POC', vpData.poc, 'rgba(160,120,255,0.95)', 0.8);
        }
        // VAH / VAL lines + badges
        [['VAH', vpData.vah, 'rgba(80,180,255,0.9)'], ['VAL', vpData.val, 'rgba(80,180,255,0.9)']].forEach(function(arr) {
            var lbl = arr[0], price = arr[1], col = arr[2];
            if (!price) return;
            var y = priceToY(price);
            ctx.strokeStyle = col.replace('0.9)', '0.65)'); ctx.lineWidth = 1; ctx.setLineDash([3, 5]);
            ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(W - 6, y); ctx.stroke(); ctx.setLineDash([]);
            drawRightBadge(lbl, price, col, 0.75);
        });
    }

    // Left axis separator line
    ctx.strokeStyle = 'rgba(255,255,255,0.15)'; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(padL, padT); ctx.lineTo(padL, padT + chartH); ctx.stroke();

    // Price axis labels — adaptive count, no overlap
    ctx.font = 'bold ' + fontSize + 'px monospace'; ctx.textAlign = 'right';
    var minLabelGap = fontSize * 3.2;  // wider gap prevents overlap
    var lastY = -999;
    for (var i = 0; i <= labelCount; i++) {
        var ratio = i / labelCount;
        var price = minP + ratio * priceRange;
        var y = padT + chartH - ratio * chartH;
        if (lastY - y < minLabelGap && i > 0) continue;
        lastY = y;
        // Tick mark
        ctx.strokeStyle = 'rgba(255,255,255,0.2)'; ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(padL - 4, y); ctx.lineTo(padL, y); ctx.stroke();
        // Grid line across chart
        ctx.strokeStyle = 'rgba(255,255,255,0.06)'; ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(padL + chartW, y); ctx.stroke();
        // Price label
        ctx.fillStyle = 'rgba(210,220,235,0.92)';
        ctx.fillText(fmtPrice(price), padL - 8, y + 4);
    }

    // Footer axis labels — left-aligned left label, right-aligned right label, never overlap
    var footerY = padT + chartH + (isMob ? 17 : 20);
    ctx.font = footerSize + 'px sans-serif';
    var longLbl  = isMob || halfW < 140 ? '◀ Longs'  : '◀ Long Liquidations';
    var shortLbl = isMob || halfW < 140 ? 'Shorts ▶' : 'Short Liquidations ▶';
    var vpLbl    = isMob || vpW < 60    ? 'VP'       : 'VPVR ▶';
    ctx.textAlign = 'left';
    ctx.fillStyle = 'rgba(255,77,106,0.8)';  ctx.fillText(longLbl,  padL + 4,             footerY);
    ctx.textAlign = 'right';
    ctx.fillStyle = 'rgba(0,214,143,0.8)';   ctx.fillText(shortLbl, centerX + halfW - 2,  footerY);
    ctx.textAlign = 'center';
    ctx.fillStyle = 'rgba(100,160,255,0.7)'; ctx.fillText(vpLbl,    vpX + vpW / 2,        footerY);

    // ── Flush to main canvas at full DPR resolution ────────────────
    canvas.width  = Math.round(W * dpr);
    canvas.height = Math.round(H * dpr);
    canvas.style.width  = W + 'px';
    canvas.style.height = H + 'px';
    var priceC = document.getElementById('liq-price-canvas');
    if (priceC) { priceC.style.width = W + 'px'; priceC.style.height = H + 'px'; }
    canvas.getContext('2d').drawImage(offscreen, 0, 0);
    renderLiqTable(data, vpData);
    drawMarkPriceLine();
    initLiqCrosshair();
}

async function loadLiqVelocity(pair) {
    try {
        var res = await fetch('/api/liq/velocity/' + pair + '?window=10', { headers: authHeaders() });
        if (!res.ok) return;
        var d = await res.json();
        renderVelocitySparkline(d);
    } catch(e) {}
}

function renderVelocitySparkline(d) {
    var rateEl = document.getElementById('liq-vel-rate');
    var spikeEl = document.getElementById('liq-vel-spike');
    var labelEl = document.getElementById('liq-vel-label');
    var canvas = document.getElementById('liq-vel-canvas');
    if (!rateEl || !canvas) return;
    var counts = (d.by_minute || []).map(function(m){return m.count});
    var cur = d.current_rate || 0, avg = d.avg_rate || 0, spike = d.spike || false;
    rateEl.textContent = cur;
    rateEl.style.color = spike ? 'var(--red)' : cur > avg ? 'var(--gold)' : 'var(--text)';
    if (labelEl) labelEl.textContent = 'liqs/min  (avg ' + avg.toFixed(1) + ')';
    if (spikeEl) spikeEl.style.display = spike ? '' : 'none';
    var W = canvas.offsetWidth || 220, H = 36;
    canvas.width = W; canvas.height = H;
    var ctx = canvas.getContext('2d'); ctx.clearRect(0, 0, W, H);
    if (!counts.length) return;
    var maxC = Math.max.apply(null, counts.concat([1]));
    var barW = W / counts.length - 1;
    counts.forEach(function(c, i) {
        var bh = Math.max(2, (c / maxC) * (H - 4));
        var isLast = i === counts.length - 1;
        ctx.fillStyle = isLast ? (spike ? 'rgba(255,77,106,0.85)' : 'rgba(240,185,11,0.8)') : 'rgba(100,160,255,0.4)';
        ctx.fillRect(i * (barW + 1), H - bh, barW, bh);
    });
    var avgY = H - (avg / maxC) * (H - 4);
    ctx.strokeStyle = 'rgba(255,255,255,0.25)'; ctx.setLineDash([3, 3]);
    ctx.beginPath(); ctx.moveTo(0, avgY); ctx.lineTo(W, avgY); ctx.stroke(); ctx.setLineDash([]);
}

function updatePocBiasCard() {
    var el = document.getElementById('liq-bias-content');
    if (!el) return;
    if (!_liqCachedVp || !_liqCachedVp.has_data || !_liqMarkPrice) { el.textContent = 'Waiting for VP + price data\u2026'; return; }
    var poc = _liqCachedVp.poc, vah = _liqCachedVp.vah, val = _liqCachedVp.val;
    if (!poc) { el.textContent = 'No POC data'; return; }
    var distPct = ((_liqMarkPrice - poc) / poc * 100).toFixed(2);
    var abovePoc = _liqMarkPrice > poc;
    var inVA = val && vah && _liqMarkPrice >= val && _liqMarkPrice <= vah;
    var aboveVah = vah && _liqMarkPrice > vah;
    var belowVal = val && _liqMarkPrice < val;
    var zone, zoneColor, verdict, verdictColor;
    if (aboveVah) { zone = 'ABOVE VALUE AREA'; zoneColor = 'var(--red)'; verdict = '\u26A0 Overextended \u2014 POC gravitational pull bearish'; verdictColor = 'var(--red)'; }
    else if (belowVal) { zone = 'BELOW VALUE AREA'; zoneColor = 'var(--green)'; verdict = '\u26A0 Oversold zone \u2014 POC gravitational pull bullish'; verdictColor = 'var(--green)'; }
    else if (inVA && abovePoc) { zone = 'INSIDE VA \u2014 ABOVE POC'; zoneColor = 'var(--gold)'; verdict = '\u2195 Ranging \u2014 mild bearish pull to POC'; verdictColor = 'var(--gold)'; }
    else if (inVA && !abovePoc) { zone = 'INSIDE VA \u2014 BELOW POC'; zoneColor = 'var(--gold)'; verdict = '\u2195 Ranging \u2014 mild bullish pull to POC'; verdictColor = 'var(--gold)'; }
    else { zone = '\u2014'; zoneColor = 'var(--text-dim)'; verdict = '\u2014'; verdictColor = 'var(--text-dim)'; }
    el.innerHTML = '<div style="display:flex;gap:16px;flex-wrap:wrap;align-items:center"><span>POC: <strong style="color:rgba(160,120,255,0.9)">' + poc.toPrecision(6) + '</strong></span><span>Dist: <strong style="color:' + (abovePoc ? 'var(--red)' : 'var(--green)') + '">' + (abovePoc ? '+' : '') + distPct + '%</strong></span><span style="color:' + zoneColor + ';font-weight:600">' + zone + '</span></div><div style="margin-top:5px;color:' + verdictColor + '">' + verdict + '</div>';
}

var _liqDepthWs = null;
var _liqTopBids = [];
var _liqTopAsks = [];

function connectOrderBookWs(symbol) {
    if (_liqDepthWs) { try { _liqDepthWs.close(); } catch(e){} _liqDepthWs = null; }
    _liqTopBids = []; _liqTopAsks = [];
    var url = 'wss://fstream.binance.com/ws/' + symbol.toLowerCase() + '@depth20@500ms';
    var ws;
    try { ws = new WebSocket(url); } catch(e) { return; }
    ws.onopen = function() { _liqDepthWs = ws; };
    ws.onmessage = function(e) {
        try {
            var d = JSON.parse(e.data);
            var bids = (d.b || []).map(function(x){return {price:parseFloat(x[0]),qty:parseFloat(x[1])}});
            var asks = (d.a || []).map(function(x){return {price:parseFloat(x[0]),qty:parseFloat(x[1])}});
            _liqTopBids = bids.slice().sort(function(a,b){return b.qty-a.qty}).slice(0,5);
            _liqTopAsks = asks.slice().sort(function(a,b){return b.qty-a.qty}).slice(0,5);
            drawMarkPriceLine();
        } catch(ex) {}
    };
    ws.onerror = function() {};
    ws.onclose = function() {
        _liqDepthWs = null;
        setTimeout(function() {
            if (document.getElementById('page-heatmap').classList.contains('active') && _liqCurrentPair === symbol) connectOrderBookWs(symbol);
        }, 4000);
    };
}

var _liqDirection = 'auto';

function setLiqDirection(d) {
    _liqDirection = d;
    document.querySelectorAll('.liq-dir-btn').forEach(function(b) { b.classList.toggle('active', b.dataset.d === d); });
    loadLiqSuggest();
}

async function loadLiqSuggest(pair) {
    pair = pair || _liqCurrentPair;
    var card = document.getElementById('liq-suggest-card');
    if (!card || !pair) return;
    card.innerHTML = '<span style="color:var(--text-dim)">\u23F3 Computing\u2026</span>';
    try {
        var res = await fetch('/api/liq/suggest/' + pair + '?direction=' + _liqDirection, { headers: authHeaders() });
        if (!res.ok) { card.innerHTML = '<span style="color:var(--text-dim)">Error</span>'; return; }
        var d = await res.json();
        if (!d.has_data) { card.innerHTML = '<span style="color:var(--text-dim)">' + (d.error || 'No data') + '</span>'; return; }
        renderSuggestCard(d);
    } catch(e) { card.innerHTML = '<span style="color:var(--text-dim)">Failed</span>'; }
}

function renderSuggestCard(d) {
    var card = document.getElementById('liq-suggest-card');
    if (!card) return;
    var isLong = d.direction === 'LONG';
    var dirColor = isLong ? 'var(--green)' : 'var(--red)';
    var dirLabel = isLong ? '\u25B2 LONG' : '\u25BC SHORT';
    var rrColor = d.risk_reward >= 2 ? 'var(--green)' : d.risk_reward >= 1 ? 'var(--gold)' : 'var(--red)';
    var pocDist = d.poc_dist_pct != null ? (d.poc_dist_pct > 0 ? '+' : '') + d.poc_dist_pct + '%' : '\u2014';
    var vaLabel = d.in_value_area ? '<span style="color:var(--gold)">Inside VA</span>' : '<span style="color:var(--text-dim)">Outside VA</span>';
    var fundColor = d.funding_bias === 'LONG_HEAVY' ? 'var(--red)' : d.funding_bias === 'SHORT_HEAVY' ? 'var(--green)' : 'var(--gold)';
    var tpRows = (d.tp_levels || []).map(function(tp, i) {
        return '<div style="display:flex;justify-content:space-between;padding:6px 10px;background:rgba(0,214,143,0.06);border-radius:6px;margin-bottom:4px">' +
            '<span style="color:var(--green);font-weight:600">TP' + (i+1) + '</span>' +
            '<span style="font-family:monospace;font-weight:700">' + tp.price.toPrecision(6) + '</span>' +
            '<span style="color:var(--green)">+' + tp.pct + '%</span>' +
            (tp.usd > 0 ? '<span style="color:var(--text-dim);font-size:11px">$' + (tp.usd/1000).toFixed(1) + 'K wall</span>' : '') + '</div>';
    }).join('');
    card.innerHTML =
        '<div style="display:flex;gap:16px;flex-wrap:wrap;align-items:center;margin-bottom:14px">' +
            '<span style="font-size:18px;font-weight:800;color:' + dirColor + '">' + dirLabel + '</span>' +
            '<span style="color:var(--text-dim)">Mark: <strong style="color:var(--gold)">' + d.mark_price + '</strong></span>' +
            '<span style="color:var(--text-dim)">R:R <strong style="color:' + rrColor + '">' + d.risk_reward + ':1</strong></span>' +
            '<span style="color:var(--text-dim)">POC dist: <strong>' + pocDist + '</strong></span>' +
            vaLabel +
            '<span style="color:var(--text-dim)">Funding: <strong style="color:' + fundColor + '">' + (d.funding_rate > 0 ? '+' : '') + d.funding_rate + '%</strong> (' + d.funding_bias + ')</span>' +
        '</div>' +
        '<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">' +
            '<div><div style="font-size:11px;color:var(--text-dim);margin-bottom:6px;text-transform:uppercase">Take Profit Levels</div>' +
                (tpRows || '<div style="color:var(--text-dim);font-size:12px">No clusters above</div>') +
            '</div>' +
            '<div><div style="font-size:11px;color:var(--text-dim);margin-bottom:6px;text-transform:uppercase">Stop Loss</div>' +
                '<div style="display:flex;justify-content:space-between;padding:6px 10px;background:rgba(255,77,106,0.08);border-radius:6px">' +
                    '<span style="color:var(--red);font-weight:600">SL</span>' +
                    '<span style="font-family:monospace;font-weight:700">' + (d.sl_price.toPrecision ? d.sl_price.toPrecision(6) : d.sl_price) + '</span>' +
                    '<span style="color:var(--red)">' + d.sl_pct + '%</span></div>' +
                '<div style="margin-top:8px;font-size:11px;color:var(--text-dim)">VP: POC <strong style="color:rgba(160,120,255,0.9)">' + (d.poc && d.poc.toPrecision ? d.poc.toPrecision(5) : '\u2014') + '</strong> | VAH <strong style="color:rgba(80,180,255,0.8)">' + (d.vah && d.vah.toPrecision ? d.vah.toPrecision(5) : '\u2014') + '</strong> | VAL <strong style="color:rgba(80,180,255,0.8)">' + (d.val && d.val.toPrecision ? d.val.toPrecision(5) : '\u2014') + '</strong></div>' +
            '</div></div>';
}

function renderLiqTable(data, vpData) {
    var container = document.getElementById('liq-table-container');
    if (!container || !data.has_data) return;
    var topBuckets = data.buckets.slice().sort(function(a,b){return b.total_usd - a.total_usd}).slice(0, 10);
    var html = '<div style="background:var(--surface);border:1px solid var(--border);border-radius:10px;overflow:hidden">' +
        '<div style="padding:13px 18px;border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between"><span style="font-weight:700;font-size:13px;letter-spacing:.02em">Top Liquidation Clusters</span><span style="font-size:11px;color:var(--text-dim)">sorted by total USD</span></div>' +
        '<div class="table-scroll-wrap"><table style="width:100%;border-collapse:collapse;font-size:12px"><thead><tr style="color:var(--text-dim);border-bottom:1px solid var(--border);font-size:11px;font-weight:700;letter-spacing:.06em;text-transform:uppercase">' +
        '<th class="liq-tbl-rank" style="padding:9px 0 9px 12px">#</th><th style="padding:9px 16px;text-align:left">Price Level</th><th style="padding:9px 16px;text-align:right;color:var(--red)">Long Liqs</th><th style="padding:9px 16px;text-align:right;color:var(--green)">Short Liqs</th><th style="padding:9px 16px;text-align:right">Total</th><th style="padding:9px 16px;text-align:right">Events</th><th style="padding:9px 16px;text-align:right">Dominant</th><th style="padding:9px 16px;text-align:right">VP</th></tr></thead><tbody>';
    topBuckets.forEach(function(b, i) {
        var dom = b.long_liq_usd > b.short_liq_usd ? 'LONG' : 'SHORT';
        var domColor = dom === 'LONG' ? 'var(--red)' : 'var(--green)';
        var _tblFmt = function(v) {
            if (v >= 1e6) return (v / 1e6).toFixed(2) + 'M';
            return (v / 1e3).toFixed(1) + 'K';
        };
        var totalM  = _tblFmt(b.total_usd);
        var longM   = _tblFmt(b.long_liq_usd);
        var shortM  = _tblFmt(b.short_liq_usd);
        var vpNote = '';
        if (vpData && vpData.has_data) {
            var pct = function(p){return Math.abs((b.price - p) / p * 100)};
            if (pct(vpData.poc) < 0.4) vpNote = '<span style="color:rgba(160,120,255,1);font-weight:700;font-size:11px">\u2605 POC</span>';
            else if (pct(vpData.vah) < 0.4) vpNote = '<span style="color:rgba(80,180,255,0.9);font-size:11px">VAH</span>';
            else if (pct(vpData.val) < 0.4) vpNote = '<span style="color:rgba(80,180,255,0.9);font-size:11px">VAL</span>';
        }
        var domBg = dom === 'LONG' ? 'rgba(255,77,106,0.12)' : 'rgba(0,214,143,0.12)';
        html += '<tr class="liq-cluster-row" style="border-bottom:1px solid rgba(255,255,255,0.04)">' +
            '<td class="liq-tbl-rank" style="padding:9px 0 9px 12px;color:var(--text-dim);font-size:11px">' + (i+1) + '</td>' +
            '<td style="padding:9px 16px;font-family:monospace;font-weight:700;font-size:13px">' + b.price.toPrecision(6) + '</td>' +
            '<td style="padding:9px 16px;text-align:right;color:var(--red);font-weight:600">$' + longM + '</td>' +
            '<td style="padding:9px 16px;text-align:right;color:var(--green);font-weight:600">$' + shortM + '</td>' +
            '<td style="padding:9px 16px;text-align:right;font-weight:700">$' + totalM + '</td>' +
            '<td style="padding:9px 16px;text-align:right;color:var(--text-dim)">' + b.count + '</td>' +
            '<td style="padding:9px 16px;text-align:right"><span style="padding:2px 10px;border-radius:20px;background:' + domBg + ';color:' + domColor + ';font-weight:700;font-size:11px">' + dom + '</span></td>' +
            '<td style="padding:9px 16px;text-align:right">' + (vpNote || '<span style="color:var(--text-dim)">\u2014</span>') + '</td></tr>';
    });
    html += '</tbody></table></div></div>';
    if (vpData && vpData.has_data) {
        html += '<div style="margin-top:10px;padding:12px 18px;background:var(--surface);border:1px solid var(--border);border-top:2px solid rgba(160,120,255,0.5);border-radius:10px;display:flex;gap:0;flex-wrap:wrap;align-items:stretch">' +
            '<div class="liq-ctx-pill" style="gap:3px"><span class="liq-ctx-pill-label">\uD83D\uDCCA Volume Profile</span><span class="liq-ctx-pill-val" style="font-size:11px;color:var(--text-dim)">' + vpData.interval + ' \u00B7 ' + (vpData.total_volume ? vpData.total_volume.toLocaleString() : '\u2014') + ' vol</span></div>' +
            '<div class="liq-ctx-pill" style="gap:3px"><span class="liq-ctx-pill-label">\u2605 POC</span><span class="liq-ctx-pill-val" style="color:rgba(160,120,255,1);font-family:monospace">' + (vpData.poc ? vpData.poc.toPrecision(6) : '\u2014') + '</span></div>' +
            '<div class="liq-ctx-pill" style="gap:3px"><span class="liq-ctx-pill-label">VAH</span><span class="liq-ctx-pill-val" style="color:rgba(80,180,255,0.9);font-family:monospace">' + (vpData.vah ? vpData.vah.toPrecision(6) : '\u2014') + '</span></div>' +
            '<div class="liq-ctx-pill" style="gap:3px;border-right:none"><span class="liq-ctx-pill-label">VAL</span><span class="liq-ctx-pill-val" style="color:rgba(80,180,255,0.9);font-family:monospace">' + (vpData.val ? vpData.val.toPrecision(6) : '\u2014') + '</span></div></div>';
    }
    container.innerHTML = html;
}

// ═══════════════════════════════════════════════════════════════
//  LIQUIDATION WATCHLIST + ALERT SYSTEM
// ═══════════════════════════════════════════════════════════════

var _liqAlertSse       = null;
var _liqWatchlist      = [];   // [{symbol, min_usd}]
var _liqAlertHistory   = [];   // last 20 notifications shown

// ── USD threshold presets ────────────────────────────────────────
var _LIQ_ALERT_USD_STEPS  = [10e3, 50e3, 100e3, 250e3, 500e3, 1e6, 5e6];
var _LIQ_ALERT_USD_LABELS = ['$10K','$50K','$100K','$250K','$500K','$1M','$5M'];

function _fmtUsd(v) {
    if (v >= 1e6) return '$' + (v/1e6).toFixed(2) + 'M';
    if (v >= 1e3) return '$' + Math.round(v/1e3) + 'K';
    return '$' + v;
}

// ── Toast notification ───────────────────────────────────────────
function _showLiqToast(ev) {
    var isLong  = ev.type === 'LONG_LIQ';
    var color   = isLong ? '#ff4d6a' : '#00d68f';
    var icon    = isLong ? '🔴' : '🟢';
    var typeStr = isLong ? 'LONG LIQ' : 'SHORT LIQ';
    var sym     = ev.symbol.replace('USDT','');
    var usdStr  = _fmtUsd(ev.usd);
    var priceStr= _liqFmtPrice(ev.price);

    // Browser Notification (if permitted)
    if (window.Notification && Notification.permission === 'granted') {
        new Notification(icon + ' ' + sym + ' — ' + typeStr, {
            body: usdStr + ' liquidated @ ' + priceStr,
            icon: '/static/img/logo.png',
            tag:  'liq-' + ev.symbol + '-' + Math.round(ev.ts),
        });
    }

    // In-page toast
    var container = document.getElementById('liq-toast-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'liq-toast-container';
        container.style.cssText = 'position:fixed;bottom:20px;right:20px;z-index:9999;display:flex;flex-direction:column-reverse;gap:8px;pointer-events:none';
        document.body.appendChild(container);
    }
    var toast = document.createElement('div');
    toast.style.cssText = 'background:rgba(10,15,25,0.97);border:1px solid ' + color + ';border-left:4px solid ' + color + ';' +
        'border-radius:10px;padding:10px 16px;min-width:240px;max-width:320px;pointer-events:auto;' +
        'box-shadow:0 4px 20px rgba(0,0,0,.6);animation:liqToastIn .25s ease;cursor:pointer';
    toast.innerHTML = '<div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">' +
        '<span style="font-size:15px">' + icon + '</span>' +
        '<strong style="color:' + color + ';font-size:12px;letter-spacing:.06em">' + typeStr + '</strong>' +
        '<strong style="font-size:13px;margin-left:auto">' + sym + '</strong>' +
        '</div>' +
        '<div style="display:flex;justify-content:space-between;font-size:12px;color:rgba(200,210,225,.9)">' +
        '<span>' + usdStr + '</span><span style="color:rgba(240,185,11,.9);font-family:monospace">@ ' + priceStr + '</span>' +
        '</div>';
    toast.onclick = function() { toast.remove(); };
    container.appendChild(toast);
    _liqAlertHistory.unshift({ev: ev, ts: Date.now()});
    if (_liqAlertHistory.length > 20) _liqAlertHistory.pop();
    setTimeout(function() { toast.style.opacity = '0'; toast.style.transition = 'opacity .4s'; setTimeout(function(){ toast.remove(); }, 450); }, 6000);

    // Update history panel if open
    _renderAlertHistory();
}

// Inject toast animation once
(function() {
    if (!document.getElementById('liq-toast-style')) {
        var s = document.createElement('style');
        s.id = 'liq-toast-style';
        s.textContent = '@keyframes liqToastIn{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:none}}';
        document.head.appendChild(s);
    }
})();

// ── SSE connection ────────────────────────────────────────────────
function _startLiqAlertSse() {
    if (_liqAlertSse) { _liqAlertSse.close(); _liqAlertSse = null; }
    var token = (typeof getAuthToken === 'function') ? getAuthToken() : localStorage.getItem('auth_token');
    if (!token || !_liqWatchlist.length) return;
    var url = '/api/liq/alerts/stream';
    var sse;
    try { sse = new EventSource(url + '?token=' + encodeURIComponent(token)); } catch(e) { return; }
    sse.onmessage = function(e) {
        try {
            var ev = JSON.parse(e.data);
            if (ev.type === 'connected') return;
            _showLiqToast(ev);
        } catch(_) {}
    };
    sse.onerror = function() {
        sse.close();
        _liqAlertSse = null;
        setTimeout(_startLiqAlertSse, 10000);  // reconnect after 10s
    };
    _liqAlertSse = sse;
}

// ── Watchlist API helpers ─────────────────────────────────────────
async function _loadLiqWatchlist() {
    try {
        var r = await fetch('/api/liq/watchlist', { headers: authHeaders() });
        if (!r.ok) return;
        var d = await r.json();
        _liqWatchlist = d.watchlist || [];
        _renderWatchlistPanel();
        if (_liqWatchlist.length) _startLiqAlertSse();
    } catch(e) {}
}

async function liqWatchlistAdd(sym, minUsd) {
    sym = (sym || document.getElementById('liq-wl-input').value || '').toUpperCase().replace('USDT','') + 'USDT';
    minUsd = minUsd || parseInt(document.getElementById('liq-wl-threshold').value) || 100000;
    if (!sym || sym === 'USDT') return;
    try {
        var r = await fetch('/api/liq/watchlist/' + sym + '?min_usd=' + minUsd, { method: 'POST', headers: authHeaders() });
        var d = await r.json();
        if (d.error) { alert(d.error); return; }
        await _loadLiqWatchlist();
    } catch(e) {}
}

async function liqWatchlistRemove(sym) {
    try {
        await fetch('/api/liq/watchlist/' + sym, { method: 'DELETE', headers: authHeaders() });
        await _loadLiqWatchlist();
    } catch(e) {}
}

function liqRequestNotifPermission() {
    if (window.Notification && Notification.permission === 'default') {
        Notification.requestPermission().then(function(p) {
            var btn = document.getElementById('liq-notif-perm-btn');
            if (btn) btn.textContent = p === 'granted' ? '🔔 Enabled' : '🔕 Blocked';
        });
    }
}

// ── Render panels ─────────────────────────────────────────────────
function _renderWatchlistPanel() {
    var el = document.getElementById('liq-watchlist-list');
    if (!el) return;
    if (!_liqWatchlist.length) {
        el.innerHTML = '<div style="color:var(--text-dim);font-size:12px;padding:8px 0">No symbols watched yet.</div>';
        return;
    }
    el.innerHTML = _liqWatchlist.map(function(w) {
        return '<div style="display:flex;align-items:center;gap:8px;padding:6px 0;border-bottom:1px solid rgba(255,255,255,0.06)">' +
            '<span style="font-weight:700;font-size:13px;flex:1">' + w.symbol + '</span>' +
            '<span style="font-size:11px;color:var(--aw-gold,#d4a84b)">≥ ' + _fmtUsd(w.min_usd) + '</span>' +
            '<button onclick="liqWatchlistRemove(\'' + w.symbol + '\')" style="background:rgba(255,77,106,0.15);border:1px solid rgba(255,77,106,0.3);color:var(--red);border-radius:5px;padding:2px 8px;font-size:11px;cursor:pointer">✕</button>' +
            '</div>';
    }).join('');
    // SSE status dot
    var dot = document.getElementById('liq-wl-sse-dot');
    if (dot) dot.style.background = _liqAlertSse ? '#00d68f' : '#ff4d6a';
}

function _renderAlertHistory() {
    var el = document.getElementById('liq-alert-history');
    if (!el) return;
    if (!_liqAlertHistory.length) { el.innerHTML = '<div style="color:var(--text-dim);font-size:11px">No alerts yet.</div>'; return; }
    el.innerHTML = _liqAlertHistory.slice(0,10).map(function(h) {
        var ev = h.ev, isLong = ev.type === 'LONG_LIQ';
        var color = isLong ? 'var(--red)' : 'var(--green)';
        var ago = Math.round((Date.now() - h.ts) / 1000);
        var agoStr = ago < 60 ? ago + 's' : Math.round(ago/60) + 'm';
        return '<div style="display:flex;align-items:center;gap:8px;padding:5px 0;border-bottom:1px solid rgba(255,255,255,0.05);font-size:11px">' +
            '<span style="color:' + color + ';font-weight:700;min-width:72px">' + ev.symbol.replace('USDT','') + '</span>' +
            '<span style="color:' + color + '">' + (isLong ? '↓LONG' : '↑SHORT') + '</span>' +
            '<span style="font-family:monospace;flex:1">' + _fmtUsd(ev.usd) + '</span>' +
            '<span style="color:var(--text-dim)">' + agoStr + ' ago</span>' +
            '</div>';
    }).join('');
}

// ── Pair autocomplete ─────────────────────────────────────────────
async function initLiqPairSuggest() {
    try {
        var r = await fetch('/api/liq/pairs', { headers: authHeaders() });
        if (!r.ok) return;
        var d = await r.json();
        var pairs = d.pairs || [];
        // Populate datalist
        var dl = document.getElementById('liq-pairs-list');
        if (dl && pairs.length) {
            dl.innerHTML = pairs.map(function(p) {
                return '<option value="' + p + '">' + p.replace('USDT', '') + '</option>';
            }).join('');
        }
    } catch(e) {}
}

// ── Init (called from initLiqHeatmap) ────────────────────────────
function initLiqWatchlist() {
    _loadLiqWatchlist();
    // Request browser notification permission if not yet decided
    if (window.Notification && Notification.permission === 'default') {
        var btn = document.getElementById('liq-notif-perm-btn');
        if (btn) { btn.style.display = ''; }
    }
}
