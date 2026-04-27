# Proposal: Enhanced Real-Time Signal Monitoring and Historical Backfill

## Summary

This proposal addresses the need for real-time monitoring of all signals (normal and lab/experimental) via Binance stream with 1-second updates, immediate database writes upon reaching take-profit (TP) targets, improved display logic for partial and full TP hits, clear indication of stop-loss (SL) after TP hits, tracking of TP and SL hit percentages, and backfilling historical signal data with real PnL adjusted by leverage.

## Requirements

1. **Real-Time Monitoring**: Monitor every signal post-firing via Binance stream with 1-second updates.
2. **Immediate Database Writes**: Write to the database immediately when a signal reaches a TP target.
3. **Display Logic**:
   - Display TP1 with a checkmark when reached.
   - Show percentage above TP1 if price continues to rise.
   - Mark as 'All TPs' with a checkmark when TP3 is reached.
   - Clearly display if a signal reaches TP1 (or higher) and then hits SL.
4. **Tracking**: Track the percentage of signals hitting TP1, TP2, TP3, and SL globally for all signals.
5. **Backfill Historical Data**: Backfill all signals from the platform's inception with real data and PnL multiplied by the signal's leverage.

## Evidence

Current system:
- `realtime_closer.py` and `realtime_signal_monitor.py` handle real-time monitoring but may not update every second or write immediately to the database for partial TP hits.
- `dashboard/app.py` and `dashboard/static/js/lab.js` manage display but lack explicit tracking for partial TP hits followed by SL.
- Historical data in `signal_registry.db` has some signals with missing or zero PnL, especially for older records.

## Proposed Fix

### Part 1 — Real-Time Monitoring via Binance Stream (1s Updates)

**File:** `/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/realtime_signal_monitor.py`

Enhance the `RealtimeSignalMonitor` class to subscribe to Binance WebSocket streams for 1-second updates:

```diff
*** Update File: /home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/realtime_signal_monitor.py
@@
    def __init__(self, telegram_sender, closed_signals_sender, open_signals_tracker, signal_registry):
        self.telegram_sender = telegram_sender
        self.closed_signals_sender = closed_signals_sender
        self.open_signals_tracker = open_signals_tracker
        self.signal_registry = signal_registry
        self.running = False
        self._active_pairs = set()
        self._needs_reconnect = False
        self._trailing_sl = {}
+       self._last_check = time.time()
+       self._check_interval = 1.0  # Check every 1 second
        self.monitoring_stats = {
            'signals_checked': 0,
            'stop_losses_hit': 0,
            'targets_hit': 0
        }
        self.logger = logging.getLogger(__name__)
@@
    async def run(self):
        self.running = True
        while self.running:
            try:
+               now = time.time()
+               if now - self._last_check >= self._check_interval:
+                   await self._check_all_signals()
+                   self._last_check = now
                if self._needs_reconnect:
                    self._needs_reconnect = False
                    await self._reconnect_streams()
                await asyncio.sleep(0.1)
            except Exception as e:
                self.logger.error(f"Monitor error: {e}")
                await asyncio.sleep(1)
+   async def _check_all_signals(self):
+       for pair in self._active_pairs:
+           mark_price = await self._get_current_price(pair)
+           if mark_price:
+               await self._check_pair(pair, mark_price)
+   async def _get_current_price(self, pair):
+       # Placeholder for fetching current price from Binance stream
+       # This should be implemented to get the latest price from the WebSocket stream
+       return PRICE_BROADCASTER.get_price(pair)  # Assuming PRICE_BROADCASTER is updated every second
```

### Part 2 — Immediate Database Writes on Target Hits

**File:** `/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/realtime_signal_monitor.py`

Modify `_evaluate_signal` to write to the database immediately upon hitting any TP or SL:

