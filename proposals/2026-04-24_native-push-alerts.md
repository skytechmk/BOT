# Proposal: Native Push Alerts Integration

## Context & Problem
Alerts are heavily reliant on Telegram (`telegram_handler.py`). While excellent for community distribution, high-value algorithmic traders often ignore Telegram noise and demand direct smartphone push notifications or unified web-browser notification APIs directly tied to the Anunnaki World dashboard session.

## Proposed Architecture: Web Push API & Firebase Cloud Messaging (FCM)

Instead of relying solely on Telegram message queuing, we will integrate Service Workers to deliver native OS-level notifications (iOS, Android, Windows, macOS) directly from the `dashboard/app.py`.

### 1. Frontend: Service Worker Initialization (`dashboard/static/js/sw.js`)
Introduce a standard Service Worker to listen for Push events.
```javascript
self.addEventListener('push', function(event) {
  const data = event.data.json();
  const options = {
    body: data.body,
    icon: '/static/logo.jpeg',
    badge: '/static/badge.png',
    data: { url: data.url }
  };
  event.waitUntil(
    self.registration.showNotification(data.title, options)
  );
});

self.addEventListener('notificationclick', function(event) {
  event.notification.close();
  event.waitUntil(clients.openWindow(event.notification.data.url));
});
```

### 2. Backend: Push Distribution Engine
Add a `webpush` mechanism alongside the Telegram dispatch in `realtime_signal_monitor.py`.
```python
from pywebpush import webpush, WebPushException

# Existing telegram trigger
# await send_telegram_signal(...)

# New native push trigger payload
payload = {
    "title": f"🚨 NEW SIGNAL: {signal.symbol} {signal.direction}",
    "body": f"Entry: {signal.entry} | Leverage: {signal.leverage}x",
    "url": f"https://anunnakiworld.com/signals/{signal.id}"
}

# Distribute to all subscribers mapping to user_id
for sub in get_user_push_subscriptions(user_id):
    try:
        webpush(subscription_info=sub.json, data=json.dumps(payload), vapid_private_key=VAPID_KEY, vapid_claims={"sub": "mailto:admin@skytech.mk"})
    except WebPushException:
         remove_stale_subscription(sub.id)
```

## Risk Assessment
**Zero Trading Risk**: Alert transmission errors fail gracefully and sit entirely outside of the `signal_generator.py` execution thread. This is a purely cosmetic but highly valuable retention feature for Pro/Ultra subscribers.
