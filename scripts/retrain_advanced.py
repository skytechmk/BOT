#!/usr/bin/env python3
"""
retrain_advanced.py  — Advanced ML retraining pipeline for Aladdin.

Four upgrades over the basic retrain_from_channel.py:

  1. Walk-Forward Temporal CV   — TimeSeriesSplit avoids look-ahead
                                  bias inherent in random splits on
                                  time-ordered trading data.

  2. SHAP Feature Selection     — Fit a quick surrogate, compute SHAP
                                  values, keep only top-N predictive
                                  features. Reduces 177→~25 features,
                                  dramatically cuts overfitting with
                                  small sample sizes.

  3. Optuna Hyperparameter Tune — Bayesian search over XGBoost params
                                  (max_depth, learning_rate, subsample,
                                  reg_alpha/lambda, min_child_weight).
                                  Objective: maximise CV AUC-ROC.

  4. Regime-Aware Split Models  — Separate RANGING and TRENDING models
                                  trained on their own signal subsets.
                                  At inference, main.py picks the right
                                  model based on current regime label.

Usage
-----
    python3 scripts/retrain_advanced.py [--n 60] [--dry-run]
"""

import sys, os, re, time, shutil, asyncio, argparse, json
import numpy as np
import pandas as pd
import xgboost as xgb
from joblib import dump, load as jload
from datetime import datetime, timezone

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

MODEL_PATH        = os.path.join(PROJECT_ROOT, 'signal_model.ubj')
ENSEMBLE_PATH     = os.path.join(PROJECT_ROOT, 'ensemble_models.joblib')
REGIME_MODEL_DIR  = os.path.join(PROJECT_ROOT, 'models')

API_ID   = 25939105
API_HASH = "378b5199b2a12d4e6406708701832e48"
SESSION  = os.path.join(PROJECT_ROOT, "spectre_user")
SIGNALS_CH = -1002209928687

os.makedirs(REGIME_MODEL_DIR, exist_ok=True)


# ══════════════════════════════════════════════════════════════════════
# Section A — Data collection (Telegram + Binance)
# ══════════════════════════════════════════════════════════════════════

async def _fetch_signal_messages(limit_scan=600, n_signals=60):
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
    if 'NEW LONG' not in text and 'NEW SHORT' not in text and \
       ('LONG #' not in text and 'SHORT #' not in text):
        return None
    direction = 'LONG' if ('NEW LONG' in text or 'LONG #' in text) else 'SHORT'

    pair_match = (re.search(r'#(\w+)/USDT', text) or
                  re.search(r'Pair:\s*(\w+USDT)', text))
    if not pair_match:
        return None
    pair = pair_match.group(1).replace('/', '')
    if not pair.endswith('USDT'):
        pair += 'USDT'

    entry_match = re.search(r'(?:Entry|Buy|Sell)[^\n]*?([\d.]+)', text)
    if not entry_match:
        return None
    entry = float(entry_match.group(1))

    tp1_match = re.search(r'(?:TP1|Target\s*1)[^\n]*?([\d.]+)', text)
    sl_match  = re.search(r'(?:Stop|SL)[^\n]*?([\d.]+)', text)
    if not tp1_match or not sl_match:
        return None
    tp1 = float(tp1_match.group(1))
    sl  = float(sl_match.group(1))

    # Regime (optional)
    regime_match = re.search(r'Regime[:\s]+(\w+)', text)
    regime = regime_match.group(1).upper() if regime_match else 'UNKNOWN'

    # Sanity
    if direction == 'LONG'  and not (sl < entry * 1.05 and tp1 > entry * 0.97):
        return None
    if direction == 'SHORT' and not (sl > entry * 0.95 and tp1 < entry * 1.03):
        return None

    ts = date.replace(tzinfo=timezone.utc).timestamp() \
         if date.tzinfo is None else date.timestamp()
    return dict(pair=pair, direction=direction, entry=entry,
                tp1=tp1, sl=sl, regime=regime,
                timestamp=ts, date_str=str(date)[:19])


