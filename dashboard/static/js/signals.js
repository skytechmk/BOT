// ═══════════════════════════════════════════════════════════════
//  DATA LOADING — OVERVIEW
// ═══════════════════════════════════════════════════════════════
var _classMap = {};  // symbol → {tier, sector, is_hot, rank, rank_change}
var _ovTierFilter   = 'all';  // 'all' or tier key
var _ovSectorFilter = 'all';  // 'all' or sector key
var _ovHotFilter    = false;
var _ovZoneFilter   = 'all';  // 'all' | 'OS_L2' | 'OS_L1' | 'OB_L1' | 'OB_L2'
var _ovAllPairs     = [];
var _ovTier         = 'free';

async function _loadClassifications() {
    try {
        const res = await fetch('/api/market/classifications', { headers: authHeaders() });
        if (res.ok) {
            const d = await res.json();
            _classMap = d.classifications || {};
        }
    } catch(e) {}
}

async function loadMonitored() {
    try {
        const [pairsRes] = await Promise.all([
            fetch('/api/monitored', { headers: authHeaders() }),
            _loadClassifications(),
        ]);
        const data = await pairsRes.json();
        _ovAllPairs = data.pairs;
        _ovTier     = data.tier || 'free';
        renderSummary(data.pairs);
        renderFilterBar();
        renderPairs(_applyOvFilters(_ovAllPairs), _ovTier);
    } catch(e) {
        document.getElementById('pairs-grid').innerHTML = '<div class="no-data">Failed to load data</div>';
    }
}

function _symFromPair(pair) { return (pair || '').replace(/USDT$|BUSD$|USDC$/i, '').toUpperCase(); }

function _applyOvFilters(pairs) {
    return pairs.filter(function(p) {
        var sym = _symFromPair(p.pair);
        var info = _classMap[sym] || {};
        if (_ovHotFilter && !info.is_hot) return false;
        if (_ovTierFilter !== 'all' && (info.tier || 'high_risk') !== _ovTierFilter) return false;
        if (_ovSectorFilter !== 'all' && (info.sector || 'other') !== _ovSectorFilter) return false;
        if (_ovZoneFilter !== 'all' && p.zone !== _ovZoneFilter) return false;
        return true;
    });
}

var _OV_TIER_DEFS = [
    ['blue_chip', '🔵', 'Blue Chip', '#2196f3'],
    ['large_cap',  '🟢', 'Large Cap', '#4caf50'],
    ['mid_cap',    '🟡', 'Mid Cap',   '#f0b429'],
    ['small_cap',  '🟠', 'Small Cap', '#ff9800'],
    ['high_risk',  '🔴', 'High Risk', '#f44336'],
];
var _OV_SECTOR_DEFS = [
    ['layer1','⛓️','L1'], ['layer2','🔗','L2'], ['defi','🏦','DeFi'],
    ['gaming','🎮','Gaming'], ['ai','🤖','AI'], ['tradefi','📈','TradFi'],
    ['meme','🐸','Meme'], ['infra','⚙️','Infra'], ['other','🔷','Other'],
];

