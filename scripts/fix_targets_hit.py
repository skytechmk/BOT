#!/usr/bin/env python3
"""
One-time retroactive fix: recalculate targets_hit for closed signals
that have pnl > 0 but targets_hit = 0.

Uses PnL-based inference: if leveraged PnL exceeds what hitting TP1/TP2/TP3
would give, then those TPs were clearly reached at some point.
"""
import sqlite3
import json

DB = "signal_registry.db"

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row

rows = con.execute("""
    SELECT signal_id, pair, signal, price, targets_json, leverage, pnl, targets_hit
    FROM signals
    WHERE pnl > 0
      AND COALESCE(targets_hit, 0) = 0
      AND status NOT IN ('SENT','OPEN','ACTIVE','VOIDED')
""").fetchall()

updates = []
for r in rows:
    entry = float(r['price'] or 0)
    if entry <= 0:
        continue
    targets = json.loads(r['targets_json']) if r['targets_json'] else []
    if not targets:
        continue
    try:
        lev = int(r['leverage'] or 1)
    except (ValueError, TypeError):
        lev = 1
    is_long = r['signal'].upper() in ('LONG', 'BUY')
    pnl = float(r['pnl'] or 0)

    # Walk targets: if PnL >= what hitting TPn would give (with 5% tolerance), mark as hit
    calc_th = 0
    for i, tp in enumerate(targets):
        tp_raw = abs(tp - entry) / entry * 100
        tp_lev = tp_raw * lev
        if pnl >= tp_lev * 0.90:  # 90% tolerance for slippage
            calc_th = i + 1
        else:
            break

    if calc_th > 0:
        updates.append((calc_th, r['signal_id']))
        print(f"  FIX: {r['pair']:15s} pnl={pnl:+8.2f}% -> targets_hit={calc_th} (was 0)")

if updates:
    con.executemany("UPDATE signals SET targets_hit=? WHERE signal_id=?", updates)
    con.commit()
    print(f"\n✅ Fixed {len(updates)} signals")
else:
    print("No signals need fixing.")

con.close()
