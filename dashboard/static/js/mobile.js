// ═══════════════════════════════════════════════════════════════
//  ANUNNAKI WORLD — MOBILE UX
//  Bottom Tab Bar · Slide-up Drawer · Signal Badge · Toast · PTR
// ═══════════════════════════════════════════════════════════════

const _MOBILE_BP = 768;
const isMobile = () => window.innerWidth <= _MOBILE_BP;

// ── Bottom nav page mapping ─────────────────────────────────────
// Maps bottom nav data-page → actual switchPage() page key
const _MBN_PAGES = {
    'overview':  'overview',
    'signals':   'signals',
    'charts':    'charts',
    'heatmap':   'heatmap',
    'more':      null,       // opens drawer instead of switching page
};

// Pages NOT in bottom nav — live in the "More" drawer
const _DRAWER_PAGES = [
    { page: 'analytics',   icon: '📈', name: 'Analytics',    sub: 'Performance stats',    tierMin: 'plus' },
    { page: 'presignals',  icon: '🎯', name: 'Pre-Signals',  sub: 'Early alerts',          tierMin: 'plus'  },
    { page: 'screener',    icon: '📺', name: 'Screener',     sub: 'TV market scan',        tierMin: 'plus' },
    { page: 'copytrading', icon: '🤖', name: 'Copy-Trade',   sub: 'Mirror our positions',  tierMin: 'plus'  },
    { page: 'account',     icon: '👤', name: 'Account',      sub: 'Profile & security',    tierMin: null   },
    { page: 'pricing',     icon: '💎', name: 'Pricing',      sub: 'Plans & upgrades',      tierMin: null   },
    { page: 'refer',       icon: '🔗', name: 'Refer & Earn', sub: 'Get free months',       tierMin: null   },
    { page: 'support',     icon: '💬', name: 'Support',      sub: 'Get help',              tierMin: null   },
    { page: 'manual',      icon: '📖', name: 'Manual',       sub: 'How it works',          tierMin: null   },
    { page: 'admin',       icon: '⚙️',  name: 'Admin',        sub: 'Dashboard admin',       tierMin: 'admin', adminOnly: true },
];

// ── State ───────────────────────────────────────────────────────
let _drawerOpen   = false;
let _currentMbnPage = 'overview';
let _signalBadgeCount = 0;

// ── Init ────────────────────────────────────────────────────────
function initMobileNav() {
    if (!isMobile()) return;

    _buildDrawerContent();
    _bindBottomNav();
    _bindDrawer();
    _bindPullToRefresh();
    _syncMbnActive(_currentMbnPage);
    _updateDrawerUser();

    // Sync on resize (e.g. orientation change)
    window.addEventListener('resize', () => {
        if (!isMobile()) closeDrawer();
    });
}

// ── Build drawer tiles dynamically ─────────────────────────────
function _buildDrawerContent() {
    const grid = document.getElementById('drawer-nav-grid');
    if (!grid) return;

    const tier = typeof _tier !== 'undefined' ? _tier : 'free';
    // DB tier keys (plus/pro/ultra). Display names (Plus/Pro/Ultra) are handled elsewhere.
    const tierRank = { free: 0, plus: 1, pro: 2, ultra: 3, admin: 99 };
    const rank = tierRank[tier] || 0;
    const isAdmin = (typeof _user !== 'undefined' && _user && _user.is_admin) || tier === 'admin';

    grid.innerHTML = _DRAWER_PAGES
        .filter(d => !d.adminOnly || isAdmin)
        .map(d => {
            const locked = d.tierMin && (tierRank[d.tierMin] || 0) > rank && !isAdmin;
            const cls = locked ? 'drawer-tile locked' : 'drawer-tile';
            const lockBadge = locked ? `<span style="font-size:9px;color:var(--text-dim);margin-left:auto">🔒</span>` : '';
            return `<div class="${cls}" onclick="mbnNavigate('${d.page}')">
                <span class="dt-icon">${d.icon}</span>
                <span class="dt-text">
                    <span class="dt-name">${d.name}</span>
                    <span class="dt-sub">${d.sub}</span>
                </span>
                ${lockBadge}
            </div>`;
        })
        .join('');
}

