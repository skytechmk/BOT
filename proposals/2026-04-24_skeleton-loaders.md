# Proposal: UI Skeleton Loaders for Perceived Performance

## 1. Screener Module (`dashboard/static/js/screener.js`)

**Reasoning**: Users currently see a synchronous spinner (`Fetching TradingView data...`), stalling the UI. Replacing this with a grid of skeleton cards (matching the final rendered grid size) maintains layout stability and vastly improves perceived application speed.
**Risk Assessment**: **Low**. We are only mutating the `innerHTML` string used during the loading state. 

### Exact Changes

```diff
--- dashboard/static/js/screener.js
+++ dashboard/static/js/screener.js
@@ -9,3 +9,16 @@
     const el = document.getElementById('screener-container');
     if (!el) return;
-    el.innerHTML = '<div class="loading"><div class="spinner"></div>Fetching TradingView data...</div>';
+    
+    // Generate skeleton layout matching the final screener-grid
+    const skeletonCards = Array(12).fill(`
+        <div class="screener-card" style="border: 1px solid var(--border); padding: 16px;">
+            <div style="height: 20px; width: 40%; background: var(--border); border-radius: 4px; margin-bottom: 16px; animation: ctpulse 1.5s infinite"></div>
+            <div style="height: 12px; width: 100%; background: var(--border); border-radius: 4px; margin-bottom: 12px; animation: ctpulse 1.5s infinite 0.1s"></div>
+            <div style="height: 12px; width: 80%; background: var(--border); border-radius: 4px; margin-bottom: 12px; animation: ctpulse 1.5s infinite 0.2s"></div>
+            <div style="height: 12px; width: 60%; background: var(--border); border-radius: 4px; animation: ctpulse 1.5s infinite 0.3s"></div>
+        </div>
+    `).join('');
+    
+    el.innerHTML = `<style>@keyframes ctpulse { 0%, 100% {opacity:0.4} 50% {opacity:0.1} }</style>
+                    <div class="screener-grid">\${skeletonCards}</div>`;
+                    
     try {
         const res = await fetch('/api/screener', { headers: authHeaders() });
```

---

## 2. Copy-Trading Module (`dashboard/static/js/copytrading.js`)

**Reasoning**: Copy-trading has a heavy parallel data fetch (config, history, balance). The user currently stares at a frozen screen. Instantly painting the structural layout wireframes reduces friction.
**Risk Assessment**: **Low**. Simply replaces loading HTML payload entirely within the SPA context.

### Exact Changes

```diff
--- dashboard/static/js/copytrading.js
+++ dashboard/static/js/copytrading.js
@@ -78,3 +78,16 @@
     }
-    container.innerHTML = '<div class="loading"><div class="spinner"></div>Loading copy-trading...</div>';
+    
+    container.innerHTML = `
+        <style>@keyframes ctpulse { 0%, 100% {opacity:0.4} 50% {opacity:0.1} }</style>
+        <div class="section-header"><h2>🤖 Copy-Trading</h2></div>
+        <div style="background:var(--surface);border:1px solid var(--border);border-radius:14px;padding:20px;margin-bottom:18px">
+            <div style="height: 12px; width: 100px; background: var(--border); border-radius: 4px; margin-bottom: 14px; animation: ctpulse 1.5s infinite"></div>
+            <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px">
+                \${Array(4).fill('<div style="height: 70px; border-radius: 10px; background: var(--border); animation: ctpulse 1.5s infinite 0.2s"></div>').join('')}
+            </div>
+        </div>
+        <div style="height: 60px; background: var(--surface); border: 1px solid var(--border); border-radius: 12px; margin-bottom: 16px; animation: ctpulse 1.5s infinite 0.4s"></div>
+        <div style="height: 200px; background: var(--surface); border: 1px solid var(--border); border-radius: 12px; animation: ctpulse 1.5s infinite 0.6s"></div>
+    `;
+
     try {
         var results = await Promise.all([
```
