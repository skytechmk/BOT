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