// ── Haptic helper ───────────────────────────────────────────────
function _haptic(ms = 8) {
    if (navigator.vibrate) navigator.vibrate(ms);
}

// ── Bind bottom nav clicks ──────────────────────────────────────
function _bindBottomNav() {
    document.querySelectorAll('.mbn-item').forEach(item => {
        item.addEventListener('click', e => {
            _haptic(6);
            const page = item.dataset.page;
            if (page === 'more') {
                openDrawer();
            } else {
                if (typeof switchPage === 'function') switchPage(page);
                _syncMbnActive(page);
                _currentMbnPage = page;
            }
        });
    });
}

// ── Sync active state on bottom nav ────────────────────────────
function _syncMbnActive(page) {
    document.querySelectorAll('.mbn-item').forEach(item => {
        item.classList.toggle('active', item.dataset.page === page);
    });
}

// Called from switchPage() in app-r7.js to keep bottom nav in sync
function mbnSyncPage(page) {
    // If the page is in the bottom nav, activate it; otherwise activate 'more'
    const inNav = Object.keys(_MBN_PAGES).includes(page) && _MBN_PAGES[page] !== null;
    _syncMbnActive(inNav ? page : 'more');
    _currentMbnPage = page;
}

// Navigation from drawer tile
function mbnNavigate(page) {
    closeDrawer();
    if (page === 'admin') {
        // Admin has its own full-page app at /admin
        setTimeout(() => window.open('/admin', '_blank', 'noopener'), 180);
        return;
    }
    setTimeout(() => {
        if (typeof switchPage === 'function') switchPage(page);
        mbnSyncPage(page);
    }, 180); // let drawer close first
}

// ── Drawer open / close ─────────────────────────────────────────
function openDrawer() {
    if (!isMobile()) return;
    _drawerOpen = true;
    _updateDrawerUser();
    document.getElementById('mobile-drawer').classList.add('open');
    document.getElementById('mobile-drawer-overlay').classList.add('open');
    document.body.style.overflow = 'hidden';
    _syncMbnActive('more');
}

function closeDrawer() {
    _drawerOpen = false;
    const drawer = document.getElementById('mobile-drawer');
    const overlay = document.getElementById('mobile-drawer-overlay');
    if (drawer) drawer.classList.remove('open');
    if (overlay) overlay.classList.remove('open');
    document.body.style.overflow = '';
    _syncMbnActive(_currentMbnPage);
}

function _bindDrawer() {
    // Close on overlay tap
    const overlay = document.getElementById('mobile-drawer-overlay');
    if (overlay) overlay.addEventListener('click', closeDrawer);

    // Close button
    const closeBtn = document.getElementById('drawer-close-btn');
    if (closeBtn) closeBtn.addEventListener('click', closeDrawer);

    // Swipe down to close
    const drawer = document.getElementById('mobile-drawer');
    if (!drawer) return;
    let _startY = 0, _dragging = false;
    drawer.addEventListener('touchstart', e => {
        _startY = e.touches[0].clientY;
        _dragging = true;
    }, { passive: true });
    drawer.addEventListener('touchmove', e => {
        if (!_dragging) return;
        const dy = e.touches[0].clientY - _startY;
        if (dy > 0 && drawer.scrollTop === 0) {
            drawer.style.transform = `translateY(${dy}px)`;
        }
    }, { passive: true });
    drawer.addEventListener('touchend', e => {
        if (!_dragging) return;
        _dragging = false;
        const dy = e.changedTouches[0].clientY - _startY;
        if (dy > 80) {
            drawer.style.transform = '';
            closeDrawer();
        } else {
            drawer.style.transform = '';
        }
    });
}

