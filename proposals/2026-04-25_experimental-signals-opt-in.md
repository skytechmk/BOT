# Proposal: Broadcast Experimental Signals with Copy-Trading Opt-In

Date: 2026-04-25
Status: Proposed
Priority: High

## Objective

Expose Reverse Hunt experimental signals in the live production-facing signal flow while keeping them clearly marked as experimental.

This change will:

- Send experimental signals to Telegram with a visible `EXPERIMENTAL SIGNAL` warning.
- Keep `signal_tier='experimental'` in storage for attribution and filtering.
- Show experimental signals in the dashboard signal feed with an experimental badge.
- Add a per-user copy-trading setting to opt in to experimental signals.
- Keep copy-trading experimental signals disabled by default for all users.

## Files Changed

- `/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/main.py`
- `/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/telegram_handler.py`
- `/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/dashboard/copy_trading.py`
- `/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/dashboard/app.py`
- `/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/dashboard/static/js/copytrading.js`
- `/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/dashboard/static/js/signals.js`

## Exact Patch

```diff
diff --git a/main.py b/main.py
--- a/main.py
+++ b/main.py
@@ -957,42 +957,45 @@ async def process_pair(pair, timeframe='1h', tv_override=None):
         # ── Tier classification ────────────────────────────────────────
         # Only the clean ARMED path is "production" (public TG + copy-trade).
         # The 6 short-circuit RH paths are routed to the admin-only Lab tab.
         _zone_used = rh_indicators.get('tsi_zone')
         signal_tier = _classify_signal_tier(_zone_used, pair)
 
         if signal_tier == 'experimental':
-            # Lab tier: skip cycle-cap (doesn't share public quota), skip Telegram,
-            # skip copy-trade. Pair cooldown still applies to avoid spamming the
-            # same pair across both tiers in one window.
-            msg_id = None
-            log_message(
-                f"🧪 LAB SIGNAL [{pair}]: {final_signal} | Zone={_zone_used} | "
-                f"SQI={sqi_score} | suppressed from public TG/copy-trade — "
-                f"available in admin Lab tab only"
+            msg = msg.replace(
+                f"{direction_word} #{pair_cornix} {direction_emoji}\n",
+                f"{direction_word} #{pair_cornix} {direction_emoji}\n"
+                f"🧪 EXPERIMENTAL SIGNAL — higher-risk research path\n"
+                f"Path: {_zone_used} | Copy-trading only for users who explicitly opt in.\n\n",
+                1,
             )
-            PAIR_COOLDOWN.record_signal(pair)
-        else:
-            # Production tier: existing public dispatch path.
-            # ── Atomic cycle-cap reservation (race-safe) ──────────────────
-            # Under async concurrency with Semaphore(15), multiple pairs can pass
-            # the optimistic pre-check simultaneously. Serialize the commit path.
-            async with _CYCLE_LOCK:
-                if _CYCLE_SIGNALS_SENT >= CYCLE_SIGNAL_LIMIT:
-                    log_message(f"🚫 Cycle cap reached ({CYCLE_SIGNAL_LIMIT} signals this scan) — {pair} dropped at commit gate")
-                    return
-                _CYCLE_SIGNALS_SENT += 1  # Reserve slot BEFORE send to prevent burst
-
-            try:
-                msg_id = await asyncio.wait_for(send_telegram_message(msg), timeout=15.0)
-            except asyncio.TimeoutError:
-                async with _CYCLE_LOCK:
-                    _CYCLE_SIGNALS_SENT = max(0, _CYCLE_SIGNALS_SENT - 1)  # release reserved slot
-                log_message(f"⏱️ Telegram send timeout (15s) for {pair} — signal slot released")
+
+        # ── Public Telegram dispatch for both production and experimental ──
+        async with _CYCLE_LOCK:
+            if _CYCLE_SIGNALS_SENT >= CYCLE_SIGNAL_LIMIT:
+                log_message(f"🚫 Cycle cap reached ({CYCLE_SIGNAL_LIMIT} signals this scan) — {pair} dropped at commit gate")
                 return
+            _CYCLE_SIGNALS_SENT += 1
 
-            # Post-send Housekeeping
-            increment_daily_signal_count()
-            PAIR_COOLDOWN.record_signal(pair)  # P0 Fix: was never called, cooldown was broken
+        try:
+            msg_id = await asyncio.wait_for(send_telegram_message(msg), timeout=15.0)
+        except asyncio.TimeoutError:
+            async with _CYCLE_LOCK:
+                _CYCLE_SIGNALS_SENT = max(0, _CYCLE_SIGNALS_SENT - 1)
+            log_message(f"⏱️ Telegram send timeout (15s) for {pair} — signal slot released")
+            return
+
+        increment_daily_signal_count()
+        PAIR_COOLDOWN.record_signal(pair)
+
+        if signal_tier == 'experimental':
+            log_message(
+                f"🧪 EXPERIMENTAL SIGNAL BROADCAST [{pair}]: {final_signal} | "
+                f"Zone={_zone_used} | SQI={sqi_score} | Telegram sent | "
+                f"copy-trade opt-in only"
+            )
@@ -1117,16 +1120,18 @@ async def process_pair(pair, timeframe='1h', tv_override=None):
-        # ── Copy-Trading: Production tier only ────────────────────────
-        # Lab/experimental signals are NOT copy-traded — they're for admin review only.
-        if _COPY_TRADING_AVAILABLE and signal_tier == 'production':
+        # ── Copy-Trading: production by default; experimental requires user opt-in.
+        if _COPY_TRADING_AVAILABLE:
             try:
                 await _execute_copy_trades({
                     'signal_id': signal_id, 'pair': pair,
                     'direction': final_signal, 'price': current_price,
                     'targets': targets, 'stop_loss': stop_loss,
                     'leverage': leverage_val,
                     'sqi_score': sqi_score,
                     'sqi_grade': sqi_grade,
+                    'signal_tier': signal_tier,
+                    'zone_used': _zone_used,
                 })
             except Exception as _ct_exc:
                 log_message(f"[copy_trading] execution error: {_ct_exc}")
diff --git a/telegram_handler.py b/telegram_handler.py
--- a/telegram_handler.py
+++ b/telegram_handler.py
@@ -131,7 +131,7 @@ def register_signal(signal_id, pair, signal, price, confidence, targets, stop_lo
             'features': feat,  # Store full technical context (key must match set_signal reader)
             'timestamp': time.time(),
-            'status': 'SENT' if signal_tier == 'production' else 'LAB',
+            'status': 'SENT' if (signal_tier == 'production' or telegram_message_id is not None) else 'LAB',
             'telegram_message_id': telegram_message_id,
             'signal_tier': signal_tier,
             'zone_used': zone_used,
diff --git a/dashboard/copy_trading.py b/dashboard/copy_trading.py
--- a/dashboard/copy_trading.py
+++ b/dashboard/copy_trading.py
@@ -279,6 +279,7 @@ def init_copy_trading_db():
         "ALTER TABLE copy_trading_config ADD COLUMN hot_only INTEGER DEFAULT 0",
+        "ALTER TABLE copy_trading_config ADD COLUMN copy_experimental INTEGER DEFAULT 0",
         "ALTER TABLE copy_trading_config ADD COLUMN sl_mode TEXT DEFAULT 'signal'",
         "ALTER TABLE copy_trading_config ADD COLUMN sl_pct REAL DEFAULT 3.0",
         "ALTER TABLE copy_trades ADD COLUMN sl_price REAL DEFAULT 0",
@@ -452,7 +453,8 @@ def save_api_keys(user_id: int, api_key: str, api_secret: str,
                   scale_with_sqi: bool = True, tp_mode: str = 'pyramid',
                   size_mode: str = 'pct', fixed_size_usd: float = 5.0,
                   leverage_mode: str = 'auto', sl_mode: str = 'signal',
-                  sl_pct: float = 3.0) -> Dict:
+                  sl_pct: float = 3.0,
+                  copy_experimental: bool = False) -> Dict:
@@ -497,20 +499,23 @@ def save_api_keys(user_id: int, api_key: str, api_secret: str,
                  max_leverage, scale_with_sqi, tp_mode,
                  size_mode, fixed_size_usd, leverage_mode, sl_mode, sl_pct,
+                 copy_experimental,
                  created_at, updated_at)
-            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
+            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
             ON CONFLICT(user_id) DO UPDATE SET
                 api_key_enc=excluded.api_key_enc,
                 api_secret_enc=excluded.api_secret_enc,
                 size_pct=excluded.size_pct,
                 max_size_pct=excluded.max_size_pct,
                 max_leverage=excluded.max_leverage,
                 scale_with_sqi=excluded.scale_with_sqi,
                 tp_mode=excluded.tp_mode,
                 size_mode=excluded.size_mode,
                 fixed_size_usd=excluded.fixed_size_usd,
                 leverage_mode=excluded.leverage_mode,
                 sl_mode=excluded.sl_mode,
                 sl_pct=excluded.sl_pct,
+                copy_experimental=excluded.copy_experimental,
                 updated_at=excluded.updated_at
         """, (user_id, encrypt_key(api_key), encrypt_key(api_secret),
               size_pct, max_size_pct, max_leverage,
               int(scale_with_sqi), tp_mode, size_mode, fixed_size_usd,
-              leverage_mode, sl_mode, sl_pct, now, now))
+              leverage_mode, sl_mode, sl_pct, int(copy_experimental), now, now))
@@ -844,7 +849,8 @@ def update_settings(user_id: int, size_pct: float = None, max_size_pct: float =
                     scale_with_sqi: bool = None, tp_mode: str = None,
                     size_mode: str = None, fixed_size_usd: float = None,
                     leverage_mode: str = None, sl_mode: str = None,
-                    sl_pct: float = None) -> Dict:
+                    sl_pct: float = None,
+                    copy_experimental: bool = None) -> Dict:
@@ -898,6 +904,9 @@ def update_settings(user_id: int, size_pct: float = None, max_size_pct: float =
     if sl_pct is not None:
         updates.append("sl_pct=?")
         params.append(max(0.1, min(float(sl_pct), 50.0)))
+    if copy_experimental is not None:
+        updates.append("copy_experimental=?")
+        params.append(int(copy_experimental))
@@ -1283,6 +1292,7 @@ async def execute_copy_trades(signal_data: Dict):
     leverage = int(signal_data.get('leverage', 5))
     sqi_score = float(signal_data.get('sqi_score', 50))
+    signal_tier = str(signal_data.get('signal_tier', 'production') or 'production').lower()
@@ -1338,6 +1348,11 @@ async def execute_copy_trades(signal_data: Dict):
         if cfg.get('tier_expires', 0) and time.time() > cfg['tier_expires']:
             log.info(f"Copy-trade skip user {uid}: tier expired")
             continue
+
+        if signal_tier == 'experimental' and not bool(cfg.get('copy_experimental', 0)):
+            log.info(f"Copy-trade skip user {uid}: experimental signal {signal_id} not enabled")
+            continue
 
         # B4: TradFi pre-flight — skip pairs that previously failed with
diff --git a/dashboard/app.py b/dashboard/app.py
--- a/dashboard/app.py
+++ b/dashboard/app.py
@@ -725,18 +725,18 @@ def _read_signals(limit: int = 50, tier: str = "free") -> list:
             cur.execute(
                 'SELECT signal_id, pair, signal, price, confidence, targets_json, '
-                'stop_loss, leverage, timestamp, status, pnl, telegram_message_id, targets_hit, features_json '
+                'stop_loss, leverage, timestamp, status, pnl, telegram_message_id, targets_hit, features_json, signal_tier, zone_used '
                 "FROM signals WHERE timestamp > ? AND timestamp < ? "
-                "AND COALESCE(signal_tier,'production') = 'production' "
+                "AND COALESCE(signal_tier,'production') IN ('production','experimental') "
                 'ORDER BY timestamp DESC LIMIT ?',
                 (cutoff_old, cutoff_new, limit)
             )
         else:
             cutoff = time.time() - 30 * 86400
             cur.execute(
                 'SELECT signal_id, pair, signal, price, confidence, targets_json, '
-                'stop_loss, leverage, timestamp, status, pnl, telegram_message_id, targets_hit, features_json '
+                'stop_loss, leverage, timestamp, status, pnl, telegram_message_id, targets_hit, features_json, signal_tier, zone_used '
                 "FROM signals WHERE timestamp > ? "
-                "AND COALESCE(signal_tier,'production') = 'production' "
+                "AND COALESCE(signal_tier,'production') IN ('production','experimental') "
                 'ORDER BY timestamp DESC LIMIT ?',
                 (cutoff, limit)
             )
@@ -778,6 +778,8 @@ def _read_signals(limit: int = 50, tier: str = "free") -> list:
                 'time_utc': ts_utc.isoformat(),
                 'time_local': ts_local.strftime('%d %b %H:%M'),
                 'timestamp': row['timestamp'],
+                'signal_tier': row['signal_tier'] or 'production',
+                'zone_used': row['zone_used'],
             }
@@ -1946,7 +1948,7 @@ async def api_signals_live_pnl(user: Optional[dict] = Depends(get_current_user)):
         rows = conn.execute(
             "SELECT signal_id, pair, signal, price, stop_loss, leverage, targets_json, status "
             "FROM signals WHERE status IN ('SENT','OPEN','ACTIVE','TP1_HIT','TP2_HIT') "
-            "AND COALESCE(signal_tier,'production') = 'production' "
+            "AND COALESCE(signal_tier,'production') IN ('production','experimental') "
             "ORDER BY timestamp DESC LIMIT 100"
         ).fetchall()
@@ -2105,7 +2107,7 @@ def _load_open_signals_for_pnl() -> list[dict]:
         rows = conn.execute(
             "SELECT signal_id, pair, signal, price, stop_loss, leverage, targets_json, status "
             "FROM signals WHERE status IN ('SENT','OPEN','ACTIVE','TP1_HIT','TP2_HIT') "
-            "AND COALESCE(signal_tier,'production') = 'production' "
+            "AND COALESCE(signal_tier,'production') IN ('production','experimental') "
             "ORDER BY timestamp DESC LIMIT 200"
         ).fetchall()
@@ -3472,6 +3474,7 @@ async def ct_save_keys(request: Request, user: dict = Depends(require_tier("pro")):
         leverage_mode=str(body.get('leverage_mode', 'auto')),
         sl_mode=str(body.get('sl_mode', 'signal')),
         sl_pct=float(body.get('sl_pct', 3.0)),
+        copy_experimental=bool(body.get('copy_experimental', False)),
     )
@@ -3521,6 +3524,7 @@ async def ct_update(request: Request, user: dict = Depends(require_tier("pro")):
     if 'leverage_mode' in body: kwargs['leverage_mode'] = str(body['leverage_mode'])
     if 'sl_mode' in body: kwargs['sl_mode'] = str(body['sl_mode'])
     if 'sl_pct' in body: kwargs['sl_pct'] = float(body['sl_pct'])
+    if 'copy_experimental' in body: kwargs['copy_experimental'] = bool(body['copy_experimental'])
     result = ct_update_settings(user['id'], **kwargs)
@@ -4614,8 +4618,8 @@ async def api_stream_signals(request: Request):
         cur.execute(
             'SELECT signal_id, pair, signal, price, confidence, targets_json, '
-            'stop_loss, leverage, timestamp, status, pnl, targets_hit '
+            'stop_loss, leverage, timestamp, status, pnl, targets_hit, signal_tier, zone_used '
             "FROM signals WHERE timestamp > ? "
-            "AND COALESCE(signal_tier,'production') = 'production' "
+            "AND COALESCE(signal_tier,'production') IN ('production','experimental') "
             'ORDER BY timestamp DESC LIMIT 30',
             (cutoff_old,)
         )
@@ -4632,6 +4636,8 @@ async def api_stream_signals(request: Request):
                 "time_utc":  ts_utc.isoformat(),
                 "timestamp": row['timestamp'],
                 "locked":    locked,
+                "signal_tier": row['signal_tier'] or 'production',
+                "zone_used": row['zone_used'],
             }
diff --git a/dashboard/static/js/copytrading.js b/dashboard/static/js/copytrading.js
--- a/dashboard/static/js/copytrading.js
+++ b/dashboard/static/js/copytrading.js
@@ -484,6 +484,7 @@ function renderCopyTrading(cfg, stats, trades, bal) {
     var allowedTiers = (hasConfig && cfg.allowed_tiers)  ? cfg.allowed_tiers.split(',')    : ['blue_chip','large_cap','mid_cap','small_cap','high_risk'];
     var allowedSectors = (hasConfig && cfg.allowed_sectors && cfg.allowed_sectors !== 'all') ? cfg.allowed_sectors.split(',') : [];
     var hotOnly      = hasConfig ? !!cfg.hot_only : false;
+    var copyExperimental = hasConfig ? !!cfg.copy_experimental : false;
@@ -541,6 +542,9 @@ function renderCopyTrading(cfg, stats, trades, bal) {
     // ── SQI Scaling ─────────────────────────────────────────────
     html += '<div style="margin-bottom:14px"><label style="display:flex;align-items:center;gap:8px;font-size:12px;color:var(--text-dim);cursor:pointer"><input type="checkbox" id="ct-scale-sqi" ' + (scaleSqi ? 'checked' : '') + ' style="width:14px;height:14px"> Scale position size with signal SQI quality score (±25% of base)</label></div>';
+
+    // ── Experimental Signal Opt-In ──────────────────────────────
+    html += '<div style="margin-bottom:14px;padding:12px 14px;border:1px solid #f0b42955;background:#f0b42910;border-radius:10px"><label style="display:flex;align-items:flex-start;gap:8px;font-size:12px;color:var(--text);cursor:pointer"><input type="checkbox" id="ct-copy-experimental" ' + (copyExperimental ? 'checked' : '') + ' style="width:14px;height:14px;margin-top:2px"><span><strong style="color:#f0b429">🧪 Copy experimental signals</strong><br><span style="color:var(--text-dim);font-size:11px">Disabled by default. Enables copy-trading for signals marked EXPERIMENTAL in Telegram/dashboard.</span></span></label></div>';
@@ -872,6 +876,7 @@ async function saveCopyTradingKeys() {
         fixed_size_usd:   parseFloat(_ctVal('ct-fixed-size-usd', 5.0)) || 5.0,
         leverage_mode:    _ctVal('ct-leverage-mode', 'auto'),
+        copy_experimental: (_ctGetEl('ct-copy-experimental') || {}).checked || false,
     };
@@ -927,6 +932,7 @@ async function saveCopyTradingSettings() {
         fixed_size_usd:   parseFloat(_ctVal('ct-fixed-size-usd', 5.0)) || 5.0,
         leverage_mode:    _ctVal('ct-leverage-mode', 'auto'),
+        copy_experimental: (_ctGetEl('ct-copy-experimental') || {}).checked || false,
     };
diff --git a/dashboard/static/js/signals.js b/dashboard/static/js/signals.js
--- a/dashboard/static/js/signals.js
+++ b/dashboard/static/js/signals.js
@@ -277,6 +277,11 @@ function renderSignals(data) {
             const chartBtn = `<span style="font-size:11px;color:var(--blue);cursor:pointer" onclick="selectPairChart('${s.pair}')">📊 Chart</span>`;
             const sigSym = _symFromPair(s.pair);
             const sigClassBadge = _tierBadgeHtml(sigSym);
+            const isExperimental = (s.signal_tier || '').toLowerCase() === 'experimental';
+            const expBadge = isExperimental
+                ? `<span title="${s.zone_used || 'experimental'}" style="font-size:10px;font-weight:800;color:#f0b429;background:#f0b42922;border:1px solid #f0b42966;border-radius:10px;padding:2px 8px;margin-left:8px;white-space:nowrap">🧪 EXPERIMENTAL${s.zone_used ? ' · ' + s.zone_used : ''}</span>`
+                : '';
 
             const isOpen = ['SENT','OPEN','ACTIVE','TP1_HIT','TP2_HIT'].includes((s.status||'').toUpperCase());
@@ -306,7 +311,7 @@ function renderSignals(data) {
             html += `<div class="signal-card${s.entry_drift_alert ? ' has-drift-alert' : ''}">
                 <div class="sc-header">
