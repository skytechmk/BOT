/* ═══════════════════════════════════════════════════════════════
 *  Lab Signals — admin-only experimental RH path viewer
 * ═══════════════════════════════════════════════════════════════
 * Fetches /api/admin/lab/signals and renders:
 *   1. Headline stats (total / win rate / avg PnL)
 *   2. Per-zone breakdown table (the 6 short-circuit paths)
 *   3. Detail signal table (last N experimental signals)
 *
 * Window selector: 7 / 30 / 90 days.
 * Auth: cookie-based JWT (same as the rest of the SPA).
 */

let _LAB_DAYS = 30;
let _LAB_DATA = null;

function _labFmtPct(v) {
    if (v === null || v === undefined) return '—';
    return (v * 100).toFixed(Math.abs(v)<0.01?3:1) + '%';
}
function _labFmtPnl(v) {
    if (v === null || v === undefined || isNaN(v)) return '—';
    const n = Number(v);
    const cls = n > 0 ? 'color:#00c853' : n < 0 ? 'color:#ff5252' : 'color:var(--text-dim)';
    const sign = n > 0 ? '+' : '';
    const dec = Math.abs(n) < 1 ? 4 : 2;
    return `<span style="${cls}">${sign}${n.toFixed(dec)}%</span>`;
}

function _labFmtSignalPnl(s) {
    if (s && s.pnl_missing) {
        return '<span style="color:var(--text-dim)" title="Closed without computed outcome PnL">—</span>';
    }
    return _labFmtPnl(s ? s.pnl : null);
}

function _labFmtSignalOutcome(s) {
    if (!s || s.status === 'SENT' || s.status === 'OPEN' || s.status === 'ACTIVE') {
        return '<span style="color:var(--text-dim)">Open</span>';
    }
    const status = (s.status || '').toUpperCase();
    const reason = (s.close_reason || '').toUpperCase();
    const th = s.targets_hit || 0;
    if (status === 'CLOSED' || status === 'CANCELLED') {
        if (reason.includes('SL_HIT')) {
            if (th > 0) {
                return `<span style="color:#ff5252">SL Hit after TP${th} ✅</span>`;
            }
            return '<span style="color:#ff5252">SL Hit</span>';
        }
        if (reason.includes('TP3_HIT') || (th === 3 && reason.includes('BACKFILLED_MARK_CLOSE'))) {
            return '<span style="color:#00c853">All TPs ✅</span>';
        }
        if (reason.includes('TP2_HIT') || (th === 2 && reason.includes('BACKFILLED_MARK_CLOSE'))) {
            return '<span style="color:#00c853">TP2 ✅</span>';
        }
        if (reason.includes('TP1_HIT') || (th === 1 && reason.includes('BACKFILLED_MARK_CLOSE'))) {
            return '<span style="color:#00c853">TP1 ✅</span>';
        }
        if (reason === 'CLOSED_EVEN' || reason === 'BACKFILLED_MARK_CLOSE') {
            return '<span style="color:var(--text-dim)">Closed Even</span>';
        }
        return '<span style="color:var(--text-dim)">Closed</span>';
    }
    return '<span style="color:var(--text-dim)">Unknown</span>';
}

function _labFmtTime(ts) {
    try {
        const d = new Date(ts * 1000);
        return d.toLocaleString(undefined, {
            month: 'short', day: '2-digit',
            hour: '2-digit', minute: '2-digit',
        });
    } catch (e) { return '—'; }
}

async function loadLabPage() {
    const root = document.getElementById('lab-content');
    if (!root) return;
    root.innerHTML = '<div class="loading"><div class="spinner"></div>Loading Lab signals…</div>';
    try {
        const headers = (typeof authHeaders === 'function') ? authHeaders() : {};
        const r = await fetch(`/api/admin/lab/signals?days=${_LAB_DAYS}&limit=300`, {
            credentials: 'same-origin',
            headers,
        });
        if (r.status === 401 || r.status === 403) {
            root.innerHTML = '<div style="color:var(--text-dim);padding:24px">Admin access required.</div>';
            return;
        }
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        _LAB_DATA = await r.json();
        _renderLab();
    } catch (e) {
        root.innerHTML = `<div style="color:#ff5252;padding:24px">Failed to load Lab signals: ${e.message}</div>`;
    }
}

