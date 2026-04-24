# Proposal: Frontend Optimizations (Navigation Refactor & Heatmap Snapshot-First)

## 1. Navigation Refactor (`dashboard/static/js/app-r7.js`)
**Reasoning**: For professional security optics, the "Admin" tab must be completely scrubbed from the DOM if a user is not an administrator, rather than simply being hidden with `display: none;`.
**Risk Assessment**: **Low**. The element is removed during UI updates if the user lacks permissions. If an admin logs out and another user logs in without refreshing the SPA, the tab will stay cleanly removed. Re-authentication via a hard reload is standard for elevating to admin privileges.

### Exact Changes

```diff
--- /home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/dashboard/static/js/app-r7.js
+++ /home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/dashboard/static/js/app-r7.js
@@ -114,3 +114,9 @@
-    // Admin tab
-    document.getElementById('nav-admin').style.display = (_user && _user.is_admin) ? '' : 'none';
+    // Admin tab
+    const adminNav = document.getElementById('nav-admin');
+    if (adminNav) {
+        if (_user && (_user.is_admin || _user.role === 'admin')) {
+            adminNav.style.display = '';
+        } else {
+            adminNav.remove();
+        }
+    }
```

## 2. Heatmap Snapshot-First Optimization (`dashboard/static/js/heatmap.js`)
**Reasoning**: Currently, the application loads "Connecting..." and attempts to establish WebSockets immediately. We have shifted to a "Snapshot-First" state where the live REST data displays immediately so the user isn't forced to see a spinner.
**Risk Assessment**: **Low**. We re-order the operations so that WebSocket connection hooking happens strictly in the background *after* the initial `loadLiqHeatmap` UI state is rendered.

### Exact Changes

```diff
--- /home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/dashboard/static/js/heatmap.js
+++ /home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/dashboard/static/js/heatmap.js
@@ -436,8 +436,5 @@
     document.getElementById('liq-chart-title').textContent = pair;
-    document.getElementById('liq-chart-sub').textContent = 'Loading...';
-    loadLiqContext(pair);
-    connectLiqMarkWs(pair);
-    connectOrderBookWs(pair);
-    loadLiqVelocity(pair);
-    loadLiqSuggest(pair);
+    document.getElementById('liq-chart-sub').innerHTML = '<span style="color:var(--gold)">Fetching snapshot...</span>';
     try {
         var results = await Promise.all([
             fetch('/api/liq/heatmap/' + pair + '?window=' + _liqWindow, { headers: authHeaders() }),
@@ -453,3 +450,9 @@
     } catch(e) {
-        document.getElementById('liq-chart-sub').textContent = 'Failed to load';
+        document.getElementById('liq-chart-sub').textContent = 'Failed to load heatmap snapshot';
+        console.error("Heatmap Snapshot Error:", e);
     }
+
+    loadLiqContext(pair);
+    connectLiqMarkWs(pair);
+    connectOrderBookWs(pair);
+    loadLiqVelocity(pair);
+    loadLiqSuggest(pair);
}
```
