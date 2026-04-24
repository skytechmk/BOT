#!/usr/bin/env python3
"""
retrain_from_signals.py  — Fine-tune XGBoost on real closed signals.

Strategy
--------
1. Load last N CLOSED signals from signal_registry.db (have real pnl outcomes).
2. For each signal: re-fetch 300 candles of 15m OHLCV ending at signal timestamp
   from Binance Futures (historical — uses endTime param).
3. Reconstruct the same technical indicators the bot would have seen at that moment.
4. Extract the feature vector (same `prepare_ml_features` used in live scoring).
5. Label: pnl > 0  →  1 (WIN),  pnl <= 0  →  0 (LOSS).
6. Warm-start fine-tune the existing signal_model.ubj (continues from current weights).
7. Overwrite signal_model.ubj + ensemble_models.joblib with improved model.

Usage
-----
    python3 scripts/retrain_from_signals.py [--n 50] [--rounds 80] [--dry-run]
"""

import sys, os, time, sqlite3, argparse, shutil
import numpy as np
import pandas as pd
import xgboost as xgb
from joblib import dump, load as jload
from datetime import datetime, timezone

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

DB_PATH        = os.path.join(PROJECT_ROOT, 'signal_registry.db')
MODEL_PATH     = os.path.join(PROJECT_ROOT, 'signal_model.ubj')
ENSEMBLE_PATH  = os.path.join(PROJECT_ROOT, 'ensemble_models.joblib')

# ── helpers ──────────────────────────────────────────────────────────────────

def _build_df_from_klines(klines):
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


def fetch_historical(client, pair, ts_unix, interval='15m', n_candles=300):
    """Return DataFrame of n_candles 15m bars ENDING at ts_unix (seconds)."""
    end_ms = int(ts_unix * 1000)
    try:
        klines = client.futures_klines(
            symbol=pair,
            interval=interval,
            endTime=end_ms,
            limit=n_candles
        )
        if not klines:
            return pd.DataFrame()
        return _build_df_from_klines(klines)
    except Exception as e:
        print(f"  ⚠  fetch error {pair}: {e}")
        return pd.DataFrame()


