#!/usr/bin/env python3
"""
Backfill signal_tier + zone_used for historical signals.

Source of truth: main.log lines like:
  2026-04-18 22:30:32,825 - INFO - 🎯 REVERSE HUNT [METAUSDT] LONG | ... | TSI Zone: PERSISTENT_OS_L2 | ...

Strategy:
  1. Parse every '🎯 REVERSE HUNT' line, extract (timestamp, pair, direction, zone).
  2. For each, find the matching signals row by pair+direction with closest
     timestamp within ±300s.
  3. UPDATE signals SET zone_used=?, signal_tier=? WHERE signal_id=?
  4. Production zones: OS_L2_ARMED, OB_L2_ARMED, TV_SIGNAL — everything else
     becomes 'experimental'.

Signals predating the log window stay as 'production' (default) — their RH
zone provenance is unrecoverable.
"""
import os, re, sys, sqlite3
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB   = os.path.join(ROOT, 'signal_registry.db')
LOG  = os.path.join(ROOT, 'main.log')

PRODUCTION_ZONES = {'OS_L2_ARMED', 'OB_L2_ARMED', 'TV_SIGNAL'}

# Match: 2026-04-18 22:30:32,825 - INFO - 🎯 REVERSE HUNT [PAIR] DIR | ... | TSI Zone: ZONE | ...
LINE_RE = re.compile(
    r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+.*?'
    r'REVERSE HUNT \[([A-Z0-9]+)\]\s+(LONG|SHORT)\s+\|.*?TSI Zone:\s*([A-Z0-9_]+)'
)
# Server is UTC+02 (CEST per system info).
SERVER_TZ_OFFSET_SEC = 2 * 3600


def parse_log(log_path: str) -> list[dict]:
    rows = []
    if not os.path.exists(log_path):
        print(f"WARN: {log_path} not found")
        return rows
    with open(log_path, 'r', errors='replace') as f:
        for line in f:
            m = LINE_RE.match(line)
            if not m:
                continue
            ts_str, pair, direction, zone = m.groups()
            try:
                # Log timestamps are local (CEST = UTC+02).
                dt = datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S')
                ts = dt.timestamp()  # interpret as local; matches DB unix ts
            except Exception:
                continue
            rows.append({
                'timestamp': ts, 'pair': pair, 'direction': direction, 'zone': zone,
            })
    return rows


def main():
    log_rows = parse_log(LOG)
    print(f"Parsed {len(log_rows)} zone-tagged signal lines from {LOG}")
    if not log_rows:
        sys.exit(0)

    # Sort log rows by timestamp for fast lookup.
    log_rows.sort(key=lambda r: r['timestamp'])
    log_min = log_rows[0]['timestamp']
    log_max = log_rows[-1]['timestamp']
    print(f"Log window: {datetime.fromtimestamp(log_min)} → {datetime.fromtimestamp(log_max)}")

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    # Pull candidate signals within the log window (+/- 1h).
    cur.execute(
        'SELECT signal_id, pair, signal, timestamp FROM signals '
        'WHERE timestamp BETWEEN ? AND ? AND zone_used IS NULL '
        'ORDER BY timestamp',
        (log_min - 3600, log_max + 3600),
    )
    db_rows = cur.fetchall()
    print(f"DB candidates with NULL zone in log window: {len(db_rows)}")

    # Index log rows by (pair, direction) → list of (timestamp, zone), sorted.
    by_key: dict = {}
    for r in log_rows:
        by_key.setdefault((r['pair'], r['direction']), []).append((r['timestamp'], r['zone']))
    for k in by_key:
        by_key[k].sort(key=lambda x: x[0])

    matched = 0
    skipped = 0
    updates = []
    TOLERANCE = 300  # seconds

    for s in db_rows:
        key = (s['pair'], s['signal'])
        candidates = by_key.get(key) or []
        if not candidates:
            skipped += 1
            continue
        # Closest by absolute timestamp delta.
        best_ts, best_zone = min(candidates, key=lambda c: abs(c[0] - s['timestamp']))
        if abs(best_ts - s['timestamp']) > TOLERANCE:
            skipped += 1
            continue
        tier = 'production' if best_zone in PRODUCTION_ZONES else 'experimental'
        updates.append((best_zone, tier, s['signal_id']))
        matched += 1

    print(f"Matched: {matched}    Skipped (no log match within {TOLERANCE}s): {skipped}")

    if updates:
        cur.executemany(
            'UPDATE signals SET zone_used = ?, signal_tier = ? WHERE signal_id = ?',
            updates,
        )
        con.commit()
        print(f"Updated {cur.rowcount} signals.")

    # Summary
    cur.execute("SELECT signal_tier, COUNT(*) FROM signals GROUP BY signal_tier")
    print("Final tier distribution:")
    for row in cur.fetchall():
        print(f"  {row[0]}: {row[1]}")
    cur.execute(
        "SELECT zone_used, COUNT(*) FROM signals "
        "WHERE signal_tier='experimental' GROUP BY zone_used ORDER BY 2 DESC"
    )
    print("Experimental zones:")
    for row in cur.fetchall():
        print(f"  {row[0]}: {row[1]}")

    con.close()


if __name__ == '__main__':
    main()