-                    <span class="sc-pair">${s.pair.replace('USDT','')}<span style="color:var(--text-dim);font-weight:400;font-size:14px">/USDT</span></span>
+                    <span class="sc-pair">${s.pair.replace('USDT','')}<span style="color:var(--text-dim);font-weight:400;font-size:14px">/USDT</span>${expBadge}</span>
                     <span class="sc-dir ${dirLower}">${dirIcon} ${s.direction}</span>
                 </div>
```

## Behavior After Patch

### Telegram

- Production signals remain unchanged.
- Experimental signals are sent to the same Telegram signal channel.
- Experimental Telegram messages retain the normal signal format but include:
  - `🧪 EXPERIMENTAL SIGNAL — higher-risk research path`
  - `Path: CE_MOMENTUM_LONG`, `CE_MOMENTUM_SHORT`, etc.
  - Explicit copy-trading opt-in warning.

### Dashboard Signals

- `/api/signals` includes both `production` and `experimental` tiers.
- Each signal includes `signal_tier` and `zone_used`.
- Frontend cards show a clear `🧪 EXPERIMENTAL` badge.
- Live PnL tracking includes experimental signals that were publicly sent.

### Copy-Trading

- Existing users remain safe because `copy_experimental` defaults to `0`.
- Production signals continue copy-trading as before.
- Experimental signals copy-trade only for users with the new checkbox enabled.
- The opt-in setting is stored per user in `users.db.copy_trading_config.copy_experimental`.

## Risk Assessment

- **Signal volume risk:** Medium. Experimental signals are more frequent than clean ARMED production signals. Mitigated by keeping the existing per-cycle cap and daily signal limit active for both tiers.
- **Copy-trading risk:** High if enabled by user. Mitigated by defaulting experimental copy-trading to disabled and requiring explicit opt-in.
- **Telegram/Cornix parsing risk:** Medium. The patch keeps the first line as `LONG #PAIR` / `SHORT #PAIR` to preserve signal readability, but adds experimental warning immediately below it.
- **Dashboard UX risk:** Low. Experimental labels are additive and do not remove existing production signal behavior.
- **Database migration risk:** Low. Adds one nullable/defaulted integer column using the existing migration pattern.

