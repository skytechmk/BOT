// ═══════════════════════════════════════════════════════════════
//  ANALYTICS (Pro+)
// ═══════════════════════════════════════════════════════════════

// Format a Unix timestamp in the user's IP-detected (or browser) timezone
function _fmtLocalTime(ts) {
    if (!ts) return '—';
    const tz = (function() {
        try { return localStorage.getItem('awd-client-tz') || Intl.DateTimeFormat().resolvedOptions().timeZone; }
        catch(_) { return 'UTC'; }
    })();
    try {
        return new Intl.DateTimeFormat('en-GB', {
            day: '2-digit', month: 'short',
            hour: '2-digit', minute: '2-digit',
            hour12: false, timeZone: tz
        }).format(new Date(ts * 1000));
    } catch(_) {
        const d = new Date(ts * 1000);
        return d.getDate().toString().padStart(2,'0') + ' ' +
               ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][d.getMonth()] +
               ' ' + d.getHours().toString().padStart(2,'0') + ':' + d.getMinutes().toString().padStart(2,'0');
    }
}
async function loadAnalytics() {
    if (!(window._hasTier ? window._hasTier('plus') : ['plus','pro','ultra'].includes(_tier))) {
        document.getElementById('analytics-content').innerHTML = `
            <div class="paywall-overlay">
                <div class="paywall-icon">📈</div>
                <div class="paywall-title">Performance Analytics — Pro Feature</div>
                <div class="paywall-desc">Track win rates, equity curves, pair performance, and hourly heatmaps.</div>
                <button class="btn btn-gold" onclick="switchPage('pricing')">Upgrade to Plus — 53 USDT/mo</button>
            </div>`;
        return;
    }
    try {
        const res = await fetch('/api/analytics/summary?days=30', { headers: authHeaders() });
        const data = await res.json();
        renderAnalytics(data);
    } catch(e) {
        document.getElementById('analytics-content').innerHTML = '<div class="no-data">Failed to load analytics</div>';
    }
}

function _pnlVariants(data) {
    return {
        cum_leveraged: {
            label: 'Cumulative Leveraged %',
            value: data.total_pnl,
            sub:   `sum of ${data.closed_signals} leveraged trades (not account growth)`,
        },
        compounded: {
            label: 'Compounded Equity %',
            value: data.compounded_equity_pct,
            sub:   `start $1000, 1% sizing per trade`,
        },
        avg_trade: {
            label: 'Avg PnL / Trade',
            value: data.avg_pnl_per_trade,
            sub:   `leveraged, across ${data.closed_signals} trades`,
        },
        unleveraged: {
            label: 'Unleveraged PnL %',
            value: data.total_pnl_unleveraged,
            sub:   `raw price moves (lev divided out)`,
        },
    };
}

function _selectedPnlMode() {
    try { return localStorage.getItem('analytics.pnlMode') || 'cum_leveraged'; }
    catch(_) { return 'cum_leveraged'; }
}

window.setPnlMode = function(mode) {
    try { localStorage.setItem('analytics.pnlMode', mode); } catch(_) {}
    if (window._lastAnalyticsData) _updatePnlCard(window._lastAnalyticsData);
};

function _updatePnlCard(data) {
    const card = document.getElementById('pnl-card');
    if (!card) return;
    const variants = _pnlVariants(data);
    const mode = _selectedPnlMode();
    const v = variants[mode] || variants.cum_leveraged;
    const pnlClass = v.value >= 0 ? 'green' : 'red';
    const sign = v.value > 0 ? '+' : '';
    const valueStr = `${sign}${v.value}%`;
    // Auto-shrink font so long numbers (e.g. +12215.34%) don't overflow the card
    let fontSize = '28px';
    if (valueStr.length >= 11)      fontSize = '18px';
    else if (valueStr.length >= 9)  fontSize = '22px';
    else if (valueStr.length >= 7)  fontSize = '26px';
    card.className = `metric-card ${pnlClass}`;
    card.innerHTML = `
        <div class="metric-label" style="display:flex;justify-content:space-between;align-items:center;gap:4px;flex-wrap:wrap">
            <span style="flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${v.label}</span>
            <select onchange="setPnlMode(this.value)" style="background:transparent;border:1px solid var(--border);color:var(--text-dim);font-size:9px;padding:1px 3px;border-radius:3px;cursor:pointer;flex-shrink:0">
                <option value="cum_leveraged"${mode==='cum_leveraged'?' selected':''}>Cumulative Lev</option>
                <option value="compounded"${mode==='compounded'?' selected':''}>Compounded</option>
                <option value="avg_trade"${mode==='avg_trade'?' selected':''}>Avg / Trade</option>
                <option value="unleveraged"${mode==='unleveraged'?' selected':''}>Unleveraged</option>
            </select>
        </div>
        <div class="metric-value" style="font-size:${fontSize};white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${valueStr}</div>
        <div class="metric-sub">${v.sub}</div>`;
}