function renderFilterBar() {
    var el = document.getElementById('pairs-filter-bar');
    if (!el) return;
    var html = '<div style="display:flex;flex-wrap:wrap;gap:6px;align-items:center;padding:10px 0 4px">';
    // HOT toggle
    html += '<button onclick="ovSetHot(!_ovHotFilter)" id="ov-hot-btn" style="padding:5px 12px;border-radius:20px;font-size:11px;font-weight:700;cursor:pointer;border:2px solid ' + (_ovHotFilter ? '#f0b429' : 'var(--border)') + ';background:' + (_ovHotFilter ? '#f0b4291a' : 'var(--bg)') + ';color:' + (_ovHotFilter ? '#f0b429' : 'var(--text-dim)') + '">🔥 HOT</button>';
    // Tier pills
    html += '<span style="font-size:10px;color:var(--text-dim);margin:0 2px">Tier:</span>';
    html += '<button onclick="ovSetTier(\'all\')" style="padding:5px 12px;border-radius:20px;font-size:11px;font-weight:700;cursor:pointer;border:2px solid ' + (_ovTierFilter==='all' ? 'var(--gold)' : 'var(--border)') + ';background:' + (_ovTierFilter==='all' ? '#f0b4291a' : 'var(--bg)') + ';color:' + (_ovTierFilter==='all' ? 'var(--gold)' : 'var(--text-dim)') + '">All</button>';
    _OV_TIER_DEFS.forEach(function(td) {
        var k=td[0], col=td[3], active=_ovTierFilter===k;
        html += '<button onclick="ovSetTier(\'' + k + '\')" style="padding:5px 12px;border-radius:20px;font-size:11px;font-weight:700;cursor:pointer;border:2px solid '+(active?col:'var(--border)')+';background:'+(active?col+'22':'var(--bg)')+';color:'+(active?col:'var(--text-dim)')+'">'+td[1]+' '+td[2]+'</button>';
    });
    // Sector pills
    html += '<span style="font-size:10px;color:var(--text-dim);margin:0 2px 0 6px">Sector:</span>';
    html += '<button onclick="ovSetSector(\'all\')" style="padding:5px 12px;border-radius:20px;font-size:11px;font-weight:700;cursor:pointer;border:2px solid ' + (_ovSectorFilter==='all' ? 'var(--gold)' : 'var(--border)') + ';background:' + (_ovSectorFilter==='all' ? '#f0b4291a' : 'var(--bg)') + ';color:' + (_ovSectorFilter==='all' ? 'var(--gold)' : 'var(--text-dim)') + '">All</button>';
    _OV_SECTOR_DEFS.forEach(function(sd) {
        var k=sd[0], active=_ovSectorFilter===k;
        html += '<button onclick="ovSetSector(\'' + k + '\')" style="padding:5px 12px;border-radius:20px;font-size:11px;font-weight:700;cursor:pointer;border:2px solid '+(active?'var(--gold)':'var(--border)')+';background:'+(active?'#f0b4291a':'var(--bg)')+';color:'+(active?'var(--gold)':'var(--text-dim)')+'">'+sd[1]+' '+sd[2]+'</button>';
    });
    html += '</div>';
    el.innerHTML = html;
}

function ovSetTier(k)   { _ovTierFilter=k;   renderFilterBar(); renderPairs(_applyOvFilters(_ovAllPairs), _ovTier); }
function ovSetSector(k) { _ovSectorFilter=k; renderFilterBar(); renderPairs(_applyOvFilters(_ovAllPairs), _ovTier); }
function ovSetHot(v)    { _ovHotFilter=v;    renderFilterBar(); renderPairs(_applyOvFilters(_ovAllPairs), _ovTier); }

function renderSummary(pairs) {
    const counts = { OS_L2: 0, OS_L1: 0, OB_L1: 0, OB_L2: 0 };
    pairs.forEach(p => { if (counts[p.zone] !== undefined) counts[p.zone]++; });
    // Each zone card toggles _ovZoneFilter. "In Zones" clears the filter.
    // Active card gets a highlighted outline + subtle tint so the user can
    // see at a glance which filter is in effect.
    const isAll = _ovZoneFilter === 'all';
    const cardCls = (zone, extra) => {
        const active = _ovZoneFilter === zone;
        return `summary-card ${extra || ''} ${active ? 'filter-active' : ''}`.trim();
    };
    document.getElementById('summary-cards').innerHTML = `
        <div class="${cardCls('all')}" onclick="ovSetZone('all')" role="button" tabindex="0" title="Show all pairs" style="cursor:pointer">
            <div class="label">In Zones</div><div class="value">${pairs.length}</div><div class="label">pairs detected</div>
        </div>
        <div class="${cardCls('OS_L2','os2')}" onclick="ovSetZone('OS_L2')" role="button" tabindex="0" title="Filter to Oversold L2 (click again to clear)" style="cursor:pointer">
            <div class="label">Oversold L2</div><div class="value">${counts.OS_L2}</div><div class="label">Extreme Long</div>
        </div>
        <div class="${cardCls('OB_L2','ob2')}" onclick="ovSetZone('OB_L2')" role="button" tabindex="0" title="Filter to Overbought L2 (click again to clear)" style="cursor:pointer">
            <div class="label">Overbought L2</div><div class="value">${counts.OB_L2}</div><div class="label">Extreme Short</div>
        </div>
        <div class="${cardCls('OS_L1','os1')}" onclick="ovSetZone('OS_L1')" role="button" tabindex="0" title="Filter to Oversold L1 (click again to clear)" style="cursor:pointer">
            <div class="label">Oversold L1</div><div class="value">${counts.OS_L1}</div><div class="label">Watch Long</div>
        </div>
        <div class="${cardCls('OB_L1','ob1')}" onclick="ovSetZone('OB_L1')" role="button" tabindex="0" title="Filter to Overbought L1 (click again to clear)" style="cursor:pointer">
            <div class="label">Overbought L1</div><div class="value">${counts.OB_L1}</div><div class="label">Watch Short</div>
        </div>
    `;
}