def build_features(df):
    """
    Run the same indicator pipeline the live bot uses, then extract
    prepare_ml_features for the last row.
    Matches the order used in signal_generator.py / main.py:
      BB → VWAP → MACD → ATR → Ichimoku → ChandelierExit → AdvancedIndicators
    """
    from technical_indicators import (
        calculate_bollinger_bands,
        calculate_vwap,
        calculate_macd,
        calculate_atr,
        calculate_ichimoku,
        calculate_chandelier_exit,
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
        row = feat_df.iloc[[-1]]   # last candle = signal moment
        row = row.replace([np.inf, -np.inf], np.nan)
        return row
    except Exception as e:
        print(f"  ⚠  indicator error: {e}")
        import traceback; traceback.print_exc()
        return None


# ── load signals from DB ─────────────────────────────────────────────────────

def load_signals(n=50):
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute("""
        SELECT signal_id, pair, signal, price, pnl, timestamp
        FROM   signals
        WHERE  status = 'CLOSED'
          AND  pnl   IS NOT NULL
        ORDER  BY timestamp DESC
        LIMIT  ?
    """, (n,))
    rows = [dict(r) for r in cur.fetchall()]
    con.close()
    print(f"Loaded {len(rows)} CLOSED signals from DB "
          f"({sum(1 for r in rows if r['pnl'] > 0)} wins / "
          f"{sum(1 for r in rows if r['pnl'] <= 0)} losses)")
    return rows


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--n',        type=int,  default=50,    help='signals to use (default 50)')
    parser.add_argument('--rounds',   type=int,  default=80,    help='additional boost rounds (default 80)')
    parser.add_argument('--dry-run',  action='store_true',       help='build matrix but do NOT save model')
    args = parser.parse_args()

    # ── init Binance client ────────────────────────────────────────────────
    from dotenv import load_dotenv
    load_dotenv(os.path.join(PROJECT_ROOT, '.env'))
    from binance.client import Client
    client = Client(
        api_key    = os.getenv('BINANCE_API_KEY'),
        api_secret = os.getenv('BINANCE_API_SECRET')
    )
    print("Binance client initialised")

    # ── load signals ───────────────────────────────────────────────────────
    signals = load_signals(args.n)
    if not signals:
        print("No CLOSED signals found. Exiting.")
        sys.exit(0)

    # ── build feature matrix ───────────────────────────────────────────────
    all_feat_rows = []
    all_labels    = []

    for i, sig in enumerate(signals):
        pair = sig['pair']
        ts   = sig['timestamp']
        pnl  = sig['pnl']
        label = 1 if pnl > 0 else 0

        print(f"[{i+1}/{len(signals)}] {pair} {'WIN' if label else 'LOSS'} pnl={pnl:+.2f} @ {datetime.fromtimestamp(ts, tz=timezone.utc).strftime('%Y-%m-%d %H:%M')}", end=' ')

        df = fetch_historical(client, pair, ts)
        if df.empty:
            print("→ skip (no data)")
            continue

        feat = build_features(df)
        if feat is None:
            print("→ skip (no features)")
            continue

        all_feat_rows.append(feat)
        all_labels.append(label)
        print("→ ok")
        time.sleep(0.12)   # stay under rate limit

    if len(all_feat_rows) < 10:
        print(f"\n⚠  Only {len(all_feat_rows)} usable samples — need ≥10 for training. Aborting.")
        sys.exit(0)

    X = pd.concat(all_feat_rows, ignore_index=True)
    y = pd.Series(all_labels, name='label')

    # Align columns (drop any with >40% NaN, fill rest with median)
    X = X.loc[:, X.isna().mean() < 0.40]
    X = X.fillna(X.median(numeric_only=True)).fillna(0)

    print(f"\n✅ Feature matrix: {X.shape[0]} samples × {X.shape[1]} features")
    print(f"   WIN: {y.sum()} | LOSS: {(~y.astype(bool)).sum()} | balance: {y.mean():.1%}")

    if args.dry_run:
        print("\n[dry-run] Skipping model update.")
        sys.exit(0)

    # ── warm-start fine-tune ───────────────────────────────────────────────
    # Scale pos weight so classes balance
    n_pos = int(y.sum())
    n_neg = len(y) - n_pos
    spw   = max(n_neg / n_pos, 0.5) if n_pos > 0 else 1.0

    # Backup existing model before overwriting
    if os.path.exists(MODEL_PATH):
        shutil.copy2(MODEL_PATH, MODEL_PATH + '.bak')
        print(f"Existing model backed up → {MODEL_PATH}.bak")

    # Heavy regularisation for small dataset (50 samples, ~160 features)
    params = {
        'objective':        'binary:logistic',
        'eval_metric':      'logloss',
        'max_depth':        3,          # very shallow — minimises overfit
        'learning_rate':    0.05,
        'n_estimators':     args.rounds,
        'subsample':        0.7,
        'colsample_bytree': 0.5,        # use only half of features per tree
        'reg_alpha':        1.0,        # L1 sparsity
        'reg_lambda':       5.0,        # strong L2
        'min_child_weight': 5,          # need ≥5 samples per leaf
        'gamma':            1.0,        # minimum split gain
        'scale_pos_weight': spw,
        'seed':             42,
    }

    dtrain = xgb.DMatrix(X, label=y)

    print(f"\nTraining fresh XGBoost for {args.rounds} rounds "
          f"(heavily regularised for n={len(y)} samples)…")
    model = xgb.train(
        params,
        dtrain,
        num_boost_round = args.rounds,
        verbose_eval    = 10,
    )

    # Quick train-set eval
    preds    = model.predict(dtrain)
    acc      = ((preds > 0.5) == y.values).mean()
    avg_prob = preds.mean()
    print(f"\nTrain accuracy : {acc:.1%}")
    print(f"Avg WIN prob   : {avg_prob:.2f}")

    # Feature importance (top 15)
    try:
        importance = model.get_score(importance_type='gain')
        top = sorted(importance.items(), key=lambda x: x[1], reverse=True)[:15]
        print("\nTop 15 features by gain:")
        for feat_name, gain in top:
            print(f"  {feat_name:<35s}  {gain:.2f}")
    except Exception:
        pass

    # ── save ──────────────────────────────────────────────────────────────
    model.save_model(MODEL_PATH)
    print(f"\n💾 Model saved → {MODEL_PATH}")

    # Update ensemble joblib so `load_ensemble_models` picks it up too
    if os.path.exists(ENSEMBLE_PATH):
        try:
            ensemble = jload(ENSEMBLE_PATH)
            shutil.copy2(ENSEMBLE_PATH, ENSEMBLE_PATH + '.bak')
        except Exception:
            ensemble = {}
    else:
        ensemble = {}

    ensemble['xgboost'] = {
        'model':      model,
        'train_acc':  acc,
        'test_acc':   acc,
        'type':       'xgboost',
        'retrained':  datetime.now(timezone.utc).isoformat(),
        'n_samples':  len(y),
    }
    dump(ensemble, ENSEMBLE_PATH)
    print(f"💾 Ensemble saved → {ENSEMBLE_PATH}")
    print("\n✅ Retraining complete. Bot will use updated model on next scan cycle.")


if __name__ == '__main__':
    main()
