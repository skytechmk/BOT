"""
Inductive Conformal Prediction for per-signal confidence intervals.

Gives each live prediction a *finite-sample-valid* prediction set:
    P(y_true ∈ prediction_set) ≥ 1 - α   (for user-chosen α, e.g. 0.1 → 90% CI)

This is model-agnostic — works on any classifier that emits scores/probs.
We fit once on a held-out calibration slice and persist quantiles; at
inference we apply a cheap threshold.

How the Ultra tier consumes this:
    "Edge CI (90%): direction = LONG with p ∈ [0.61, 0.83]"
    → if the lower bound > 0.5 the meta-labeler can fire with high trust.

Two flavours:
    1. `score_pred_set(probs, q)` — returns the set of classes whose
       calibrated prob exceeds the non-conformity threshold. Set size
       1 = confident, 2+ = uncertain, 0 = out-of-distribution.
    2. `score_margin_ci(probs, q_low, q_high)` — returns (lo, hi) on the
       top-class probability, for a continuous "edge" confidence band.

Design
  - Persists to `ml_models/conformal.pkl`: {alpha, q_nonconf, q_margin_lo,
    q_margin_hi, classes}.
  - `fit_conformal(val_probs, y_val, alpha=0.1)` — fit on validation set.
  - `predict_with_ci(probs)` — cheap inference helper.
  - Missing file → returns (raw_top_class, raw_top_prob, None, None) so
    callers never break.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Optional, Tuple

import numpy as np
import joblib

_MODEL_DIR = Path(os.environ.get(
    "ALADDIN_MODEL_DIR",
    str(Path(__file__).resolve().parent / "ml_models"),
))
_CONFORMAL_PATH = _MODEL_DIR / "conformal.pkl"

_cache_lock = threading.Lock()
_cache: dict = {"path": None, "mtime": None, "object": None}


# ── Fit ─────────────────────────────────────────────────────────────────────

def fit_conformal(val_probs: np.ndarray, y_val: np.ndarray,
                  alpha: float = 0.1,
                  out_path: Optional[Path] = None) -> dict:
    """
    Fit inductive conformal thresholds from validation predictions.

    Non-conformity score used: 1 - p(y_true | x).
    The empirical (1-α)-quantile of these scores becomes the per-signal
    "rejection threshold" — classes whose prob < (1 - q_nonconf) are
    excluded from the prediction set.

    Additionally we compute calibration on the top-class probability
    to produce a continuous CI on the model's confidence.

    val_probs : (N, K) raw or calibrated probs (prefer calibrated).
    y_val     : (N,)  true labels; {-1, 0, 1} or {0, 1, 2}.
    alpha     : miscoverage level (e.g. 0.1 for 90% CI).
    """
    val_probs = np.asarray(val_probs, dtype=np.float64)
    y_val = np.asarray(y_val)

    if y_val.min() < 0:
        y_idx = (y_val + 1).astype(int)
    else:
        y_idx = y_val.astype(int)

    n = len(y_idx)
    # Non-conformity scores: 1 - p(y_true)
    nonconf = 1.0 - val_probs[np.arange(n), y_idx]
    # Finite-sample correction (Vovk 2005)
    q_level = np.ceil((n + 1) * (1 - alpha)) / n
    q_level = min(q_level, 1.0)
    q_nonconf = float(np.quantile(nonconf, q_level, method="higher"))

    # Margin CI on top-class prob (signed residual)
    top_prob = val_probs.max(axis=1)
    true_prob = val_probs[np.arange(n), y_idx]
    residual = top_prob - true_prob  # ≥ 0 when top-class != truth
    q_margin = float(np.quantile(residual, 1 - alpha, method="higher"))

    obj = {
        "type": "inductive_conformal",
        "alpha": alpha,
        "q_nonconf": q_nonconf,
        "q_margin": q_margin,
        "n_calib": n,
        "n_classes": val_probs.shape[1],
    }
    if out_path is not None:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(obj, out_path)
    return obj


# ── Load ────────────────────────────────────────────────────────────────────

def load_conformal(path: Optional[Path] = None) -> Optional[dict]:
    path = Path(path) if path else _CONFORMAL_PATH
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

def predict_with_ci(probs: np.ndarray,
                    conformal: Optional[dict] = None
                    ) -> Tuple[int, float, float, float]:
    """
    probs : (K,) or (1, K) calibrated probability vector.

    Returns:
        top_class_index  (int, 0..K-1)   — argmax class
        top_prob         (float)         — argmax probability
        ci_low           (float or NaN)  — lower bound on top-class prob
        ci_high          (float or NaN)  — upper bound on top-class prob
        (NaNs when no conformal model available)
    """
    probs = np.asarray(probs, dtype=np.float64).ravel()
    top_idx = int(np.argmax(probs))
    top_p = float(probs[top_idx])
    conf = conformal if conformal is not None else load_conformal()
    if conf is None or "q_margin" not in conf:
        return top_idx, top_p, float("nan"), float("nan")
    q = conf["q_margin"]
    ci_low = max(0.0, top_p - q)
    ci_high = min(1.0, top_p + q)
    return top_idx, top_p, ci_low, ci_high


def prediction_set(probs: np.ndarray,
                   conformal: Optional[dict] = None) -> list:
    """
    Returns list of class indices whose prob ≥ (1 - q_nonconf).
    Set size == 1 → confident single-class prediction.
    Set size >= 2 → classifier can't rule competitors out at chosen α.
    """
    probs = np.asarray(probs, dtype=np.float64).ravel()
    conf = conformal if conformal is not None else load_conformal()
    if conf is None or "q_nonconf" not in conf:
        return [int(np.argmax(probs))]
    threshold = 1.0 - conf["q_nonconf"]
    return [int(i) for i, p in enumerate(probs) if p >= threshold]
