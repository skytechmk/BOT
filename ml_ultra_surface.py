"""
Unified Ultra-tier prediction surface.

Given a built feature row (from feature_engine.build_features), returns a
rich prediction payload combining:
  - Raw model probabilities       (all tiers)
  - Calibrated probabilities       (Pro + Ultra)
  - Conformal 90% CI on top-class  (Ultra only)
  - Conformal prediction set       (Ultra only)
  - SHAP top-5 drivers             (Ultra only)
  - Human-readable text summary    (Ultra only)

This is the single entry point that the Telegram `/explain` command and the
dashboard Ultra widget should call.

Tier-gating happens at the caller (Telegram handler / dashboard endpoint);
this module produces everything and the caller redacts per tier.

Usage:
    from ml_ultra_surface import predict_ultra
    payload = predict_ultra(feature_row)
    # payload is a dict with keys documented below.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import joblib
import xgboost as xgb

from ml_calibration import load_calibrator, calibrate_probs
from ml_conformal import load_conformal, predict_with_ci, prediction_set
from ml_explainer import explain_signal, explain_signal_text

_MODEL_DIR = Path(os.environ.get(
    "ALADDIN_MODEL_DIR",
    str(Path(__file__).resolve().parent / "ml_models"),
))
_CLASS_NAMES = ("SHORT", "NEUTRAL", "LONG")

_cache = {"xgb": None, "xgb_mtime": None, "feat_cols": None, "scaler": None}
_model_lock = threading.Lock()


def _ensure_model():
    """Thread-safe singleton loader for the XGBoost booster and companions.

    Guards against the race where a concurrent autotrainer overwrites
    ``xgboost_best.json`` while ``booster.load_model()`` is reading it —
    which would produce a SIGABRT / partial-binary crash in the ASGI process.
    """
    xgb_path = _MODEL_DIR / "xgboost_best.json"
    if not xgb_path.exists():
        return None
    mtime = xgb_path.stat().st_mtime

    # Fast path: model already loaded and file hasn't changed.
    if _cache["xgb"] is not None and _cache["xgb_mtime"] == mtime:
        return _cache

    with _model_lock:
        # Double-check inside the lock — another thread may have loaded
        # the model between the fast-path check and acquiring the lock.
        _mtime_now = xgb_path.stat().st_mtime
        if _cache["xgb"] is not None and _cache["xgb_mtime"] == _mtime_now:
            return _cache

        booster = xgb.Booster()
        booster.load_model(str(xgb_path))

        fcols = None
        fcols_path = _MODEL_DIR / "xgboost_features.pkl"
        if fcols_path.exists():
            try:
                fcols = joblib.load(fcols_path)
            except Exception:
                fcols = None

        scaler = None
        scaler_path = _MODEL_DIR / "scaler.pkl"
        if scaler_path.exists():
            try:
                scaler = joblib.load(scaler_path)
            except Exception:
                scaler = None

        _cache.update({
            "xgb": booster,
            "xgb_mtime": _mtime_now,
            "feat_cols": fcols,
            "scaler": scaler,
        })
    return _cache


def predict_ultra(feature_row: pd.Series,
                  include_shap: bool = True,
                  shap_top_n: int = 5) -> dict:
    """
    Run the full prediction stack on a single feature row.

    Returns dict:
      ok                : bool
      class             : "SHORT" | "NEUTRAL" | "LONG"
      class_idx         : 0 | 1 | 2
      probs_raw         : [p_short, p_neutral, p_long]
      probs_calibrated  : same shape, post-isotonic
      ci_low, ci_high   : conformal 90% CI on top-class prob, or None
      prediction_set    : list[str] class names whose prob passes α-threshold
      shap              : list[(feature, raw_value, contribution, direction)]
      text_explanation  : multi-line string (for Telegram)
      error             : present only if ok=False
    """
    out = {"ok": False}
    art = _ensure_model()
    if art is None or art["feat_cols"] is None:
        out["error"] = "model artifacts missing"
        return out

    fcols  = art["feat_cols"]
    scaler = art["scaler"]
    booster = art["xgb"]

    x = np.array([[float(feature_row.get(c, 0.0)) for c in fcols]],
                 dtype=np.float64)
    if scaler is not None:
        try:
            x = scaler.transform(x)
        except Exception:
            pass

    # Raw probs
    try:
        probs_raw = booster.predict(xgb.DMatrix(x))
        if probs_raw.ndim == 1:
            probs_raw = np.column_stack([1 - probs_raw, probs_raw])
        probs_raw = probs_raw[0]
    except Exception as e:
        out["error"] = f"predict failed: {e}"
        return out

    # Calibrated probs
    cal = load_calibrator()
    probs_cal = calibrate_probs(probs_raw.reshape(1, -1), cal)[0] if cal else probs_raw
    class_idx = int(np.argmax(probs_cal))
    class_name = (_CLASS_NAMES[class_idx] if class_idx < len(_CLASS_NAMES)
                  else f"class_{class_idx}")

    # Conformal CI + set
    conf = load_conformal()
    _, top_p, ci_low, ci_high = predict_with_ci(probs_cal, conf)
    pred_set_idx = prediction_set(probs_cal, conf)
    pred_set_names = [
        _CLASS_NAMES[i] if i < len(_CLASS_NAMES) else f"class_{i}"
        for i in pred_set_idx
    ]

    # SHAP
    shap_rows: list = []
    text_expl = ""
    if include_shap:
        try:
            shap_rows = explain_signal(feature_row, top_n=shap_top_n,
                                       class_idx=class_idx)
            text_expl = explain_signal_text(feature_row, top_n=shap_top_n,
                                            class_idx=class_idx,
                                            signal_name=f"{class_name} signal")
        except Exception:
            pass

    out.update({
        "ok": True,
        "class": class_name,
        "class_idx": class_idx,
        "probs_raw": probs_raw.tolist(),
        "probs_calibrated": probs_cal.tolist(),
        "ci_low": None if np.isnan(ci_low) else float(ci_low),
        "ci_high": None if np.isnan(ci_high) else float(ci_high),
        "prediction_set": pred_set_names,
        "shap": [
            {"feature": n, "raw_value": rv, "contribution": c, "direction": d}
            for (n, rv, c, d) in shap_rows
        ],
        "text_explanation": text_expl,
    })
    return out


def format_for_tier(payload: dict, tier: str, is_admin: bool = False) -> dict:
    """
    Redact the payload per tier policy. Call after `predict_ultra`.

    Tier policy (matches proposal 2026-04-22_ml-feature-expansion.md):
      free / plus  : class + bucketed probability
      pro          : class + exact probability + calibrated prob
      ultra/admin  : everything (CI, prediction set, SHAP, text)
    """
    t = tier.lower() if isinstance(tier, str) else "free"
    if is_admin:
        t = "ultra"
    if not payload.get("ok"):
        return payload

    out = {"class": payload["class"], "tier": t}

    if t in ("free", "plus"):
        # bucketed probability
        top_p = payload["probs_calibrated"][payload["class_idx"]]
        if   top_p >= 0.80: bucket = "very_high"
        elif top_p >= 0.65: bucket = "high"
        elif top_p >= 0.50: bucket = "medium"
        else:               bucket = "low"
        out["confidence_bucket"] = bucket
        return out

    if t == "pro":
        out["probability_raw"]   = payload["probs_raw"]
        out["probability_final"] = payload["probs_calibrated"]
        return out

    # ultra / admin — full surface
    out.update({
        "probability_raw":      payload["probs_raw"],
        "probability_final":    payload["probs_calibrated"],
        "ci_low":               payload["ci_low"],
        "ci_high":              payload["ci_high"],
        "prediction_set":       payload["prediction_set"],
        "shap":                 payload["shap"],
        "text_explanation":     payload["text_explanation"],
    })
    return out
