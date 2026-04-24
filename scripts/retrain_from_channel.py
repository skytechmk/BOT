#!/usr/bin/env python3
"""
retrain_from_channel.py  — Read the last N signals from the Telegram
signals channel, verify outcomes via Binance historical data (did TP1
or SL hit first?), then fine-tune the XGBoost model.

Why this approach?
  - Cornix never executed our signals (all "not parsed properly" errors).
  - Instead, we verify outcomes by re-playing 1m candle data starting
    from the signal timestamp: first touch of SL = LOSS, first touch
    of TP1 = WIN.

Usage
-----
    python3 scripts/retrain_from_channel.py [--n 50] [--rounds 80] [--dry-run]
"""

import sys, os, re, time, shutil, asyncio, argparse
import numpy as np
import pandas as pd
import xgboost as xgb
from joblib import dump, load as jload
from datetime import datetime, timezone

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

MODEL_PATH    = os.path.join(PROJECT_ROOT, 'signal_model.ubj')
ENSEMBLE_PATH = os.path.join(PROJECT_ROOT, 'ensemble_models.joblib')

API_ID   = 25939105
API_HASH = "378b5199b2a12d4e6406708701832e48"
SESSION  = os.path.join(PROJECT_ROOT, "spectre_user")
SIGNALS_CH = -1002209928687   # AnunnakiWorld


# ─── Telegram: fetch signal messages ────────────────────────────────────────

async def _fetch_signal_messages(limit_scan=500, n_signals=50):
    """
    Scan up to `limit_scan` recent messages in the signals channel,
    return the first `n_signals` that look like our bot's signal format.
    """
    from telethon import TelegramClient

    client = TelegramClient(SESSION, API_ID, API_HASH)
    await client.start()

    signals = []
    async for msg in client.iter_messages(SIGNALS_CH, limit=limit_scan):
        if not msg.text:
            continue
        parsed = _parse_signal_message(msg.text, msg.date)
        if parsed:
            signals.append(parsed)
            if len(signals) >= n_signals:
                break

    await client.disconnect()
    return signals


def _parse_signal_message(text, date):
    """
    Parse our bot's Telegram signal format (both old and new style).
    Returns dict or None.
    """
    # Must be a NEW signal (not a portfolio update / other message)
    if 'NEW LONG' not in text and 'NEW SHORT' not in text:
        return None

    direction = 'LONG' if 'NEW LONG' in text else 'SHORT'

    # Pair — two formats:
    #   new: 💰 **#SPELL/USDT**   or  💰 **#SPELL/USDT**
    #   old: 💰 **Pair: SPELLUSDT**
    pair_match = (
        re.search(r'#(\w+)/USDT', text) or
        re.search(r'Pair:\s*(\w+USDT)', text)
    )
    if not pair_match:
        return None

    raw_pair = pair_match.group(1)
    # Normalise: SPELL/USDT → SPELLUSDT
    pair = raw_pair.replace('/', '')
    if not pair.endswith('USDT'):
        pair = pair + 'USDT'

    # Entry price — `0.00012345` or `0.00012345` - `0.00012400` (range)
    entry_match = re.search(r'Entry[^\n]*`([\d.]+)`', text)
    buy_match   = re.search(r'Buy[^\n]*`([\d.]+)`\s*-\s*`([\d.]+)`', text)

    if buy_match:
        entry = (float(buy_match.group(1)) + float(buy_match.group(2))) / 2
    elif entry_match:
        entry = float(entry_match.group(1))
    else:
        return None

    # TP1
    tp1_match = re.search(r'TP1[^\n]*`([\d.]+)`', text)
    if not tp1_match:
        return None
    tp1 = float(tp1_match.group(1))

    # SL
    sl_match = re.search(r'SL[^\n]*`([\d.]+)`', text)
    if not sl_match:
        return None
    sl = float(sl_match.group(1))

    # Sanity: entry must be between SL and TP1 (approximately)
    if direction == 'LONG':
        if not (sl < entry and tp1 > entry * 0.998):
            return None
    else:
        if not (sl > entry and tp1 < entry * 1.002):
            return None

    return {
        'pair':      pair,
        'direction': direction,
        'entry':     entry,
        'tp1':       tp1,
        'sl':        sl,
        'timestamp': date.replace(tzinfo=timezone.utc).timestamp() if date.tzinfo is None else date.timestamp(),
        'date_str':  str(date)[:19],
    }


# ─── Binance: verify outcome ─────────────────────────────────────────────────