// Toggle zone filter; clicking the active zone again clears it.
// After applying the filter, smoothly scroll the pairs grid into view so the
// user immediately sees the filtered results (they're below the macro/analytics
// section and would otherwise be off-screen).
function ovSetZone(zone) {
    if (zone === 'all') {
        _ovZoneFilter = 'all';
    } else {
        _ovZoneFilter = (_ovZoneFilter === zone) ? 'all' : zone;
    }
    renderSummary(_ovAllPairs);
    renderPairs(_applyOvFilters(_ovAllPairs), _ovTier);

    // Scroll to the pairs grid (skip for the "In Zones" clear-all click to
    // avoid jarring movement when the user is just resetting).
    if (zone !== 'all' && _ovZoneFilter !== 'all') {
        const grid = document.getElementById('pairs-filter-bar') || document.getElementById('pairs-grid');
        if (grid) {
            // Delay one frame so the DOM has reflowed with the new filter.
            requestAnimationFrame(() => {
                try { grid.scrollIntoView({ behavior: 'smooth', block: 'start' }); }
                catch(_) { grid.scrollIntoView(); }
            });
        }
    }
}

function _tierBadgeHtml(sym) {
    var info = _classMap[sym];
    if (!info) return '';
    var colors = {blue_chip:'#2196f3',large_cap:'#4caf50',mid_cap:'#f0b429',small_cap:'#ff9800',high_risk:'#f44336'};
    var labels = {blue_chip:'🔵',large_cap:'🟢',mid_cap:'🟡',small_cap:'🟠',high_risk:'🔴'};
    var sectorEmoji = {layer1:'⛓️',layer2:'🔗',defi:'🏦',gaming:'🎮',ai:'🤖',tradefi:'📈',meme:'🐸',infra:'⚙️',other:'🔷'};
    var col = colors[info.tier] || '#888';
    var hot = info.is_hot ? '<span style="color:#f0b429;font-size:10px;font-weight:800;margin-left:3px">🔥</span>' : '';
    var rankStr = info.rank ? '#' + info.rank : '';
    var sec = (sectorEmoji[info.sector] || '') + ' ';
    return '<div style="display:flex;gap:4px;align-items:center;margin-top:4px;flex-wrap:wrap">'
        + '<span style="font-size:10px;font-weight:700;color:'+col+';background:'+col+'22;padding:2px 7px;border-radius:10px">'
        + (labels[info.tier]||'') + ' ' + (info.tier||'').replace('_',' ') + hot
        + '</span>'
        + (info.sector && info.sector !== 'other' ? '<span style="font-size:10px;color:var(--text-dim);background:var(--bg);padding:2px 7px;border-radius:10px;border:1px solid var(--border)">'+sec+(info.sector||'')+'</span>' : '')
        + (rankStr ? '<span style="font-size:9px;color:var(--text-dim)">'+rankStr+'</span>' : '')
        + '</div>';
}