function _renderLab() {
    const root = document.getElementById('lab-content');
    if (!root || !_LAB_DATA) return;
    const { signals = [], stats = {}, by_zone = [] } = _LAB_DATA;

    const winRateColor = stats.win_rate === null
        ? 'var(--text-dim)'
        : stats.win_rate >= 0.5 ? '#00c853' : '#ff5252';

    root.innerHTML = `
        <!-- Window selector -->
        <div style="display:flex;gap:8px;margin-bottom:20px;align-items:center">
            <span style="font-size:12px;color:var(--text-dim);font-weight:700;letter-spacing:.06em;text-transform:uppercase">Window:</span>
            ${[7, 30, 90].map(d => `
                <button onclick="_labSetDays(${d})"
                    style="padding:6px 14px;border-radius:6px;border:1px solid var(--border);background:${d === _LAB_DAYS ? 'var(--accent)' : 'var(--surface)'};color:${d === _LAB_DAYS ? '#000' : 'var(--text)'};font-weight:700;cursor:pointer;font-size:12px">
                    ${d}d
                </button>
            `).join('')}
            <button onclick="loadLabPage()"
                style="margin-left:auto;padding:6px 12px;border-radius:6px;border:1px solid var(--border);background:var(--surface);color:var(--text);cursor:pointer;font-size:12px">
                ↻ Refresh
            </button>
        </div>

        <!-- Headline stats -->
        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-bottom:24px">
            <div style="background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:16px">
                <div style="font-size:11px;color:var(--text-dim);font-weight:700;text-transform:uppercase;letter-spacing:.06em">Total Lab Signals</div>
                <div style="font-size:26px;font-weight:800;margin-top:4px">${stats.total || 0}</div>
            </div>
            <div style="background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:16px">
                <div style="font-size:11px;color:var(--text-dim);font-weight:700;text-transform:uppercase;letter-spacing:.06em">Win Rate</div>
                <div style="font-size:26px;font-weight:800;margin-top:4px;color:${winRateColor}">${_labFmtPct(stats.win_rate)}</div>
                <div style="font-size:11px;color:var(--text-dim);margin-top:2px">${stats.wins || 0}W / ${stats.losses || 0}L</div>
            </div>
            <div style="background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:16px">
                <div style="font-size:11px;color:var(--text-dim);font-weight:700;text-transform:uppercase;letter-spacing:.06em">Avg PnL</div>
                <div style="font-size:26px;font-weight:800;margin-top:4px">${_labFmtPnl(stats.avg_pnl)}</div>
            </div>
            <div style="background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:16px">
                <div style="font-size:11px;color:var(--text-dim);font-weight:700;text-transform:uppercase;letter-spacing:.06em">Window</div>
                <div style="font-size:26px;font-weight:800;margin-top:4px">${stats.window_days || _LAB_DAYS}d</div>
            </div>
        </div>

        <!-- Per-zone breakdown -->
        <div style="margin-bottom:8px;display:flex;align-items:baseline;gap:12px">
            <h3 style="margin:0;font-size:15px;font-weight:700">Per-Path Breakdown</h3>
            <span style="font-size:12px;color:var(--text-dim)">— count, win rate &amp; avg PnL by RH zone tag</span>
        </div>
        ${_renderZoneTable(by_zone)}

        <!-- Signal detail table -->
        <div style="margin:24px 0 8px;display:flex;align-items:baseline;gap:12px">
            <h3 style="margin:0;font-size:15px;font-weight:700">Recent Lab Signals</h3>
            <span style="font-size:12px;color:var(--text-dim)">— ${signals.length} most recent</span>
        </div>
        ${_renderSignalTable(signals)}
    `;
}

