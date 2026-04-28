// ═══════════════════════════════════════════════════════════════════════
//  SIGNAL SHARE CARD — Client-side PNG generator for Instagram / X
// ═══════════════════════════════════════════════════════════════════════
//
//  Builds a styled off-screen DOM element, renders it to canvas via
//  html2canvas, then shows a modal with download + native share.
//
//  Card size: 1080×1350 (IG story / portrait — works great on X too).
// ═══════════════════════════════════════════════════════════════════════

(function() {
'use strict';

var CARD_W = 1080;
var CARD_H = 1350;
var BRAND  = 'anunnakiworld.com';
var LOGO   = '/static/logo.jpeg';

// ── Color palette (matches Anunnaki brand) ───────────────────────────
var C = {
    gold:      '#d4a843',
    goldLight: '#f0d478',
    goldDim:   '#9a7a2e',
    cyan:      '#38bdf8',
    cyanGlow:  '#0ea5e9',
    green:     '#22c55e',
    greenGlow: '#4ade80',
    red:       '#ef4444',
    redGlow:   '#f87171',
    bgTop:     '#0c1220',
    bgMid:     '#080e1a',
    bgBot:     '#050a12',
    textPri:   '#f1f5f9',
    textSec:   '#94a3b8',
    textDim:   '#475569',
};

// ── Utility helpers ──────────────────────────────────────────────────

function _esc(s) { return String(s||'').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function _fmtPrice(v) {
    var n = +v;
    if (!n) return '—';
    if (n >= 1000)  return n.toLocaleString('en-US', {minimumFractionDigits:2, maximumFractionDigits:2});
    if (n >= 1)     return n.toFixed(4);
    if (n >= 0.01)  return n.toFixed(5);
    return n.toFixed(6);
}
function _pctDiff(entry, target) {
    if (!entry || !target) return '';
    var pct = ((target - entry) / entry * 100);
    return (pct >= 0 ? '+' : '') + pct.toFixed(2) + '%';
}

// ── Build the share card DOM ─────────────────────────────────────────

function buildShareCardHTML(s) {
    var dir       = s.direction || 'LONG';
    var isLong    = dir === 'LONG';
    var dirColor  = isLong ? C.green : C.red;
    var dirGlow   = isLong ? C.greenGlow : C.redGlow;
    var dirBg     = isLong
        ? 'linear-gradient(135deg, rgba(34,197,94,0.18) 0%, transparent 50%)'
        : 'linear-gradient(135deg, rgba(239,68,68,0.18) 0%, transparent 50%)';

    var pair      = (s.pair || '').replace('USDT', '');
    var leverage  = s.leverage || '—';
    var entry     = s.price || 0;
    var sl        = s.stop_loss || 0;
    var targets   = s.targets || [];
    var confidence = s.confidence || '—';
    var status    = s.status || 'SENT';
    var pnl       = s.pnl;
    var timeStr   = s.time_local || '';
    if (typeof _fmtLocalTime === 'function' && s.timestamp) {
        timeStr = _fmtLocalTime(s.timestamp);
    }

    // R:R calculation
    var rr = '—';
    if (entry && sl && targets && targets.length) {
        var risk = Math.abs(entry - sl);
        var reward = Math.abs(targets[targets.length - 1] - entry);
        if (risk > 0) rr = (reward / risk).toFixed(1) + ':1';
    }

    // Status styling
    var statusColor = C.cyan;
    var statusLabel = status;
    var statusGlow  = C.cyanGlow;
    var isOpen = ['SENT','OPEN','ACTIVE','TP1_HIT','TP2_HIT'].includes(status.toUpperCase());
    if (!isOpen) {
        var reason = (s.close_reason || '').toUpperCase();
        if (reason.includes('SL') || status.toUpperCase().includes('SL') || pnl < 0) {
            statusColor = C.red; statusGlow = C.redGlow;
            statusLabel = 'SL HIT';
        } else if (reason.includes('TP') || (s.targets_hit && s.targets_hit > 0)) {
            statusColor = C.green; statusGlow = C.greenGlow;
            var th = s.targets_hit || 0;
            var total = targets.length;
            statusLabel = th >= total && total > 0 ? 'ALL TPs HIT' : 'TP' + (th || '') + ' HIT';
        } else {
            statusColor = C.gold; statusGlow = C.goldLight;
            statusLabel = reason || 'CLOSED';
        }
    } else {
        statusLabel = status;
    }

    // PnL display
    var pnlHtml = '';
    if (pnl !== null && pnl !== undefined && pnl !== 0) {
        var pnlColor = pnl > 0 ? C.green : C.red;
        var pnlGlow  = pnl > 0 ? C.greenGlow : C.redGlow;
        var pnlSign  = pnl > 0 ? '+' : '';
        pnlHtml =
            '<div style="margin:28px 48px 0;padding:24px 0;text-align:center;' +
                'background:linear-gradient(135deg,' + pnlColor + '0a,' + pnlColor + '05);' +
                'border:1px solid ' + pnlColor + '22;border-radius:16px">' +
                '<div style="font-size:16px;font-weight:700;color:' + C.textSec + ';letter-spacing:0.14em;margin-bottom:10px">' +
                    (isOpen ? 'UNREALIZED P&L' : 'REALIZED P&L') + '</div>' +
                '<div style="font-size:60px;font-weight:900;color:' + pnlColor + ';' +
                    'text-shadow:0 0 40px ' + pnlGlow + '55, 0 2px 0 rgba(0,0,0,0.3);letter-spacing:-0.02em">' +
                    pnlSign + pnl + '%</div>' +
            '</div>';
    }

    // Build price ladder rows
    var ladderRows = '';
    if (isLong) {
        for (var i = targets.length - 1; i >= 0; i--) {
            ladderRows += _ladderRow('TP' + (i + 1), targets[i], _pctDiff(entry, targets[i]), C.green, C.greenGlow);
        }
        ladderRows += _ladderRow('ENTRY', entry, '—', C.cyan, C.cyanGlow);
        ladderRows += _ladderRow('STOP', sl, _pctDiff(entry, sl), C.red, C.redGlow);
    } else {
        ladderRows += _ladderRow('STOP', sl, _pctDiff(entry, sl), C.red, C.redGlow);
        ladderRows += _ladderRow('ENTRY', entry, '—', C.cyan, C.cyanGlow);
        for (var j = 0; j < targets.length; j++) {
            ladderRows += _ladderRow('TP' + (j + 1), targets[j], _pctDiff(entry, targets[j]), C.green, C.greenGlow);
        }
    }

    var html = '' +
    '<div id="__share-card-render" style="' +
        'position:fixed;left:-9999px;top:0;z-index:-1;' +
        'width:' + CARD_W + 'px;height:' + CARD_H + 'px;' +
        'background:linear-gradient(180deg, ' + C.bgTop + ' 0%, ' + C.bgMid + ' 50%, ' + C.bgBot + ' 100%);' +
        'font-family:Inter,system-ui,-apple-system,sans-serif;color:' + C.textPri + ';overflow:hidden;' +
    '">' +

    // ── Decorative layers ──
    // Direction glow (top-left)
    '<div style="position:absolute;inset:0;' + dirBg + ';pointer-events:none"></div>' +
    // Gold accent glow (top-right)
    '<div style="position:absolute;top:-80px;right:-80px;width:400px;height:400px;' +
        'background:radial-gradient(circle,' + C.gold + '12 0%,transparent 70%);pointer-events:none"></div>' +
    // Cyan accent glow (bottom-left)
    '<div style="position:absolute;bottom:-100px;left:-60px;width:350px;height:350px;' +
        'background:radial-gradient(circle,' + C.cyan + '0a 0%,transparent 70%);pointer-events:none"></div>' +
    // Subtle grid
    '<div style="position:absolute;inset:0;opacity:0.025;' +
        'background-image:linear-gradient(rgba(255,255,255,0.15) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,0.15) 1px,transparent 1px);' +
        'background-size:54px 54px;pointer-events:none"></div>' +

    // ── Top gold accent line ──
    '<div style="height:4px;background:linear-gradient(90deg,transparent,' + C.gold + ',' + C.goldLight + ',' + C.gold + ',transparent)"></div>' +

    // ── Header: Logo + Brand + Time ──
    '<div style="padding:36px 48px 0;display:flex;align-items:center;justify-content:space-between">' +
        '<div style="display:flex;align-items:center;gap:16px">' +
            '<img src="' + LOGO + '" style="width:64px;height:64px;border-radius:14px;border:2px solid ' + C.gold + '44;object-fit:cover" crossorigin="anonymous" />' +
            '<div>' +
                '<div style="font-size:26px;font-weight:900;letter-spacing:0.04em;color:' + C.goldLight + '">ANUNNAKI WORLD</div>' +
                '<div style="font-size:14px;font-weight:600;color:' + C.textDim + ';letter-spacing:0.12em;margin-top:2px">TRADING SIGNALS</div>' +
            '</div>' +
        '</div>' +
        '<div style="text-align:right">' +
            '<div style="font-size:13px;font-weight:600;color:' + C.textDim + ';letter-spacing:0.06em">' + _esc(timeStr) + '</div>' +
        '</div>' +
    '</div>' +

    // ── Divider ──
    '<div style="margin:24px 48px 0;height:1px;background:linear-gradient(90deg,transparent,' + C.gold + '33,transparent)"></div>' +

    // ── Pair name (huge) ──
    '<div style="padding:28px 48px 0">' +
        '<div style="font-size:72px;font-weight:900;letter-spacing:-0.03em;line-height:1;color:#fff;' +
            'text-shadow:0 2px 0 rgba(0,0,0,0.4)">' + _esc(pair) +
            '<span style="font-size:36px;color:' + C.textDim + ';font-weight:500">/USDT</span></div>' +
    '</div>' +

    // ── Direction + meta pills ──
    '<div style="padding:16px 48px 0;display:flex;align-items:center;gap:14px;flex-wrap:wrap">' +
        // Direction pill (vibrant)
        '<div style="font-size:22px;font-weight:900;color:#fff;letter-spacing:0.05em;' +
            'background:linear-gradient(135deg,' + dirColor + ',' + dirGlow + ');' +
            'border-radius:12px;padding:10px 28px;' +
            'box-shadow:0 4px 20px ' + dirColor + '44, inset 0 1px 0 rgba(255,255,255,0.2)">' + dir + '</div>' +
        // Leverage
        _pill('⚡ ' + leverage + 'x') +
        // Confidence
        _pill('🎯 ' + confidence + '%') +
        // R:R
        _pill('R:R ' + rr) +
    '</div>' +

    // ── Status badge ──
    '<div style="padding:20px 48px 0">' +
        '<div style="display:inline-block;font-size:16px;font-weight:800;color:' + statusColor + ';letter-spacing:0.1em;' +
            'background:' + statusColor + '14;border:2px solid ' + statusColor + '33;' +
            'border-radius:10px;padding:8px 24px;' +
            'box-shadow:0 0 20px ' + statusGlow + '15">' + statusLabel + '</div>' +
    '</div>' +

    // ── PnL (if available) ──
    pnlHtml +

    // ── Price Ladder ──
    '<div style="padding:' + (pnlHtml ? '20' : '32') + 'px 48px 0">' +
        '<div style="font-size:13px;font-weight:800;color:' + C.gold + ';letter-spacing:0.18em;margin-bottom:18px;' +
            'text-shadow:0 0 12px ' + C.gold + '33">PRICE LEVELS</div>' +
        '<div style="background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.05);border-radius:14px;padding:6px 20px">' +
            ladderRows +
        '</div>' +
    '</div>' +

    // ── Bottom bar: watermark + accent ──
    '<div style="position:absolute;bottom:0;left:0;right:0">' +
        '<div style="text-align:center;padding:0 0 20px">' +
            '<div style="font-size:15px;font-weight:700;color:' + C.gold + '55;letter-spacing:0.2em">' + BRAND + '</div>' +
        '</div>' +
        '<div style="height:4px;background:linear-gradient(90deg,transparent,' + C.gold + ',' + C.goldLight + ',' + C.gold + ',transparent)"></div>' +
    '</div>' +

    '</div>';

    return html;
}

function _pill(text) {
    return '<div style="font-size:18px;font-weight:700;color:' + C.textPri + ';' +
        'background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.1);' +
        'border-radius:10px;padding:10px 20px">' + text + '</div>';
}

function _ladderRow(label, price, pct, color, glow) {
    var isEntry = label === 'ENTRY';
    var dotColor = color;
    return '<div style="display:flex;align-items:center;padding:12px 4px;' +
        (isEntry ? '' : 'border-bottom:1px solid rgba(255,255,255,0.04);') + '">' +
        // Glowing dot
        '<div style="width:10px;height:10px;border-radius:50%;background:' + dotColor + ';' +
            'box-shadow:0 0 8px ' + glow + '66;margin-right:14px;flex-shrink:0"></div>' +
        // Label
        '<div style="width:80px;font-size:16px;font-weight:800;color:' + color + ';letter-spacing:0.08em">' + label + '</div>' +
        // Bar
        '<div style="flex:1;height:2px;background:linear-gradient(90deg,' + color + '44,' + color + '08);border-radius:2px;margin:0 16px"></div>' +
        // Price
        '<div style="font-size:24px;font-weight:700;color:' + C.textPri + ';min-width:160px;text-align:right;' +
            'font-variant-numeric:tabular-nums">' + _fmtPrice(price) + '</div>' +
        // Pct
        (pct && pct !== '—'
            ? '<div style="font-size:15px;font-weight:700;color:' + color + ';min-width:90px;text-align:right">' + pct + '</div>'
            : '<div style="min-width:90px"></div>') +
    '</div>';
}


// ── Render to canvas + show modal ────────────────────────────────────

window.generateShareCard = async function(signalJson) {
    var s;
    try {
        s = typeof signalJson === 'string' ? JSON.parse(signalJson) : signalJson;
    } catch(e) {
        console.error('[share-card] Invalid signal data', e);
        return;
    }

    // Remove any previous render container
    var prev = document.getElementById('__share-card-render');
    if (prev) prev.remove();

    // Build and insert the card DOM
    var wrapper = document.createElement('div');
    wrapper.innerHTML = buildShareCardHTML(s);
    document.body.appendChild(wrapper.firstElementChild);

    var cardEl = document.getElementById('__share-card-render');
    if (!cardEl) { console.error('[share-card] Failed to create card element'); return; }

    // Wait for fonts to load
    try { await document.fonts.ready; } catch(e) {}

    // Render with html2canvas
    try {
        var canvas = await html2canvas(cardEl, {
            width: CARD_W,
            height: CARD_H,
            scale: 1,
            backgroundColor: '#090c14',
            useCORS: true,
            logging: false,
        });
        cardEl.remove();
        _showShareModal(canvas, s);
    } catch(e) {
        console.error('[share-card] html2canvas failed', e);
        cardEl.remove();
        alert('Failed to generate share card. Please try again.');
    }
};


// ── Share modal ──────────────────────────────────────────────────────

function _showShareModal(canvas, signal) {
    // Remove previous modal
    var old = document.getElementById('__share-modal');
    if (old) old.remove();

    var pair = (signal.pair || '').replace('USDT', '/USDT');
    var dir  = signal.direction || '';

    var modal = document.createElement('div');
    modal.id = '__share-modal';
    modal.style.cssText = 'position:fixed;inset:0;z-index:99999;background:rgba(0,0,0,0.85);display:flex;align-items:center;justify-content:center;backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px)';
    modal.onclick = function(e) { if (e.target === modal) modal.remove(); };

    var inner = document.createElement('div');
    inner.style.cssText = 'background:#13171f;border:1px solid rgba(255,255,255,0.1);border-radius:16px;padding:24px;max-width:420px;width:95%;box-shadow:0 24px 64px rgba(0,0,0,0.6)';

    // Title
    var title = document.createElement('div');
    title.style.cssText = 'font-size:16px;font-weight:700;color:#fff;margin-bottom:16px;display:flex;align-items:center;justify-content:space-between';
    title.innerHTML = '<span>📤 Share Signal Card</span><span style="cursor:pointer;font-size:20px;color:rgba(255,255,255,0.4)" id="__share-close">✕</span>';
    inner.appendChild(title);

    // Canvas preview
    var preview = document.createElement('div');
    preview.style.cssText = 'border-radius:12px;overflow:hidden;margin-bottom:16px;border:1px solid rgba(255,255,255,0.06)';
    canvas.style.cssText = 'width:100%;height:auto;display:block';
    preview.appendChild(canvas);
    inner.appendChild(preview);

    // Buttons row
    var btns = document.createElement('div');
    btns.style.cssText = 'display:flex;gap:10px';

    // Download button
    var dlBtn = document.createElement('button');
    dlBtn.style.cssText = 'flex:1;padding:12px;border:none;border-radius:10px;font-size:14px;font-weight:700;cursor:pointer;background:linear-gradient(135deg,#ffd54f,#f0b429);color:#000;display:flex;align-items:center;justify-content:center;gap:6px';
    dlBtn.innerHTML = '⬇️ Download';
    dlBtn.onclick = function() { _downloadCanvas(canvas, signal.pair); };
    btns.appendChild(dlBtn);

    // Share to X button
    var xBtn = document.createElement('button');
    xBtn.style.cssText = 'flex:1;padding:12px;border:none;border-radius:10px;font-size:14px;font-weight:700;cursor:pointer;background:#000;color:#fff;border:1px solid rgba(255,255,255,0.2);display:flex;align-items:center;justify-content:center;gap:6px';
    xBtn.innerHTML = '𝕏 Post';
    xBtn.onclick = function() {
        var text = dir + ' ' + pair + (signal.leverage ? ' ' + signal.leverage + 'x' : '') + ' | anunnakiworld.com';
        window.open('https://x.com/intent/tweet?text=' + encodeURIComponent(text), '_blank');
        // User can paste the downloaded image
        _downloadCanvas(canvas, signal.pair);
    };
    btns.appendChild(xBtn);

    // Native share (mobile)
    if (navigator.share && navigator.canShare) {
        var nativeBtn = document.createElement('button');
        nativeBtn.style.cssText = 'flex:1;padding:12px;border:none;border-radius:10px;font-size:14px;font-weight:700;cursor:pointer;background:linear-gradient(135deg,#7dd3fc,#3b82f6);color:#000;display:flex;align-items:center;justify-content:center;gap:6px';
        nativeBtn.innerHTML = '📤 Share';
        nativeBtn.onclick = function() { _nativeShare(canvas, signal); };
        btns.appendChild(nativeBtn);
    }

    inner.appendChild(btns);

    // Hint text
    var hint = document.createElement('div');
    hint.style.cssText = 'font-size:11px;color:rgba(255,255,255,0.3);text-align:center;margin-top:12px;line-height:1.5';
    hint.textContent = 'Download the image, then upload it to Instagram or X when posting.';
    inner.appendChild(hint);

    modal.appendChild(inner);
    document.body.appendChild(modal);

    document.getElementById('__share-close').onclick = function() { modal.remove(); };
    // ESC to close
    var escHandler = function(e) { if (e.key === 'Escape') { modal.remove(); document.removeEventListener('keydown', escHandler); } };
    document.addEventListener('keydown', escHandler);
}


// ── Download ─────────────────────────────────────────────────────────

function _downloadCanvas(canvas, pair) {
    var link = document.createElement('a');
    link.download = 'anunnaki-signal-' + (pair || 'card').toLowerCase() + '.png';
    link.href = canvas.toDataURL('image/png');
    link.click();
}


// ── Native Web Share API (mobile) ────────────────────────────────────

async function _nativeShare(canvas, signal) {
    try {
        var blob = await new Promise(function(resolve) { canvas.toBlob(resolve, 'image/png'); });
        var file = new File([blob], 'anunnaki-signal-' + (signal.pair || 'card').toLowerCase() + '.png', { type: 'image/png' });
        var shareData = {
            title: (signal.direction || '') + ' ' + (signal.pair || ''),
            text: (signal.direction || '') + ' ' + (signal.pair || '').replace('USDT', '/USDT') + (signal.leverage ? ' ' + signal.leverage + 'x' : '') + ' | anunnakiworld.com',
            files: [file],
        };
        if (navigator.canShare(shareData)) {
            await navigator.share(shareData);
        } else {
            // Fallback without file
            delete shareData.files;
            await navigator.share(shareData);
        }
    } catch(e) {
        if (e.name !== 'AbortError') {
            console.error('[share-card] native share failed', e);
        }
    }
}

})();