function renderPairs(pairs, tier) {
    if (!pairs.length) {
        var msg = (_ovTierFilter !== 'all' || _ovSectorFilter !== 'all' || _ovHotFilter)
            ? 'No pairs match your filters right now'
            : 'No pairs in TSI zones right now';
        document.getElementById('pairs-grid').innerHTML = '<div class="no-data">' + msg + '</div>';
        return;
    }
    const isPro = tier !== 'free';
    document.getElementById('pairs-grid').innerHTML = pairs.map(p => {
        const sym = _symFromPair(p.pair);
        const hookBadge = p.hooked ? `<span class="hook-badge">🔄 HOOKED</span>` : '';
        const classBadge = _tierBadgeHtml(sym);
        const metaHtml = isPro && p.tsi !== null ? `
            <div class="pair-meta">
                <div class="meta-item"><span>TSI</span><span class="meta-val">${p.tsi}</span></div>
                <div class="meta-item"><span>L2</span><span class="meta-val neutral">±${p.adapt_l2}</span></div>
                <div class="meta-item"><span>CE Line</span><span class="meta-val ${p.ce_line?.toLowerCase()}">${p.ce_line}</span></div>
                <div class="meta-item"><span>CE Cloud</span><span class="meta-val ${p.ce_cloud?.toLowerCase()}">${p.ce_cloud}</span></div>
                <div class="meta-item"><span>CE Dist</span><span class="meta-val ${p.ce_distance_pct >= 0 ? 'positive' : 'negative'}">${Math.abs(p.ce_distance_pct||0).toFixed(2)}%</span></div>
                <div class="meta-item"><span>LinReg</span><span class="meta-val">${p.linreg}</span></div>
            </div>
        ` : (isPro ? '' : '<div style="font-size:11px;color:var(--text-muted);margin-top:10px;text-align:center">🔒 Upgrade to Pro for indicator details</div>');

        return `
        <div class="pair-card ${_currentPair === p.pair ? 'active' : ''}"
             onclick="${isPro ? `selectPairChart('${p.pair}')` : `switchPage('pricing')`}" id="card-${p.pair}">
            <div class="zone-badge ${p.zone}">${p.zone}${hookBadge}</div>
            <div class="pair-name">${p.pair.replace('USDT','')}<span style="color:var(--text-dim);font-weight:400">/USDT</span></div>
            <div class="pair-price">${formatPrice(p.price)}</div>
            <div class="pair-change ${p.change_pct >= 0 ? 'positive' : 'negative'}">
                ${p.change_pct >= 0 ? '+' : ''}${p.change_pct.toFixed(2)}% (24h)
            </div>
            ${classBadge}
            ${metaHtml}
        </div>`;
    }).join('');
}

// ═══════════════════════════════════════════════════════════════
//  SIGNALS
// ═══════════════════════════════════════════════════════════════
async function loadSignals() {
    try {
        const res = await fetch('/api/signals', { headers: authHeaders() });
        const data = await res.json();
        renderSignals(data);
    } catch(e) {
        document.getElementById('signals-container').innerHTML = '<div class="no-data">Failed to load signals</div>';
    }
}

function renderPriceLadder(s) {
    if (!s.price || !s.stop_loss) return '';
    const isLong = s.direction === 'LONG' || s.direction === 'BUY';
    const tgts = [...(s.targets || [])];
    let rows = [];

    if (isLong) {
        // LONG: TP5..TP1 (highest first) → Entry → SL
        const sorted = [...tgts].reverse();
        sorted.forEach((t, i) => {
            const tpNum = sorted.length - i;
            rows.push(`<div class="pl-row tp" id="tprow-${s.signal_id}-${tpNum}"><span class="pl-label">TP${tpNum}</span><span class="pl-bar"></span><span class="pl-price">${formatPrice(t)}</span><span class="pl-pct">${pctDiff(s.price, t)}</span></div>`);
        });
        rows.push(`<div class="pl-row entry"><span class="pl-label">Entry</span><span class="pl-bar"></span><span class="pl-price">${formatPrice(s.price)}</span><span class="pl-pct">—</span></div>`);
        rows.push(`<div class="pl-row sl"><span class="pl-label">SL</span><span class="pl-bar"></span><span class="pl-price">${formatPrice(s.stop_loss)}</span><span class="pl-pct">${pctDiff(s.price, s.stop_loss)}</span></div>`);
    } else {
        // SHORT: SL → Entry → TP1..TP5 (descending)
        rows.push(`<div class="pl-row sl"><span class="pl-label">SL</span><span class="pl-bar"></span><span class="pl-price">${formatPrice(s.stop_loss)}</span><span class="pl-pct">${pctDiff(s.price, s.stop_loss)}</span></div>`);
        rows.push(`<div class="pl-row entry"><span class="pl-label">Entry</span><span class="pl-bar"></span><span class="pl-price">${formatPrice(s.price)}</span><span class="pl-pct">—</span></div>`);
        tgts.forEach((t, i) => {
            const tpNum = i + 1;
            rows.push(`<div class="pl-row tp" id="tprow-${s.signal_id}-${tpNum}"><span class="pl-label">TP${tpNum}</span><span class="pl-bar"></span><span class="pl-price">${formatPrice(t)}</span><span class="pl-pct">${pctDiff(s.price, t)}</span></div>`);
        });
    }
    return `<div class="price-ladder">${rows.join('')}</div>`;
}