function renderAnalytics(data) {
    window._lastAnalyticsData = data;
    const wrClass = data.win_rate >= 55 ? 'green' : data.win_rate >= 45 ? 'gold' : 'red';
    document.getElementById('analytics-content').innerHTML = `
        <div class="section-header"><h2>📈 Performance Analytics (${data.period_days}d)</h2></div>
        <div class="analytics-grid">
            <div class="metric-card ${wrClass}"><div class="metric-label">Win Rate</div><div class="metric-value">${data.win_rate}%</div><div class="metric-sub">${data.wins}W / ${data.losses}L</div></div>
            <div id="pnl-card" class="metric-card"></div>
            <div class="metric-card gold"><div class="metric-label">Profit Factor</div><div class="metric-value">${data.profit_factor}x</div><div class="metric-sub">gross profit / gross loss</div></div>
            <div class="metric-card blue"><div class="metric-label">Open Signals</div><div class="metric-value">${data.open_signals}</div><div class="metric-sub">currently active</div></div>
            <div class="metric-card green"><div class="metric-label">Avg Win</div><div class="metric-value">+${data.avg_win}%</div><div class="metric-sub">per winning trade</div></div>
            <div class="metric-card red"><div class="metric-label">Avg Loss</div><div class="metric-value">${data.avg_loss}%</div><div class="metric-sub">per losing trade</div></div>
            <div class="metric-card"><div class="metric-label">Best Streak</div><div class="metric-value" style="color:var(--green)">${data.max_win_streak}W</div><div class="metric-sub">consecutive wins</div></div>
            <div class="metric-card"><div class="metric-label">Worst Streak</div><div class="metric-value" style="color:var(--red)">${data.max_loss_streak}L</div><div class="metric-sub">consecutive losses</div></div>
        </div>
        <div class="analytics-grid" style="grid-template-columns:1fr 1fr">
            <div class="metric-card"><div class="metric-label">Long Performance</div><div class="metric-value" style="color:var(--green)">${data.long_win_rate}%</div><div class="metric-sub">${data.long_signals} signals</div></div>
            <div class="metric-card"><div class="metric-label">Short Performance</div><div class="metric-value" style="color:var(--red)">${data.short_win_rate}%</div><div class="metric-sub">${data.short_signals} signals</div></div>
        </div>
        ${data.best_trade ? `<div style="background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:16px;margin-top:12px;display:flex;justify-content:space-between">
            <div><span style="color:var(--text-dim);font-size:12px">Best Trade</span><br><span style="font-weight:700">${data.best_trade.pair}</span> <span class="pnl-pos">+${data.best_trade.pnl}%</span></div>
            <div><span style="color:var(--text-dim);font-size:12px">Worst Trade</span><br><span style="font-weight:700">${data.worst_trade.pair}</span> <span class="pnl-neg">${data.worst_trade.pnl}%</span></div>
        </div>` : ''}
    `;

    // Populate the selectable PnL card
    _updatePnlCard(data);

    // Update landing stats
    document.getElementById('stat-signals').textContent = data.total_signals;
    document.getElementById('stat-winrate').textContent = data.win_rate + '%';

    // Load extended analytics
    loadSignalBreakdown();
    loadAttribution();
    loadRegimes();
}

async function loadSignalBreakdown() {
    try {
        const res = await fetch('/api/analytics/breakdown?days=30', { headers: authHeaders() });
        const data = await res.json();
        renderSignalBreakdown(data.signals || []);
    } catch(e) {}
}

