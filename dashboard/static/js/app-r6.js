// ═══════════════════════════════════════════════════════════════
//  STATE
// ═══════════════════════════════════════════════════════════════
let _user = null;
let _token = localStorage.getItem('aladdin_token');
let _tier = 'free';
let _currentPage = 'overview';
let _currentPair = null;
let _authMode = 'login';
let _selectedPlan = 'plus_monthly';
let _selectedCrypto = 'usdt_trc20';
let _paymentId = null;
let _paymentPollTimer = null;
let priceChart = null, indChart = null;
let _candleSeries = null, _volSeries = null, _ceLineSeries = null;
let _ceCloudSeries = null, _tsiSeries = null, _linregSeries = null;
let _signalCache = [];
let _entryLine = null, _slLine = null, _tpLines = [];

const _SERVER_TZ_OFFSET = 2 * 3600;
function toUnix(ts) {
    const utcStr = ts.endsWith('Z') ? ts : ts + 'Z';
    return Math.floor(new Date(utcStr).getTime() / 1000) + _SERVER_TZ_OFFSET;
}

// ═══════════════════════════════════════════════════════════════
//  AUTH
// ═══════════════════════════════════════════════════════════════
async function checkAuth() {
    if (!_token) { updateUI(); return; }
    try {
        const res = await fetch('/api/auth/me', { headers: { 'Authorization': `Bearer ${_token}` } });
        if (res.ok) {
            const data = await res.json();
            _user = data.user;
            _tier = _user.tier;
        } else {
            _token = null; _user = null; _tier = 'free';
            localStorage.removeItem('aladdin_token');
        }
    } catch(e) { _tier = 'free'; }
    updateUI();
}

function updateUI() {
    const loggedOut = document.getElementById('user-section-loggedout');
    const loggedIn = document.getElementById('user-section-loggedin');
    if (_user) {
        loggedOut.style.display = 'none';
        loggedIn.style.display = 'flex';
        document.getElementById('header-user-email').textContent = _user.email;
        const badge = document.getElementById('header-tier-badge');
        badge.textContent = _tier.toUpperCase();
        badge.className = `tier-badge ${_tier}`;
    } else {
        loggedOut.style.display = 'flex';
        loggedIn.style.display = 'none';
    }
    // Update locks
    document.getElementById('lock-charts').style.display = _tier === 'free' ? '' : 'none';
    document.getElementById('lock-analytics').style.display = ['free'].includes(_tier) ? '' : 'none';
    // Delay badge
    document.getElementById('delay-badge').style.display = _tier === 'free' ? '' : 'none';
    // Pro+ features
    const isElite = _tier === 'pro';
    document.getElementById('nav-presignals').style.display = isElite ? '' : 'none';
    const isProOrElite = ['plus','pro'].includes(_tier);
    document.getElementById('nav-heatmap').style.display = isProOrElite ? '' : 'none';
    document.getElementById('nav-screener').style.display = isProOrElite ? '' : 'none';
    // Copy-trading tab (pro+ only)
    const ctNav = document.getElementById('nav-copytrading');
    if (ctNav) ctNav.style.display = isElite ? '' : 'none';
    const tgBanner = document.getElementById('pro-telegram-banner');
    if (isElite && _user && _user.telegram_invite) {
        tgBanner.classList.add('visible');
        document.getElementById('telegram-invite-link').href = _user.telegram_invite;
    } else {
        tgBanner.classList.remove('visible');
    }
    // Manual lock icon (visible for free, hidden for paid)
    const lockManual = document.getElementById('lock-manual');
    if (lockManual) lockManual.style.display = _tier === 'free' ? '' : 'none';
    // Manual overlay
    const manualOverlay = document.getElementById('manual-lock-overlay');
    if (manualOverlay) manualOverlay.style.display = _tier === 'free' ? 'flex' : 'none';
    // Admin tab
    document.getElementById('nav-admin').style.display = (_user && _user.is_admin) ? '' : 'none';
    // Subscription timer
    updateSubTimer();
}

function updateSubTimer() {
    const el = document.getElementById('sub-timer');
    if (!_user || _tier === 'free' || !_user.tier_expires) {
        el.classList.remove('visible'); return;
    }
    const now = Date.now() / 1000;
    const left = _user.tier_expires - now;
    if (left <= 0) { el.classList.remove('visible'); return; }
    const days = Math.floor(left / 86400);
    const hours = Math.floor((left % 86400) / 3600);
    let cls = 'ok';
    if (days <= 3) cls = 'critical';
    else if (days <= 7) cls = 'warning';
    el.className = `sub-timer visible ${cls}`;
    el.textContent = days > 0 ? `${days}d ${hours}h remaining` : `${hours}h remaining`;
}