function renderSignals(data) {
    document.getElementById('signal-count').textContent = `(${data.open_count} open / ${data.total} total)`;
    const tier = data.tier || 'free';
    const isPro = tier !== 'free';
    _signalCache = data.signals || [];
    if (isPro) startLivePnlPolling();

    if (!data.signals.length) {
        document.getElementById('signals-container').innerHTML = '<div class="no-data">No signals available</div>';
        return;
    }

    if (isPro) {
        // Rich card view for Pro/Elite
        let html = '<div class="signal-cards">';
        for (const s of data.signals) {
            const dirLower = s.direction.toLowerCase();
            const dirIcon = s.direction === 'LONG' ? '🚀' : '📉';
            const statusLower = (s.status || '').toLowerCase();
            let statusClass = 'status-sent';
            if (statusLower.includes('closed') || statusLower.includes('tp')) statusClass = 'status-tp';
            if (statusLower.includes('sl') || statusLower.includes('stop')) statusClass = 'status-sl';
            if (statusLower.includes('cancelled')) statusClass = 'status-closed';
            const pnlClass = s.pnl > 0 ? 'pnl-pos' : s.pnl < 0 ? 'pnl-neg' : 'pnl-zero';
            const pnlStr = s.pnl > 0 ? `+${s.pnl}%` : s.pnl < 0 ? `${s.pnl}%` : '—';
            const rr = calcRR(s.price, s.stop_loss, s.targets);
            const rrCls = rr >= 2 ? 'good' : rr >= 1 ? 'ok' : 'bad';
            const rrStr = rr ? `${rr}:1` : '—';
            const chartBtn = `<span style="font-size:11px;color:var(--blue);cursor:pointer" onclick="selectPairChart('${s.pair}')">📊 Chart</span>`;
            const sigSym = _symFromPair(s.pair);
            const sigClassBadge = _tierBadgeHtml(sigSym);

            const isOpen = ['SENT','OPEN','ACTIVE','TP1_HIT','TP2_HIT'].includes((s.status||'').toUpperCase());
            // Build outcome badge for closed signals
            let outcomeHtml = '';
            if (!isOpen) {
                const numTargets = (s.targets || []).length;
                const th = s.targets_hit || 0;
                const isSL = (s.status||'').toUpperCase().includes('SL') || s.pnl < 0;
                if (isSL) {
                    outcomeHtml = `<span class="tp-outcome loss">🛑 SL HIT &nbsp;${s.pnl > 0 ? '+' : ''}${s.pnl}%</span>`;
                } else if (th > 0) {
                    const allHit = th >= numTargets && numTargets > 0;
                    const label = allHit ? `ALL TPs ✅` : `TP${th} ✅`;
                    outcomeHtml = `<span class="tp-outcome win">${label} &nbsp;${s.pnl > 0 ? '+' : ''}${s.pnl}%</span>`;
                } else {
                    outcomeHtml = `<span class="tp-outcome age">CLOSED &nbsp;${s.pnl !== 0 ? (s.pnl > 0 ? '+' : '') + s.pnl + '%' : '—'}</span>`;
                }
            }
            const livePnlHtml = isOpen
                ? `<div class="live-pnl-wrap" id="livepnl-${s.signal_id}">
                       <span class="live-pnl-lev pnl-zero"><span class="live-dot"></span>—</span>
                       <span class="live-pnl-raw">raw: —</span>
                   </div>`
                : outcomeHtml;
            const driftBanner = s.entry_drift_alert
                ? `<div class="drift-alert-banner">⚠️ Entry drift ${s.entry_drift_pct}% — CE signal valid, verify entry manually</div>`
                : '';
            html += `<div class="signal-card${s.entry_drift_alert ? ' has-drift-alert' : ''}">
                <div class="sc-header">
                    <span class="sc-pair">${s.pair.replace('USDT','')}<span style="color:var(--text-dim);font-weight:400;font-size:14px">/USDT</span></span>
                    <span class="sc-dir ${dirLower}">${dirIcon} ${s.direction}</span>
                </div>
                ${driftBanner}
                ${sigClassBadge ? '<div style="padding:0 0 4px">' + sigClassBadge + '</div>' : ''}
                <div class="sc-meta">
                    <span>🕐 ${typeof _fmtLocalTime === 'function' && s.timestamp ? _fmtLocalTime(s.timestamp) : s.time_local}</span>
                    <span>⚡ ${s.leverage ? s.leverage + 'x' : '—'}</span>
                    <span>🎯 ${s.confidence ? s.confidence + '%' : '—'}</span>
                    ${rr ? `<span class="rr-badge ${rrCls}">R:R ${rrStr}</span>` : ''}
                </div>
                ${renderPriceLadder(s)}
                <div class="sc-footer">
                    <span class="${statusClass}" style="font-weight:600;font-size:12px">${s.status}</span>
                    ${livePnlHtml}
                    ${chartBtn}
                </div>
            </div>`;
        }
        html += '</div>';
        document.getElementById('signals-container').innerHTML = html;
    } else {
        // Simple table for Free tier
        let html = `<table class="signal-table"><thead><tr>
            <th>Time</th><th>Pair</th><th>Direction</th><th>Status</th><th>PnL</th>
        </tr></thead><tbody>`;
        for (const s of data.signals) {
            const dirClass = s.direction === 'LONG' ? 'dir-long' : 'dir-short';
            const dirIcon = s.direction === 'LONG' ? '🚀' : '📉';
            const statusLower = (s.status || '').toLowerCase();
            let statusClass = 'status-sent';
            if (statusLower.includes('closed') || statusLower.includes('tp')) statusClass = 'status-tp';
            if (statusLower.includes('sl') || statusLower.includes('stop')) statusClass = 'status-sl';
            if (statusLower.includes('cancelled')) statusClass = 'status-closed';
            const pnlClass = s.pnl > 0 ? 'pnl-pos' : s.pnl < 0 ? 'pnl-neg' : 'pnl-zero';
            const pnlStr = s.pnl > 0 ? `+${s.pnl}%` : s.pnl < 0 ? `${s.pnl}%` : '—';
            html += `<tr>
                <td>${typeof _fmtLocalTime === 'function' && s.timestamp ? _fmtLocalTime(s.timestamp) : s.time_local}</td>
                <td style="font-weight:600">${s.pair.replace('USDT','')}<span style="color:var(--text-dim);font-weight:400">/USDT</span></td>
                <td class="${dirClass}">${dirIcon} ${s.direction}</td>
                <td class="${statusClass}">${s.status}</td>
                <td class="${pnlClass}">${pnlStr}</td>
            </tr>`;
        }
        html += '</tbody></table>';
        html += '<div style="text-align:center;padding:20px;color:var(--text-dim);font-size:13px">🔒 <a style="color:var(--gold);cursor:pointer" onclick="switchPage(\'pricing\')">Upgrade to Pro</a> for real-time signals with entry, targets, and stop-loss prices</div>';
        document.getElementById('signals-container').innerHTML = html;
    }
}

