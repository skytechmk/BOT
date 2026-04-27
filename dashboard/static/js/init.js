// ═══════════════════════════════════════════════════════════════
//  INIT
// ═══════════════════════════════════════════════════════════════
(async function() {
    await checkAuth();
    loadMonitored();
    loadSignals();

    // Fetch live KPIs for landing-page hero stats
    try {
        const res = await fetch('/api/kpis');
        if (res.ok) {
            const k = await res.json();
            const sc = document.getElementById('summary-cards');
            if (sc) {
                sc.innerHTML = `
                    <div class=\"metric-card blue\"><div class=\"metric-label\">Total Signals</div><div class=\"metric-value\">${k.total_signals}</div></div>
                    <div class=\"metric-card gold\"><div class=\"metric-label\">Signals (30d)</div><div class=\"metric-value\">${k.signals_last_30d}</div></div>
                    <div class=\"metric-card green\"><div class=\"metric-label\">Win Rate</div><div class=\"metric-value\">${k.win_rate}%</div></div>
                    <div class=\"metric-card ${k.total_pnl>=0?'green':'red'}\"><div class=\"metric-label\">Total PnL</div><div class=\"metric-value\">${k.total_pnl>0?'+':''}${k.total_pnl}%</div></div>`;
            }
        }
    } catch(e) { /* ignore */ }

    // Periodic refresh
    setInterval(loadMonitored, 60000);
    setInterval(() => {
        if (_currentPage === 'signals') loadSignals();
    }, 30000);
})();