```diff
*** Update File: /home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/realtime_signal_monitor.py
@@
    async def _evaluate_signal(self, sid: str, sig: Dict, mark: float):
        # ... existing code for SL and TP checks ...
        # ── SL check ──────────────────────────────────────────────────────
        sl_triggered = (is_long and mark <= sl) or (not is_long and mark >= sl)
        if sl_triggered:
            raw_pnl = ((sl - entry) / entry * 100) if is_long else ((entry - sl) / entry * 100)
            lev_pnl = round(raw_pnl * leverage, 2)
            # Pass highest_pierced so a trailing-SL exit after TPs were
            # reached records the real outcome (e.g. SL after TP2 → targets_hit=2).
+           self._db_write(sid, pnl=lev_pnl, targets_hit=highest_pierced, close=True, close_reason='SL_HIT')
            await self._on_close(sid, sig, mark, lev_pnl, 'SL_HIT', targets_hit=highest_pierced)
            return
        # ── TP check ───────────────────────────────────────────────────────
        # Walk *every* unhit TP that has been pierced (not just one per tick).
        # Handles price gaps that jump multiple TPs in a single tick.
        new_hits = [n for n in range(1, highest_pierced + 1) if n not in hits]
        for tn in new_hits:
            tp = targets[tn - 1]
            hits.append(tn)
            raw_pnl = ((tp - entry) / entry * 100) if is_long else ((entry - tp) / entry * 100)
            lev_pnl = round(raw_pnl * leverage, 2)
            is_final = (tn == len(targets))
            reason   = f'TP{tn}_HIT'
+           self._db_write(sid, pnl=lev_pnl, targets_hit=tn, close=is_final, close_reason=reason if is_final else None)
            self.monitoring_stats['targets_hit'] += 1
            if is_final:
                await self._on_close(sid, sig, mark, lev_pnl, reason, targets_hit=tn)
                return  # signal is closed
            # Partial TP — persist hit but keep signal active
-           self._db_write(sid, pnl=lev_pnl, targets_hit=tn, close=False)
            self.logger.info(f"🎯 {sig['pair']} TP{tn} hit @ {mark:.6f} (+{lev_pnl:.2f}%)")
```

### Part 3 — Display Logic for TP and SL Hits

**File:** `/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/dashboard/static/js/lab.js`

Update the display logic to show TP hits with checkmarks and SL after TP:

```diff
*** Update File: /home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/dashboard/static/js/lab.js
@@
+function _labFmtSignalOutcome(s) {
+    if (!s || s.status === 'SENT' || s.status === 'OPEN' || s.status === 'ACTIVE') {
+        return '<span style="color:var(--text-dim)">Open</span>';
+    }
+    const status = (s.status || '').toUpperCase();
+    const reason = (s.close_reason || '').toUpperCase();
+    const th = s.targets_hit || 0;
+    if (status === 'CLOSED' || status === 'CANCELLED') {
+        if (reason.includes('SL_HIT')) {
+            if (th > 0) {
+                return `<span style="color:#ff5252">SL Hit after TP${th} ✅</span>`;
+            }
+            return '<span style="color:#ff5252">SL Hit</span>';
+        }
+        if (reason.includes('TP3_HIT') || (th === 3 && reason.includes('BACKFILLED_MARK_CLOSE'))) {
+            return '<span style="color:#00c853">All TPs ✅</span>';
+        }
+        if (reason.includes('TP2_HIT') || (th === 2 && reason.includes('BACKFILLED_MARK_CLOSE'))) {
+            return '<span style="color:#00c853">TP2 ✅</span>';
+        }
+        if (reason.includes('TP1_HIT') || (th === 1 && reason.includes('BACKFILLED_MARK_CLOSE'))) {
+            return '<span style="color:#00c853">TP1 ✅</span>';
+        }
+        if (reason === 'CLOSED_EVEN' || reason === 'BACKFILLED_MARK_CLOSE') {
+            return '<span style="color:var(--text-dim)">Closed Even</span>';
+        }
+        return '<span style="color:var(--text-dim)">Closed</span>';
+    }
+    return '<span style="color:var(--text-dim)">Unknown</span>';
+}
@@
-                            <td style="text-align:right;padding:8px 14px;font-weight:700">${_labFmtSignalPnl(s)}</td>
+                            <td style="text-align:right;padding:8px 14px;font-weight:700">${_labFmtSignalPnl(s)}</td>
+                            <td style="text-align:left;padding:8px 14px">${_labFmtSignalOutcome(s)}</td>
```

**File:** `/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/dashboard/static/js/signals.js`

Apply similar logic for normal signals:

