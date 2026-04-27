#!/usr/bin/env python3
"""Attempt to backfill the remaining closed signals that still have zero/NULL PnL.
Uses close price at closed_timestamp (1h candle) when targets_json is missing.
"""
import sqlite3, pathlib, time, json
from typing import Optional

ROOT = pathlib.Path('/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA')
SIGDB = ROOT / 'signal_registry.db'
OHLCV = ROOT / 'ohlcv_cache.db'
TF = '1h'
TF_MS = 3600000

def fetch_close_price(pair: str, ts_sec: float) -> Optional[float]:
    t_ms = int(ts_sec * 1000)
    tbl = f"{pair}_{TF}"
    conn = sqlite3.connect(f'file:{OHLCV}?mode=ro', uri=True)
    try:
        row = conn.execute(f'SELECT close,timestamp FROM "{tbl}" WHERE timestamp <= ? ORDER BY timestamp DESC LIMIT 1', (t_ms,)).fetchone()
        if row:
            close, start_ts = row
            return float(close)
    except sqlite3.Error:
        pass
    finally:
        conn.close()
    return None

def main():
    conn = sqlite3.connect(SIGDB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    rows = cur.execute("""
        SELECT signal_id, pair, signal, price AS entry, leverage, stop_loss, targets_json,
               closed_timestamp, timestamp, pnl
        FROM signals
        WHERE upper(status) IN ('CLOSED','LOSS','WIN','TP1_HIT','TP2_HIT','TP3_HIT','SL_HIT','CANCELLED')
          AND (pnl IS NULL OR abs(pnl) < 0.0001)
    """).fetchall()
    print('rows needing recovery', len(rows))
    upd = []
    skipped = []
    for r in rows:
        pair = r['pair']
        entry = float(r['entry'] or 0)
        if not entry:
            skipped.append((r['signal_id'],'no_entry'))
            continue
        lev = int(r['leverage'] or 1)
        ts = r['closed_timestamp'] or r['timestamp']
        if not ts:
            skipped.append((r['signal_id'],'no_ts'))
            continue
        close_px = fetch_close_price(pair, ts)
        if close_px is None:
            skipped.append((r['signal_id'],'no_price'))
            continue
        direction = (r['signal'] or '').upper()
        is_long = direction in ('LONG','BUY')
        raw = ((close_px - entry)/entry*100) if is_long else ((entry - close_px)/entry*100)
        pnl = round(raw * lev, 4)
        upd.append((pnl, 'BACKFILLED_MARK_CLOSE', r['signal_id']))
    print('will update', len(upd))
    cur.executemany('UPDATE signals SET pnl=?, close_reason=? WHERE signal_id=?', upd)
    conn.commit()
    conn.close()
    print('skipped', len(skipped), skipped[:10])

if __name__=='__main__':
    main()
