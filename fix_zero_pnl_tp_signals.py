#!/usr/bin/env python3
"""Fix zero-PnL closed signals that have TP*_HIT close_reason but targets_hit=0.
   Uses targets_json to compute exit price; if missing, skips the row.
   Assumes leveraged PnL is desired (same logic as realtime monitor).
"""
import sqlite3, json, time, pathlib

DB = pathlib.Path('/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/signal_registry.db')
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

rows = cur.execute(
    """
    SELECT signal_id, pair, signal, price AS entry, leverage, targets_json,
           stop_loss, close_reason
    FROM signals
    WHERE upper(status) IN ('CLOSED','TP1_HIT','TP2_HIT','TP3_HIT','SL_HIT','CLOSED_WIN','CLOSED_LOSS','LOSS')
      AND (pnl IS NULL OR abs(pnl) < 0.0001)
      AND close_reason LIKE 'TP%_HIT'
    """
).fetchall()

update_data = []
for r in rows:
    sid = r['signal_id']
    direction = (r['signal'] or '').upper()
    is_long = direction in ('LONG','BUY')
    leverage = int(r['leverage'] or 1)
    entry = float(r['entry'] or 0)
    targets = []
    if r['targets_json']:
        try:
            targets = json.loads(r['targets_json'])
        except json.JSONDecodeError:
            pass
    if not entry or not targets:
        continue
    # Determine N from close_reason (TP3_HIT -> 3)
    try:
        n = int(r['close_reason'][2])
    except Exception:
        continue
    if n < 1 or n > len(targets):
        continue
    exit_price = float(targets[n-1])
    raw_pct = ((exit_price - entry)/entry*100) if is_long else ((entry - exit_price)/entry*100)
    pnl = round(raw_pct * leverage, 4)
    update_data.append((pnl, n, sid))

print('Will fix', len(update_data), 'signals')
cur.executemany("UPDATE signals SET pnl=?, targets_hit=? WHERE signal_id=?", update_data)
conn.commit()
conn.close()
print('Done')