// ═══════════════════════════════════════════════════════════════
//  LIVE PNL — SHARED SSE STREAM (with polling fallback)
// ═══════════════════════════════════════════════════════════════
//
//  One Binance WebSocket is consumed by the backend and fanned out to
//  every connected browser via `/api/stream/live_pnl`. All users see
//  identical ticks at the same moment.
//
//  If SSE fails (proxy, network, tier gate), we fall back to polling
//  `/api/signals/live_pnl` so the UI still works.
// ═══════════════════════════════════════════════════════════════
let _livePnlTimer = null;
let _livePnlES    = null;
let _livePnlSSEFailures = 0;

function _applyLivePnl(pnlMap) {
    for (const [sid, info] of Object.entries(pnlMap)) {
        const wrap = document.getElementById(`livepnl-${sid}`);
        if (!wrap) continue;
        const lev = info.leveraged_pct;
        const raw = info.raw_pct;
        const levCls = lev > 0 ? 'pnl-pos' : lev < 0 ? 'pnl-neg' : 'pnl-zero';
        const levStr = (lev >= 0 ? '+' : '') + lev.toFixed(2) + '%';
        const rawStr = (raw >= 0 ? '+' : '') + raw.toFixed(2) + '%';
        const tHit = info.targets_hit || 0;
        const badge = info.sl_hit ? '⚠️ SL' : tHit >= 2 ? '✅ TP2' : tHit >= 1 ? '✅ TP1' : '';
        wrap.innerHTML = `
            <span class="live-pnl-lev ${levCls}"><span class="live-dot"></span>${levStr} ${info.leverage}x${badge ? ' ' + badge : ''}</span>
            <span class="live-pnl-raw">raw: ${rawStr} @ ${info.current_price}</span>`;
        for (let n = 1; n <= 3; n++) {
            const tpRow = document.getElementById(`tprow-${sid}-${n}`);
            if (tpRow) tpRow.classList.toggle('tp-hit', tHit >= n);
        }
    }
}

