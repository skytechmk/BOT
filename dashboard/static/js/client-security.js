/* ═══════════════════════════════════════════════════════════════
 *  Client Security — Device Fingerprint · Theme · Maintenance banner
 *  Light-weight, no external deps. Loads before other scripts.
 * ═══════════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  // ── 1. DEVICE FINGERPRINT (stable per browser+device) ──
  // Privacy-respecting: canvas + UA + screen + timezone + hardware hints.
  function _hash(str) {
    let h = 0, i, chr;
    if (!str) return '';
    for (i = 0; i < str.length; i++) {
      chr = str.charCodeAt(i);
      h = ((h << 5) - h) + chr;
      h |= 0;
    }
    // Convert to unsigned and base36
    return (h >>> 0).toString(36);
  }

  async function _canvasHash() {
    try {
      const c = document.createElement('canvas');
      c.width = 280; c.height = 60;
      const ctx = c.getContext('2d');
      ctx.textBaseline = 'top';
      ctx.font = '14px "Arial"';
      ctx.fillStyle = '#f60';
      ctx.fillRect(125, 1, 62, 20);
      ctx.fillStyle = '#069';
      ctx.fillText('Anunnaki.Fingerprint!@#$%^', 2, 15);
      ctx.fillStyle = 'rgba(102, 204, 0, 0.7)';
      ctx.fillText('Anunnaki.Fingerprint!@#$%^', 4, 17);
      return _hash(c.toDataURL());
    } catch (_) { return 'nc'; }
  }

  async function _webglHash() {
    try {
      const c = document.createElement('canvas');
      const gl = c.getContext('webgl') || c.getContext('experimental-webgl');
      if (!gl) return 'nowebgl';
      const dbgInfo = gl.getExtension('WEBGL_debug_renderer_info');
      const vendor = dbgInfo ? gl.getParameter(dbgInfo.UNMASKED_VENDOR_WEBGL) : '';
      const renderer = dbgInfo ? gl.getParameter(dbgInfo.UNMASKED_RENDERER_WEBGL) : '';
      return _hash(vendor + '|' + renderer);
    } catch (_) { return 'nwg'; }
  }

  async function computeFingerprint() {
    try {
      const existing = localStorage.getItem('awd_fp');
      if (existing) return existing;
      const parts = [
        navigator.userAgent || '',
        navigator.language || '',
        (navigator.languages || []).join(','),
        screen.width + 'x' + screen.height + 'x' + (screen.colorDepth || 24),
        String(new Date().getTimezoneOffset()),
        Intl.DateTimeFormat().resolvedOptions().timeZone || '',
        String(navigator.hardwareConcurrency || 0),
        String(navigator.deviceMemory || 0),
        navigator.platform || '',
        await _canvasHash(),
        await _webglHash(),
      ].join('||');
      const fp = _hash(parts) + '-' + _hash(parts.split('').reverse().join(''));
      localStorage.setItem('awd_fp', fp);
      return fp;
    } catch (_) {
      // Fallback: random per browser
      let r = localStorage.getItem('awd_fp_fallback');
      if (!r) {
        r = Array.from(crypto.getRandomValues(new Uint8Array(16))).map(b => b.toString(16).padStart(2, '0')).join('');
        localStorage.setItem('awd_fp_fallback', r);
      }
      return r;
    }
  }

  function deviceLabel() {
    const ua = navigator.userAgent || '';
    const isMobile = /Mobi|Android|iPhone/.test(ua);
    let browser = 'Browser';
    if (/Chrome\//.test(ua) && !/Edg/.test(ua)) browser = 'Chrome';
    else if (/Edg\//.test(ua)) browser = 'Edge';
    else if (/Firefox\//.test(ua)) browser = 'Firefox';
    else if (/Safari\//.test(ua) && !/Chrome/.test(ua)) browser = 'Safari';
    let os = 'OS';
    if (/Windows/.test(ua)) os = 'Windows';
    else if (/Mac OS/.test(ua)) os = 'macOS';
    else if (/Android/.test(ua)) os = 'Android';
    else if (/iPhone|iPad/.test(ua)) os = 'iOS';
    else if (/Linux/.test(ua)) os = 'Linux';
    return `${browser} · ${os}${isMobile ? ' · Mobile' : ''}`;
  }

  // Expose globally
  window.AWDSecurity = {
    getFingerprint: computeFingerprint,
    getDeviceLabel: deviceLabel,
  };

  // Precompute & cache early
  computeFingerprint();

  // Patch window.fetch so EVERY request auto-includes device fingerprint headers.
  // This way login/register/me/etc. carry the fingerprint without touching each call.
  const _fetch = window.fetch;
  window.fetch = async function (input, init) {
    try {
      init = init || {};
      init.headers = init.headers || {};
      // Headers may be a Headers instance
      if (init.headers instanceof Headers) {
        if (!init.headers.has('X-Device-Fingerprint')) init.headers.set('X-Device-Fingerprint', await computeFingerprint());
        if (!init.headers.has('X-Device-Label')) init.headers.set('X-Device-Label', deviceLabel());
      } else {
        if (!init.headers['X-Device-Fingerprint']) init.headers['X-Device-Fingerprint'] = await computeFingerprint();
        if (!init.headers['X-Device-Label']) init.headers['X-Device-Label'] = deviceLabel();
      }
    } catch (_) {}
    return _fetch.call(this, input, init);
  };

  // ── 2. THEME — single toggle, matches admin panel pattern ──
  //   First load: use saved preference if any; otherwise detect by IP-timezone hour.
  //   Click: flip between 'dark' and 'light'. No "auto" selectable mode — same as /admin.
  function detectTheme(hint) {
    const tzHint = hint || localStorage.getItem('awd-client-tz') || Intl.DateTimeFormat().resolvedOptions().timeZone;
    try {
      const fmt = new Intl.DateTimeFormat('en-US', { hour: 'numeric', hour12: false, timeZone: tzHint });
      const h = parseInt(fmt.format(new Date()));
      return (h >= 6 && h < 19) ? 'light' : 'dark';
    } catch (_) {
      const h = new Date().getHours();
      return (h >= 6 && h < 19) ? 'light' : 'dark';
    }
  }
  function applyTheme(theme) {
    const t = theme || localStorage.getItem('awd-theme') || detectTheme();
    document.documentElement.setAttribute('data-theme', t);
    const icon = document.getElementById('awd-theme-icon');
    if (icon) icon.textContent = t === 'dark' ? '☀️' : '🌙';
    localStorage.setItem('awd-theme', t);
  }
  window.toggleTheme = function () {
    const cur = document.documentElement.getAttribute('data-theme') || 'dark';
    localStorage.setItem('awd-theme-user-set', '1');
    applyTheme(cur === 'dark' ? 'light' : 'dark');
  };
  // Legacy shim: anything still calling setThemeMode will keep working.
  window.setThemeMode = function (mode) {
    if (mode === 'auto') {
      localStorage.removeItem('awd-theme'); localStorage.removeItem('awd-theme-user-set');
      applyTheme(detectTheme()); return;
    }
    localStorage.setItem('awd-theme-user-set', '1');
    applyTheme(mode === 'light' ? 'light' : 'dark');
  };
  applyTheme();

  // ── TIME HELPERS ───────────────────────────────────────────────
  function _getClientTZ() {
    try { return localStorage.getItem('awd-client-tz') || Intl.DateTimeFormat().resolvedOptions().timeZone; }
    catch(_) { return 'UTC'; }
  }
  function _getClientTZName() {
    const tz = _getClientTZ();
    // Extract short name like "CEST" or "EST" from timezone
    try {
      const parts = new Intl.DateTimeFormat('en-US', { timeZone: tz, timeZoneName: 'short' }).formatToParts(new Date());
      const tzName = parts.find(p => p.type === 'timeZoneName');
      return tzName ? tzName.value : tz;
    } catch(_) { return tz; }
  }
  function _fmtLocalClock() {
    const now = new Date();
    const tz = _getClientTZ();
    try {
      const fmt = new Intl.DateTimeFormat('en-GB', {
        hour: '2-digit', minute: '2-digit', second: '2-digit',
        hour12: false, timeZone: tz
      });
      return fmt.format(now);
    } catch(_) {
      return now.toLocaleTimeString('en-GB', { hour12: false });
    }
  }

  // ── 3. MAINTENANCE BANNER + CLIENT TIMEZONE HINT ──
  async function fetchSiteMeta() {
    try {
      const r = await fetch('/api/public/site', { cache: 'no-store' });
      if (!r.ok) return;
      const d = await r.json();
      window._awdSiteMeta = d;
      if (d.client && d.client.timezone) {
        localStorage.setItem('awd-client-tz', d.client.timezone);
        // If user hasn't explicitly picked a theme yet, re-detect using the
        // freshly-learned IP timezone so the default feels correct.
        if (!localStorage.getItem('awd-theme-user-set')) applyTheme(detectTheme(d.client.timezone));
      }
      renderMaintenanceBanner(d.maintenance);
      if (d.sessions) renderSessionBar(d.sessions);
    } catch (_) {}
  }

  // ── SESSION BAR ───────────────────────────────────────────────

  function _sessProgress(def) {
    const now  = new Date();
    const curS = now.getUTCHours() * 3600 + now.getUTCMinutes() * 60 + now.getUTCSeconds();
    const DAY  = 24 * 3600;
    const o = def.open_h * 3600 + def.open_m * 60;
    const c = def.close_h * 3600 + def.close_m * 60;
    let active, elapsed, total, secsLeft;
    if (def.midnight) {
      active = curS >= o || curS < c;
      total  = (DAY - o) + c;
      if (active) {
        elapsed  = curS >= o ? curS - o : (DAY - o) + curS;
        secsLeft = curS >= o ? (DAY - curS) + c : c - curS;
      }
    } else {
      active   = curS >= o && curS < c;
      total    = c - o;
      elapsed  = active ? curS - o : 0;
      secsLeft = active ? c - curS : 0;
    }
    if (!active) return { active: false, pct: 0, secsLeft: 0 };
    return { active: true, pct: Math.min(100, Math.max(0, elapsed / total * 100)), secsLeft };
  }

  function _fmtSecs(s) {
    s = Math.max(0, Math.floor(s));
    const h  = Math.floor(s / 3600);
    const m  = Math.floor((s % 3600) / 60);
    const sc = s % 60;
    if (h > 0) return `${h}h ${m}m ${String(sc).padStart(2,'0')}s`;
    if (m > 0) return `${m}m ${String(sc).padStart(2,'0')}s`;
    return `${sc}s`;
  }

  function _updatePillFills() {
    const defs = window._awdSessionDefs;
    if (!defs) return;
    defs.forEach(def => {
      const pill = document.querySelector(`[data-sess="${CSS.escape(def.name)}"]`);
      if (!pill) return;
      const { active, pct, secsLeft } = _sessProgress(def);
      if (active) {
        const pctStr = pct.toFixed(2);
        pill.style.background = `linear-gradient(to right, ${def.color}45 ${pctStr}%, ${def.color}14 ${pctStr}%)`;
        const cdwn = pill.querySelector('.awd-sess-cdwn');
        if (cdwn) cdwn.textContent = _fmtSecs(secsLeft);
        pill.title = `${def.name} (${def.open_utc}–${def.close_utc} UTC) · Closes in ${_fmtSecs(secsLeft)}`;
      }
    });
  }

  function renderSessionBar(s) {
    if (!s || !s.sessions) return;
    let bar = document.getElementById('awd-session-bar');
    if (!bar) {
      bar = document.createElement('div');
      bar.id = 'awd-session-bar';
      bar.style.cssText = `
        display:flex; align-items:center; justify-content:center; flex-wrap:wrap;
        gap:7px; padding:7px 18px; background:var(--surface,#0d1117);
        border-bottom:1px solid var(--border,#1e2d40); font-size:13px;
        position:sticky; top:0; z-index:9998; min-height:38px;
      `;
      const maint = document.getElementById('awd-maintenance-banner');
      if (maint && maint.nextSibling) {
        document.body.insertBefore(bar, maint.nextSibling);
      } else {
        document.body.insertBefore(bar, document.body.firstChild);
      }
    }

    const liqColor = { peak:'#00d68f', high:'#4caf50', medium:'#f0b429', low:'#ff9800', dead:'#666' };
    const liqLabel = { peak:'Peak Liquidity', high:'High Liquidity', medium:'Medium Liquidity', low:'Low Liquidity', dead:'Thin Market' };
    const liq = s.liquidity || 'low';

    let html = `<span style="color:${liqColor[liq]||'#888'};font-weight:700;font-size:12px;letter-spacing:.06em;margin-right:4px">${liqLabel[liq]||liq}</span>`;
    html += `<span id="awd-session-clock" style="color:var(--text-dim,#556);font-size:12px;margin-right:8px;font-variant-numeric:tabular-nums" title="Local time (${_getClientTZName()})">${_fmtLocalClock()}</span>`;

    // Store session defs for client-side progress ticking
    window._awdSessionDefs = (s.sessions||[]).map(sess => ({
      name:     sess.name,
      color:    sess.color,
      emoji:    sess.emoji,
      open_h:   sess.open_h   != null ? sess.open_h   : parseInt((sess.open_utc  ||'00:00').split(':')[0]),
      open_m:   sess.open_m   != null ? sess.open_m   : parseInt((sess.open_utc  ||'00:00').split(':')[1]),
      close_h:  sess.close_h  != null ? sess.close_h  : parseInt((sess.close_utc ||'00:00').split(':')[0]),
      close_m:  sess.close_m  != null ? sess.close_m  : parseInt((sess.close_utc ||'00:00').split(':')[1]),
      midnight: !!sess.midnight,
      open_utc: sess.open_utc, close_utc: sess.close_utc,
    }));

    // Session pills
    (s.sessions||[]).forEach(sess => {
      const prog   = _sessProgress(window._awdSessionDefs.find(d => d.name === sess.name) || {});
      const pct    = prog.pct || 0;
      const brd    = sess.active ? sess.color : 'var(--border,#1e2d40)';
      const col    = sess.active ? sess.color : 'var(--text-dim,#556)';
      const bgFill = sess.active
        ? `linear-gradient(to right, ${sess.color}45 ${pct.toFixed(2)}%, ${sess.color}14 ${pct.toFixed(2)}%)`
        : 'transparent';
      const dot = sess.active
        ? `<span style="width:7px;height:7px;border-radius:50%;background:${sess.color};box-shadow:0 0 7px ${sess.color};display:inline-block;flex-shrink:0"></span>`
        : '';
      const cdwn = sess.active
        ? `<span class="awd-sess-cdwn" style="font-size:11px;opacity:.65;font-variant-numeric:tabular-nums;margin-left:3px">${_fmtSecs(prog.secsLeft)}</span>`
        : '';
      const ttip = `${sess.name} (${sess.open_utc}–${sess.close_utc} UTC) · ${sess.active ? 'Closes in ' + sess.countdown : 'Opens in ' + sess.countdown}`;
      html += `<span data-sess="${sess.name}" title="${ttip}"
        style="display:inline-flex;align-items:center;gap:5px;padding:4px 12px;border-radius:20px;
               border:1px solid ${brd};background:${bgFill};color:${col};
               font-weight:${sess.active?700:500};cursor:default;white-space:nowrap;
               transition:background .6s ease">
        ${dot}${sess.emoji} ${sess.name}${cdwn}
      </span>`;
    });

    // Overlap badges
    (s.overlaps||[]).forEach(ov => {
      html += `<span style="padding:4px 11px;border-radius:20px;background:${ov.color}22;
        border:1px solid ${ov.color};color:${ov.color};font-weight:700;font-size:11px;
        letter-spacing:.04em">${ov.name}</span>`;
    });

    bar.innerHTML = html;
    bar.style.display = 'flex';

    // Start real-time clock + pill fill ticker (once only)
    if (!window._awdClockRunning) {
      window._awdClockRunning = true;
      setInterval(() => {
        const el = document.getElementById('awd-session-clock');
        if (el) {
          el.textContent = _fmtLocalClock();
        }
        _updatePillFills();
      }, 1000);
    }
  }

  function renderMaintenanceBanner(m) {
    if (!m) return;
    let el = document.getElementById('awd-maintenance-banner');

    if (!m.enabled) {
      if (el && !el.hidden) {
        // Slide-up dismiss
        el.style.transition = 'max-height .4s ease, opacity .4s ease, padding .4s ease';
        el.style.maxHeight  = '0';
        el.style.opacity    = '0';
        el.style.padding    = '0 18px';
        setTimeout(() => { if (el) el.hidden = true; }, 420);
      }
      return;
    }

    if (!el) {
      el = document.createElement('div');
      el.id = 'awd-maintenance-banner';
      el.style.cssText = `
        position: sticky; top: 0; z-index: 9999;
        background: linear-gradient(90deg, #ff6b85, #d8364e);
        color: white; text-align: center;
        font-size: 13px; font-weight: 600; letter-spacing: .02em;
        box-shadow: 0 2px 8px rgba(0,0,0,.3);
        overflow: hidden; max-height: 0; opacity: 0; padding: 0 18px;
        transition: max-height .4s ease, opacity .4s ease, padding .4s ease;
      `;
      document.body.insertBefore(el, document.body.firstChild);
    }

    el.innerHTML = `🛠️ ${escape(m.message || 'Platform under maintenance — copy-trading paused.')}`;
    el.hidden = false;
    // Trigger slide-down on next frame
    requestAnimationFrame(() => {
      el.style.maxHeight = '60px';
      el.style.opacity   = '1';
      el.style.padding   = '10px 18px';
    });
  }

  function escape(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', fetchSiteMeta);
  } else {
    fetchSiteMeta();
  }

  // Re-poll every 15s — banner appears within 15s of admin toggling, no refresh needed
  setInterval(fetchSiteMeta, 15 * 1000);

  // Instant update when user tabs back in or window regains focus
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') fetchSiteMeta();
  });
  window.addEventListener('focus', fetchSiteMeta);

  // ── 4. DEVICE-LIMIT ERROR HANDLER FOR LOGIN ──
  window.AWDShowDeviceLimitError = function (detail) {
    const msg = detail || 'Device limit reached. Revoke an old device or contact support to purchase an extra slot.';
    // Try to display inside the auth modal error slot; otherwise alert.
    const errEl = document.getElementById('auth-error');
    if (errEl) { errEl.textContent = msg; errEl.style.display = 'block'; }
    else alert(msg);
  };
})();
