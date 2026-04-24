/* ═══════════════════════════════════════════════════════════════
 *  Admin Panel — full rebuild (2026-04-18)
 *  - Standalone /admin page OR embedded panel inside dashboard's Admin tab
 *  - Self-protection: admin rows cannot be deleted / deactivated / tier-edited
 *  - Users, Devices, Maintenance, Payments, Referrals, Settings tabs
 * ═══════════════════════════════════════════════════════════════ */

(function () {
  'use strict';

  // ── Auth: token either from dashboard (aladdin_token) or query-string fallback
  function getToken() {
    return localStorage.getItem('aladdin_token') || '';
  }
  function authHeaders() {
    const t = getToken();
    return t ? { Authorization: `Bearer ${t}` } : {};
  }

  // ── State cache
  const state = {
    users: [],
    filter: 'all',
    search: '',
    maintenance: null,
    pricing: null,
    me: null,
  };

  // ── THEME ─────────────────────────────────────────────────────────
  //  Only defined on the standalone /admin page. On the main dashboard the
  //  theme is already managed by client-security.js — do NOT shadow those
  //  functions here or the two systems fight (user-preference is stored under
  //  different localStorage keys and the dashboard's periodic poll re-applies).
  const IS_STANDALONE_ADMIN_PAGE = !!document.getElementById('ap-stats');

  function applyTheme(theme) {
    const t = theme || localStorage.getItem('ap-theme') || detectAutoTheme();
    document.documentElement.setAttribute('data-theme', t);
    const icon = document.getElementById('ap-theme-icon');
    if (icon) icon.textContent = t === 'dark' ? '☀️' : '🌙';
    localStorage.setItem('ap-theme', t);
  }
  function detectAutoTheme() {
    // Light 06:00–19:00 local, dark otherwise. If system pref exists, honor it.
    try {
      if (window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches) return 'light';
    } catch (_) {}
    const h = new Date().getHours();
    return (h >= 6 && h < 19) ? 'light' : 'dark';
  }
  if (IS_STANDALONE_ADMIN_PAGE) {
    window.toggleTheme = function () {
      const cur = document.documentElement.getAttribute('data-theme') || 'dark';
      applyTheme(cur === 'dark' ? 'light' : 'dark');
    };
  }

  // ── TAB SWITCH ────────────────────────────────────────────────────
  window.selectTab = function (tab) {
    document.querySelectorAll('.ap-tab').forEach(b => b.classList.toggle('active', b.dataset.tab === tab));
    document.querySelectorAll('.ap-section').forEach(s => s.classList.toggle('active', s.id === `ap-tab-${tab}`));
    if (tab === 'users') loadUsers();
    if (tab === 'devices') {/* trigger-on-load-only */}
    if (tab === 'maintenance') loadMaintenance();
    if (tab === 'payments') { loadPaymentConfig(); loadPaymentHistory(); }
    if (tab === 'referrals') loadReferrals();
    if (tab === 'settings') loadSettings();
  };

  // ── USERS ─────────────────────────────────────────────────────────
  async function loadUsers() {
    const el = document.getElementById('ap-users-table');
    if (!el) return;
    el.innerHTML = '<div class="ap-empty">Loading…</div>';
    try {
      const r = await fetch('/api/admin/users', { headers: authHeaders() });
      if (r.status === 401 || r.status === 403) {
        el.innerHTML = '<div class="ap-empty">Admin access denied.</div>';
        return;
      }
      const d = await r.json();
      state.users = d.users || [];
      renderUserStats();
      renderUsers();
    } catch (e) {
      el.innerHTML = '<div class="ap-empty">Failed to load users.</div>';
    }
  }

  function renderUserStats() {
    const s = document.getElementById('ap-stats');
    if (!s) return;
    const u = state.users;
    const total = u.length;
    const free = u.filter(x => x.tier_raw === 'free').length;
    const plus = u.filter(x => x.tier_raw === 'plus' && x.days_left > 0).length;
    const pro = u.filter(x => x.tier_raw === 'pro' && x.days_left > 0).length;
    const admins = u.filter(x => x.is_admin).length;
    const expiring = u.filter(x => x.days_left > 0 && x.days_left <= 7 && !x.is_admin).length;
    const unverified = u.filter(x => !x.email_verified && !x.is_admin).length;
    s.innerHTML = `
      <div class="ap-stat"><div class="ap-stat-val">${total}</div><div class="ap-stat-lbl">Total users</div></div>
      <div class="ap-stat"><div class="ap-stat-val">${free}</div><div class="ap-stat-lbl">Free</div></div>
      <div class="ap-stat"><div class="ap-stat-val" style="color:var(--ap-blue)">${plus}</div><div class="ap-stat-lbl">Plus active</div></div>
      <div class="ap-stat"><div class="ap-stat-val" style="color:var(--ap-purple)">${pro}</div><div class="ap-stat-lbl">Pro active</div></div>
      <div class="ap-stat"><div class="ap-stat-val" style="color:${expiring ? 'var(--ap-red)' : 'var(--ap-green)'}">${expiring}</div><div class="ap-stat-lbl">Expiring ≤ 7d</div></div>
      <div class="ap-stat"><div class="ap-stat-val" style="color:#ffb454">${unverified}</div><div class="ap-stat-lbl">Unverified</div></div>
      <div class="ap-stat"><div class="ap-stat-val" style="color:var(--ap-red)">${admins}</div><div class="ap-stat-lbl">Admins</div></div>
    `;
  }

  window.renderUsers = function () {
    const el = document.getElementById('ap-users-table');
    if (!el) return;
    const filter = (document.getElementById('ap-users-filter') || {}).value || 'all';
    const searchEl = document.getElementById('ap-users-search');
    const q = ((searchEl && searchEl.value) || '').trim().toLowerCase();
    let users = state.users;
    if (filter === 'admin') users = users.filter(u => u.is_admin);
    else if (filter === 'unverified') users = users.filter(u => !u.email_verified && !u.is_admin);
    else if (filter !== 'all') users = users.filter(u => u.tier_raw === filter);
    if (q) users = users.filter(u =>
      (u.email || '').toLowerCase().includes(q) ||
      (u.username || '').toLowerCase().includes(q)
    );
    if (!users.length) {
      el.innerHTML = '<div class="ap-empty">No users match the filter.</div>';
      return;
    }
    const tierLabel = { free: 'Free', plus: 'Plus', pro: 'Pro', ultra: 'Ultra' };
    const rows = users.map(u => {
      const tierRaw = u.tier_raw;
      const tierText = u.tier.includes('expired') ? 'Free (expired)' : (tierLabel[tierRaw] || tierRaw);
      const badgeCls = u.is_admin ? 'admin' : `tier-${tierRaw}`;
      const badgeText = u.is_admin ? 'ADMIN' : tierText;
      const daysCls = u.days_left <= 0 ? '' : u.days_left <= 3 ? 'ap-days-critical' : u.days_left <= 7 ? 'ap-days-warning' : 'ap-days-ok';
      const daysStr = u.is_admin ? '∞' : (u.tier_raw === 'free' && !u.tier.includes('expired') ? '—' : (u.days_left > 0 ? `${u.days_left}d` : 'Expired'));
      const reg = new Date(u.created_at * 1000).toLocaleDateString();
      const login = u.last_login ? new Date(u.last_login * 1000).toLocaleDateString() : 'Never';
      const verifyBadge = u.is_admin
        ? '<span class="ap-badge verified">BUILT-IN</span>'
        : (u.email_verified ? '<span class="ap-badge verified">VERIFIED</span>' : '<span class="ap-badge unverified">UNVERIFIED</span>');
      const devCount = u.device_count || 0;
      const devOverride = u.device_limit_override;
      const devText = u.is_admin
        ? `<span class="muted">∞</span>`
        : (devOverride != null ? `${devCount}/<strong>${devOverride >= 9999 ? '∞' : devOverride}</strong>` : `${devCount}`);

      // Action buttons with self-protection rules
      let actions = '';
      if (u.is_admin) {
        actions = `<span class="ap-badge admin" style="opacity:.8">PROTECTED</span>`;
      } else {
        actions = `
          <button class="ap-btn ap-btn-small" onclick="apOpenTierModal(${u.id})">Tier</button>
          <button class="ap-btn ap-btn-small" onclick="apOpenDeviceModal(${u.id})">Devices</button>
          ${!u.email_verified ? `<button class="ap-btn ap-btn-small" onclick="apResendVerify(${u.id})">Verify</button>` : ''}
          ${u.tier_raw !== 'free' ? `<button class="ap-btn ap-btn-small ap-btn-danger" onclick="apDeactivate(${u.id}, '${escapeAttr(u.username || u.email)}')">Deactivate</button>` : ''}
          <button class="ap-btn ap-btn-small ap-btn-danger" onclick="apDeleteUser(${u.id}, '${escapeAttr(u.username || u.email)}')">Delete</button>
        `;
      }

      return `<tr>
        <td class="num">${u.id}</td>
        <td style="font-weight:600">${escapeHtml(u.username || '—')}</td>
        <td class="muted">${escapeHtml(u.email)}</td>
        <td><span class="ap-badge ${badgeCls}">${badgeText}</span></td>
        <td>${verifyBadge}</td>
        <td>${devText}</td>
        <td class="num ${daysCls}">${daysStr}</td>
        <td class="muted">${reg}</td>
        <td class="muted">${login}</td>
        <td>${actions}</td>
      </tr>`;
    }).join('');

    el.innerHTML = `<table class="ap-table"><thead><tr>
      <th>ID</th><th>Username</th><th>Email</th><th>Tier</th><th>Verified</th>
      <th>Devices</th><th>Days left</th><th>Registered</th><th>Last login</th><th>Actions</th>
    </tr></thead><tbody>${rows}</tbody></table>`;
  };

  // ── USER ACTION MODALS ────────────────────────────────────────────
  function openModal(title, bodyHtml) {
    document.getElementById('ap-modal-title').textContent = title;
    document.getElementById('ap-modal-body').innerHTML = bodyHtml;
    document.getElementById('ap-modal').hidden = false;
  }
  window.closeModal = function () {
    document.getElementById('ap-modal').hidden = true;
  };

  window.apOpenTierModal = function (userId) {
    const u = state.users.find(x => x.id === userId);
    if (!u) return;
    if (u.is_admin) { alert("Admin accounts don't carry subscription tiers."); return; }
    openModal(`Edit Tier — ${u.username || u.email}`, `
      <div class="ap-modal-body">
        <div class="ap-field-group">
          <label>Tier</label>
          <select id="apmod-tier">
            <option value="free" ${u.tier_raw === 'free' ? 'selected' : ''}>Free</option>
            <option value="plus" ${u.tier_raw === 'plus' ? 'selected' : ''}>Plus (53 USDT/mo)</option>
            <option value="pro" ${u.tier_raw === 'pro' ? 'selected' : ''}>Pro (109 USDT/mo)</option>
            <option value="ultra" ${u.tier_raw === 'ultra' ? 'selected' : ''}>Ultra (200 USDT/mo — dev)</option>
          </select>
        </div>
        <div class="ap-field-group">
          <label>Duration (days) — ignored when setting Free</label>
          <input type="number" id="apmod-days" value="30" min="1" max="3650">
        </div>
        <div class="ap-row-actions">
          <button class="ap-btn" onclick="closeModal()">Cancel</button>
          <button class="ap-btn ap-btn-primary" onclick="apSubmitTier(${u.id})">Save</button>
        </div>
      </div>
    `);
  };

  window.apSubmitTier = async function (userId) {
    const tier = document.getElementById('apmod-tier').value;
    const days = parseInt(document.getElementById('apmod-days').value) || 30;
    const r = await fetch(`/api/admin/users/${userId}/tier`, {
      method: 'POST', headers: { ...authHeaders(), 'Content-Type': 'application/json' },
      body: JSON.stringify({ tier, days }),
    });
    const d = await r.json();
    if (d.error) { alert(d.error); return; }
    closeModal(); loadUsers();
  };

  window.apOpenDeviceModal = async function (userId) {
    const u = state.users.find(x => x.id === userId);
    if (!u) return;
    openModal(`Devices — ${u.username || u.email}`, `<div class="ap-modal-body"><div class="ap-empty">Loading…</div></div>`);
    try {
      const r = await fetch(`/api/admin/users/${userId}/devices`, { headers: authHeaders() });
      const d = await r.json();
      const li = d.limit_info || {};
      const limitText = li.unlimited ? '∞ (unlimited)' : `${li.limit}`;
      const devs = (d.devices || []).map(x => `
        <div class="ap-kv">
          <div>
            <div><strong>${escapeHtml(x.label || x.first_ua.slice(0, 40) || 'Device #' + x.id)}</strong>
              ${x.revoked ? '<span class="ap-badge danger" style="margin-left:8px">REVOKED</span>' : ''}
            </div>
            <div class="muted" style="font-size:11px">${escapeHtml(x.first_city || '')}${x.first_country ? ', ' + escapeHtml(x.first_country) : ''}
            · IP ${escapeHtml(x.last_ip || x.first_ip || 'n/a')}
            · last seen ${new Date(x.last_seen * 1000).toLocaleString()}</div>
          </div>
          ${x.revoked ? '' : `<button class="ap-btn ap-btn-small ap-btn-danger" onclick="apAdminRevoke(${userId}, ${x.id})">Revoke</button>`}
        </div>`).join('') || '<div class="ap-empty" style="padding:20px 0">No devices registered.</div>';

      document.getElementById('ap-modal-body').innerHTML = `
        <div class="ap-modal-body">
          <div class="ap-kv"><span class="k">Base limit</span><span class="v">${li.base}</span></div>
          <div class="ap-kv"><span class="k">Paid / granted extras</span><span class="v">${li.extras}</span></div>
          <div class="ap-kv"><span class="k">Admin override</span><span class="v">${li.override == null ? 'none' : (li.override >= 9999 ? '∞' : li.override)}</span></div>
          <div class="ap-kv"><span class="k"><strong>Effective limit</strong></span><span class="v" style="color:var(--ap-accent)"><strong>${limitText}</strong></span></div>

          <div class="ap-field-group" style="margin-top:18px">
            <label>Override device limit (blank = default, enter number to force, 9999 = unlimited)</label>
            <input type="number" id="apmod-limit" placeholder="e.g. 5 or 9999" min="-1" value="${li.override != null ? li.override : ''}">
          </div>
          <div class="ap-row-actions">
            <button class="ap-btn" onclick="apSetLimit(${userId}, null)">Reset to default</button>
            <button class="ap-btn ap-btn-primary" onclick="apSetLimit(${userId})">Apply override</button>
          </div>

          <hr style="margin:22px 0;border-color:var(--ap-border-soft)">

          <div class="ap-field-group">
            <label>Grant extra paid device slots (monthly; 0 months = permanent admin grant)</label>
            <div style="display:flex;gap:8px">
              <input type="number" id="apmod-slots" placeholder="slots" min="1" max="20" value="1">
              <input type="number" id="apmod-months" placeholder="months (0 = permanent)" min="0" max="120" value="1">
            </div>
            <input type="text" id="apmod-note" class="ap-input" placeholder="Optional note" style="margin-top:8px;width:100%">
          </div>
          <div class="ap-row-actions">
            <button class="ap-btn ap-btn-primary" onclick="apGrantSlots(${userId})">Grant slots</button>
          </div>

          <h4 style="margin:22px 0 10px;font-size:13px;color:var(--ap-text-dim);text-transform:uppercase;letter-spacing:.08em">Registered Devices</h4>
          ${devs}
        </div>`;
    } catch (e) {
      document.getElementById('ap-modal-body').innerHTML = '<div class="ap-empty">Failed to load.</div>';
    }
  };

  window.apSetLimit = async function (userId, forceNull) {
    const raw = forceNull === null ? null : document.getElementById('apmod-limit').value;
    const limit = (raw === '' || raw == null) ? null : parseInt(raw);
    const r = await fetch(`/api/admin/users/${userId}/device-limit`, {
      method: 'POST', headers: { ...authHeaders(), 'Content-Type': 'application/json' },
      body: JSON.stringify({ limit })
    });
    const d = await r.json();
    if (d.error) { alert(d.error); return; }
    apOpenDeviceModal(userId); loadUsers();
  };

  window.apGrantSlots = async function (userId) {
    const slots = parseInt(document.getElementById('apmod-slots').value) || 1;
    const months = parseInt(document.getElementById('apmod-months').value) || 0;
    const note = document.getElementById('apmod-note').value || '';
    const r = await fetch(`/api/admin/users/${userId}/grant-slots`, {
      method: 'POST', headers: { ...authHeaders(), 'Content-Type': 'application/json' },
      body: JSON.stringify({ slots, months, note })
    });
    const d = await r.json();
    if (d.error) { alert(d.error); return; }
    apOpenDeviceModal(userId); loadUsers();
  };

  window.apAdminRevoke = async function (userId, deviceId) {
    if (!confirm('Revoke this device?')) return;
    const r = await fetch(`/api/admin/users/${userId}/devices/${deviceId}`, {
      method: 'DELETE', headers: authHeaders()
    });
    const d = await r.json();
    if (d.error) { alert(d.error); return; }
    apOpenDeviceModal(userId); loadUsers();
  };

  window.apResendVerify = async function (userId) {
    const r = await fetch(`/api/admin/users/${userId}/resend-verification`, {
      method: 'POST', headers: authHeaders()
    });
    const d = await r.json();
    alert(d.ok ? `Verification email sent to ${d.email}` : (d.error || 'Failed to send'));
  };

  window.apDeactivate = async function (userId, name) {
    if (!confirm(`Deactivate ${name}? Tier → Free.`)) return;
    const r = await fetch(`/api/admin/users/${userId}/deactivate`, { method: 'POST', headers: authHeaders() });
    const d = await r.json();
    if (d.error) { alert(d.error); return; }
    loadUsers();
  };

  window.apDeleteUser = async function (userId, name) {
    if (!confirm(`PERMANENTLY delete ${name}? Payment history will be removed. This cannot be undone.`)) return;
    const r = await fetch(`/api/admin/users/${userId}`, { method: 'DELETE', headers: authHeaders() });
    const d = await r.json();
    if (d.error) { alert(d.error); return; }
    loadUsers();
  };

  window.adminCheckExpiry = async function () {
    const r = await fetch('/api/admin/check-expiry', { method: 'POST', headers: authHeaders() });
    const d = await r.json();
    alert(`Reminders sent: ${(d.reminders_sent || []).length}\nDeactivated: ${(d.deactivated || []).length}`);
    loadUsers();
  };

  // ── MAINTENANCE ──────────────────────────────────────────────────
  async function loadMaintenance() {
    try {
      const r = await fetch('/api/admin/settings', { headers: authHeaders() });
      const d = await r.json();
      state.maintenance = d.maintenance || {};
      document.getElementById('ap-maint-toggle').checked = !!state.maintenance.enabled;
      document.getElementById('ap-maint-message').value = state.maintenance.message || '';
      updateMaintPill();
    } catch (_) {}
  }

  function updateMaintPill() {
    const toggle = document.getElementById('ap-maint-toggle');
    const state_label = document.getElementById('ap-maint-state');
    const pill = document.getElementById('ap-maintenance-pill');
    const on = toggle && toggle.checked;
    if (state_label) state_label.textContent = on ? 'Maintenance ON — copy-trading paused, users see banner' : 'Maintenance OFF — platform normal';
    if (pill) pill.hidden = !on;
  }

  window.saveMaintenance = async function () {
    const enabled = document.getElementById('ap-maint-toggle').checked;
    const message = document.getElementById('ap-maint-message').value;
    const status = document.getElementById('ap-maint-status');
    status.textContent = 'Saving…';
    const r = await fetch('/api/admin/settings/maintenance', {
      method: 'POST', headers: { ...authHeaders(), 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled, message })
    });
    const d = await r.json();
    if (d.ok) {
      status.textContent = '✓ Saved ' + new Date().toLocaleTimeString();
      state.maintenance = d.maintenance;
      updateMaintPill();
    } else {
      status.textContent = 'Error: ' + (d.error || 'unknown');
    }
  };

  // react to toggle change
  document.addEventListener('change', (e) => {
    if (e.target && e.target.id === 'ap-maint-toggle') updateMaintPill();
  });

  // ── PAYMENTS ─────────────────────────────────────────────────────
  async function loadPaymentConfig() {
    const el = document.getElementById('ap-payments-config');
    if (!el) return;
    el.innerHTML = '<div class="ap-empty">Loading…</div>';
    try {
      const r = await fetch('/api/admin/payments/config', { headers: authHeaders() });
      const d = await r.json();
      const cfg = d.config || {};
      const health = d.health || {};
      el.innerHTML = `
        <div class="ap-kv"><span class="k">API Health</span><span class="v">${health.ok ? '✅ OK' : '❌'} ${escapeHtml(health.message || '')}</span></div>
        <div class="ap-kv"><span class="k">Sandbox</span><span class="v">${cfg.sandbox ? '🧪 Yes' : 'No (production)'}</span></div>
        <div class="ap-kv"><span class="k">API key</span><span class="v">${cfg.api_key_set ? '✅' : '❌'}</span></div>
        <div class="ap-kv"><span class="k">IPN secret</span><span class="v">${cfg.ipn_secret_set ? '✅' : '❌'}</span></div>
        <div class="ap-kv"><span class="k">Configured</span><span class="v">${cfg.configured ? '✅ Ready' : '❌ Not ready'}</span></div>
        <div class="ap-kv"><span class="k">IPN URL</span><span class="v mono">${escapeHtml(cfg.ipn_url || 'N/A')}</span></div>
        <div class="ap-kv"><span class="k">Currencies</span><span class="v">${d.currency_count || 0}</span></div>
      `;
    } catch (_) {
      el.innerHTML = '<div class="ap-empty">Failed to load.</div>';
    }
  }
  window.loadPaymentConfig = loadPaymentConfig;

  async function loadPaymentHistory() {
    const el = document.getElementById('ap-payments-history');
    if (!el) return;
    el.innerHTML = '<div class="ap-empty">Loading…</div>';
    try {
      const r = await fetch('/api/admin/payments/history?limit=50', { headers: authHeaders() });
      const d = await r.json();
      const pays = d.payments || [];
      if (!pays.length) { el.innerHTML = '<div class="ap-empty">No payments yet.</div>'; return; }
      const statusColors = {
        completed: 'color:var(--ap-green)',
        awaiting_payment: 'color:var(--ap-accent)',
        confirming: 'color:var(--ap-blue)',
        failed: 'color:var(--ap-red)',
        expired: 'color:var(--ap-red)',
        refunded: 'color:var(--ap-red)',
      };
      const rows = pays.map(p => `<tr>
        <td class="muted">${new Date(p.created_at * 1000).toLocaleString()}</td>
        <td>
          <div style="font-weight:600">${escapeHtml(p.username || 'N/A')}</div>
          <div class="muted" style="font-size:11px">${escapeHtml(p.email || '')}</div>
        </td>
        <td><span class="ap-badge tier-${p.tier_granted || 'free'}">${escapeHtml(p.tier_granted || 'N/A')}</span></td>
        <td class="num" style="font-weight:600">$${p.amount_usd}</td>
        <td style="${statusColors[p.status] || ''};font-weight:700;text-transform:uppercase;font-size:11px">${escapeHtml(p.status || 'unknown')}</td>
        <td class="mono">${escapeHtml((p.payment_id || '').slice(-10))}</td>
      </tr>`).join('');
      el.innerHTML = `<table class="ap-table"><thead><tr>
        <th>Date</th><th>User</th><th>Plan</th><th>Amount</th><th>Status</th><th>ID</th>
      </tr></thead><tbody>${rows}</tbody></table>`;
    } catch (_) {
      el.innerHTML = '<div class="ap-empty">Failed to load.</div>';
    }
  }
  window.loadPaymentHistory = loadPaymentHistory;

  // ── REFERRALS ────────────────────────────────────────────────────
  async function loadReferrals() {
    const el = document.getElementById('ap-referrals-table');
    if (!el) return;
    el.innerHTML = '<div class="ap-empty">Loading…</div>';
    try {
      const r = await fetch('/api/admin/referrals', { headers: authHeaders() });
      const d = await r.json();
      const refs = d.referrers || [];
      if (!refs.length) { el.innerHTML = '<div class="ap-empty">No referrals yet.</div>'; return; }
      const rows = refs.map(r => `<tr>
        <td>${escapeHtml(r.username || r.email)}</td>
        <td class="muted">${escapeHtml(r.email)}</td>
        <td class="num">${r.total || 0}</td>
        <td class="num" style="color:var(--ap-green)">${r.credited || 0}</td>
        <td class="num" style="color:var(--ap-accent)">${r.pending || 0}</td>
        <td class="num">${r.total_bonus_days || 0}d</td>
        <td class="num">$${(r.total_volume || 0).toFixed(2)}</td>
      </tr>`).join('');
      el.innerHTML = `<table class="ap-table"><thead><tr>
        <th>Referrer</th><th>Email</th><th>Total</th><th>Credited</th><th>Pending</th><th>Bonus days</th><th>Volume</th>
      </tr></thead><tbody>${rows}</tbody></table>`;
    } catch (_) {
      el.innerHTML = '<div class="ap-empty">Failed to load.</div>';
    }
  }
  window.loadReferrals = loadReferrals;

  // ── SETTINGS ─────────────────────────────────────────────────────
  async function loadSettings() {
    const priceEl = document.getElementById('ap-settings-pricing');
    if (priceEl) {
      try {
        const r = await fetch('/api/public/site');
        const d = await r.json();
        state.pricing = d.device_pricing || {};
        priceEl.innerHTML = `
          <p class="ap-card-sub" style="margin-bottom:14px">Monthly recurring charge per extra device, tied to active subscription.</p>
          <div class="ap-pricing-row"><span class="p-tier">Plus (base 1 device)</span><span class="p-val">+${state.pricing.plus_monthly} USDT / extra device / mo</span></div>
          <div class="ap-pricing-row"><span class="p-tier">Pro (base 2 devices)</span><span class="p-val">+${state.pricing.pro_monthly} USDT / extra device / mo</span></div>
          <div class="ap-pricing-row"><span class="p-tier">Ultra (base 3 devices)</span><span class="p-val">+${state.pricing.ultra_monthly} USDT / extra device / mo</span></div>
          <div class="ap-pricing-row"><span class="p-tier">Free tier</span><span class="p-val" style="color:var(--ap-text-dim)">1 device, extras not sold</span></div>
        `;
      } catch (_) {}
    }
    const adminEl = document.getElementById('ap-settings-admin');
    if (adminEl && state.me) {
      adminEl.innerHTML = `
        <div class="ap-kv"><span class="k">Signed in as</span><span class="v">${escapeHtml(state.me.email)}</span></div>
        <div class="ap-kv"><span class="k">Role</span><span class="v">${state.me.is_admin ? 'Administrator' : 'User'}</span></div>
        <div class="ap-kv"><span class="k">Tier</span><span class="v">${state.me.is_admin ? '∞ (admin bypass)' : state.me.tier}</span></div>
        <div class="ap-kv"><span class="k">Created</span><span class="v">${new Date(state.me.created_at * 1000).toLocaleDateString()}</span></div>
      `;
    }
  }

  async function loadMe() {
    try {
      const r = await fetch('/api/auth/me', { headers: authHeaders() });
      if (r.ok) {
        const d = await r.json();
        state.me = d.user || null;
        if (state.me && !state.me.is_admin) {
          alert('Admin access required — redirecting.');
          window.location.href = '/';
        }
      } else {
        window.location.href = '/?redirect=admin';
      }
    } catch (_) {}
  }

  // ── HELPERS ──────────────────────────────────────────────────────
  function escapeHtml(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }
  function escapeAttr(s) { return escapeHtml(s).replace(/`/g, '&#96;'); }

  // Search live-filter
  document.addEventListener('input', e => {
    if (e.target && e.target.id === 'ap-users-search') {
      state.search = e.target.value;
      window.renderUsers();
    }
  });

  // ── BOOT (standalone /admin page only) ───────────────────────────
  function bootStandalone() {
    if (!document.getElementById('ap-stats')) return; // not on standalone page
    if (!getToken()) {
      alert('Not logged in. Redirecting.');
      window.location.href = '/?redirect=admin';
      return;
    }
    applyTheme();
    loadMe().then(() => {
      loadUsers();
      loadMaintenance();
    });
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bootStandalone);
  } else {
    bootStandalone();
  }

  // ── DASHBOARD-EMBEDDED SHIMS ──────────────────────────────────────
  // Keep old entry points used by the dashboard's Admin tab working.
  window.loadAdminUsers = async function () {
    await loadUsers();
    // If the dashboard HTML wrapper exists, project our rendered table into it.
    const dashTable = document.getElementById('admin-users-table');
    const dashStats = document.getElementById('admin-stats');
    const adminTable = document.getElementById('ap-users-table');
    const adminStats = document.getElementById('ap-stats');
    if (dashTable && !adminTable) {
      // Inject a mini-version of the admin panel into the dashboard tab.
      dashTable.innerHTML = `
        <div class="ap-card" style="margin-top:0">
          <div class="ap-card-head">
            <div><h2>Registered Users</h2><div class="ap-card-sub">Full admin panel at <a href='/admin'>/admin</a></div></div>
            <div class="ap-card-actions">
              <input id="ap-users-search" class="ap-input" placeholder="Search">
              <select id="ap-users-filter" class="ap-input" onchange="renderUsers()">
                <option value="all">All</option><option value="free">Free</option><option value="plus">Plus</option>
                <option value="pro">Pro</option><option value="admin">Admin</option>
                <option value="unverified">Unverified</option>
              </select>
              <button class="ap-btn" onclick="loadAdminUsers()">↻</button>
              <a class="ap-btn ap-btn-primary" href="/admin">Full Panel</a>
            </div>
          </div>
          <div id="ap-users-table" class="ap-table-wrap"></div>
        </div>`;
      if (dashStats) {
        dashStats.innerHTML = '<div id="ap-stats" class="ap-statgrid"></div>';
      }
      renderUserStats();
      renderUsers();
    }
  };

})();