function _renderZoneTable(rows) {
    if (!rows || rows.length === 0) {
        return '<div style="color:var(--text-dim);padding:18px;background:var(--surface);border:1px solid var(--border);border-radius:10px">No experimental signals in this window.</div>';
    }
    return `
        <div style="background:var(--surface);border:1px solid var(--border);border-radius:10px;overflow:hidden">
            <table style="width:100%;border-collapse:collapse;font-size:13px">
                <thead>
                    <tr style="background:rgba(255,255,255,.02);border-bottom:1px solid var(--border)">
                        <th style="text-align:left;padding:10px 14px;font-weight:700;font-size:11px;text-transform:uppercase;color:var(--text-dim);letter-spacing:.06em">Zone</th>
                        <th style="text-align:right;padding:10px 14px;font-weight:700;font-size:11px;text-transform:uppercase;color:var(--text-dim);letter-spacing:.06em">Count</th>
                        <th style="text-align:right;padding:10px 14px;font-weight:700;font-size:11px;text-transform:uppercase;color:var(--text-dim);letter-spacing:.06em">W / L</th>
                        <th style="text-align:right;padding:10px 14px;font-weight:700;font-size:11px;text-transform:uppercase;color:var(--text-dim);letter-spacing:.06em">Win Rate</th>
                        <th style="text-align:right;padding:10px 14px;font-weight:700;font-size:11px;text-transform:uppercase;color:var(--text-dim);letter-spacing:.06em">Avg PnL</th>
                    </tr>
                </thead>
                <tbody>
                    ${rows.map(r => `
                        <tr style="border-bottom:1px solid var(--border)">
                            <td style="padding:10px 14px"><code style="background:rgba(255,107,157,.08);color:#ff6b9d;padding:2px 8px;border-radius:4px;font-size:12px;font-weight:700">${r.zone_used}</code></td>
                            <td style="text-align:right;padding:10px 14px;font-weight:700">${r.count}</td>
                            <td style="text-align:right;padding:10px 14px;color:var(--text-dim);font-size:12px">${r.wins}W / ${r.losses}L</td>
                            <td style="text-align:right;padding:10px 14px;font-weight:700;color:${r.win_rate === null ? 'var(--text-dim)' : r.win_rate >= 0.5 ? '#00c853' : '#ff5252'}">${_labFmtPct(r.win_rate)}</td>
                            <td style="text-align:right;padding:10px 14px;font-weight:700">${_labFmtPnl(r.avg_pnl)}</td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        </div>
    `;
}

function _renderSignalTable(rows) {
    if (!rows || rows.length === 0) {
        return '<div style="color:var(--text-dim);padding:18px;background:var(--surface);border:1px solid var(--border);border-radius:10px">No signals.</div>';
    }
    return `
        <div style="background:var(--surface);border:1px solid var(--border);border-radius:10px;overflow:hidden;max-height:600px;overflow-y:auto">
            <table style="width:100%;border-collapse:collapse;font-size:13px">
                <thead style="position:sticky;top:0;background:var(--surface);z-index:1">
                    <tr style="background:rgba(255,255,255,.02);border-bottom:1px solid var(--border)">
                        <th style="text-align:left;padding:10px 14px;font-size:11px;color:var(--text-dim);text-transform:uppercase;letter-spacing:.06em">Time</th>
                        <th style="text-align:left;padding:10px 14px;font-size:11px;color:var(--text-dim);text-transform:uppercase;letter-spacing:.06em">Pair</th>
                        <th style="text-align:left;padding:10px 14px;font-size:11px;color:var(--text-dim);text-transform:uppercase;letter-spacing:.06em">Dir</th>
                        <th style="text-align:left;padding:10px 14px;font-size:11px;color:var(--text-dim);text-transform:uppercase;letter-spacing:.06em">Zone</th>
                        <th style="text-align:right;padding:10px 14px;font-size:11px;color:var(--text-dim);text-transform:uppercase;letter-spacing:.06em">Entry</th>
                        <th style="text-align:right;padding:10px 14px;font-size:11px;color:var(--text-dim);text-transform:uppercase;letter-spacing:.06em">Status</th>
                        <th style="text-align:right;padding:10px 14px;font-size:11px;color:var(--text-dim);text-transform:uppercase;letter-spacing:.06em">Outcome</th>
                        <th style="text-align:right;padding:10px 14px;font-size:11px;color:var(--text-dim);text-transform:uppercase;letter-spacing:.06em">PnL</th>
                    </tr>
                </thead>
                <tbody>
                    ${rows.map(s => `
                        <tr style="border-bottom:1px solid var(--border)">
                            <td style="padding:8px 14px;color:var(--text-dim);font-size:12px;white-space:nowrap">${_labFmtTime(s.timestamp)}</td>
                            <td style="padding:8px 14px;font-weight:700">${s.pair}</td>
                            <td style="padding:8px 14px;font-weight:700;color:${s.signal === 'LONG' ? '#00c853' : '#ff5252'}">${s.signal}</td>
                            <td style="padding:8px 14px"><code style="background:rgba(255,107,157,.08);color:#ff6b9d;padding:2px 6px;border-radius:4px;font-size:11px;font-weight:700">${s.zone_used || '—'}</code></td>
                            <td style="text-align:right;padding:8px 14px;color:var(--text-dim);font-size:12px">${s.price ? s.price.toPrecision(6) : '—'}</td>
                            <td style="text-align:left;padding:8px 14px">${_labFmtSignalOutcome(s)}</td>
                            <td style="text-align:right;padding:8px 14px;font-weight:700">${_labFmtSignalPnl(s)}</td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        </div>
    `;
}

function _labSetDays(d) {
    _LAB_DAYS = d;
    loadLabPage();
}