async function loadAttribution() {
    try {
        const res = await fetch('/api/analytics/attribution?days=30', { headers: authHeaders() });
        const data = await res.json();
        renderAttribution(data);
    } catch(e) {}
}

async function loadRegimes() {
    try {
        const res = await fetch('/api/analytics/regimes?days=30', { headers: authHeaders() });
        const data = await res.json();
        renderRegimes(data);
    } catch(e) {}
}

function renderSignalBreakdown(signals) {
    if (!signals.length) return;
    let html = `<div class="analytics-breakdown">
        <h3>📋 Signal Breakdown (${signals.length} signals)</h3>
        <div style="overflow-x:auto"><table class="signal-table"><thead><tr>
            <th>Time</th><th>Pair</th><th>Dir</th><th>Entry</th><th>SL</th>
            <th>TP1</th><th>TP2</th><th>TP3</th><th>R:R</th><th>Lev</th><th>Status</th><th>PnL</th>
        </tr></thead><tbody>`;

    for (const s of signals) {
        const dirCls = (s.direction === 'LONG' || s.direction === 'BUY') ? 'dir-long' : 'dir-short';
        const dirIcon = (s.direction === 'LONG' || s.direction === 'BUY') ? '🚀' : '📉';
        const statusLower = (s.status || '').toLowerCase();
        let statusClass = 'status-sent';
        if (statusLower.includes('closed') || statusLower.includes('tp')) statusClass = 'status-tp';
        if (statusLower.includes('sl') || statusLower.includes('stop')) statusClass = 'status-sl';
        if (statusLower.includes('cancelled')) statusClass = 'status-closed';
        const pnlClass = s.pnl > 0 ? 'pnl-pos' : s.pnl < 0 ? 'pnl-neg' : 'pnl-zero';
        const pnlStr = s.pnl > 0 ? `+${s.pnl}%` : s.pnl < 0 ? `${s.pnl}%` : '—';
        const tgts = s.targets || [];
        const rrCls = s.rr >= 2 ? 'good' : s.rr >= 1 ? 'ok' : 'bad';

        html += `<tr>
            <td style="font-size:11px;white-space:nowrap">${s.timestamp ? _fmtLocalTime(s.timestamp) : s.time_local}</td>
            <td style="font-weight:600;font-size:12px">${s.pair.replace('USDT','')}<span style="color:var(--text-dim);font-weight:400">/USDT</span></td>
            <td class="${dirCls}" style="font-size:12px">${dirIcon}</td>
            <td style="color:var(--gold);font-size:12px">${s.entry ? formatPrice(s.entry) : '—'}</td>
            <td style="color:var(--red);font-size:12px">${s.stop_loss ? formatPrice(s.stop_loss) : '—'}</td>
            <td style="color:var(--green);font-size:11px">${tgts[0] ? formatPrice(tgts[0]) : '—'}</td>
            <td style="color:var(--green);font-size:11px">${tgts[1] ? formatPrice(tgts[1]) : '—'}</td>
            <td style="color:var(--green);font-size:11px">${tgts[2] ? formatPrice(tgts[2]) : '—'}</td>
            <td>${s.rr ? `<span class="rr-badge ${rrCls}">${s.rr}:1</span>` : '—'}</td>
            <td style="font-size:12px">${s.leverage ? s.leverage + 'x' : '—'}</td>
            <td class="${statusClass}" style="font-size:12px">${s.status}</td>
            <td class="${pnlClass}" style="font-size:12px">${pnlStr}</td>
        </tr>`;
    }
    html += '</tbody></table></div></div>';

    const container = document.getElementById('analytics-content');
    if (container) container.innerHTML += html;
}

