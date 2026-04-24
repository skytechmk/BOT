"""
Feature-drift monitoring via Population Stability Index (PSI).

Why: ML models silently degrade when the live data distribution drifts
from the training distribution — e.g. funding regimes shifting, a new
volatility regime, Binance venue microstructure changes. PSI is the
industry-standard metric for detecting this early:

    PSI < 0.10  → no significant drift
    PSI 0.10-0.25 → moderate drift (investigate)
    PSI > 0.25  → major drift (retrain)

How it works
  1. On every training run, `snapshot_training_distribution()` stores a
     histogram of each feature (10 equal-frequency bins) in
     `ml_models/feature_distribution.pkl`.
  2. A daily task calls `compute_drift(live_df)` which compares the
     recent live features against the saved histogram.
  3. Features with high PSI are logged + emitted to the Ops channel.

CLI:
    python -m ml_drift_monitor                       # uses default cache
    python -m ml_drift_monitor --top 20              # show worst 20
"""

from __future__ import annotations

import os
import json
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import joblib

_MODEL_DIR = Path(os.environ.get(
    "ALADDIN_MODEL_DIR",
    str(Path(__file__).resolve().parent / "ml_models"),
))
_DIST_PATH = _MODEL_DIR / "feature_distribution.pkl"

N_BINS = 10
_EPS = 1e-6


# ─────────────────────────── Snapshot ───────────────────────────────────────

def snapshot_training_distribution(df: pd.DataFrame,
                                   feature_cols: list,
                                   out_path: Optional[Path] = None) -> dict:
    """
    Store per-feature quantile bin edges + bin probabilities for later PSI.
    Call this once at the end of each training run, passing the combined
    feature DataFrame used during training.
    """
    snapshot = {}
    for col in feature_cols:
        if col not in df.columns:
            continue
        values = df[col].dropna().to_numpy()
        if len(values) < 20:
            continue
        try:
            edges = np.unique(np.quantile(values,
                                          np.linspace(0, 1, N_BINS + 1)))
            if len(edges) < 3:
                continue
            counts, _ = np.histogram(values, bins=edges)
            probs = counts.astype(np.float64)
            probs = probs / max(probs.sum(), 1)
            probs = np.clip(probs, _EPS, None)
            snapshot[col] = {"edges": edges.tolist(),
                             "probs": probs.tolist()}
        except Exception:
            continue

    out_path = Path(out_path) if out_path else _DIST_PATH
    out_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(snapshot, out_path)
    return snapshot


def load_distribution(path: Optional[Path] = None) -> Optional[dict]:
    path = Path(path) if path else _DIST_PATH
    if not path.exists():
        return None
    try:
        return joblib.load(path)
    except Exception:
        return None


# ────────────────────────────── PSI ─────────────────────────────────────────

def _psi_single(live_values: np.ndarray,
                edges: np.ndarray,
                train_probs: np.ndarray) -> float:
    counts, _ = np.histogram(live_values, bins=edges)
    probs = counts.astype(np.float64) / max(counts.sum(), 1)
    probs = np.clip(probs, _EPS, None)
    train_probs = np.clip(np.asarray(train_probs, dtype=np.float64), _EPS, None)
    return float(np.sum((probs - train_probs) * np.log(probs / train_probs)))


def compute_drift(df_live: pd.DataFrame,
                  snapshot: Optional[dict] = None) -> pd.DataFrame:
    """
    Compute per-feature PSI between `df_live` and the stored training
    distribution. Returns a DataFrame sorted by PSI descending.
    """
    snapshot = snapshot if snapshot is not None else load_distribution()
    if snapshot is None:
        return pd.DataFrame(columns=["feature", "psi", "status"])
    rows = []
    for col, payload in snapshot.items():
        if col not in df_live.columns:
            continue
        live = df_live[col].dropna().to_numpy()
        if len(live) < 20:
            continue
        try:
            psi = _psi_single(live,
                              np.asarray(payload["edges"]),
                              np.asarray(payload["probs"]))
        except Exception:
            continue
        if psi < 0.10:
            status = "stable"
        elif psi < 0.25:
            status = "moderate"
        else:
            status = "major"
        rows.append({"feature": col, "psi": psi, "status": status})
    return (pd.DataFrame(rows)
              .sort_values("psi", ascending=False)
              .reset_index(drop=True))


# ─────────────────────────── CLI entrypoint ────────────────────────────────

def _build_live_dataframe(pairs, bars_1h: int = 500) -> pd.DataFrame:
    """Assemble recent features from top pairs for drift comparison."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from data_fetcher import fetch_data
    from ml_engine_archive.feature_engine import build_features

    frames = []
    for p in pairs[:30]:
        try:
            df = fetch_data(p, "1h")
            if df is None or len(df) < bars_1h:
                continue
            feat = build_features(df.tail(bars_1h).copy(), pair=p).tail(200)
            frames.append(feat)
        except Exception:
            continue
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Aladdin ML drift monitor")
    parser.add_argument("--top", type=int, default=15, help="Show N worst features")
    parser.add_argument("--pairs", nargs="*", default=None)
    parser.add_argument("--json", action="store_true", help="Emit JSON only")
    args = parser.parse_args()

    if args.pairs is None:
        from data_fetcher import fetch_trading_pairs
        args.pairs = fetch_trading_pairs()[:30]

    print(f"🔍 Drift monitor — comparing live distribution against "
          f"{_DIST_PATH.name}...")
    df_live = _build_live_dataframe(args.pairs)
    if df_live.empty:
        print("❌ No live data available.")
        return
    report = compute_drift(df_live)
    if report.empty:
        print("⚠️  No snapshot found or no overlapping features.")
        return

    if args.json:
        print(json.dumps(report.head(args.top).to_dict(orient="records"),
                         indent=2))
    else:
        print(f"\nTop {args.top} by PSI:")
        print(report.head(args.top).to_string(index=False))
        n_major = (report["status"] == "major").sum()
        n_mod = (report["status"] == "moderate").sum()
        print(f"\nSummary: {len(report)} features | "
              f"{n_major} major drift | {n_mod} moderate drift")


if __name__ == "__main__":
    main()
