#!/usr/bin/env python3
import sqlite3
c = sqlite3.connect("signal_registry.db")
c.row_factory = sqlite3.Row
rows = c.execute(
    "SELECT pair, status, pnl, targets_hit "
    "FROM signals WHERE pnl > 0 AND status NOT IN ('SENT','OPEN','ACTIVE','VOIDED') "
    "ORDER BY timestamp DESC LIMIT 15"
).fetchall()
for r in rows:
    print(f"{r['pair']:15s} {r['status']:8s} pnl={r['pnl']:+8.2f} th={r['targets_hit']}")
c.close()
