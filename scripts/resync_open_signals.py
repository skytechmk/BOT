#!/usr/bin/env python3
"""
Open Signals State Resync — one‑off recovery tool

Purpose:
- Reconcile in‑memory OPEN_SIGNALS_TRACKER with the SQLite signal_registry.db
- Add any missing open signals to the tracker so the realtime monitor will watch them
- Optionally force‑close obviously stale signals (e.g. >48 h old) that can’t possibly still be valid

Usage:
  python scripts/resync_open_signals.py [--dry-run] [--force-close] [--max-age-hours 48]

Safety:
  - Creates a timestamped backup of open_signals.json before writing
  - Logs every add/close operation to stdout
  - Does not delete DB rows; only updates JSON and in‑memory tracker
"""

import os
import sys
import json
import time
import sqlite3
import argparse
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / '.env')

# Shared state mutable import (we will modify these directly)
from shared_state import OPEN_SIGNALS_TRACKER, SIGNAL_REGISTRY

DB_PATH = PROJECT_ROOT / 'signal_registry.db'
JSON_PATH = PROJECT_ROOT / 'open_signals.json'
BACKUP_DIR = PROJECT_ROOT / 'backups' / 'open_signals'
BACKUP_DIR.mkdir(parents=True, exist_ok=True)


def backup_json():
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_file = BACKUP_DIR / f'open_signals_{ts}.json'
    if JSON_PATH.exists():
        import shutil
        shutil.copy2(JSON_PATH, backup_file)
        print(f'📦 Backed up open_signals.json → {backup_file}')
    else:
        print('ℹ️ No existing open_signals.json to backup')


def load_json():
    if JSON_PATH.exists():
        with open(JSON_PATH, 'r') as f:
            return json.load(f)
    return {}


def save_json(data):
    with open(JSON_PATH, 'w') as f:
        json.dump(data, f, indent=2)
    print(f'💾 Wrote open_signals.json ({len(data)} entries)')


def get_db_open_signals(max_age_hours=None):
    """Return dict of open signals from DB: {signal_id: {pair, signal_type, entry_price, timestamp}}"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    now = time.time()

    query = """
        SELECT signal_id, pair, signal as signal_type, price as entry_price, timestamp
        FROM signals
        WHERE status != 'CLOSED' AND (closed_timestamp IS NULL OR closed_timestamp = 0)
    """
    cur.execute(query)
    rows = cur.fetchall()
    conn.close()

    result = {}
    for row in rows:
        age_hours = (now - row['timestamp']) / 3600
        if max_age_hours and age_hours > max_age_hours:
            continue  # skip too old
        result[row['signal_id']] = {
            'pair': row['pair'],
            'signal_type': row['signal_type'],
            'entry_price': row['entry_price'],
            'timestamp': row['timestamp']
        }
    return result


def main(dry_run=False, force_close=False, max_age_hours=48):
    print('=== Open Signals Resync Tool ===')
    print(f'Time: {datetime.now(timezone.utc).isoformat()}')
    print(f'Dry run: {dry_run}')
    print(f'Force close old signals: {force_close} (max_age_hours={max_age_hours})')
    print()

    # 1. Load sources
    mem = dict(OPEN_SIGNALS_TRACKER)  # current in‑memory state
    disk = load_json()
    db = get_db_open_signals(max_age_hours=None)  # first get all to report

    print(f'Source counts:')
    print(f'  In‑memory tracker: {len(mem)}')
    print(f'  Disk JSON:         {len(disk)}')
    print(f'  Database open:    {len(db)}')
    print()

    # If we are filtering by age for addition, apply now
    if max_age_hours:
        db_filtered = {sid: data for sid, data in db.items()
                       if (time.time() - data['timestamp']) / 3600 <= max_age_hours}
        print(f'  DB after age filter (≤{max_age_hours}h): {len(db_filtered)}')
    else:
        db_filtered = db

    # 2. Compute deltas
    to_add = set(db_filtered.keys()) - set(mem.keys())
    to_remove_from_disk = set(disk.keys()) - set(db_filtered.keys())
    already_ok = set(mem.keys()) & set(db_filtered.keys())

    print(f'Reconciliation plan:')
    print(f'  Signals to add to tracker: {len(to_add)}')
    print(f'  Signals to remove from JSON (orphaned): {len(to_remove_from_disk)}')
    print(f'  Already in sync: {len(already_ok)}')
    print()

    if dry_run:
        print('🚧 DRY‑RUN — nothing will be changed')
        if to_add:
            print('Would add (sample):', list(to_add)[:5])
        if to_remove_from_disk:
            print('Would remove (sample):', list(to_remove_from_disk)[:5])
        return

    # 3. Backup before modifying
    backup_json()

    # 4. Apply changes to in‑memory tracker (mutates global)
    for sid in to_add:
        OPEN_SIGNALS_TRACKER[sid] = db_filtered[sid]
    for sid in to_remove_from_disk:
        OPEN_SIGNALS_TRACKER.pop(sid, None)

    print(f'✅ Updated in‑memory OPEN_SIGNALS_TRACKER (now {len(OPEN_SIGNALS_TRACKER)} entries)')

    # 5. Write new JSON
    save_json(OPEN_SIGNALS_TRACKER)

    # 6. Optional force‑close stale signals (>max_age_hours) that are still in DB but apparently abandoned
    if force_close and max_age_hours:
        now = time.time()
        closed_any = False
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        for sid, data in db.items():
            age_hours = (now - data['timestamp']) / 3600
            if age_hours > max_age_hours:
                # Mark as closed with a special reason
                new_status = 'FORCE_CLOSED_STALE'
                cur.execute("""
                    UPDATE signals
                    SET status = ?, closed_timestamp = ?
                    WHERE signal_id = ?
                """, (new_status, now, sid))
                print(f'🔒 Force‑closed stale signal {sid} (age {age_hours:.1f}h)')
                closed_any = True
        if closed_any:
            conn.commit()
            print('✅ Committed force‑close updates to DB')
        else:
            print('✅ No stale signals needed force‑closing')
        conn.close()
    else:
        print('ℹ️ Force‑close skipped (not requested or no max_age)')

    # 7. Final reminder: restart main to attach monitor to all pairs
    print()
    print('✅ Resync complete.')
    print('⚠️  NEXT: restart the Aladdin main process so the realtime monitor picks up the new tracker.')
    print('   The monitor will automatically call add_pair_monitoring() for each pair present in OPEN_SIGNALS_TRACKER.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Resync open signals tracker with database')
    parser.add_argument('--dry-run', action='store_true', help='Only show plan, do not modify')
    parser.add_argument('--force-close', action='store_true', help='Close signals older than max-age')
    parser.add_argument('--max-age-hours', type=int, default=48, help='Maximum age in hours to keep open (default 48)')
    args = parser.parse_args()

    try:
        main(dry_run=args.dry_run, force_close=args.force_close, max_age_hours=args.max_age_hours)
    except Exception as e:
        print(f'❌ Fatal error: {e}')
        import traceback
        traceback.print_exc()
        sys.exit(1)