function renderAttribution(data) {
    const factors = data.factors || [];
    if (!factors.length && !data.sqi_correlation?.total_with_sqi) return;
    let html = `<div class="analytics-breakdown" style="margin-top:20px">
        <h3>🔬 Indicator Attribution — SQI Factor Analysis</h3>`;

    if (data.sqi_correlation?.total_with_sqi) {
        const sc = data.sqi_correlation;
        html += `<div style="display:flex;gap:12px;margin-bottom:16px;flex-wrap:wrap">
            <div class="metric-card green" style="flex:1;min-width:140px"><div class="metric-label">Win Avg SQI</div><div class="metric-value">${sc.win_avg_sqi}</div></div>
            <div class="metric-card red" style="flex:1;min-width:140px"><div class="metric-label">Loss Avg SQI</div><div class="metric-value">${sc.loss_avg_sqi}</div></div>
            <div class="metric-card" style="flex:1;min-width:140px"><div class="metric-label">Signals w/ SQI</div><div class="metric-value">${sc.total_with_sqi}</div></div>
        </div>`;
    }

    if (factors.length) {
        html += `<table class="signal-table"><thead><tr>
            <th>Factor</th><th>Max</th><th>Win Avg</th><th>Loss Avg</th><th>Delta</th><th style="width:200px">Win vs Loss</th>
        </tr></thead><tbody>`;
        for (const f of factors) {
            const winPct = f.max > 0 ? (f.win_avg / f.max * 100) : 0;
            const lossPct = f.max > 0 ? (f.loss_avg / f.max * 100) : 0;
            const deltaColor = f.delta > 0 ? 'var(--green)' : f.delta < 0 ? 'var(--red)' : 'var(--text-dim)';
            html += `<tr>
                <td style="font-weight:600">${f.name}</td>
                <td>${f.max}</td>
                <td style="color:var(--green)">${f.win_avg}</td>
                <td style="color:var(--red)">${f.loss_avg}</td>
                <td style="color:${deltaColor};font-weight:700">${f.delta > 0 ? '+' : ''}${f.delta}</td>
                <td><div style="display:flex;gap:2px;align-items:center;height:18px">
                    <div style="background:var(--green);height:100%;width:${winPct}%;border-radius:3px;min-width:2px" title="Win: ${f.win_avg}"></div>
                    <div style="background:var(--red);height:100%;width:${lossPct}%;border-radius:3px;min-width:2px;opacity:0.6" title="Loss: ${f.loss_avg}"></div>
                </div></td>
            </tr>`;
        }
        html += '</tbody></table>';
    }
    html += `<p style="color:var(--text-dim);font-size:11px;margin-top:8px">Factors with higher delta contribute most to winning trades. Data populates as new SQI-scored signals close.</p></div>`;
    const container = document.getElementById('analytics-content');
    if (container) container.innerHTML += html;
}

function renderRegimes(data) {
    if (!data.leverage && !data.rr) return;
    let html = `<div class="analytics-breakdown" style="margin-top:20px">
        <h3>📊 Regime Performance Breakdown</h3>
        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:16px">`;

    function bucketTable(title, buckets) {
        if (!buckets) return '';
        let t = `<div><h4 style="color:var(--gold);margin-bottom:8px">${title}</h4>
            <table class="signal-table"><thead><tr><th>Bucket</th><th>#</th><th>WR</th><th>Avg PnL</th></tr></thead><tbody>`;
        for (const [k, v] of Object.entries(buckets)) {
            if (!v.count) continue;
            const wrColor = v.wr >= 55 ? 'var(--green)' : v.wr >= 40 ? 'var(--gold)' : 'var(--red)';
            const pnlColor = v.avg_pnl >= 0 ? 'var(--green)' : 'var(--red)';
            t += `<tr>
                <td style="font-weight:600">${k}</td>
                <td>${v.count}</td>
                <td style="color:${wrColor};font-weight:700">${v.wr}%</td>
                <td style="color:${pnlColor}">${v.avg_pnl > 0 ? '+' : ''}${v.avg_pnl}%</td>
            </tr>`;
        }
        t += '</tbody></table></div>';
        return t;
    }

    html += bucketTable('By Leverage', data.leverage);
    html += bucketTable('By R:R Ratio', data.rr);
    html += bucketTable('By Direction', data.direction);
    html += bucketTable('By Extension (EMA21)', data.extension);
    html += bucketTable('By PREDATOR Regime', data.regime);
    html += bucketTable('By Positioning Alignment', data.positioning);
    html += '</div></div>';

    const container = document.getElementById('analytics-content');
    if (container) container.innerHTML += html;
}
