"""
Probability calibration for the Aladdin ML ensemble.

Why: raw XGBoost/LightGBM outputs are ordered but poorly calibrated
(e.g. a raw score of 0.7 often corresponds to ~55% true win-rate).
Fitting an isotonic-regression calibrator on a held-out validation set
transforms the raw scores so that `calibrated_prob > 0.7` actually
means the empirical TP-hit rate is ≥ 70%.

Design
  - Fit once, off-line, from the model's validation-set predictions.
  - Persist as `ml_models/calibrator.pkl`.
  - `calibrate_probs(raw_probs)` is a cheap vectorised transform at
    live-signal time.
  - If the calibrator file is missing the module returns raw probs
    unchanged (zero-risk fallback).

Per-class isotonic calibration (one-vs-rest) is used because XGBoost
multi-class output is a [N, 3] probability matrix. We fit 3 isotonic
regressors and renormalise the output row.

Usage from train.py (optional add-on step after tree training):

    from ml_calibration import fit_calibrator
    fit_calibrator(raw_val_probs, y_val, out_path=MODEL_DIR/'calibrator.pkl')

Usage at inference:

    from ml_calibration import load_calibrator, calibrate_probs
    cal = load_calibrator()                     # cached
    cal_probs = calibrate_probs(raw_probs, cal)
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Optional

import numpy as np
import joblib

try:
    from sklearn.isotonic import IsotonicRegression
except Exception:
    IsotonicRegression = None

_MODEL_DIR = Path(os.environ.get(
    "ALADDIN_MODEL_DIR",
    str(Path(__file__).resolve().parent / "ml_models"),
))
_CALIBRATOR_PATH = _MODEL_DIR / "calibrator.pkl"

_cache_lock = threading.Lock()
_cache: dict = {"path": None, "mtime": None, "object": None}


# ── Fit ─────────────────────────────────────────────────────────────────────

def fit_calibrator(val_probs: np.ndarray, y_val: np.ndarray,
                   out_path: Optional[Path] = None) -> dict:
    """
    Fit one isotonic regressor per class using validation predictions.

    val_probs : ndarray shape (N, 3) — raw model probabilities (softmax).
    y_val     : ndarray shape (N,)   — true labels, values in {-1, 0, 1}
                                       OR class indices {0, 1, 2}.
    Returns the calibrator dict, also persists if `out_path` given.
    """
    if IsotonicRegression is None:
        raise RuntimeError("sklearn.isotonic not available")
    val_probs = np.asarray(val_probs, dtype=np.float64)
    y_val = np.asarray(y_val)

    # Remap {-1, 0, 1} to {0, 1, 2} if needed
    if y_val.min() < 0:
        y_idx = y_val + 1
    else:
        y_idx = y_val
    y_idx = y_idx.astype(int)

    calibrators = []
    for k in range(val_probs.shape[1]):
        y_bin = (y_idx == k).astype(int)
        if y_bin.sum() == 0 or y_bin.sum() == len(y_bin):
            # Degenerate class — use identity
            iso = None
        else:
            iso = IsotonicRegression(out_of_bounds='clip', y_min=0.0, y_max=1.0)
            iso.fit(val_probs[:, k], y_bin)
        calibrators.append(iso)

    obj = {
        "type": "isotonic_ovr",
        "n_classes": val_probs.shape[1],
        "calibrators": calibrators,
        "class_mapping": {-1: 0, 0: 1, 1: 2},
    }
    if out_path is not None:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(obj, out_path)
    return obj


# ── Load ────────────────────────────────────────────────────────────────────

def load_calibrator(path: Optional[Path] = None) -> Optional[dict]:
    """Load calibrator from disk with mtime-based cache invalidation."""
    path = Path(path) if path else _CALIBRATOR_PATH
    if not path.exists():
        return None
    try:
        mtime = path.stat().st_mtime
    except Exception:
        return None
    with _cache_lock:
        if (_cache["path"] == path and _cache["mtime"] == mtime
                and _cache["object"] is not None):
            return _cache["object"]
        try:
            obj = joblib.load(path)
        except Exception:
            return None
        _cache.update({"path": path, "mtime": mtime, "object": obj})
        return obj


# ── Apply ───────────────────────────────────────────────────────────────────

def calibrate_probs(raw_probs: np.ndarray,
                    calibrator: Optional[dict] = None) -> np.ndarray:
    """
    Transform raw (N, K) probability matrix into calibrated probabilities.
    Renormalises rows so they sum to 1.0.
    Falls back to raw_probs if calibrator unavailable or malformed.
    """
    raw_probs = np.asarray(raw_probs, dtype=np.float64)
    if calibrator is None:
        calibrator = load_calibrator()
    if calibrator is None or "calibrators" not in calibrator:
        return raw_probs

    cals = calibrator["calibrators"]
    if raw_probs.ndim == 1:
        raw_probs = raw_probs.reshape(1, -1)
    if raw_probs.shape[1] != len(cals):
        return raw_probs

    out = np.zeros_like(raw_probs)
    for k, iso in enumerate(cals):
        if iso is None:
            out[:, k] = raw_probs[:, k]
        else:
            out[:, k] = iso.transform(raw_probs[:, k])
    row_sums = out.sum(axis=1, keepdims=True)
    row_sums[row_sums == 0] = 1.0
    return out / row_sums