def check_outcome(client, sig, window_hours=72):
    """
    Fetch 1-minute candles starting from signal time.
    Return 1 (WIN) if TP1 hit first, 0 (LOSS) if SL hit first, None if undecided.
    """
    start_ms = int(sig['timestamp'] * 1000)
    end_ms   = start_ms + window_hours * 3_600_000

    tp1       = sig['tp1']
    sl        = sig['sl']
    direction = sig['direction']
    pair      = sig['pair']

    try:
        klines = client.futures_klines(
            symbol    = pair,
            interval  = '1m',
            startTime = start_ms,
            endTime   = end_ms,
            limit     = 1000,
        )
        if not klines:
            return None

        for k in klines:
            high = float(k[2])
            low  = float(k[3])

            if direction == 'LONG':
                if low  <= sl:  return 0   # SL hit
                if high >= tp1: return 1   # TP1 hit
            else:  # SHORT
                if high >= sl:  return 0   # SL hit
                if low  <= tp1: return 1   # TP1 hit

        return None   # Neither hit within window
    except Exception as e:
        print(f"  ⚠  outcome check error for {pair}: {e}")
        return None


# ─── features from historical OHLCV ─────────────────────────────────────────

def fetch_historical(client, pair, ts_unix, interval='15m', n_candles=300):
    end_ms = int(ts_unix * 1000)
    try:
        klines = client.futures_klines(
            symbol   = pair,
            interval = interval,
            endTime  = end_ms,
            limit    = n_candles,
        )
        if not klines:
            return pd.DataFrame()
        df = pd.DataFrame(klines, columns=[
            'timestamp','open','high','low','close','volume','close_time',
            'quote_asset_volume','number_of_trades',
            'taker_buy_base_asset_volume','taker_buy_quote_asset_volume','ignore'
        ])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        for c in ['open','high','low','close','volume']:
            df[c] = df[c].astype(float)
        return df
    except Exception as e:
        print(f"  ⚠  fetch error {pair}: {e}")
        return pd.DataFrame()


def build_features(df):
    from technical_indicators import (
        calculate_bollinger_bands, calculate_vwap, calculate_macd,
        calculate_atr, calculate_ichimoku, calculate_chandelier_exit,
        calculate_advanced_indicators,
    )
    from ml_engine_archive.feature_engine import build_features as prepare_ml_features

    if df.empty or len(df) < 50:
        return None
    try:
        df = calculate_bollinger_bands(df)
        df = calculate_vwap(df)
        df = calculate_macd(df)
        df = calculate_atr(df)
        df = calculate_ichimoku(df)
        df = calculate_chandelier_exit(df)
        df = calculate_advanced_indicators(df)
        feat_df = prepare_ml_features(df)
        if feat_df.empty:
            return None
        row = feat_df.iloc[[-1]].replace([np.inf, -np.inf], np.nan)
        return row
    except Exception as e:
        print(f"  ⚠  indicator error: {e}")
        return None


