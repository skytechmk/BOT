// ═══════════════════════════════════════════════════════════════
//  INIT
// ═══════════════════════════════════════════════════════════════
(async function() {
    await checkAuth();
    loadMonitored();
    loadSignals();

    // Periodic refresh
    setInterval(loadMonitored, 60000);
    setInterval(() => {
        if (_currentPage === 'signals') loadSignals();
    }, 30000);
})();
