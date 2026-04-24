// ═══════════════════════════════════════════════════════════════
//  PAYMENTS (NOWPayments hosted checkout only)
// ═══════════════════════════════════════════════════════════════

// Cached public config — whether crypto-checkout is available
let _paymentsConfig = { crypto_checkout_enabled: false, sandbox: false };

(async function loadPaymentsConfig() {
    try {
        const res = await fetch('/api/payments/config', { cache: 'no-store' });
        if (res.ok) _paymentsConfig = await res.json();
    } catch (_) { /* silent */ }
    const btn = document.querySelector('.crypto-checkout-btn');
    const fallback = document.getElementById('crypto-checkout-fallback');
    if (btn) btn.style.display = _paymentsConfig.crypto_checkout_enabled ? 'inline-flex' : 'none';
    if (fallback) fallback.style.display = _paymentsConfig.crypto_checkout_enabled ? 'none' : 'block';
})();

function startPayment(tier) {
    if (!_user) { openModal('register'); return; }
    _selectedPlan = tier + '_monthly';
    document.getElementById('modal-payment').classList.add('open');
    document.getElementById('payment-step1').style.display = 'block';
    document.getElementById('payment-step2').style.display = 'none';
    renderPlanSelect(tier);
}

// ─── Hosted-checkout flow (NOWPayments Invoice API) ────────────────
// User clicks → we POST → get invoice_url → redirect to NOWPayments
// hosted page → user pays any of 300+ coins → auto-redirect to /payment/success
async function payWithCrypto(planId) {
    if (!_user) { openModal('register'); return; }
    const plan = planId || _selectedPlan;
    if (!plan) { alert('Please select a plan first'); return; }
    try {
        const res = await fetch('/api/payment/invoice/create', {
            method:  'POST',
            headers: { ...authHeaders(), 'Content-Type': 'application/json' },
            body:    JSON.stringify({ plan_id: plan }),
        });
        const data = await res.json();
        if (!res.ok || data.error || data.detail) {
            alert(data.error || data.detail || 'Could not start crypto checkout. Please try again.');
            return;
        }
        if (!data.invoice_url) {
            alert('Payment provider did not return a checkout URL. Please contact support.');
            return;
        }
        // Redirect to NOWPayments hosted checkout
        window.location.href = data.invoice_url;
    } catch (e) {
        alert('Checkout failed. Please try again.');
    }
}

function renderPlanSelect(tier) {
    const plans = tier === 'plus'
        ? [{ id: 'plus_monthly', name: 'Plus Monthly', price: '53 USDT', period: '/month' }, { id: 'plus_quarterly', name: 'Plus Quarterly', price: '139 USDT', period: '/3 months' }]
        : [{ id: 'pro_monthly', name: 'Pro Monthly', price: '109 USDT', period: '/month' }, { id: 'pro_quarterly', name: 'Pro Quarterly', price: '279 USDT', period: '/3 months' }];
    document.getElementById('plan-select').innerHTML = plans.map(p => `
        <div class="plan-option ${p.id === _selectedPlan ? 'selected' : ''}" onclick="selectPlan('${p.id}')">
            <div class="plan-name">${p.name}</div>
            <div class="plan-price">${p.price}</div>
            <div class="plan-period">${p.period}</div>
        </div>
    `).join('');
}

function selectPlan(id) {
    _selectedPlan = id;
    document.querySelectorAll('.plan-option').forEach(o => o.classList.toggle('selected', o.querySelector('.plan-name')?.parentElement === event.currentTarget));
    renderPlanSelect(_selectedPlan.startsWith('plus') ? 'plus' : 'pro');
}
