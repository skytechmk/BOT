#!/usr/bin/env python3
"""
Reconcile open_signals.json from signal_registry.json.

Active signals are those NOT in terminal states:
- CLOSED, STOP_LOSS_HIT, SL_HIT, CANCELLED, PARTIAL_CLOSE? (check logic)

This script reads signal_registry.json and writes/updates open_signals.json
with current active signals in the format expected by the bot.
"""

import json
import time
from pathlib import Path

BASE = Path('/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA')
REGISTRY_FILE = BASE / 'signal_registry.json'
OPEN_FILE = BASE / 'open_signals.json'

# Define terminal statuses (exact strings as they appear in signal_registry.json)
TERMINAL_STATUSES = {
    'CLOSED',
    'STOP_LOSS_HIT',
    'SL_HIT',
    'CANCELLED',
    'TP_HIT',  # if fully closed after all TPs
    'PARTIAL_CLOSE',  # unclear, but if closed then not open
}

def is_active(entry: dict) -> bool:
    """Return True if signal is still active (not terminal)."""
    status = entry.get('status', '').upper()
    if status in TERMINAL_STATUSES:
        return False
    # Also consider if close_reason exists? That indicates closed.
    if 'close_reason' in entry:
        return False
    return True

def main():
    if not REGISTRY_FILE.exists():
        print(f"❌ Registry not found: {REGISTRY_FILE}")
        return

    with open(REGISTRY_FILE, 'r') as f:
        registry = json.load(f)

    active = {}
    now = time.time()
    for sig_id, data in registry.items():
        if is_active(data):
            pair = data.get('pair')
            if not pair:
                continue
            # Build open-signals entry
            active[sig_id] = {
                'signal_id': sig_id,
                'pair': pair,
                'signal_type': data.get('signal') or data.get('direction') or 'LONG',  # fallback
                'entry_price': float(data.get('price', data.get('entry_price', 0))),
                'timestamp': float(data.get('timestamp', now)),
                'status': 'OPEN',
                'last_updated': float(data.get('last_updated', data.get('timestamp', now)))
            }

    # Write open_signals.json
    with open(OPEN_FILE, 'w') as f:
        json.dump(active, f, indent=2)

    print(f"✅ Reconcile complete: {len(active)} active signals written to {OPEN_FILE}")

if __name__ == '__main__':
    main()