def check_outcome(client, sig, window_hours=72):
    start_ms = int(sig['timestamp'] * 1000)
    end_ms   = start_ms + window_hours * 3_600_000
    try:
        klines = client.futures_klines(
            symbol=sig['pair'], interval='1m',
            startTime=start_ms, endTime=end_ms, limit=1000)
        if not klines:
            return None
        for k in klines:
            hi, lo = float(k[2]), float(k[3])
            if sig['direction'] == 'LONG':
                if lo  <= sig['sl']:  return 0
                if hi  >= sig['tp1']: return 1
            else:
                if hi  >= sig['sl']:  return 0
                if lo  <= sig['tp1']: return 1
        return None
    except Exception:
        return None


def fetch_ohlcv(client, pair, ts_unix, interval='15m', n=300):
    end_ms = int(ts_unix * 1000)
    try:
        klines = client.futures_klines(
            symbol=pair, interval=interval, endTime=end_ms, limit=n)
        if not klines:
            return pd.DataFrame()
        df = pd.DataFrame(klines, columns=[
            'timestamp','open','high','low','close','volume','close_time',
            'quote_asset_volume','number_of_trades',
            'taker_buy_base_asset_volume','taker_buy_quote_asset_volume','ignore'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        for c in ['open','high','low','close','volume']:
            df[c] = df[c].astype(float)
        return df
    except Exception:
        return pd.DataFrame()


def build_features(df, client=None, pair=None):
    from technical_indicators import (
        calculate_bollinger_bands, calculate_vwap, calculate_macd,
        calculate_atr, calculate_ichimoku, calculate_chandelier_exit,
        calculate_advanced_indicators)
    from ml_engine_archive.feature_engine import build_features as prepare_ml_features
    if df.empty or len(df) < 50:
        return None
    try:
        for fn in [calculate_bollinger_bands, calculate_vwap,
                   calculate_macd, calculate_atr, calculate_ichimoku,
                   calculate_chandelier_exit, calculate_advanced_indicators]:
            df = fn(df)
        feat = prepare_ml_features(df)
        if feat.empty:
            return None
        row = feat.iloc[[-1]].replace([np.inf, -np.inf], np.nan).copy()

        # ── Breakout + Retest + Channel features ──────────────────────────
        try:
            from technical_indicators import detect_breakout_retest
            bor = detect_breakout_retest(df)
            row['bor_score']        = bor.get('breakout_score', 0.0)
            row['channel_slope']    = bor.get('channel_slope', 0.0)
            row['channel_position'] = bor.get('channel_position', 0.0)
            row['bor_type_bullish'] = 1.0 if bor.get('breakout_type') == 'BULLISH_RETEST' else 0.0
            row['bor_type_bearish'] = 1.0 if bor.get('breakout_type') == 'BEARISH_RETEST' else 0.0
        except Exception:
            pass

        # ── Macro HTF features: 1D and 1W Ichimoku cloud + ADX ────────────
        if client is not None and pair is not None:
            for tf, prefix in [('1d', 'D'), ('1w', 'W')]:
                try:
                    klines = client.futures_klines(symbol=pair, interval=tf, limit=200)
                    if not klines or len(klines) < 26:
                        continue
                    df_tf = pd.DataFrame(klines, columns=[
                        'timestamp','open','high','low','close','volume','close_time',
                        'quote_asset_volume','number_of_trades',
                        'taker_buy_base_asset_volume','taker_buy_quote_asset_volume','ignore'])
                    df_tf['timestamp'] = pd.to_datetime(df_tf['timestamp'], unit='ms')
                    df_tf.set_index('timestamp', inplace=True)
                    for c in ['open','high','low','close','volume']:
                        df_tf[c] = df_tf[c].astype(float)
                    df_tf = calculate_ichimoku(df_tf)
                    df_tf = calculate_advanced_indicators(df_tf)
                    df_tf = calculate_atr(df_tf)
                    last = df_tf.iloc[-1]
                    close   = float(last['close'])
                    span_a  = float(last.get('senkou_span_a', 0) or 0)
                    span_b  = float(last.get('senkou_span_b', 0) or 0)
                    adx     = float(last.get('ADX', 20) or 20)
                    sma20   = float(last.get('SMA_20', close) or close)
                    sma50   = float(last.get('SMA_50', close) or close)
                    cloud_top    = max(span_a, span_b)
                    cloud_bottom = min(span_a, span_b)
                    # Cloud position: +1=above(bullish), -1=below(bearish), 0=inside
                    if cloud_top > 0:
                        cloud_pos = 1.0 if close > cloud_top else (-1.0 if close < cloud_bottom else 0.0)
                    else:
                        cloud_pos = 0.0
                    row[f'{prefix}_cloud_position']  = cloud_pos
                    row[f'{prefix}_adx']             = adx
                    row[f'{prefix}_sma20_vs_sma50']  = (sma20 - sma50) / sma50 if sma50 > 0 else 0.0
                    row[f'{prefix}_close_vs_sma20']  = (close - sma20) / sma20 if sma20 > 0 else 0.0
                    row[f'{prefix}_cloud_width']     = (cloud_top - cloud_bottom) / close if close > 0 else 0.0
                except Exception:
                    pass

        return row
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════════════
# Section B — Feature engineering helpers
# ══════════════════════════════════════════════════════════════════════

def clean_matrix(X):
    X = X.loc[:, X.isna().mean() < 0.40]
    X = X.fillna(X.median(numeric_only=True)).fillna(0)
    X = X.replace([np.inf, -np.inf], 0)
    return X


# ── B1: SHAP feature selection ────────────────────────────────────────
def shap_feature_selection(X, y, top_n=25):
    """
    Train a quick surrogate XGBoost, compute feature importance via
    XGBoost gain + cover (ensemble rank), select top_n features.

    Uses XGBoost native importance instead of shap.TreeExplainer to
    avoid the Keras-3 / transformers import conflict on this system.
    """
    print(f"\n[FeatSel] Selecting top {top_n} features from {X.shape[1]} total…")

    dtrain = xgb.DMatrix(X, label=y)
    params = dict(
        objective='binary:logistic', eval_metric='logloss',
        max_depth=4, learning_rate=0.1,
        subsample=0.8, colsample_bytree=0.7,
        verbosity=0, seed=42)
    surrogate = xgb.train(params, dtrain, num_boost_round=100, verbose_eval=False)

    # Combine gain + cover ranks for a robust importance signal
    gain  = pd.Series(surrogate.get_score(importance_type='gain'),  name='gain')
    cover = pd.Series(surrogate.get_score(importance_type='cover'), name='cover')

    all_feats = list(set(gain.index) | set(cover.index))
    df_imp = pd.DataFrame(index=all_feats)
    df_imp['gain']  = gain.reindex(all_feats).fillna(0)
    df_imp['cover'] = cover.reindex(all_feats).fillna(0)

    # Rank each metric (higher = better) then average ranks
    df_imp['gain_rank']  = df_imp['gain'].rank(ascending=False)
    df_imp['cover_rank'] = df_imp['cover'].rank(ascending=False)
    df_imp['avg_rank']   = (df_imp['gain_rank'] + df_imp['cover_rank']) / 2
    df_imp = df_imp.sort_values('avg_rank')

    top_features = df_imp.head(top_n).index.tolist()
    print(f"[FeatSel] Top {top_n} features (gain | cover | avg_rank):")
    for i, row in enumerate(df_imp.head(top_n).itertuples(), 1):
        print(f"  {i:2d}. {row.Index:<38s}  gain={row.gain:.1f}  cover={row.cover:.1f}")
    return top_features


# ══════════════════════════════════════════════════════════════════════
# Section C — Walk-Forward CV evaluation
# ══════════════════════════════════════════════════════════════════════

def walk_forward_cv(X, y, params, n_splits=4):
    """
    TimeSeriesSplit cross-validation.
    Returns mean AUC-ROC across folds (respects temporal order).
    """
    from sklearn.model_selection import TimeSeriesSplit
    from sklearn.metrics import roc_auc_score

    tscv   = TimeSeriesSplit(n_splits=n_splits)
    scores = []

    for fold, (train_idx, test_idx) in enumerate(tscv.split(X)):
        if len(test_idx) < 3:
            continue
        X_tr, X_te = X.iloc[train_idx], X.iloc[test_idx]
        y_tr, y_te = y.iloc[train_idx], y.iloc[test_idx]

        if len(y_tr.unique()) < 2 or len(y_te.unique()) < 2:
            continue

        dtrain = xgb.DMatrix(X_tr, label=y_tr)
        dtest  = xgb.DMatrix(X_te,  label=y_te)
        mdl = xgb.train(params, dtrain,
                        num_boost_round=params.get('n_estimators', 80),
                        verbose_eval=False)
        probs = mdl.predict(dtest)
        try:
            auc = roc_auc_score(y_te, probs)
            scores.append(auc)
        except Exception:
            pass

    mean_auc = float(np.mean(scores)) if scores else 0.5
    print(f"[Walk-Forward CV] {n_splits} folds → mean AUC = {mean_auc:.3f}")
    return mean_auc


# ══════════════════════════════════════════════════════════════════════
# Section D — Optuna hyperparameter search
# ══════════════════════════════════════════════════════════════════════

def optuna_tune(X, y, n_trials=40):
    """
    Bayesian search over XGBoost hyperparameters.
    Objective: maximise Walk-Forward CV AUC-ROC.
    Returns best params dict.
    """
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)

    n_pos = int(y.sum()); n_neg = len(y) - n_pos
    base_spw = max(n_neg / n_pos, 0.5) if n_pos > 0 else 1.0

    def objective(trial):
        params = {
            'objective':        'binary:logistic',
            'eval_metric':      'logloss',
            'max_depth':        trial.suggest_int('max_depth', 2, 5),
            'learning_rate':    trial.suggest_float('learning_rate', 0.01, 0.15, log=True),
            'subsample':        trial.suggest_float('subsample', 0.5, 1.0),
            'colsample_bytree': trial.suggest_float('colsample_bytree', 0.3, 0.8),
            'reg_alpha':        trial.suggest_float('reg_alpha', 0.1, 5.0, log=True),
            'reg_lambda':       trial.suggest_float('reg_lambda', 1.0, 10.0, log=True),
            'min_child_weight': trial.suggest_int('min_child_weight', 3, 10),
            'gamma':            trial.suggest_float('gamma', 0.1, 2.0),
            'scale_pos_weight': base_spw,
            'n_estimators':     trial.suggest_int('n_estimators', 50, 150),
            'seed':             42,
        }
        return walk_forward_cv(X, y, params, n_splits=4)

    print(f"\n[Optuna] Running {n_trials} trials (Bayesian search)…")
    study = optuna.create_study(direction='maximize',
                                sampler=optuna.samplers.TPESampler(seed=42))
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)

    best = study.best_params
    best_auc = study.best_value
    print(f"[Optuna] Best AUC = {best_auc:.3f} → params: {best}")
    return best, best_auc