```diff
*** Update File: /home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/dashboard/static/js/signals.js
@@
+function _signalFmtOutcome(s) {
+    if (!s || s.status === 'SENT' || s.status === 'OPEN' || s.status === 'ACTIVE') {
+        return '<span style="color:var(--text-dim)">Open</span>';
+    }
+    const status = (s.status || '').toUpperCase();
+    const reason = (s.close_reason || '').toUpperCase();
+    const th = s.targets_hit || 0;
+    if (status === 'CLOSED' || status === 'CANCELLED') {
+        if (reason.includes('SL_HIT')) {
+            if (th > 0) {
+                return `<span style="color:#ff5252">SL Hit after TP${th} ✅</span>`;
+            }
+            return '<span style="color:#ff5252">SL Hit</span>';
+        }
+        if (reason.includes('TP3_HIT') || (th === 3 && reason.includes('BACKFILLED_MARK_CLOSE'))) {
+            return '<span style="color:#00c853">All TPs ✅</span>';
+        }
+        if (reason.includes('TP2_HIT') || (th === 2 && reason.includes('BACKFILLED_MARK_CLOSE'))) {
+            return '<span style="color:#00c853">TP2 ✅</span>';
+        }
+        if (reason.includes('TP1_HIT') || (th === 1 && reason.includes('BACKFILLED_MARK_CLOSE'))) {
+            return '<span style="color:#00c853">TP1 ✅</span>';
+        }
+        if (reason === 'CLOSED_EVEN' || reason === 'BACKFILLED_MARK_CLOSE') {
+            return '<span style="color:var(--text-dim)">Closed Even</span>';
+        }
+        return '<span style="color:var(--text-dim)">Closed</span>';
+    }
+    return '<span style="color:var(--text-dim)">Unknown</span>';
+}
@@
-                            <td class="signal-status">${s.status}</td>
+                            <td class="signal-status">${_signalFmtOutcome(s)}</td>
```

### Part 4 — Tracking TP and SL Hit Percentages

**File:** `/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/dashboard/analytics.py`

Add tracking for TP1, TP2, TP3, and SL hit percentages:

```diff
*** Update File: /home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/dashboard/analytics.py
@@
+def get_signal_hit_stats(days=30):
+    cutoff = time.time() - max(1, int(days)) * 86400
+    conn = sqlite3.connect(f"file:{_SIGNAL_DB}?mode=ro", uri=True)
+    conn.row_factory = sqlite3.Row
+    cur = conn.cursor()
+    cur.execute(
+        "SELECT COUNT(*) AS total, "
+        "SUM(CASE WHEN targets_hit >= 1 THEN 1 ELSE 0 END) AS tp1_hit, "
+        "SUM(CASE WHEN targets_hit >= 2 THEN 1 ELSE 0 END) AS tp2_hit, "
+        "SUM(CASE WHEN targets_hit = 3 THEN 1 ELSE 0 END) AS tp3_hit, "
+        "SUM(CASE WHEN close_reason LIKE '%SL_HIT%' THEN 1 ELSE 0 END) AS sl_hit "
+        "FROM signals WHERE status IN ('CLOSED', 'TP1_HIT', 'TP2_HIT', 'TP3_HIT', 'SL_HIT', 'CLOSED_WIN', 'CLOSED_LOSS', 'LOSS') AND timestamp > ?",
+        (cutoff,)
+    )
+    row = cur.fetchone()
+    total = row['total']
+    stats = {
+        'total_closed': total,
+        'tp1_hit': row['tp1_hit'],
+        'tp2_hit': row['tp2_hit'],
+        'tp3_hit': row['tp3_hit'],
+        'sl_hit': row['sl_hit'],
+        'tp1_hit_pct': (row['tp1_hit'] / total * 100) if total > 0 else 0,
+        'tp2_hit_pct': (row['tp2_hit'] / total * 100) if total > 0 else 0,
+        'tp3_hit_pct': (row['tp3_hit'] / total * 100) if total > 0 else 0,
+        'sl_hit_pct': (row['sl_hit'] / total * 100) if total > 0 else 0,
+    }
+    conn.close()
+    return stats
```

**File:** `/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/dashboard/app.py`

Expose these stats via API:

```diff
*** Update File: /home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/dashboard/app.py
@@
+@app.get("/api/signals/hit_stats")
+async def api_signals_hit_stats(days: int = 30):
+    from analytics import get_signal_hit_stats
+    return JSONResponse(get_signal_hit_stats(days))
```

### Part 5 — Backfill Historical Data with Real PnL Adjusted by Leverage

**File:** `/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/backfill_signals.py`

Create a script to backfill historical signal data:

```python
*** New File: /home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/backfill_signals.py
#!/usr/bin/env python3
import sqlite3, json, pathlib, time
root = pathlib.Path('/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA')
sigdb = root / 'signal_registry.db'
ohlcv = root / 'ohlcv_cache.db'
sc = sqlite3.connect(sigdb); sc.row_factory = sqlite3.Row
oc = sqlite3.connect(f'file:{ohlcv}?mode=ro', uri=True); oc.row_factory = sqlite3.Row
TF_MS = {'1m': 60000, '5m': 300000, '15m': 900000, '1h': 3600000}

def best_table(pair, start, end):
    for tf in ('1m', '5m', '15m', '1h'):
        t = f'{pair}_{tf}'
        ex = oc.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone()
        if not ex: continue
        tf_ms = TF_MS[tf]
        n = oc.execute(f'SELECT COUNT(*) FROM "{t}" WHERE timestamp <= ? AND timestamp + ? >= ?', (end, tf_ms, start)).fetchone()[0]
        if n: return t, tf
    return None, None

def pnl_for(direction, entry, px, lev):
    raw = ((px - entry) / entry * 100) if direction == 'LONG' else ((entry - px) / entry * 100)
    return round(raw * lev, 4)

rows = sc.execute("""
SELECT signal_id, pair, signal, price, stop_loss, leverage, timestamp, closed_timestamp, status, pnl, targets_hit, targets_json, close_reason
FROM signals
WHERE status IN ('CLOSED', 'TP1_HIT', 'TP2_HIT', 'TP3_HIT', 'SL_HIT', 'CLOSED_WIN', 'CLOSED_LOSS', 'LOSS')
ORDER BY timestamp ASC
""").fetchall()

updates = []; skipped = []
for r in rows:
    pair = r['pair']; direction = (r['signal'] or '').upper(); is_long = direction == 'LONG'
    entry = float(r['price'] or 0); sl = float(r['stop_loss'] or 0); lev = int(r['leverage'] or 1)
    targets = json.loads(r['targets_json'] or '[]')
    start = int(float(r['timestamp']) * 1000); end = int(float(r['closed_timestamp'] or r['timestamp']) * 1000)
    table, tf = best_table(pair, start, end)
    if not table:
        skipped.append((r['signal_id'], pair, 'no_covered_candles')); continue
    tf_ms = TF_MS[tf]
    candles = oc.execute(f'SELECT timestamp, high, low, close FROM "{table}" WHERE timestamp <= ? AND timestamp + ? >= ? ORDER BY timestamp ASC', (end, tf_ms, start)).fetchall()
    terminal = None; partial = 0
    for c in candles:
        hi = float(c['high']); lo = float(c['low'])
        for i, tp in enumerate(targets):
            if i + 1 <= partial: continue
            if (is_long and hi >= tp) or ((not is_long) and lo <= tp): partial = i + 1
        sl_hit = sl and ((is_long and lo <= sl) or ((not is_long) and hi >= sl))
        final_hit = bool(targets) and partial == len(targets)
        if sl_hit:
            terminal = ('SL_HIT', sl, partial); break
        if final_hit:
            terminal = (f'TP{len(targets)}_HIT', targets[-1], len(targets)); break
    if terminal:
        reason, px, th = terminal
    else:
        px = float(candles[-1]['close']) if candles else entry; th = partial; reason = 'BACKFILLED_MARK_CLOSE'
    pnl = pnl_for(direction, entry, px, lev)
    updates.append((pnl, th, reason, r['signal_id'], pair, tf))

sc.executemany("UPDATE signals SET pnl=?, targets_hit=?, close_reason=COALESCE(close_reason, ?) WHERE signal_id=?", [(p, t, reason, sid) for p, t, reason, sid, pair, tf in updates])
sc.commit()
print('updated', len(updates))
for p, t, reason, sid, pair, tf in updates[:20]:
    print(pair, sid[:8], tf, p, t, reason)
print('skipped', len(skipped), skipped[:20])
sc.close(); oc.close()
"""

## Risk Assessment

- **High risk for real-time monitoring:** Implementing 1-second updates may increase system load and require optimization of WebSocket connections.
- **Medium risk for immediate DB writes:** Ensures data consistency but may increase database operations.
- **Low risk for display logic:** Changes are frontend-only and improve user experience.
- **Medium risk for tracking stats:** Requires accurate historical data for meaningful statistics.
- **High risk for historical backfill:** Backfilling all signals from platform inception is resource-intensive and must be conservative to avoid incorrect data.

## Verification Plan

1. **Real-Time Monitoring:** Confirm signals are updated every second via Binance stream.
2. **Immediate DB Writes:** Check database entries for immediate updates on TP hits.
3. **Display Logic:** Verify frontend shows TP hits with checkmarks and SL after TP clearly.
4. **Tracking Stats:** Confirm API `/api/signals/hit_stats` returns accurate percentages for TP1, TP2, TP3, and SL hits.
5. **Historical Backfill:** Verify a sample of old signals have updated PnL and targets_hit reflecting real historical data adjusted by leverage.

## Operator Notes

This proposal does not directly modify production code. After review, the operator can apply these changes or request a helper script for implementation. The backfill operation is particularly intensive and should be run during a maintenance window.