// ── Populate user card in drawer ────────────────────────────────
function _updateDrawerUser() {
    const emailEl = document.getElementById('header-user-email');
    const tierEl  = document.getElementById('header-tier-badge');
    const ducEmail = document.getElementById('duc-email');
    const ducTier  = document.getElementById('duc-tier');
    const ducAvatar = document.getElementById('duc-avatar');

    if (!ducEmail) return;

    const email = emailEl ? emailEl.textContent.trim() : '';
    const tier  = tierEl  ? tierEl.textContent.trim() : 'FREE';

    if (email) {
        ducEmail.textContent = email;
        ducAvatar.textContent = email.charAt(0).toUpperCase();
        // Show logged-in card
        const card = document.getElementById('drawer-user-card');
        if (card) card.style.display = 'flex';
        // Show logout action
        const actionRow = document.getElementById('drawer-action-row');
        if (actionRow) actionRow.style.display = 'flex';
        // Hide login action
        const loginAction = document.getElementById('drawer-login-action');
        if (loginAction) loginAction.style.display = 'none';
    } else {
        // Logged out state
        const card = document.getElementById('drawer-user-card');
        if (card) card.style.display = 'none';
        const actionRow = document.getElementById('drawer-action-row');
        if (actionRow) actionRow.style.display = 'none';
        const loginAction = document.getElementById('drawer-login-action');
        if (loginAction) loginAction.style.display = 'flex';
    }
    ducTier.textContent = tier;
}

// ── Signal badge ────────────────────────────────────────────────
function mbnSetSignalBadge(count) {
    _signalBadgeCount = count;
    const badge = document.getElementById('mbn-badge-signals');
    if (!badge) return;
    if (count > 0) {
        badge.textContent = count > 99 ? '99+' : count;
        badge.classList.add('visible');
    } else {
        badge.classList.remove('visible');
    }
}

function mbnClearSignalBadge() {
    mbnSetSignalBadge(0);
}

// ── Toast notifications ─────────────────────────────────────────
let _toastTimer = null;
function mobileToast(msg, type = 'info', durationMs = 2800) {
    if (!isMobile()) return;
    let toast = document.getElementById('mobile-toast');
    if (!toast) {
        toast = document.createElement('div');
        toast.id = 'mobile-toast';
        toast.className = 'mobile-toast';
        document.body.appendChild(toast);
    }
    toast.textContent = msg;
    toast.className = `mobile-toast ${type}`;
    clearTimeout(_toastTimer);
    // Force reflow before adding .show
    void toast.offsetWidth;
    toast.classList.add('show');
    _toastTimer = setTimeout(() => toast.classList.remove('show'), durationMs);
}

// ── Pull-to-Refresh (overview & signals) ───────────────────────
function _bindPullToRefresh() {
    let _ptrStart = 0, _ptrActive = false;
    const THRESHOLD = 70;
    const indicator = document.getElementById('ptr-indicator');

    document.addEventListener('touchstart', e => {
        if (window.scrollY === 0 && isMobile()) {
            _ptrStart = e.touches[0].clientY;
        }
    }, { passive: true });

    document.addEventListener('touchmove', e => {
        if (!_ptrStart) return;
        const dy = e.touches[0].clientY - _ptrStart;
        if (dy > THRESHOLD && !_ptrActive) {
            _ptrActive = true;
            if (indicator) { indicator.textContent = '↓ Release to refresh'; indicator.classList.add('visible'); }
        }
    }, { passive: true });

    document.addEventListener('touchend', () => {
        if (_ptrActive) {
            _ptrActive = false;
            _ptrStart = 0;
            if (indicator) { indicator.textContent = '↻ Refreshing...'; }
            // Trigger refresh based on active page
            const page = _currentMbnPage;
            if (page === 'overview'  && typeof loadOverview === 'function')  loadOverview();
            if (page === 'signals'   && typeof loadSignals  === 'function')  loadSignals();
            if (page === 'charts'    && typeof loadCharts   === 'function')  loadCharts();
            if (page === 'heatmap'   && typeof loadLiqHeatmap === 'function') loadLiqHeatmap();
            setTimeout(() => {
                if (indicator) indicator.classList.remove('visible');
            }, 1200);
        }
        _ptrStart = 0;
    });
}

// ── Swipe navigation between main tabs ─────────────────────────
const _SWIPE_TABS = ['overview', 'signals', 'charts', 'heatmap'];
let _swipeStartX = 0, _swipeStartY = 0, _swipeLocked = false;