async function loadLivePnl() {
    if (!['plus','pro','ultra'].includes(_tier)) return;
    try {
        const res = await fetch('/api/signals/live_pnl', { headers: authHeaders() });
        if (!res.ok) return;
        const data = await res.json();
        _applyLivePnl(data.pnl || {});
    } catch(e) {}
}

function _stopLivePnlPolling() {
    if (_livePnlTimer) { clearInterval(_livePnlTimer); _livePnlTimer = null; }
}

function _startLivePnlPolling() {
    if (_livePnlTimer) return;
    loadLivePnl();
    const interval = _tier === 'pro' || _tier === 'ultra' ? 10000 : 20000;
    _livePnlTimer = setInterval(loadLivePnl, interval);
}

function _closeLivePnlStream() {
    if (_livePnlES) { try { _livePnlES.close(); } catch(e) {} _livePnlES = null; }
}

function _startLivePnlStream() {
    _closeLivePnlStream();
    const tok = (typeof _token !== 'undefined' && _token)
             || localStorage.getItem('aladdin_token');
    if (!tok) { _startLivePnlPolling(); return; }

    try {
        const url = `/api/stream/live_pnl?token=${encodeURIComponent(tok)}`;
        const es  = new EventSource(url);
        _livePnlES = es;

        es.addEventListener('pnl', (ev) => {
            try {
                const data = JSON.parse(ev.data);
                _applyLivePnl(data.pnl || {});
                _livePnlSSEFailures = 0;   // successful tick resets backoff
                _stopLivePnlPolling();     // cancel polling if it was running
            } catch(e) {}
        });

        es.onerror = () => {
            _livePnlSSEFailures += 1;
            // Too many consecutive failures → give up SSE, use polling
            if (_livePnlSSEFailures >= 3) {
                _closeLivePnlStream();
                _startLivePnlPolling();
            }
            // Otherwise the browser auto-reconnects per `retry: 5000`.
        };
    } catch(e) {
        // EventSource unsupported → polling fallback
        _startLivePnlPolling();
    }
}

// Public entry point (unchanged name — called from renderSignals)
function startLivePnlPolling() {
    if (!['plus','pro','ultra'].includes(_tier)) return;
    if (typeof EventSource !== 'undefined') {
        _startLivePnlStream();
        // Safety-net: if SSE never delivers a tick within 8 s, start polling
        setTimeout(() => {
            if (_livePnlSSEFailures > 0 && !_livePnlTimer) _startLivePnlPolling();
        }, 8000);
    } else {
        _startLivePnlPolling();
    }
}