## Verification Plan

After applying patch:

```bash
python -m py_compile main.py telegram_handler.py dashboard/app.py dashboard/copy_trading.py
```

Restart services:

```bash
systemctl restart anunnaki-bot.service
systemctl restart anunnaki-dashboard.service
```

Verify DB migration after dashboard startup:

```bash
sqlite3 dashboard/users.db "PRAGMA table_info(copy_trading_config);" | grep copy_experimental
```

Verify dashboard config API returns the new setting for a Pro user:

```bash
curl -s -H "Authorization: Bearer <TOKEN>" http://127.0.0.1:8050/api/copy-trading/config | jq '.config.copy_experimental'
```

Verify experimental signals are visible in signal API after one fires:

```bash
curl -s -H "Authorization: Bearer <TOKEN>" http://127.0.0.1:8050/api/signals | jq '.signals[] | select(.signal_tier=="experimental") | {pair,direction,signal_tier,zone_used}'
```

Verify copy-trading filtering:

```bash
grep "experimental signal" /var/log/anunnaki-bot.log | tail -n 20
```

Expected result for users who did not opt in:

```text
Copy-trade skip user <id>: experimental signal <signal_id> not enabled
```

## Rollback Plan

If signal volume is too high:

1. Revert `main.py` to the old experimental suppression branch.
2. Leave the DB column in place; it is harmless.
3. Restart services.

If copy-trading opt-in creates too much risk:

```sql
UPDATE copy_trading_config SET copy_experimental=0;
```

Then restart dashboard and bot.