function _bindSwipeNav() {
    const content = document.querySelector('.main-content') || document.body;

    content.addEventListener('touchstart', e => {
        _swipeStartX = e.touches[0].clientX;
        _swipeStartY = e.touches[0].clientY;
        _swipeLocked = false;
    }, { passive: true });

    content.addEventListener('touchmove', e => {
        if (_swipeLocked) return;
        const dx = e.touches[0].clientX - _swipeStartX;
        const dy = e.touches[0].clientY - _swipeStartY;
        // Only lock if horizontal movement dominates and exceeds threshold
        if (Math.abs(dx) > 16 && Math.abs(dx) > Math.abs(dy) * 1.8) {
            _swipeLocked = true;
        }
    }, { passive: true });

    content.addEventListener('touchend', e => {
        if (!_swipeLocked) return;
        const dx = e.changedTouches[0].clientX - _swipeStartX;
        if (Math.abs(dx) < 60) return;

        const currentIdx = _SWIPE_TABS.indexOf(_currentMbnPage);
        if (currentIdx === -1) return; // not a swipeable page

        if (dx < 0 && currentIdx < _SWIPE_TABS.length - 1) {
            // Swipe left → next tab
            _haptic(8);
            const next = _SWIPE_TABS[currentIdx + 1];
            if (typeof switchPage === 'function') switchPage(next);
            _syncMbnActive(next);
            _currentMbnPage = next;
        } else if (dx > 0 && currentIdx > 0) {
            // Swipe right → prev tab
            _haptic(8);
            const prev = _SWIPE_TABS[currentIdx - 1];
            if (typeof switchPage === 'function') switchPage(prev);
            _syncMbnActive(prev);
            _currentMbnPage = prev;
        }
        _swipeLocked = false;
    });
}

// ── Drawer quick-stats ──────────────────────────────────────────
async function _loadDrawerQuickStats() {
    const strip = document.getElementById('drawer-quickstats');
    if (!strip) return;

    // Show strip only when logged in
    const emailEl = document.getElementById('header-user-email');
    if (!emailEl || !emailEl.textContent.trim()) return;
    strip.style.display = 'flex';

    // Active signals count
    try {
        const res = await fetch('/api/signals', { headers: typeof authHeaders === 'function' ? authHeaders() : {} });
        if (res.ok) {
            const data = await res.json();
            const active = (data.signals || []).filter(s => s.status === 'OPEN' || s.status === 'open').length;
            const el = document.getElementById('dqs-signals-val');
            if (el) {
                el.textContent = active;
                el.style.color = active > 0 ? 'var(--gold)' : 'var(--text-dim)';
            }
        }
    } catch (_) {}

    // Live balance (unrealized PnL + futures balance)
    try {
        const res = await fetch('/api/copy-trading/balance', { headers: typeof authHeaders === 'function' ? authHeaders() : {} });
        if (res.ok) {
            const data = await res.json();
            if (!data.error) {
                const pnl  = data.unrealized_pnl ?? 0;
                const bal  = data.balance_usdt ?? null;
                const pnlEl = document.getElementById('dqs-pnl-val');
                const balEl = document.getElementById('dqs-balance-val');
                if (pnlEl) {
                    pnlEl.textContent = (pnl >= 0 ? '+' : '') + pnl.toFixed(2) + ' USDT';
                    pnlEl.style.color = pnl >= 0 ? 'var(--green)' : 'var(--red)';
                }
                if (balEl && bal != null) {
                    balEl.textContent = '$' + bal.toFixed(2);
                    balEl.style.color = 'var(--gold)';
                }
            }
        }
    } catch (_) {}
}