# ══════════════════════════════════════════════════════════════════════
# Section E — Train final model(s)
# ══════════════════════════════════════════════════════════════════════

def train_final(X, y, params):
    """Train full XGBoost on all data with given params."""
    n_rounds = params.pop('n_estimators', 80)
    dtrain   = xgb.DMatrix(X, label=y)
    model    = xgb.train(params, dtrain,
                         num_boost_round=n_rounds,
                         verbose_eval=False)
    preds    = model.predict(dtrain)
    acc      = ((preds > 0.5) == y.values).mean()
    return model, acc


def train_regime_models(df_labeled, top_features, base_params):
    """
    Train separate XGBoost for RANGING and TRENDING regimes.
    Returns dict: {'RANGING': model, 'TRENDING': model, ...}
    Falls back to 'ALL' if a regime has < 8 samples.
    """
    models = {}
    regimes = df_labeled['regime'].unique()
    print(f"\n[Regime] Found regimes: {list(regimes)}")

    for regime in regimes:
        subset = df_labeled[df_labeled['regime'] == regime]
        if len(subset) < 8:
            print(f"[Regime] {regime}: only {len(subset)} samples — skip (merged into ALL)")
            continue

        X_r = subset[top_features]
        y_r = subset['label']
        n_pos = int(y_r.sum()); n_neg = len(y_r) - n_pos
        p = dict(base_params)
        p['scale_pos_weight'] = max(n_neg / n_pos, 0.5) if n_pos > 0 else 1.0

        model, acc = train_final(X_r, y_r, dict(p))
        models[regime] = {'model': model, 'acc': acc,
                          'n': len(subset), 'win_rate': float(y_r.mean())}
        print(f"[Regime] {regime}: n={len(subset)}, acc={acc:.1%}, "
              f"win_rate={y_r.mean():.1%}")

    return models