function openModal(mode) {
    _authMode = mode;
    document.getElementById('modal-auth').classList.add('open');
    document.getElementById('auth-modal-title').textContent = mode === 'login' ? 'Login' : 'Create Account';
    document.getElementById('group-username').style.display = mode === 'register' ? 'block' : 'none';
    document.getElementById('label-email').textContent = mode === 'login' ? 'Email / Username' : 'Email';
    document.getElementById('input-email').placeholder = mode === 'login' ? 'Email or Username' : 'you@example.com';
    document.getElementById('auth-submit').textContent = mode === 'login' ? 'Login' : 'Register';
    document.getElementById('auth-switch-text').textContent = mode === 'login' ? "Don't have an account?" : 'Already have an account?';
    document.getElementById('auth-switch-link').textContent = mode === 'login' ? 'Register' : 'Login';
    document.getElementById('auth-error').style.display = 'none';
    const fpLink = document.getElementById('forgot-pw-link');
    if (fpLink) fpLink.style.display = mode === 'login' ? 'block' : 'none';
    // Promo code field — only on register
    const promoGroup = document.getElementById('group-promo');
    const promoInput = document.getElementById('input-promo');
    if (promoGroup) promoGroup.style.display = mode === 'register' ? 'block' : 'none';
    // Pre-fill promo from sessionStorage and show discount banner
    const storedRef = sessionStorage.getItem('ref_code') || '';
    if (promoInput && storedRef && mode === 'register') promoInput.value = storedRef;
    const banner = document.getElementById('ref-discount-banner');
    if (banner) banner.style.display = (mode === 'register' && storedRef) ? 'block' : 'none';
}

function toggleAuthMode() {
    openModal(_authMode === 'login' ? 'register' : 'login');
}

function closeModals() {
    document.querySelectorAll('.modal-bg').forEach(m => m.classList.remove('open'));
    if (_paymentPollTimer) clearInterval(_paymentPollTimer);
}

