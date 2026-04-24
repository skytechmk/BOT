// ═══════════════════════════════════════════════════════════════════
//  Anunnaki World · Service Worker (v1 · 2026-04-24)
//
//  Responsibilities (minimal on purpose):
//   1. Receive Web Push events and display a system notification.
//   2. On notification click, focus an existing dashboard tab or
//      open /app with the signal's deep-link URL.
//
//  We deliberately do NOT cache assets here — caching is handled by
//  Cloudflare at the edge and by the NoCacheJSMiddleware for JS/CSS.
//  Adding a cache-first strategy now would risk serving stale JS bundles
//  to users after we deploy fixes.
// ═══════════════════════════════════════════════════════════════════

self.addEventListener('install',  (e) => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));

self.addEventListener('push', (event) => {
    // Default payload in case the server ever sends an empty push.
    let payload = { title: 'Anunnaki World', body: 'You have a new signal.',
                    url: '/app' };
    try {
        if (event.data) payload = Object.assign(payload, event.data.json());
    } catch (e) { /* keep defaults */ }

    const options = {
        body: payload.body,
        icon: '/static/logo.jpeg',
        badge: '/static/logo.jpeg',
        data: { url: payload.url, extra: payload.data || {} },
        // Signals should interrupt — this is a trading platform, not
        // a newsletter. Users who don't want this UX can simply not
        // subscribe.
        requireInteraction: false,
        silent:             false,
        tag:                'anunnaki-signal',   // collapse bursts
        renotify:           true,
    };
    event.waitUntil(self.registration.showNotification(payload.title, options));
});

self.addEventListener('notificationclick', (event) => {
    event.notification.close();
    const target = (event.notification.data && event.notification.data.url) || '/app';
    event.waitUntil((async () => {
        const clis = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
        // If any dashboard tab is already open, focus it and navigate.
        for (const c of clis) {
            if (c.url.includes('/app') || c.url.includes('/dashboard')) {
                await c.focus();
                if ('navigate' in c) await c.navigate(target);
                return;
            }
        }
        await self.clients.openWindow(target);
    })());
});
