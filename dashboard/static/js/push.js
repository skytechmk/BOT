// ═══════════════════════════════════════════════════════════════════
//  Anunnaki World · Push-notification subscription UI (v1 · 2026-04-24)
//
//  Adds a "🔔 Notify me" toggle wherever an element with
//  id="push-subscribe-btn" exists. Safe to include on any page — if
//  the element isn't present or push is unsupported, we silently no-op.
//
//  End-to-end flow:
//    1. GET /api/push/vapid-public-key → if empty, hide the button.
//    2. Register /static/sw.js as a service worker.
//    3. On click, request Notification.permission.
//    4. Call pushManager.subscribe(…) with the VAPID public key.
//    5. POST the subscription JSON to /api/push/subscribe.
// ═══════════════════════════════════════════════════════════════════

(function() {
    'use strict';

    // Base64 URL-safe → Uint8Array (Web Push spec).
    function urlB64ToUint8Array(base64String) {
        const padding = '='.repeat((4 - base64String.length % 4) % 4);
        const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
        const raw = atob(base64);
        const out = new Uint8Array(raw.length);
        for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
        return out;
    }

    async function getPublicKey() {
        try {
            const res = await fetch('/api/push/vapid-public-key');
            if (!res.ok) return null;
            const d = await res.json();
            return d.public_key || null;
        } catch (e) { return null; }
    }

    async function subscribe(btn) {
        if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
            btn.textContent = 'Push not supported on this browser';
            btn.disabled = true;
            return;
        }
        const pubKey = await getPublicKey();
        if (!pubKey) {
            btn.style.display = 'none';   // server not configured → hide entirely
            return;
        }
        btn.disabled = true;
        btn.textContent = '⏳ Requesting permission…';
        try {
            const permission = await Notification.requestPermission();
            if (permission !== 'granted') {
                btn.textContent = '🔕 Notifications blocked';
                return;
            }
            const reg = await navigator.serviceWorker.register('/static/sw.js');
            // Reuse existing subscription if the user previously opted in.
            let sub = await reg.pushManager.getSubscription();
            if (!sub) {
                sub = await reg.pushManager.subscribe({
                    userVisibleOnly: true,
                    applicationServerKey: urlB64ToUint8Array(pubKey),
                });
            }
            const token = localStorage.getItem('aladdin_token') || '';
            const res = await fetch('/api/push/subscribe', {
                method: 'POST',
                headers: {
                    'Content-Type':  'application/json',
                    'Authorization': 'Bearer ' + token,
                },
                body: JSON.stringify({
                    subscription: sub.toJSON(),
                    user_agent:   navigator.userAgent,
                }),
            });
            if (!res.ok) throw new Error('server rejected subscription');
            btn.textContent = '🔔 Notifications on';
            btn.classList.add('active');
            btn.disabled = false;
        } catch (e) {
            console.error('[push] subscribe failed:', e);
            btn.textContent = '⚠️ Enable failed';
            btn.disabled = false;
        }
    }

    function init() {
        const btn = document.getElementById('push-subscribe-btn');
        if (!btn) return;
        btn.addEventListener('click', () => subscribe(btn));
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
