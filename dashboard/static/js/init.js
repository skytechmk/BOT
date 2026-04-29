// ═══════════════════════════════════════════════════════════════
//  LIVE PRICE STREAM  (SSE fan-out from PRICE_BROADCASTER)
// ═══════════════════════════════════════════════════════════════

/**
 * Opens an SSE connection to /api/stream/prices and updates every
 * .pair-price element inside its pair-card in real time.
 *
 * Reconnects automatically after 5 s on error/drop so the stream
 * is resilient to transient network blips or server restarts.
 *
 * DOM contract:
 *   Pair cards must have  id="card-{SYMBOL}USDT"
 *   Price cell must have  class="pair-price"  inside that card.
 */
function connectPriceStream() {
    const token = localStorage.getItem('aladdin_token');
    if (!token) return;  // not authenticated — skip

    const evtSource = new EventSource('/api/stream/prices?token=' + encodeURIComponent(token));

    function applyPrices(prices) {
        if (!prices || typeof prices !== 'object') return;
        Object.entries(prices).forEach(([symbol, price]) => {
            // Match elements via id="card-BTCUSDT" containing .pair-price
            const el = document.querySelector('#card-' + symbol + ' .pair-price');
            if (el && typeof formatPrice === 'function') {
                el.textContent = formatPrice(price);
            }
        });
    }

    // Initial full snapshot — paint all prices immediately on connect
    evtSource.addEventListener('snapshot', function(e) {
        try { applyPrices(JSON.parse(e.data).prices); } catch(_) {}
    });

    // Subsequent per-tick diffs/snapshots every ~1 s
    evtSource.addEventListener('tick', function(e) {
        try { applyPrices(JSON.parse(e.data).prices); } catch(_) {}
    });

    // Reconnect on error with a 5-second back-off
    evtSource.onerror = function() {
        evtSource.close();
        setTimeout(connectPriceStream, 5000);
    };
}

// ═══════════════════════════════════════════════════════════════
//  INIT
// ═══════════════════════════════════════════════════════════════
(async function() {
    await checkAuth();
    connectPriceStream();
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

    // Periodic refresh — signals & monitored pairs (prices handled via SSE)
    setInterval(loadMonitored, 60000);
    setInterval(() => {
        if (_currentPage === 'signals') loadSignals();
    }, 30000);
})();
