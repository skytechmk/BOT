# Proposal: Fix Closed Lab Signals Showing 0.00% PnL

## Summary

The `Recent Lab Signals` table is showing `0.00%` for many closed lab signals because the dashboard displays the persisted `signals.pnl` value directly. Several experimental rows in `signal_registry.db` are already stored as `status='CLOSED'` with `pnl=0.0` and `targets_hit=0`.

This is a data/outcome persistence issue, not a frontend formatting issue.

## Evidence

Dashboard flow:

- `dashboard/static/js/lab.js` renders PnL using `_labFmtPnl(s.pnl)`.
- `/api/admin/lab/signals` in `dashboard/app.py` returns `row['pnl']` from `signal_registry.db` without recalculation.
- Therefore, if DB says `pnl=0.0`, the Lab table correctly renders `0.00%`.

Read-only DB inspection showed these clusters for experimental signals:

```text
{'status': 'CLOSED', 'close_reason': 'SL_HIT',       'n': 18, 'zero_or_null': 0}
{'status': 'CLOSED', 'close_reason': 'CLOSED_EVEN',  'n': 14, 'zero_or_null': 14}
{'status': 'CLOSED', 'close_reason': None,           'n': 5,  'zero_or_null': 4}
{'status': 'CANCELLED', 'close_reason': None,        'n': 2,  'zero_or_null': 2}
```

Recent examples:

```text
PHAUSDT      SHORT  CLOSED  pnl=0.0  close_reason=None         closed_timestamp=1777294860.0
DOLOUSDT     LONG   CLOSED  pnl=0.0  close_reason=None         closed_timestamp=1777280580.0
INXUSDT      LONG   CLOSED  pnl=0.0  close_reason=None         closed_timestamp=1777280460.0
BIGTIMEUSDT  SHORT  CLOSED  pnl=0.0  close_reason=CLOSED_EVEN  closed_timestamp=1777276834.416141
ANKRUSDT     SHORT  CLOSED  pnl=0.0  close_reason=None         closed_timestamp=1777273320.0
SWARMSUSDT   LONG   CLOSED  pnl=0.0  close_reason=CLOSED_EVEN  closed_timestamp=1777276471.2881904
```

Rows closed by the live TP/SL paths do have valid non-zero PnL, for example `SL_HIT`, `TP3_HIT`, `LOSS`, `WIN`, and some generic `CLOSED` rows.

## Root Cause

The Lab API is doing exactly what it is coded to do: return the canonical stored PnL.

The incorrect `0.00%` rows come from ambiguous close paths that mark experimental signals as terminal without calculating or preserving actual outcome PnL:

- `CLOSED_EVEN`
- `CLOSED` with `close_reason IS NULL`
- `CANCELLED`
- likely old cleanup/manual closure paths outside the current TP/SL monitor

The current live paths are mostly correct:

- `realtime_closer.py` calculates PnL on `SL_HIT` and final TP.
- `realtime_signal_monitor.py` calculates PnL on `SL_HIT` and final TP.
- `dashboard/app.py::_close_signal_and_feedback()` calculates PnL on live PnL stream closure.

But ambiguous non-TP/SL closures can still persist `pnl=0.0`, making Lab analytics and rows misleading.

## Proposed Fix

### Part 1 — Make Lab API expose ambiguous zero-PnL rows clearly

File:

`/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/dashboard/app.py`

In `/api/admin/lab/signals`, add `close_reason` and `closed_timestamp` to the selected fields, and add an `pnl_is_estimated` / `pnl_missing` marker.

This prevents operators from confusing real breakeven trades with uncomputed outcomes.

```diff
*** Update File: /home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/dashboard/app.py
@@
         cur.execute(
             "SELECT signal_id, pair, signal, price, confidence, targets_json, "
             "stop_loss, leverage, timestamp, status, pnl, targets_hit, "
-            "zone_used, signal_tier "
+            "zone_used, signal_tier, close_reason, closed_timestamp "
             "FROM signals WHERE signal_tier = 'experimental' AND timestamp > ? "
             "ORDER BY timestamp DESC LIMIT ?",
             (cutoff, max(1, min(int(limit), 1000))),
         )
@@
-            signals.append({
+            pnl_value = row["pnl"]
+            close_reason = row["close_reason"]
+            status_upper = (row["status"] or "").upper()
+            pnl_missing = (
+                status_upper in ("CLOSED", "CANCELLED")
+                and (pnl_value is None or float(pnl_value or 0) == 0.0)
+                and close_reason not in ("SL_HIT", "TP1_HIT", "TP2_HIT", "TP3_HIT")
+            )
+
+            signals.append({
                 "signal_id":   row["signal_id"],
                 "pair":        row["pair"],
                 "signal":      row["signal"],
                 "price":       row["price"],
@@
-                "pnl":         row["pnl"],
+                "pnl":         pnl_value,
+                "pnl_missing": pnl_missing,
                 "targets_hit": t_hit,
                 "zone_used":   row["zone_used"],
+                "close_reason": close_reason,
+                "closed_timestamp": row["closed_timestamp"],
             })
```