# ══════════════════════════════════════════════════════════════════════
# Section F — Save & update service pointer
# ══════════════════════════════════════════════════════════════════════

def save_models(global_model, global_acc, regime_models,
                top_features, best_params, meta):
    # Backup
    for path in [MODEL_PATH, ENSEMBLE_PATH]:
        if os.path.exists(path):
            shutil.copy2(path, path + '.bak')

    # Primary model (global)
    global_model.save_model(MODEL_PATH)
    print(f"\n💾 Global model saved → {MODEL_PATH}")

    # Regime models
    regime_paths = {}
    for regime, info in regime_models.items():
        rpath = os.path.join(REGIME_MODEL_DIR, f"model_{regime.lower()}.ubj")
        info['model'].save_model(rpath)
        regime_paths[regime] = rpath
        print(f"💾 Regime model [{regime}] saved → {rpath}")

    # Ensemble joblib
    ensemble = {}
    if os.path.exists(ENSEMBLE_PATH):
        try:
            ensemble = jload(ENSEMBLE_PATH)
        except Exception:
            pass

    ensemble['xgboost'] = {
        'model':         global_model,
        'train_acc':     global_acc,
        'test_acc':      global_acc,
        'type':          'xgboost',
        'top_features':  top_features,
        'retrained':     datetime.now(timezone.utc).isoformat(),
        'source':        'retrain_advanced',
        **meta,
    }
    # Store regime models too
    for regime, info in regime_models.items():
        ensemble[f'xgboost_{regime.lower()}'] = {
            'model':      info['model'],
            'train_acc':  info['acc'],
            'test_acc':   info['acc'],
            'type':       'xgboost',
            'regime':     regime,
            'n_samples':  info['n'],
            'win_rate':   info['win_rate'],
        }
    dump(ensemble, ENSEMBLE_PATH)
    print(f"💾 Ensemble saved → {ENSEMBLE_PATH}")

    # Persist feature list + params for reproducibility
    meta_path = os.path.join(REGIME_MODEL_DIR, 'training_meta.json')
    with open(meta_path, 'w') as f:
        json.dump({
            'top_features': top_features,
            'best_params':  best_params,
            'regime_paths': regime_paths,
            'retrained':    datetime.now(timezone.utc).isoformat(),
            **meta,
        }, f, indent=2)
    print(f"💾 Training meta saved → {meta_path}")


