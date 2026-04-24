"""
One-time fix: retroactively place TP orders for open copy trades from today
that had TP placement fail due to -4120 (algo endpoint) or -1111 (precision) errors.

Run: python3 fix_missing_tps.py
"""
import os, sys, json, math, time, sqlite3
from pathlib import Path

sys.path.insert(0, '/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA')
from dotenv import load_dotenv
load_dotenv('/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/.env')

from dashboard.copy_trading import (
    _get_decrypted_keys, _get_exchange_info_cached, _get_futures_client
)

DB = Path('/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/dashboard/users.db')

def place_tps_for_user(user_id, conn):
    client = _get_futures_client(user_id)
    if not client:
        print(f"  ❌ Could not create client for user {user_id}")
        return

    # Get hedge mode
    try:
        pos_mode = client.futures_get_position_mode()
        hedge_mode = pos_mode.get('dualSidePosition', False)
    except Exception:
        hedge_mode = False

    # Get all open trades for this user from today
    rows = conn.execute("""
        SELECT id, pair, direction, quantity, leverage, entry_price, sl_price, tp_prices
        FROM copy_trades
        WHERE user_id=? AND status='open'
        AND created_at > strftime('%s', '2026-04-17 17:55:00')
        ORDER BY created_at
    """, (user_id,)).fetchall()

    print(f"\nUser {user_id}: {len(rows)} open trades to fix")

    # Get exchange info for precision
    exinfo = _get_exchange_info_cached(client)

    for row in rows:
        pair      = row['pair']
        direction = row['direction'].upper()
        quantity  = float(row['quantity'])
        entry     = float(row['entry_price'] or 0)
        tps       = json.loads(row['tp_prices']) if row['tp_prices'] else []

        if not tps:
            print(f"  ⚠️  {pair}: no TP prices stored — skipping")
            continue

        # Get step_size and price_precision for this pair
        sym_info = next((s for s in exinfo['symbols'] if s['symbol'] == pair), None)
        if not sym_info:
            print(f"  ⚠️  {pair}: symbol not in exchange info — skipping")
            continue

        step_size      = 0.001
        qty_precision  = 3
        price_precision = 2
        for f in sym_info.get('filters', []):
            if f['filterType'] == 'LOT_SIZE':
                step_str = f['stepSize']
                step_size = float(step_str)
                qty_precision = max(0, len(step_str.rstrip('0').split('.')[-1]))
            if f['filterType'] == 'PRICE_FILTER':
                tick = f['tickSize']
                price_precision = max(0, len(tick.rstrip('0').split('.')[-1]))

        sl_side = 'SELL' if direction == 'LONG' else 'BUY'
        position_side = direction if hedge_mode else 'BOTH'

        # Check if TPs are valid (above entry for LONG, below for SHORT)
        valid_tps = []
        for tp in tps:
            tp = float(tp)
            if direction == 'LONG' and tp > entry:
                valid_tps.append(tp)
            elif direction == 'SHORT' and tp < entry:
                valid_tps.append(tp)

        if not valid_tps:
            print(f"  🚫 {pair}: ALL TPs ({[f'{t:.5g}' for t in tps]}) are {'below' if direction=='LONG' else 'above'} entry ({entry:.5g}) — INVERTED SIGNAL. Skipping TP placement.")
            continue

        print(f"  📌 {pair} {direction} | entry={entry:.5g} | qty={quantity} | valid_tps={[f'{t:.5g}' for t in valid_tps]}")

        # Pyramid allocation: 50/30/20
        n = len(valid_tps)
        if n == 1:   allocs = [1.0]
        elif n == 2: allocs = [0.60, 0.40]
        else:        allocs = [0.50, 0.30, 0.20]
        total_alloc = sum(allocs[:n])
        allocs = [a / total_alloc for a in allocs[:n]]

        placed_qty = 0.0
        for i, (tp, alloc) in enumerate(zip(valid_tps, allocs)):
            tp_price = round(tp, price_precision)
            is_last = (i == len(valid_tps) - 1)
            raw_close = (quantity - placed_qty) if is_last else (quantity * alloc)
            if step_size > 0:
                close_qty = math.floor(raw_close / step_size) * step_size
                close_qty = round(close_qty, qty_precision)
            else:
                close_qty = round(raw_close, qty_precision)

            if close_qty <= 0:
                continue

            tp_params = dict(
                symbol=pair,
                side=sl_side,
                type='TAKE_PROFIT_MARKET',
                stopPrice=tp_price,
                quantity=close_qty,
                workingType='MARK_PRICE',
            )
            if hedge_mode:
                tp_params['positionSide'] = position_side
            else:
                tp_params['reduceOnly'] = True

            try:
                client.futures_create_order(**tp_params)
                placed_qty += close_qty
                print(f"    ✅ TP{i+1} placed @ {tp_price} qty={close_qty}")
            except Exception as e:
                err = str(e)
                print(f"    ❌ TP{i+1} FAILED @ {tp_price} qty={close_qty} | {err}")
                # Try algo endpoint as fallback
                if '-4120' in err or 'algo' in err.lower():
                    print(f"    ↩️  Attempting algo endpoint fallback for TP{i+1}...")
                    try:
                        algo_p = {
                            'symbol': pair, 'side': sl_side,
                            'algoType': 'CONDITIONAL', 'type': 'TAKE_PROFIT_MARKET',
                            'triggerPrice': str(tp_price),
                            'workingType': 'MARK_PRICE',
                            'quantity': str(close_qty),
                        }
                        if hedge_mode:
                            algo_p['positionSide'] = position_side
                        client._request_futures_api('post', 'algoOrder', True, data=algo_p)
                        placed_qty += close_qty
                        print(f"    ✅ TP{i+1} placed via algo endpoint @ {tp_price}")
                    except Exception as e2:
                        print(f"    ❌ Algo also failed: {e2}")

            time.sleep(0.2)  # rate limit


def main():
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row

    # Get all unique active users with open trades from today
    users = conn.execute("""
        SELECT DISTINCT ct.user_id
        FROM copy_trades ct
        JOIN copy_trading_config ctc ON ct.user_id = ctc.user_id
        WHERE ct.status = 'open'
        AND ct.created_at > strftime('%s', '2026-04-17 17:55:00')
        AND ctc.is_active = 1
    """).fetchall()

    print(f"Found {len(users)} user(s) with open trades to fix")
    for u in users:
        place_tps_for_user(u['user_id'], conn)

    conn.close()
    print("\n✅ Done")


if __name__ == '__main__':
    main()