### Part 2 — Render missing PnL as `—` instead of fake `0.00%`

File:

`/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/dashboard/static/js/lab.js`

```diff
*** Update File: /home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/dashboard/static/js/lab.js
@@
 function _labFmtPnl(v) {
     if (v === null || v === undefined || isNaN(v)) return '—';
     const n = Number(v);
@@
 }
+
+function _labFmtSignalPnl(s) {
+    if (s && s.pnl_missing) {
+        return '<span style="color:var(--text-dim)" title="Closed without computed outcome PnL">—</span>';
+    }
+    return _labFmtPnl(s ? s.pnl : null);
+}
@@
-                            <td style="text-align:right;padding:8px 14px;font-weight:700">${_labFmtPnl(s.pnl)}</td>
+                            <td style="text-align:right;padding:8px 14px;font-weight:700">${_labFmtSignalPnl(s)}</td>
```

### Part 3 — Fix future expiry closures in `performance_tracker.py`

Current code closes expired signals with no PnL:

```python
close_open_signal(signal_id, "EXPIRED")
```

That can persist `pnl=None` or `0` for a terminal row.

Replace it with an estimated current PnL when available.

```diff
*** Update File: /home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/performance_tracker.py
@@
         # Remove expired signals
         for signal_id in expired_signals:
-            close_open_signal(signal_id, "EXPIRED")
+            sig = OPEN_SIGNALS_TRACKER.get(signal_id, {})
+            estimated_pnl = _estimate_pnl(sig)
+            close_open_signal(signal_id, "EXPIRED", pnl=estimated_pnl)
             log_message(f"Expired signal {signal_id} removed from open signals")
```

If `_estimate_pnl()` can return `None`, guard `SIGNAL_REGISTRY.update_signal()` in `close_open_signal()` so it does not overwrite a previously valid non-zero PnL with `None`.

```diff
*** Update File: /home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/performance_tracker.py
@@
-                SIGNAL_REGISTRY.update_signal(signal_id, {
+                update_payload = {
                     'status': 'CLOSED',
                     'close_reason': close_reason,
-                    'pnl': pnl,
                     'closed_timestamp': time.time()
-                })
+                }
+                if pnl is not None:
+                    update_payload['pnl'] = pnl
+                SIGNAL_REGISTRY.update_signal(signal_id, update_payload)
```

### Part 4 — Optional safe backfill for existing ambiguous lab rows

For existing rows already closed with `pnl=0.0`, do not guess blindly from current price. Backfill should replay OHLCV from `timestamp` to `closed_timestamp` and calculate whether TP/SL was reached first.

Recommended approach:

- Use `dashboard/backtest_engine.py` logic or a small one-off script.
- Only target rows where:
  - `signal_tier='experimental'`
  - `status IN ('CLOSED','CANCELLED')`
  - `COALESCE(pnl,0)=0`
  - `close_reason IS NULL OR close_reason='CLOSED_EVEN'`
  - `closed_timestamp IS NOT NULL`
- For each signal, replay cached 1h/mark-compatible OHLCV after entry.
- If SL/TP was hit before `closed_timestamp`, write derived PnL and `close_reason`.
- If neither was hit by close time, keep as `CLOSED_EVEN` and `pnl=0.0`.

## Risk Assessment

- **Low risk for display fix:** Adds metadata and changes misleading `0.00%` to `—` only for ambiguous terminal rows.
- **Medium risk for expiry logic:** Uses `_estimate_pnl()` for future expired closes; this depends on live/current price availability.
- **Medium risk for backfill:** Historical reconstruction must be conservative to avoid inventing outcomes.

## Verification Plan

1. Call `/api/admin/lab/signals?days=30&limit=300`.
2. Confirm rows like `PHAUSDT`, `DOLOUSDT`, `INXUSDT`, `BIGTIMEUSDT`, `ANKRUSDT`, `SWARMSUSDT` include `pnl_missing: true`.
3. Open Lab page and verify ambiguous closed rows render `—`, not `0.00%`.
4. Confirm real zero PnL rows are still possible only when close reason indicates true breakeven.
5. Confirm rows with real PnL, such as `ETHFIUSDT -13.70%`, `PENDLEUSDT +24.91%`, still render unchanged.
6. After applying expiry fix, create/test an expired dummy lab signal and confirm it closes with estimated PnL or leaves existing PnL untouched if unavailable.

## Operator Notes

This proposal intentionally does not directly mutate `signal_registry.db`. The existing zero rows should not be backfilled until the replay method is reviewed, because some may genuinely be even/manual closures while others are missing computed PnL.