async function submitAuth() {
    const email = document.getElementById('input-email').value.trim();
    const password = document.getElementById('input-password').value;
    const errEl = document.getElementById('auth-error');

    if (!email || password.length < 6) {
        errEl.textContent = 'Valid identifier and password (min 6 chars) required';
        errEl.style.display = 'block'; return;
    }

    // Use promo field value first, fall back to sessionStorage ref_code
    const _promoFieldVal = (document.getElementById('input-promo') || {}).value || '';
    const _refCode = _promoFieldVal.trim().toUpperCase() || sessionStorage.getItem('ref_code') || '';
    const _refSuffix = (_authMode === 'register' && _refCode) ? `?ref=${encodeURIComponent(_refCode)}` : '';
    const endpoint = _authMode === 'login' ? '/api/auth/login' : `/api/auth/register${_refSuffix}`;
    let body;
    if (_authMode === 'login') {
        body = { password, email: email.includes('@') ? email : '', username: email.includes('@') ? '' : email };
    } else {
        body = { email, password, username: document.getElementById('input-username').value.trim() };
    }

    try {
        const res = await fetch(endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        const data = await res.json();
        if (!res.ok || data.error) {
            const msg = data.error || data.detail || (res.status === 401 ? 'Wrong username or password' : 'Authentication failed');
            errEl.textContent = msg;
            errEl.style.display = 'block';
            return;
        }
        if (data.access_token) {
            _token = data.access_token;
            _user = data.user;
            _tier = _user.tier;
            localStorage.setItem('aladdin_token', _token);
            closeModals();
            updateUI();
            loadMonitored();
            loadSignals();
            // Show referral modal once per browser session
            if (!sessionStorage.getItem('referral_shown')) {
                sessionStorage.setItem('referral_shown', '1');
                setTimeout(() => {
                    document.getElementById('modal-referral').classList.add('open');
                }, 800);
            }
        }
    } catch(e) {
        errEl.textContent = 'Connection error'; errEl.style.display = 'block';
    }
}

function logout() {
    _token = null; _user = null; _tier = 'free';
    localStorage.removeItem('aladdin_token');
    updateUI(); switchPage('overview');
    loadMonitored(); loadSignals();
}

// ═══════════════════════════════════════════════════════════════
//  NAVIGATION
// ═══════════════════════════════════════════════════════════════
function switchPage(page) {
    // Check tier access
    if (page === 'charts' && _tier === 'free') {
        switchPage('pricing'); return;
    }
    if (page === 'analytics' && !['plus','pro'].includes(_tier)) {
        switchPage('pricing'); return;
    }
    if (page === 'presignals' && _tier !== 'pro') {
        switchPage('pricing'); return;
    }
    if (page === 'screener' && !['plus','pro'].includes(_tier)) {
        switchPage('pricing'); return;
    }
    if (page === 'copytrading' && _tier !== 'pro') {
        switchPage('pricing'); return;
    }
    if (page === 'admin' && (!_user || !_user.is_admin)) {
        switchPage('overview'); return;
    }
    _currentPage = page;
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    document.getElementById(`page-${page}`).classList.add('active');
    document.querySelectorAll('.nav-tab').forEach(t => t.classList.toggle('active', t.dataset.page === page));

    if (page === 'charts') renderChartsPage();
    if (page === 'analytics') loadAnalytics();
    if (page === 'signals') loadSignals();
    if (page === 'presignals') loadPreSignals();
    if (page === 'screener') loadScreener();
    if (page === 'heatmap') initLiqHeatmap();
    if (page === 'admin') loadAdminUsers();
    if (page === 'copytrading') loadCopyTradingPage();
    if (page === 'refer') loadReferralPage();
    // manual page — show/hide lock overlay based on tier
    if (page === 'manual') {
        const ov = document.getElementById('manual-lock-overlay');
        if (ov) ov.style.display = _tier === 'free' ? 'flex' : 'none';
    }
    // support page is static — no loader needed
}

// ═══════════════════════════════════════════════════════════════
//  REFERRAL
// ═══════════════════════════════════════════════════════════════
async function loadReferralPage() {
    if (!_token) {
        document.getElementById('ref-link-input').value = 'Login to get your referral link';
        return;
    }
    try {
        const res = await fetch('/api/referral/stats', { headers: authHeaders() });
        const d = await res.json();
        if (d.error) return;

        const base = window.location.origin;
        const link = `${base}/ref/${d.code}`;
        document.getElementById('ref-link-input').value = link;
        document.getElementById('ref-code-value').textContent = d.code;
        document.getElementById('ref-stat-total').textContent = d.total_referred;
        document.getElementById('ref-stat-credited').textContent = d.total_credited;
        document.getElementById('ref-stat-days').textContent = d.total_bonus_days || '0';
        document.getElementById('ref-stat-pending').textContent = d.pending;

        const list = document.getElementById('ref-events-list');
        if (!d.events || d.events.length === 0) {
            list.innerHTML = '<div style="color:var(--text-dim);font-size:13px;padding:20px 0">No referrals yet — share your link to get started!</div>';
        } else {
            list.innerHTML = d.events.map(e => {
                const badge = e.status === 'credited'
                    ? '<span style="font-size:10px;color:var(--green);background:rgba(0,200,83,0.12);padding:2px 7px;border-radius:4px;font-weight:700">CREDITED</span>'
                    : '<span style="font-size:10px;color:var(--gold);background:rgba(244,162,54,0.12);padding:2px 7px;border-radius:4px;font-weight:700">PENDING</span>';
                const days = e.bonus_days ? `+${e.bonus_days}d earned` : '';
                return `<div style="display:flex;justify-content:space-between;align-items:center;padding:12px 0;border-bottom:1px solid var(--border);font-size:13px">
                    <div style="display:flex;align-items:center;gap:10px">${badge}<span style="color:var(--text-dim)">${e.user_email}</span><span style="font-size:11px;color:var(--text-dim)">(• ${e.user_tier})</span></div>
                    <div style="color:var(--green);font-weight:700">${days}</div>
                </div>`;
            }).join('');
        }
    } catch(err) {
        console.error('Referral load error:', err);
    }
}

function copyReferralLink(btn) {
    const input = document.getElementById('ref-link-input');
    if (!input || !input.value || input.value === 'Login to get your referral link') return;
    navigator.clipboard.writeText(input.value).then(() => {
        const orig = btn.textContent;
        btn.textContent = 'Copied!';
        setTimeout(() => { btn.textContent = orig; }, 1800);
    });
}

// Pre-fill ?ref= code and auto-open register modal
(function() {
    const params = new URLSearchParams(window.location.search);
    const ref = params.get('ref');
    if (ref) {
        sessionStorage.setItem('ref_code', ref);
        window.history.replaceState({}, '', window.location.pathname);
        // Open register modal immediately — referral links always land on registration
        document.addEventListener('DOMContentLoaded', () => {
            setTimeout(() => openModal('register'), 400);
        });
        // Fallback if DOMContentLoaded already fired
        if (document.readyState !== 'loading') {
            setTimeout(() => openModal('register'), 400);
        }
    }
})();

// ═══════════════════════════════════════════════════════════════
//  UTILITIES
// ═══════════════════════════════════════════════════════════════
function authHeaders() {
    const h = {};
    if (_token) h['Authorization'] = `Bearer ${_token}`;
    return h;
}

function formatPrice(price) {
    if (!price) return '—';
    if (price >= 1000) return price.toFixed(2);
    if (price >= 1) return price.toFixed(4);
    if (price >= 0.01) return price.toFixed(5);
    return price.toFixed(6);
}

function calcRR(entry, sl, targets) {
    if (!entry || !sl || !targets || !targets.length) return null;
    const risk = Math.abs(entry - sl);
    if (risk === 0) return null;
    const bestTP = targets[targets.length - 1];
    const reward = Math.abs(bestTP - entry);
    return Math.round((reward / risk) * 100) / 100;
}

function pctDiff(a, b) {
    if (!a || !b) return '';
    return ((Math.abs(b - a) / a) * 100).toFixed(2) + '%';
}