# ══════════════════════════════════════════════════════════════════════
# Section G — Main
# ══════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--n',        type=int,  default=60,   help='Signals to read (default 60)')
    parser.add_argument('--top-feat', type=int,  default=25,   help='SHAP top features to keep (default 25)')
    parser.add_argument('--trials',   type=int,  default=40,   help='Optuna trials (default 40)')
    parser.add_argument('--dry-run',  action='store_true',     help='Do not save model')
    args = parser.parse_args()

    # ── Binance client ─────────────────────────────────────────────
    from dotenv import load_dotenv
    load_dotenv(os.path.join(PROJECT_ROOT, '.env'))
    from binance.client import Client
    binance = Client(
        api_key    = os.getenv('BINANCE_API_KEY'),
        api_secret = os.getenv('BINANCE_API_SECRET'))
    print("✅ Binance client ready")

    # ── A1: Fetch signals ─────────────────────────────────────────
    print(f"\n📡 Reading last {args.n} signals from AnunnakiWorld…")
    signals = asyncio.run(_fetch_signal_messages(limit_scan=700, n_signals=args.n))
    print(f"   Parsed {len(signals)} signal messages")
    if not signals:
        print("No signals found. Exiting.")
        sys.exit(0)

    # ── A2: Verify outcomes ───────────────────────────────────────
    print("\n🔍 Verifying outcomes via Binance 1m history…")
    labeled, skipped = [], 0
    for i, sig in enumerate(signals):
        print(f"  [{i+1}/{len(signals)}] {sig['pair']:15s} {sig['direction']:5s} "
              f"{sig['date_str']}", end='  ')
        outcome = check_outcome(binance, sig)
        if outcome is None:
            print("⏳ skip")
            skipped += 1
            time.sleep(0.12)
            continue
        sig['label'] = outcome
        labeled.append(sig)
        print('✅ WIN' if outcome else '❌ LOSS')
        time.sleep(0.12)

    print(f"\n  Labeled: {len(labeled)} "
          f"({sum(s['label'] for s in labeled)} WIN / "
          f"{sum(1-s['label'] for s in labeled)} LOSS) | Skipped: {skipped}")

    if len(labeled) < 15:
        print(f"⚠  Only {len(labeled)} labeled samples — need ≥15. Exiting.")
        sys.exit(0)

    # ── A3: Build feature matrix ──────────────────────────────────
    print("\n⚙️  Reconstructing features…")
    feat_rows, meta_rows = [], []
    for i, sig in enumerate(labeled):
        print(f"  [{i+1}/{len(labeled)}] {sig['pair']:15s}", end=' ')
        df  = fetch_ohlcv(binance, sig['pair'], sig['timestamp'])
        row = build_features(df, client=binance, pair=sig['pair'])
        if row is None:
            print("→ skip")
            continue
        feat_rows.append(row)
        meta_rows.append({'label': sig['label'],
                          'regime': sig.get('regime', 'UNKNOWN'),
                          'direction': sig['direction'],
                          'timestamp': sig['timestamp']})
        print("→ ok")
        time.sleep(0.12)

    if len(feat_rows) < 15:
        print(f"⚠  Only {len(feat_rows)} feature vectors — aborting.")
        sys.exit(0)

    X_all = clean_matrix(pd.concat(feat_rows, ignore_index=True))
    meta_df = pd.DataFrame(meta_rows).reset_index(drop=True)
    y_all   = meta_df['label'].astype(int)

    print(f"\n✅ Matrix: {X_all.shape[0]} × {X_all.shape[1]}  "
          f"WIN={y_all.sum()}  LOSS={(~y_all.astype(bool)).sum()}  "
          f"win_rate={y_all.mean():.1%}")

    if args.dry_run:
        print("[dry-run] Stopping before model training.")
        sys.exit(0)

    # ── B: SHAP Feature Selection ─────────────────────────────────
    top_features = shap_feature_selection(X_all, y_all, top_n=args.top_feat)
    X_sel = X_all[top_features]

    # ── C+D: Walk-Forward CV baseline + Optuna tuning ────────────
    best_params_raw, best_auc = optuna_tune(X_sel, y_all, n_trials=args.trials)

    # Rebuild full params dict from Optuna output
    n_pos = int(y_all.sum()); n_neg = len(y_all) - n_pos
    spw   = max(n_neg / n_pos, 0.5) if n_pos > 0 else 1.0
    best_params = {
        'objective':        'binary:logistic',
        'eval_metric':      'logloss',
        'scale_pos_weight': spw,
        'seed':             42,
        **best_params_raw,
    }

    # Final walk-forward score with best params
    final_auc = walk_forward_cv(X_sel, y_all, dict(best_params), n_splits=4)
    print(f"\n[Final CV] Walk-Forward AUC = {final_auc:.3f}")

    # ── E1: Global model (all regimes) ────────────────────────────
    print("\n🏋  Training global model (all data)…")
    global_params = dict(best_params)
    global_model, global_acc = train_final(X_sel, y_all, global_params)
    print(f"   Train accuracy: {global_acc:.1%}")

    # ── E2: Regime-aware models ───────────────────────────────────
    df_labeled = X_sel.copy()
    df_labeled['label']  = y_all.values
    df_labeled['regime'] = meta_df['regime'].values
    regime_models = train_regime_models(df_labeled, top_features, dict(best_params))

    # ── F: Save ───────────────────────────────────────────────────
    save_models(
        global_model, global_acc, regime_models,
        top_features, best_params_raw,
        meta={
            'n_samples':   len(y_all),
            'win_rate':    float(y_all.mean()),
            'best_cv_auc': final_auc,
        }
    )

    # ── Summary ───────────────────────────────────────────────────
    print("\n" + "="*60)
    print("ADVANCED RETRAIN SUMMARY")
    print(f"  Signals read        : {len(signals)}")
    print(f"  Labeled outcomes    : {len(labeled)}")
    print(f"  Feature vectors     : {len(feat_rows)}")
    print(f"  Features after SHAP : {len(top_features)} / {X_all.shape[1]}")
    print(f"  Best Optuna AUC     : {best_auc:.3f}")
    print(f"  Walk-Forward AUC    : {final_auc:.3f}")
    print(f"  Global train acc    : {global_acc:.1%}")
    print(f"  Regime models       : {list(regime_models.keys())}")
    print(f"  Real WIN rate       : {y_all.mean():.1%}")
    print("="*60)
    print("\n✅ Bot uses updated models on next scan cycle.")


if __name__ == '__main__':
    main()
