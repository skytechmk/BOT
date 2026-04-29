// ═══════════════════════════════════════════════════════════════════
//  BACKTEST — historical-replay UI (Phase 3 · 2026-04-24)
//
//  Drives #page-backtest. Renders:
//    • Parameter form (date range, sizing, leverage, SL/TP mode)
//    • Results stats card
//    • Equity-curve SVG (hand-drawn, no chart library — keeps bundle
//      tiny and avoids a new dependency for one chart)
//    • Per-trade table (sortable, capped to 200 rows for DOM sanity)
//    • Recent runs list
//
//  Backend contract:  see backtest_engine.py / app.py `/api/backtest/*`
// ═══════════════════════════════════════════════════════════════════

(function () {
    'use strict';

    let _lastRun = null;

    // ── Helpers ─────────────────────────────────────────────────────
    // Format a unix-seconds timestamp to the user's local timezone.
    function fmtLocalDt(ts) {
        if (!ts) return '—';
        return new Date(ts * 1000).toLocaleString(undefined, {
            year: 'numeric', month: '2-digit', day: '2-digit',
            hour: '2-digit', minute: '2-digit', hour12: false,
        });
    }

    function fmtUsd(v) {
        const n = Number(v) || 0;
        const sign = n < 0 ? '-' : '';
        const abs = Math.abs(n).toLocaleString(undefined, { maximumFractionDigits: 2 });
        return `${sign}$${abs}`;
    }
    function fmtPct(v) {
        const n = Number(v) || 0;
        return `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`;
    }
    function dateDaysAgo(n) {
        const d = new Date(Date.now() - n * 86400000);
        return d.toISOString().slice(0, 10);
    }
    function epochFromDate(dateStr, endOfDay) {
        // Dates are entered in the user's local tz; backend expects UTC
        // unix seconds. We use local-midnight semantics because that's
        // what the input[type=date] widget shows.
        const d = new Date(dateStr + (endOfDay ? 'T23:59:59' : 'T00:00:00'));
        return Math.floor(d.getTime() / 1000);
    }

    // ── Render form + container skeleton ────────────────────────────
    function renderShell() {
        const host = document.getElementById('backtest-content');
        if (!host) return;
        host.innerHTML = `
<div class="bt-wrap" style="display:grid;grid-template-columns:340px 1fr;gap:20px;align-items:start">
  <!-- ── Parameter form ── -->
  <form id="bt-form" style="background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:18px">
    <h3 style="margin:0 0 14px;font-size:14px;letter-spacing:.04em;color:var(--text-dim);text-transform:uppercase">Parameters</h3>

    <label class="bt-lbl">From
      <input type="date" id="bt-start" value="${dateDaysAgo(30)}" required>
    </label>
    <label class="bt-lbl">To
      <input type="date" id="bt-end"   value="${dateDaysAgo(0)}"  required>
    </label>

    <label class="bt-lbl">Initial capital (USD)
      <input type="number" id="bt-capital" value="10000" min="100" step="100">
    </label>

    <label class="bt-lbl">Position sizing
      <select id="bt-posmode">
        <option value="fixed" selected>Fixed amount per trade</option>
        <option value="risk_pct">% of equity per trade</option>
      </select>
    </label>
    <div id="bt-fixed-row">
    <label class="bt-lbl">Fixed margin per trade (USD)
      <input type="number" id="bt-fixed" value="200" min="1" step="10">
    </label>
    </div>
    <div id="bt-risk-row" style="display:none">
    <label class="bt-lbl">Risk per trade (% of equity)
      <input type="number" id="bt-risk" value="2" min="0.1" max="50" step="0.1">
    </label>
    </div>

    <label class="bt-lbl">Fee per side (%)
      <input type="number" id="bt-fee" value="0.05" min="0" max="0.5" step="0.01">
    </label>

    <label class="bt-lbl">ATR multiplier sweep (comma-separated, optional)
      <input type="text" id="bt-atr-sweep" placeholder="e.g. 1.5, 2.0, 2.5, 3.0">
    </label>

    <p style="font-size:11px;color:var(--text-dim);margin:0 0 12px;padding:8px 10px;background:rgba(16,185,129,.07);border:1px solid rgba(16,185,129,.2);border-radius:6px;line-height:1.5">
      📊 Uses the actual recorded outcome of each signal — the same PnL Aladdin computed at close. Results match what you would have seen following every signal on Binance with the sizing below.
    </p>

    <div id="bt-quota" style="font-size:11px;color:var(--text-dim);margin-bottom:8px;text-align:center"></div>
    <button type="submit" class="btn btn-primary" style="width:100%;margin-top:4px" id="bt-submit">
      Run backtest
    </button>
  </form>

  <!-- ── Results ── -->
  <div id="bt-results" style="min-height:200px;background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:20px">
    <p style="color:var(--text-dim);font-size:13px;text-align:center;padding:40px 0">
      Choose your parameters and click <strong style="color:var(--text)">Run backtest</strong>.
    </p>
  </div>
</div>

<!-- ── Recent runs ── -->
<div id="bt-history" style="margin-top:24px"></div>

<style>
.bt-lbl { display:block; font-size:12px; color:var(--text-dim); margin-bottom:12px; }
.bt-lbl input, .bt-lbl select {
  width:100%; margin-top:4px; padding:8px 10px;
  background:var(--bg); border:1px solid var(--border); border-radius:6px;
  color:var(--text); font-size:13px;
}
.bt-stat { background:var(--bg); border:1px solid var(--border); border-radius:8px;
           padding:14px; min-width:0; }
.bt-stat-lbl { font-size:10px; color:var(--text-dim); letter-spacing:.06em;
               text-transform:uppercase; margin-bottom:4px; }
.bt-stat-val { font-size:20px; font-weight:700; }
.bt-pos { color:var(--green); }
.bt-neg { color:var(--red); }
.bt-tbl { width:100%; border-collapse:collapse; font-size:12px; }
.bt-tbl th, .bt-tbl td { padding:6px 8px; border-bottom:1px solid var(--border);
                          text-align:left; white-space:nowrap; }
.bt-tbl th { color:var(--text-dim); font-weight:600; font-size:10px;
             text-transform:uppercase; letter-spacing:.05em; }
.bt-tbl tr:hover td { background:rgba(255,255,255,.02); }
</style>
`;
        document.getElementById('bt-form').addEventListener('submit', onSubmit);
        // Position mode toggle
        document.getElementById('bt-posmode').addEventListener('change', function() {
            const fixed = this.value === 'fixed';
            document.getElementById('bt-fixed-row').style.display = fixed ? '' : 'none';
            document.getElementById('bt-risk-row').style.display  = fixed ? 'none' : '';
        });
        loadHistory();
        loadQuota();
    }

    // ── Quota badge ─────────────────────────────────────────────────
    function updateQuotaBadge(q) {
        const el = document.getElementById('bt-quota');
        if (!el || !q) return;
        const submit = document.getElementById('bt-submit');
        // Admin: unlimited
        if (q.admin) {
            el.innerHTML = `<span style="color:var(--green)">✓ Admin — unlimited backtests</span>`;
            if (submit) submit.disabled = false;
            return;
        }
        const remaining = Math.max(0, q.limit - q.used);
        const color = remaining === 0 ? 'var(--red)' : remaining <= 2 ? '#f59e0b' : 'var(--text-dim)';
        el.innerHTML = `<span style="color:${color}">
            ${remaining} of ${q.limit} backtests remaining this month
        </span>`;
        if (submit) submit.disabled = remaining === 0;
    }

    async function loadQuota() {
        try {
            const res = await fetch('/api/backtest/list', { headers: authHeaders() });
            if (!res.ok) return;
            const data = await res.json();
            if (data.quota) updateQuotaBadge(data.quota);
        } catch (e) { /* ignore */ }
    }

    // ── Equity-curve SVG (plain math, no library) ───────────────────
    function equityCurveSvg(trades, initial) {
        if (!trades.length) return '';
        const W = 880, H = 260, pad = 28;
        const xs = trades.map((_, i) => i);
        const ys = trades.map(t => t.equity_after);
        const yMin = Math.min(initial, ...ys);
        const yMax = Math.max(initial, ...ys);
        const xRng = xs.length - 1 || 1;
        const yRng = (yMax - yMin) || 1;
        const toX = i => pad + (i / xRng) * (W - 2 * pad);
        const toY = v => H - pad - ((v - yMin) / yRng) * (H - 2 * pad);

        // Baseline (initial capital)
        const baselineY = toY(initial);
        // Area + line path
        let d = `M ${toX(0)},${toY(initial)}`;
        xs.forEach((i, idx) => { d += ` L ${toX(i)},${toY(ys[idx])}`; });
        const areaD = d + ` L ${toX(xRng)},${H - pad} L ${toX(0)},${H - pad} Z`;

        const finalEq = ys[ys.length - 1];
        const profit = finalEq >= initial;
        const lineColor = profit ? 'var(--green)' : 'var(--red)';
        const areaColor = profit ? 'rgba(16,185,129,.12)' : 'rgba(239,68,68,.12)';

        return `
<svg viewBox="0 0 ${W} ${H}" style="width:100%;height:${H}px;display:block">
  <defs>
    <linearGradient id="btGrad" x1="0" x2="0" y1="0" y2="1">
      <stop offset="0%"   stop-color="${lineColor}" stop-opacity=".18"/>
      <stop offset="100%" stop-color="${lineColor}" stop-opacity="0"/>
    </linearGradient>
  </defs>
  <line x1="${pad}" x2="${W - pad}" y1="${baselineY}" y2="${baselineY}"
        stroke="var(--border)" stroke-dasharray="4,4" />
  <path d="${areaD}" fill="url(#btGrad)" />
  <path d="${d}"    fill="none" stroke="${lineColor}" stroke-width="1.6" />
  <text x="${W - pad}" y="${baselineY - 6}" text-anchor="end"
        font-size="10" fill="var(--text-dim)">
    baseline ${fmtUsd(initial)}
  </text>
</svg>`;
    }

    // ── Stats grid ──────────────────────────────────────────────────
    function renderStats(stats, initial) {
        const pfCol = stats.profit_factor >= 1 ? 'bt-pos' : 'bt-neg';
        const pnlCol = stats.net_pnl_usd >= 0 ? 'bt-pos' : 'bt-neg';
        return `
<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:10px;margin-bottom:20px">
  <div class="bt-stat"><div class="bt-stat-lbl">Net PnL</div>
      <div class="bt-stat-val ${pnlCol}">${fmtUsd(stats.net_pnl_usd)}</div>
      <div style="font-size:11px;color:var(--text-dim)">${fmtPct(stats.net_pnl_pct)}</div></div>
  <div class="bt-stat"><div class="bt-stat-lbl">Final equity</div>
      <div class="bt-stat-val">${fmtUsd(stats.final_equity)}</div>
      <div style="font-size:11px;color:var(--text-dim)">from ${fmtUsd(initial)}</div></div>
  <div class="bt-stat"><div class="bt-stat-lbl">Trades</div>
      <div class="bt-stat-val">${stats.trades}</div>
      <div style="font-size:11px;color:var(--text-dim)">${stats.wins}W / ${stats.losses}L</div></div>
  <div class="bt-stat"><div class="bt-stat-lbl">Win rate</div>
      <div class="bt-stat-val">${stats.win_rate.toFixed(1)}%</div></div>
  <div class="bt-stat"><div class="bt-stat-lbl">Profit factor</div>
      <div class="bt-stat-val ${pfCol}">${stats.profit_factor.toFixed(2)}</div></div>
  <div class="bt-stat"><div class="bt-stat-lbl">Max drawdown</div>
      <div class="bt-stat-val bt-neg">-${stats.max_drawdown_pct.toFixed(2)}%</div></div>
  <div class="bt-stat"><div class="bt-stat-lbl">Sharpe</div>
      <div class="bt-stat-val">${stats.sharpe.toFixed(2)}</div></div>
  <div class="bt-stat"><div class="bt-stat-lbl">Sortino</div>
      <div class="bt-stat-val">${stats.sortino.toFixed(2)}</div></div>
</div>`;
    }

    // ── Trade table ─────────────────────────────────────────────────
    function renderTrades(trades) {
        const capped = trades.slice(-200).reverse();
        const rows = capped.map(t => {
            const col = t.pnl_usd >= 0 ? 'bt-pos' : 'bt-neg';
            const dt  = fmtLocalDt(t.entry_ts);
            return `<tr>
  <td>${dt}</td>
  <td>${t.pair}</td>
  <td>${t.direction}</td>
  <td>${Number(t.entry_price).toPrecision(5)}</td>
  <td>${Number(t.exit_price).toPrecision(5)}</td>
  <td>${t.exit_reason}</td>
  <td class="${col}">${fmtPct(t.pnl_pct)}</td>
  <td class="${col}">${fmtUsd(t.pnl_usd)}</td>
  <td>${fmtUsd(t.equity_after)}</td>
</tr>`;
        }).join('');
        const note = trades.length > 200
            ? `<p style="color:var(--text-dim);font-size:11px;margin:8px 0">Showing most recent 200 of ${trades.length} trades.</p>`
            : '';
        return `
<h3 style="font-size:13px;letter-spacing:.04em;color:var(--text-dim);text-transform:uppercase;margin:0 0 10px">
  Trades${note ? ` (${trades.length})` : ''}
</h3>
<div style="max-height:400px;overflow:auto;border:1px solid var(--border);border-radius:8px">
  <table class="bt-tbl">
    <thead><tr>
      <th>Entry (UTC)</th><th>Pair</th><th>Side</th>
      <th>Entry</th><th>Exit</th><th>Reason</th>
      <th>PnL %</th><th>PnL $</th><th>Equity</th>
    </tr></thead>
    <tbody>${rows}</tbody>
  </table>
</div>${note}`;
    }

    // ── Submit handler ──────────────────────────────────────────────
    async function onSubmit(ev) {
        ev.preventDefault();
        const submit = document.getElementById('bt-submit');
        const results = document.getElementById('bt-results');
        submit.disabled = true;
        submit.textContent = '⏳ Running…';
        results.innerHTML = `<p style="color:var(--text-dim);text-align:center;padding:40px 0">
            Loading signal outcomes from Binance records…</p>`;

        const posMode = document.getElementById('bt-posmode').value;
        const atrRaw = (document.getElementById('bt-atr-sweep').value || '').trim();
        const atrSweep = atrRaw
            ? atrRaw.split(',').map(s => parseFloat(s.trim())).filter(n => !isNaN(n) && n > 0)
            : null;

        const params = {
            start:           epochFromDate(document.getElementById('bt-start').value, false),
            end:             epochFromDate(document.getElementById('bt-end').value,   true),
            initial_capital: Number(document.getElementById('bt-capital').value),
            position_mode:   posMode,
            fixed_amount:    Number(document.getElementById('bt-fixed').value),
            risk_pct:        Number((document.getElementById('bt-risk') || {value: 2}).value),
            leverage:        0,   // actual mode: signal leverage is already in recorded PnL
            fee_pct:         Number(document.getElementById('bt-fee').value),
            atr_multipliers: atrSweep && atrSweep.length ? atrSweep : null,
        };

        try {
            const res = await fetch('/api/backtest/run', {
                method: 'POST',
                headers: Object.assign({ 'Content-Type': 'application/json' }, authHeaders()),
                body: JSON.stringify(params),
            });
            const data = await res.json();
            if (res.status === 429) {
                const q = data.quota || {};
                results.innerHTML = `<div style="text-align:center;padding:30px 0">
                    <p style="color:var(--red);font-size:15px;font-weight:600;margin-bottom:8px">Monthly limit reached</p>
                    <p style="color:var(--text-dim);font-size:13px">${data.error || ''}</p>
                    ${ q.limit < 50 ? '<p style="color:var(--text-dim);font-size:12px;margin-top:12px">Upgrade your plan for more backtests per month.</p>' : '' }
                </div>`;
                updateQuotaBadge(q);
                return;
            }
            if (!res.ok || data.error) throw new Error(data.error || `HTTP ${res.status}`);
            _lastRun = data;
            if (data.quota) updateQuotaBadge(data.quota);
            renderRunOrSweep(data);
            loadHistory();
        } catch (e) {
            results.innerHTML = `<p style="color:var(--red);text-align:center;padding:30px 0">
                Error: ${e.message}</p>`;
        } finally {
            submit.disabled = false;
            submit.textContent = 'Run backtest';
        }
    }

    // ── ATR sweep results table (sorted by PnL desc) ────────────────
    function renderSweepResults(results) {
        if (!results || !results.length) return '';
        // Already sorted by pnl_usd desc on the backend.
        const rows = results.map(r => {
            const pnlCol = r.pnl_usd >= 0 ? 'bt-pos' : 'bt-neg';
            return `<tr>
  <td>${r.atr_multiplier.toFixed(1)}×</td>
  <td class="${pnlCol}">${fmtUsd(r.pnl_usd)}</td>
  <td class="${pnlCol}">${fmtPct(r.pnl_pct)}</td>
  <td class="bt-neg">${r.drawdown.toFixed(2)}%</td>
  <td>${r.trades}</td>
  <td>${r.wins}W / ${r.losses}L</td>
  <td>${r.win_rate.toFixed(1)}%</td>
  <td>${r.profit_factor.toFixed(2)}</td>
  <td>${r.sharpe.toFixed(2)}</td>
  <td>${r.sortino.toFixed(2)}</td>
</tr>`;
        }).join('');
        return `
<h3 style="font-size:13px;letter-spacing:.04em;color:var(--text-dim);text-transform:uppercase;margin:0 0 10px">
  ATR Multiplier Sweep — ${results.length} configurations (sorted by PnL ↓)
</h3>
<div style="max-height:500px;overflow:auto;border:1px solid var(--border);border-radius:8px">
  <table class="bt-tbl">
    <thead><tr>
      <th>ATR Mult</th><th>PnL $</th><th>PnL %</th><th>Drawdown</th>
      <th>Trades</th><th>W / L</th><th>Win%</th><th>PF</th><th>Sharpe</th><th>Sortino</th>
    </tr></thead>
    <tbody>${rows}</tbody>
  </table>
</div>`;
    }

    function renderRun(run) {
        const results = document.getElementById('bt-results');
        if (!run || !run.stats || run.status !== 'done') {
            results.innerHTML = `<p style="color:var(--red);text-align:center;padding:30px 0">
                Run ${run && run.id}: ${run && run.error || 'unknown error'}</p>`;
            return;
        }
        const p = run.params || {};
        const header = `
<div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:14px">
  <h3 style="margin:0;font-size:16px">Run #${run.id}</h3>
  <small style="color:var(--text-dim)">
    ${p.sl_mode || 'strict'} SL · ${p.tp_mode || 'first'} TP ·
    ${p.leverage}× · ${p.risk_pct}% risk · ${p.fee_pct}% fee
  </small>
</div>`;
        results.innerHTML = header
            + renderStats(run.stats, p.initial_capital)
            + '<div style="background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:10px;margin-bottom:20px">'
            + equityCurveSvg(run.trades || [], p.initial_capital)
            + '</div>'
            + renderTrades(run.trades || []);
    }

    function renderRunOrSweep(data) {
        const results = document.getElementById('bt-results');
        // Sweep path: data.results is a list of per-multiplier KPI dicts
        if (data.results && data.results.length > 0 && 'atr_multiplier' in data.results[0]) {
            results.innerHTML = renderSweepResults(data.results);
            return;
        }
        // Legacy path: full run payload with stats + trades
        if (data.stats) {
            renderRun(data);
            return;
        }
        results.innerHTML = `<p style="color:var(--red);text-align:center;padding:30px 0">
            No results returned.</p>`;
    }

    // ── History ─────────────────────────────────────────────────────
    async function loadHistory() {
        const host = document.getElementById('bt-history');
        if (!host) return;
        try {
            const res = await fetch('/api/backtest/list', { headers: authHeaders() });
            if (!res.ok) return;
            const data = await res.json();
            if (data.quota) updateQuotaBadge(data.quota);
            const runs = (data.runs || []).filter(r => r.status === 'done');
            if (!runs.length) { host.innerHTML = ''; return; }
            const rows = runs.map(r => {
                const p = r.params || {};
                const s = r.stats  || {};
                const col = (s.net_pnl_usd || 0) >= 0 ? 'bt-pos' : 'bt-neg';
                const sizing = p.position_mode === 'fixed'
                    ? `$${p.fixed_amount} fixed`
                    : `${p.risk_pct}% risk`;
                return `<tr>
  <td>#${r.id}</td>
  <td>${fmtLocalDt(r.created_at)}</td>
  <td>${sizing}</td>
  <td>${s.trades || 0}</td>
  <td>${(s.win_rate || 0).toFixed(1)}%</td>
  <td class="${col}">${fmtUsd(s.net_pnl_usd)}</td>
  <td><button class="btn" style="padding:3px 10px;font-size:11px"
              onclick="window.__btLoad(${r.id})">View</button></td>
</tr>`;
            }).join('');
            host.innerHTML = `
<h3 style="font-size:13px;letter-spacing:.04em;color:var(--text-dim);text-transform:uppercase;margin:0 0 10px">
  Recent runs
</h3>
<div style="border:1px solid var(--border);border-radius:8px;overflow:hidden">
  <table class="bt-tbl">
    <thead><tr>
      <th>#</th><th>When (local)</th><th>Sizing</th><th>Trades</th><th>Win%</th><th>PnL</th><th></th>
    </tr></thead>
    <tbody>${rows}</tbody>
  </table>
</div>`;
        } catch (e) { /* ignore */ }
    }

    window.__btLoad = async function (runId) {
        const results = document.getElementById('bt-results');
        results.innerHTML = `<p style="color:var(--text-dim);text-align:center;padding:30px 0">Loading run #${runId}…</p>`;
        try {
            const res = await fetch('/api/backtest/' + runId, { headers: authHeaders() });
            const data = await res.json();
            renderRun(data);
        } catch (e) {
            results.innerHTML = `<p style="color:var(--red);text-align:center">Error loading run.</p>`;
        }
    };

    // Called by app-r7.js switchPage dispatcher.
    window.loadBacktestPage = function () {
        renderShell();
    };
})();