# ─── main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--n',       type=int, default=50,  help='signal messages to read (default 50)')
    parser.add_argument('--rounds',  type=int, default=80,  help='XGBoost boost rounds (default 80)')
    parser.add_argument('--dry-run', action='store_true',   help='do not save model')
    args = parser.parse_args()

    # ── Binance client ────────────────────────────────────────────────
    from dotenv import load_dotenv
    load_dotenv(os.path.join(PROJECT_ROOT, '.env'))
    from binance.client import Client
    binance = Client(
        api_key    = os.getenv('BINANCE_API_KEY'),
        api_secret = os.getenv('BINANCE_API_SECRET'),
    )
    print("Binance client ready")

    # ── Fetch signals from Telegram ───────────────────────────────────
    print(f"\n📡 Reading last {args.n} signals from AnunnakiWorld channel…")
    signals = asyncio.run(_fetch_signal_messages(limit_scan=600, n_signals=args.n))
    print(f"   Parsed {len(signals)} signal messages")

    if not signals:
        print("No signals found. Exiting.")
        sys.exit(0)

    # ── Verify outcome (TP1 vs SL via 1m candles) ────────────────────
    print("\n🔍 Checking outcomes via Binance 1m history (72h window)…")
    labeled  = []
    skipped  = 0

    for i, sig in enumerate(signals):
        print(f"  [{i+1}/{len(signals)}] {sig['pair']:15s} {sig['direction']:5s}  "
              f"entry={sig['entry']:.8g}  tp1={sig['tp1']:.8g}  sl={sig['sl']:.8g} "
              f"@ {sig['date_str']}", end='  ')

        outcome = check_outcome(binance, sig)
        if outcome is None:
            print("⏳ undecided — skip")
            skipped += 1
            time.sleep(0.12)
            continue

        label_str = '✅ WIN' if outcome == 1 else '❌ LOSS'
        print(label_str)
        sig['label'] = outcome
        labeled.append(sig)
        time.sleep(0.12)

    print(f"\n  Labeled: {len(labeled)} ({sum(s['label'] for s in labeled)} WIN / "
          f"{sum(1-s['label'] for s in labeled)} LOSS)  |  Skipped: {skipped}")

    if len(labeled) < 10:
        print(f"⚠  Only {len(labeled)} labeled — need ≥10. Try --n 80 or wait for more signals to close.")
        sys.exit(0)

    # ── Build feature matrix ──────────────────────────────────────────
    print("\n⚙️  Reconstructing technical features at signal time…")
    feat_rows, labels = [], []

    for i, sig in enumerate(labeled):
        print(f"  [{i+1}/{len(labeled)}] {sig['pair']:15s}", end=' ')
        df  = fetch_historical(binance, sig['pair'], sig['timestamp'])
        row = build_features(df)
        if row is None:
            print("→ skip (no features)")
            continue
        feat_rows.append(row)
        labels.append(sig['label'])
        print("→ ok")
        time.sleep(0.12)

    if len(feat_rows) < 10:
        print(f"⚠  Only {len(feat_rows)} usable feature vectors — aborting.")
        sys.exit(0)

    X = pd.concat(feat_rows, ignore_index=True)
    y = pd.Series(labels, name='label')

    # Clean
    X = X.loc[:, X.isna().mean() < 0.40]
    X = X.fillna(X.median(numeric_only=True)).fillna(0)

    print(f"\n✅ Feature matrix: {X.shape[0]} × {X.shape[1]}  "
          f"WIN={y.sum()}  LOSS={(~y.astype(bool)).sum()}  "
          f"win_rate={y.mean():.1%}")

    if args.dry_run:
        print("[dry-run] Not saving model.")
        sys.exit(0)

    # ── Train XGBoost ─────────────────────────────────────────────────
    n_pos = int(y.sum())
    n_neg = len(y) - n_pos
    spw   = max(n_neg / n_pos, 0.5) if n_pos > 0 else 1.0

    if os.path.exists(MODEL_PATH):
        shutil.copy2(MODEL_PATH, MODEL_PATH + '.bak')
        print(f"Model backed up → {MODEL_PATH}.bak")

    params = {
        'objective':        'binary:logistic',
        'eval_metric':      'logloss',
        'max_depth':        3,
        'learning_rate':    0.05,
        'subsample':        0.7,
        'colsample_bytree': 0.5,
        'reg_alpha':        1.0,
        'reg_lambda':       5.0,
        'min_child_weight': 5,
        'gamma':            1.0,
        'scale_pos_weight': spw,
        'seed':             42,
    }

    dtrain = xgb.DMatrix(X, label=y)
    print(f"\nTraining XGBoost ({args.rounds} rounds, heavily regularised for n={len(y)})…")
    model = xgb.train(params, dtrain, num_boost_round=args.rounds, verbose_eval=10)

    preds = model.predict(dtrain)
    acc   = ((preds > 0.5) == y.values).mean()
    print(f"Train accuracy: {acc:.1%}  |  Avg WIN prob: {preds.mean():.2f}")

    # Feature importance
    try:
        importance = model.get_score(importance_type='gain')
        top = sorted(importance.items(), key=lambda x: x[1], reverse=True)[:15]
        print("\nTop 15 features (gain):")
        for name, gain in top:
            print(f"  {name:<35s}  {gain:.2f}")
    except Exception:
        pass

    # ── Save ─────────────────────────────────────────────────────────
    model.save_model(MODEL_PATH)
    print(f"\n💾 Model saved → {MODEL_PATH}")

    # Update ensemble
    ensemble = {}
    if os.path.exists(ENSEMBLE_PATH):
        try:
            ensemble = jload(ENSEMBLE_PATH)
            shutil.copy2(ENSEMBLE_PATH, ENSEMBLE_PATH + '.bak')
        except Exception:
            pass

    ensemble['xgboost'] = {
        'model':      model,
        'train_acc':  acc,
        'test_acc':   acc,
        'type':       'xgboost',
        'retrained':  datetime.now(timezone.utc).isoformat(),
        'n_samples':  len(y),
        'win_rate':   float(y.mean()),
        'source':     'channel_telegram',
    }
    dump(ensemble, ENSEMBLE_PATH)
    print(f"💾 Ensemble saved → {ENSEMBLE_PATH}")
    print(f"\n✅ Done. Bot uses updated model on next scan cycle.")

    # ── Summary report ───────────────────────────────────────────────
    print("\n" + "="*60)
    print(f"CHANNEL RETRAIN SUMMARY")
    print(f"  Signals read from Telegram : {len(signals)}")
    print(f"  Outcomes verified          : {len(labeled)}")
    print(f"  Feature vectors built      : {len(feat_rows)}")
    print(f"  WIN rate (real outcomes)   : {y.mean():.1%}")
    print(f"  Train accuracy             : {acc:.1%}")
    print("="*60)


if __name__ == '__main__':
    main()