// ── Mobile trade history cards (replaces table on phone) ────────
function renderMobileTradeCards(trades) {
    const wrap = document.getElementById('ct-history-cards');
    if (!wrap) return;
    if (!trades || !trades.length) {
        wrap.innerHTML = '<div style="text-align:center;color:var(--text-dim);font-size:13px;padding:16px 0">No trades yet.</div>';
        return;
    }
    const _sign = n => n >= 0 ? '+' : '';
    const _col  = n => n >= 0 ? 'var(--green)' : 'var(--red)';
    wrap.innerHTML = trades.map(t => {
        const isOpen = t.status === 'open';
        const pnlU   = t.pnl_usd != null ? t.pnl_usd : 0;
        const pnlP   = t.pnl_pct != null ? t.pnl_pct : 0;
        const dirCol = t.direction === 'LONG' ? 'var(--green)' : 'var(--red)';
        const ts     = t.created_at ? new Date(t.created_at * 1000).toLocaleDateString('en-GB',
            {day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'}) : '—';
        const statusBg = {open:'#1565c0',closed:'#2e7d32',skipped:'#5d4037',error:'#b71c1c'}[t.status] || '#333';

        return `<div class="ct-trade-card">
            <div class="ctc-row">
                <div style="display:flex;align-items:center;gap:8px">
                    <span class="ctc-pair">${(t.pair||'—').replace('USDT','')}<span style="color:var(--text-dim);font-size:11px;font-weight:400">/USDT</span></span>
                    <span style="color:${dirCol};font-size:11px;font-weight:700">${t.direction||'—'}</span>
                    <span style="background:${statusBg};color:#fff;font-size:9px;font-weight:700;padding:2px 6px;border-radius:3px">${(t.status||'—').toUpperCase()}</span>
                </div>
                <div class="ctc-pnl-block">
                    <div style="color:${_col(pnlU)};font-weight:800;font-size:14px">${_sign(pnlU)}${pnlU.toFixed(2)} <span style="font-size:10px;font-weight:400">USDT</span></div>
                    <div style="color:${_col(pnlP)};font-size:11px">${_sign(pnlP)}${pnlP.toFixed(2)}%${isOpen ? '<span style="color:var(--text-dim);margin-left:4px;font-size:9px">UNREAL.</span>' : ''}</div>
                </div>
            </div>
            <div class="ctc-meta">
                <span>$${(t.size_usd||0).toFixed(0)} · ${t.leverage||'—'}× lev</span>
                <span>Entry: ${t.entry_price ? (typeof formatPrice === 'function' ? formatPrice(t.entry_price) : t.entry_price) : '—'}</span>
                <span>${ts}</span>
                ${isOpen ? `<button onclick="ctClosePosition('${t.pair}')" style="padding:2px 8px;font-size:9px;font-weight:700;border-radius:4px;background:transparent;border:1px solid #f44336;color:#f44336;cursor:pointer;margin-left:auto">Close</button>` : ''}
            </div>
        </div>`;
    }).join('');
}

// ── Pull-to-Refresh (all main pages) ───────────────────────────
function _bindPullToRefresh() {
    let _ptrStart = 0, _ptrActive = false;
    const THRESHOLD = 70;
    const indicator = document.getElementById('ptr-indicator');
    const _loaders = {
        overview:  () => typeof loadOverview    === 'function' && loadOverview(),
        signals:   () => typeof loadSignals     === 'function' && loadSignals(),
        charts:    () => typeof renderChartsPage === 'function' && renderChartsPage(),
        heatmap:   () => typeof initLiqHeatmap  === 'function' && initLiqHeatmap(),
    };

    document.addEventListener('touchstart', e => {
        if (window.scrollY === 0 && isMobile()) {
            _ptrStart = e.touches[0].clientY;
        }
    }, { passive: true });

    document.addEventListener('touchmove', e => {
        if (!_ptrStart) return;
        const dy = e.touches[0].clientY - _ptrStart;
        if (dy > THRESHOLD && !_ptrActive) {
            _ptrActive = true;
            if (indicator) { indicator.textContent = '↓ Release to refresh'; indicator.classList.add('visible'); }
        }
    }, { passive: true });

    document.addEventListener('touchend', () => {
        if (_ptrActive) {
            _ptrActive = false;
            _ptrStart = 0;
            if (indicator) indicator.textContent = '↻ Refreshing…';
            const loader = _loaders[_currentMbnPage];
            if (loader) loader();
            setTimeout(() => {
                if (indicator) indicator.classList.remove('visible');
            }, 1400);
        }
        _ptrStart = 0;
    });
}

// ── Bootstrap ───────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    initMobileNav();
    if (isMobile()) _bindSwipeNav();
});

// Re-init on orientation change
window.addEventListener('orientationchange', () => {
    setTimeout(initMobileNav, 200);
});

// ── Hook openDrawer to also load quick-stats ────────────────────
const _origOpenDrawer = openDrawer;
openDrawer = function() {
    _origOpenDrawer();
    _loadDrawerQuickStats();
};
