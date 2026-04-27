"""
Signal Quality Index (SQI) — Data-Driven Composite Score
═══════════════════════════════════════════════════════════

Replaces opaque ML confidence with a transparent, interpretable score
based on factors that ACTUALLY correlate with winning trades (from 587
historical signals analysis, Apr 2026).

Scoring (0–100):
  ┌─────────────────────────────────────────────┐
  │ R:R Quality            → 0–30 pts  (30%)   │
  │ Volume Confirmation    → 0–20 pts  (20%)   │
  │ CE Alignment           → 0–15 pts  (15%)   │
  │ Mean Extension         → 0–15 pts  (15%)   │
  │ ATR Regime             → 0–10 pts  (10%)   │
  │ Momentum Acceleration  → 0–10 pts  (10%)   │
  └─────────────────────────────────────────────┘

Factor weights derived from win/loss correlation analysis:
  - R:R ≥ 2.0 → 53.8% WR vs R:R < 0.5 → 0.8% WR
  - Volume 3.5× higher in wins than losses
  - CE alignment: 100% of wins had CE aligned, 0% of losses
  - Low extension from EMA21 correlates with cleaner entries
"""

import os
import numpy as np
from utils_logger import log_message
from smc_structure import detect_market_structure

# [2026-04-22] Factor pruning — removed Volume, ATR regime, Candlestick,
# RSI divergence, and Wyckoff phase factors (plus their helpers and the
# wyckoff_filter import) because ML ensemble (Factor 11) already consumes
# their underlying features and was double-counting them. Remaining
# factors capture orthogonal signal quality dimensions.

# ── BEAST change-point cache ─────────────────────────────────────────────────

_BEAST_CACHE: dict = {}   # {cache_key: (timestamp, prob)}
_BEAST_TTL   = 3600       # 1 hour


def _get_beast_changepoint_prob(close_series, cache_key: str = None) -> float:
    """
    Run Bayesian change-point detection (Rbeast) on recent close prices.
    Returns the max cpOccPr across the last 3 bars (0.0 – 1.0).
    Cached per pair for 1 hour; silently returns 0.0 on any failure.
    """
    import time as _t
    now = _t.time()
    if cache_key and cache_key in _BEAST_CACHE:
        ts, prob = _BEAST_CACHE[cache_key]
        if now - ts < _BEAST_TTL:
            return prob
    try:
        import Rbeast as rb
        close_arr = list(close_series.dropna().tail(200))
        if len(close_arr) < 50:
            return 0.0
        extra = rb.args()
        extra.quiet = True
        extra.printProgress = False
        extra.printParameter = False
        extra.printWarning   = False
        # Suppress C-level stdout
        devnull_fd = os.open(os.devnull, os.O_WRONLY)
        saved_fd   = os.dup(1)
        os.dup2(devnull_fd, 1)
        os.close(devnull_fd)
        try:
            o = rb.beast(close_arr, season='none', extra=extra)
        finally:
            os.dup2(saved_fd, 1)
            os.close(saved_fd)
        cp_probs    = list(o.trend.cpOccPr)
        recent_max  = float(max(cp_probs[-3:])) if len(cp_probs) >= 3 else float(cp_probs[-1])
        if cache_key:
            _BEAST_CACHE[cache_key] = (_t.time(), recent_max)
        return recent_max
    except Exception:
        return 0.0


def calculate_sqi(df, entry_price, stop_loss, targets, signal_direction,
                  ce_line_dir=None, ce_cloud_dir=None, volume_sma_period=20,
                  positioning_score=0, positioning_aligned=True,
                  regime=None, stop_hunt=None, pair=None, cvd_data=None):
    """
    Calculate Signal Quality Index v2.

    Parameters
    ----------
    df : pd.DataFrame  — 1h OHLCV with indicators (ATR, RSI, TSI, etc.)
    entry_price : float
    stop_loss : float
    targets : list[float]
    signal_direction : str — 'LONG' or 'SHORT'
    ce_line_dir : str|None — 'LONG' or 'SHORT'
    ce_cloud_dir : str|None — 'LONG' or 'SHORT'
    volume_sma_period : int
    positioning_score : int (0-20 from PREDATOR L2)
    positioning_aligned : bool (does positioning agree with direction?)
    regime : str|None (PREDATOR regime name)
    stop_hunt : dict|None (from detect_stop_hunt)

    Returns
    -------
    dict with 'sqi' (0–120), 'grade' (S/A/B/C/D), 'factors' (breakdown),
    and 'flags' (list of warning strings).
    """
    try:
        is_long = signal_direction.upper() in ('LONG', 'BUY')
        latest = df.iloc[-1]
        factors = {}
        flags = []

        # ══════════════════════════════════════════════════════════════
        # Factor 1: R:R Quality (0–30 pts)
        # ══════════════════════════════════════════════════════════════
        risk = abs(entry_price - stop_loss)
        best_reward = abs(targets[-1] - entry_price) if targets else 0
        rr = best_reward / risk if risk > 0 else 0

        if rr >= 3.0:
            rr_score = 30
        elif rr >= 2.5:
            rr_score = 27
        elif rr >= 2.0:
            rr_score = 24
        elif rr >= 1.5:
            rr_score = 18
        elif rr >= 1.0:
            rr_score = 10
        else:
            rr_score = 0
            flags.append(f'LOW_RR:{rr:.2f}')

        factors['rr'] = {'score': rr_score, 'max': 30, 'value': round(rr, 2)}

        # ══════════════════════════════════════════════════════════════
        # Factor 3: CE Alignment (0–15 pts)
        # ══════════════════════════════════════════════════════════════
        ce_score = 0
        expected = 'LONG' if is_long else 'SHORT'

        line_aligned = (ce_line_dir == expected) if ce_line_dir else False
        cloud_aligned = (ce_cloud_dir == expected) if ce_cloud_dir else False

        # Fallback: read from df columns
        if ce_line_dir is None and 'CE_Direction' in df.columns:
            ce_dir_val = int(latest['CE_Direction'])
            line_aligned = (ce_dir_val == 1 and is_long) or (ce_dir_val == -1 and not is_long)
        if ce_cloud_dir is None and 'CE_Cloud_Direction' in df.columns:
            cloud_dir_val = int(latest['CE_Cloud_Direction'])
            cloud_aligned = (cloud_dir_val == 1 and is_long) or (cloud_dir_val == -1 and not is_long)

        if line_aligned and cloud_aligned:
            ce_score = 15
        elif line_aligned:
            ce_score = 10
        elif cloud_aligned:
            ce_score = 5
        else:
            ce_score = 0
            flags.append('CE_DISAGREE')

        factors['ce_alignment'] = {
            'score': ce_score, 'max': 15,
            'value': f"Line={'Y' if line_aligned else 'N'} Cloud={'Y' if cloud_aligned else 'N'}"
        }

        # ══════════════════════════════════════════════════════════════
        # Factor 4: Mean Extension (0–15 pts)
        # Lower extension from EMA21 = better entry = higher score
        # ══════════════════════════════════════════════════════════════
        ext_score = 0
        ema21 = df['close'].ewm(span=21, adjust=False).mean().iloc[-1]
        ext_pct = abs(entry_price - ema21) / ema21 * 100 if ema21 > 0 else 0

        if ext_pct <= 1.0:
            ext_score = 15  # tight to mean — ideal entry
        elif ext_pct <= 2.5:
            ext_score = 12
        elif ext_pct <= 5.0:
            ext_score = 8
        elif ext_pct <= 10.0:
            ext_score = 3
            flags.append(f'EXTENDED:{ext_pct:.1f}%')
        else:
            ext_score = 0
            flags.append(f'OVEREXTENDED:{ext_pct:.1f}%')

        factors['extension'] = {'score': ext_score, 'max': 15, 'value': round(ext_pct, 2)}

        # ══════════════════════════════════════════════════════════════
        # Factor 6: Momentum Acceleration (0–10 pts)
        # TSI rate-of-change: is momentum accelerating into the trade?
        # ══════════════════════════════════════════════════════════════
        mom_score = 0
        if 'TSI' in df.columns and len(df) >= 5:
            tsi_now = float(latest['TSI'])
            tsi_prev = float(df['TSI'].iloc[-3])  # 2 bars ago
            tsi_delta = tsi_now - tsi_prev

            # For LONG: TSI should be rising. For SHORT: TSI should be falling.
            favorable = (tsi_delta > 0 and is_long) or (tsi_delta < 0 and not is_long)
            magnitude = abs(tsi_delta)

            if favorable:
                if magnitude >= 3.0:
                    mom_score = 10
                elif magnitude >= 1.5:
                    mom_score = 7
                elif magnitude >= 0.5:
                    mom_score = 4
                else:
                    mom_score = 2
            else:
                mom_score = 0
                if magnitude >= 2.0:
                    flags.append(f'MOM_AGAINST:{tsi_delta:+.2f}')

            factors['momentum'] = {'score': mom_score, 'max': 10, 'value': round(tsi_delta, 2)}
        else:
            factors['momentum'] = {'score': 5, 'max': 10, 'value': None}
            mom_score = 5

        # ══════════════════════════════════════════════════════════════
        # Factor 7: Positioning Alignment (0–20 pts) — PREDATOR Layer 2
        # Crypto-native: funding, OI divergence, taker delta
        # ══════════════════════════════════════════════════════════════
        pos_score = 0
        if positioning_aligned:
            pos_score = min(positioning_score, 20)
        else:
            pos_score = 0
            if positioning_score >= 10:
                flags.append('POS_AGAINST')

        factors['positioning'] = {
            'score': pos_score, 'max': 20,
            'value': f"{'aligned' if positioning_aligned else 'against'}:{positioning_score}"
        }

        # ── Stop Hunt Bonus (0-5 pts) ──
        hunt_bonus = 0
        if stop_hunt and stop_hunt.get('hunt_detected'):
            hunt_type = stop_hunt.get('hunt_type', '')
            # Hunt must align with signal direction
            if (hunt_type == 'LONG_HUNT' and is_long) or (hunt_type == 'SHORT_HUNT' and not is_long):
                hunt_bonus = 5
                factors['stop_hunt'] = {'score': 5, 'max': 5, 'value': hunt_type}
            else:
                factors['stop_hunt'] = {'score': 0, 'max': 5, 'value': f'{hunt_type}_MISALIGNED'}
        else:
            factors['stop_hunt'] = {'score': 0, 'max': 5, 'value': None}

        # ══════════════════════════════════════════════════════════════
        # Factor 9: BEAST Change-Point Probability (0–8 pts)
        # Bayesian regime change detection — bars near a structural
        # inflection score higher (genuine reversal, not noise).
        # ══════════════════════════════════════════════════════════════
        beast_score = 0
        try:
            cp_prob = _get_beast_changepoint_prob(df['close'], cache_key=pair)
            if   cp_prob >= 0.70: beast_score = 8
            elif cp_prob >= 0.50: beast_score = 5
            elif cp_prob >= 0.30: beast_score = 3
            factors['beast_cp'] = {'score': beast_score, 'max': 8, 'value': round(cp_prob, 3)}
        except Exception:
            factors['beast_cp'] = {'score': 0, 'max': 8, 'value': None}

        # ══════════════════════════════════════════════════════════════
        # Factor 11: ML Stacking Ensemble (−5 to +8 pts) — Phase 6 wiring
        # BiLSTM + TFT (GPU) + XGBoost + LightGBM → meta-learner, then
        # calibrated via isotonic regression and gated by inductive
        # conformal prediction:
        #   - `probs_calibrated` replaces raw confidence (more honest).
        #   - If the conformal prediction set contains >1 class the
        #     model is genuinely uncertain → score halved + ML_UNCERTAIN flag.
        #   - Top-3 SHAP drivers persisted for /explain and analytics.
        # Falls back to the legacy predictor path on any failure.
        # ══════════════════════════════════════════════════════════════
        ml_score = 0
        ml_ultra_payload = None
        try:
            from ml_ultra_surface import predict_ultra
            from ml_engine_archive.feature_engine import build_features
            # build_features adds the 127-col ML feature matrix on top of the
            # OHLCV+TA df. predict_ultra then projects to the 50 pruned cols.
            _df_feat = build_features(df.copy(), pair=pair or 'UNKNOWN')
            feat_row = _df_feat.iloc[-1]
            _p = predict_ultra(feat_row, include_shap=True, shap_top_n=3)
            if _p.get('ok'):
                ml_ultra_payload = _p
                _probs_cal = _p['probs_calibrated']
                # probs layout: [SHORT, NEUTRAL, LONG]
                ml_sig_idx   = int(max(range(3), key=lambda i: _probs_cal[i]))
                ml_sig       = ('SHORT', 'NEUTRAL', 'LONG')[ml_sig_idx]
                ml_conf      = float(_probs_cal[ml_sig_idx])   # calibrated
                ml_directional_conf = float(_probs_cal[2] if is_long else _probs_cal[0])
                ml_aligned   = (ml_sig == 'LONG' and is_long) or (ml_sig == 'SHORT' and not is_long)
                pred_set     = _p.get('prediction_set') or []
                ci_low       = _p.get('ci_low')
                ci_high      = _p.get('ci_high')
                uncertain    = len(pred_set) > 1   # conformal ambiguity

                if ml_aligned and ml_sig != 'NEUTRAL':
                    if   ml_conf >= 0.55: ml_score = 8
                    elif ml_conf >= 0.45: ml_score = 5
                    elif ml_conf >= 0.35: ml_score = 2
                elif not ml_aligned and ml_sig != 'NEUTRAL':
                    if   ml_conf >= 0.55: ml_score = -5
                    elif ml_conf >= 0.45: ml_score = -3
                    else:                 ml_score = -1
                # else ml_sig == NEUTRAL → ml_score stays 0

                # Conformal uncertainty dampener: halve magnitude if
                # model couldn't rule out competing classes.
                if uncertain and ml_score != 0:
                    ml_score = int(round(ml_score / 2))
                    flags.append(f'ML_UNCERTAIN:set={"+".join(pred_set)}')

                # Phase 7: MC-Dropout for close-call signals
                if os.getenv('ML_USE_MC_DROPOUT', 'true').lower() == 'true':
                    if 0.40 < ml_conf < 0.60:
                        try:
                            from ml_engine_archive.models import get_ensemble
                            _ens = get_ensemble()
                            if _ens and hasattr(_ens, 'predict_with_uncertainty'):
                                mc_result = _ens.predict_with_uncertainty(feat_row.values.reshape(1, -1), n_samples=int(os.getenv('ML_MC_DROPOUT_SAMPLES', '30')))
                                mc_unc = mc_result.get('uncertainty', 0)
                                if mc_unc > float(os.getenv('ML_MC_UNCERTAINTY_THRESHOLD', '0.15')):
                                    ml_score = int(round(ml_score / 2))
                                    flags.append(f"MC_UNCERTAIN:{mc_unc:.3f}")
                        except Exception as mc_e:
                            pass

                if ml_aligned and ml_conf >= 0.50:
                    flags.append(f'ML_CONFIRM:{ml_sig}({ml_conf:.2f})')
                elif not ml_aligned and ml_conf >= 0.45 and ml_sig != 'NEUTRAL':
                    flags.append(f'ML_OPPOSE:{ml_sig}({ml_conf:.2f})')

                factors['ml_ensemble'] = {
                    'score': ml_score, 'max': 8,
                    'value': (
                        f"{ml_sig}@cal={ml_conf:.2f} "
                        f"dir={ml_directional_conf:.2f} "
                        f"CI=[{ci_low:.2f},{ci_high:.2f}] "
                        f"set={'+'.join(pred_set) if pred_set else '?'}"
                        if ci_low is not None and ci_high is not None
                        else f"{ml_sig}@cal={ml_conf:.2f} dir={ml_directional_conf:.2f}"
                    ),
                    # Extra keys (ignored by core scoring, consumed downstream
                    # by main.py feature_snapshot + /explain handler):
                    'probs_calibrated':  _probs_cal,
                    'probs_raw':         _p.get('probs_raw'),
                    'ci_low':            ci_low,
                    'ci_high':           ci_high,
                    'prediction_set':    pred_set,
                    'shap_top':          _p.get('shap', []),
                    'text_explanation':  _p.get('text_explanation', ''),
                    '_raw_features_array': feat_row.values,  # Pass down for Meta-Labeler
                }
            else:
                # Fallback to legacy predictor if Ultra surface unavailable
                from ml_engine_archive.predictor import predict_signal as _ml_predict
                _legacy = _ml_predict(df, pair=pair or 'UNKNOWN')
                if _legacy and _legacy.get('signal') and _legacy['signal'] != 'NEUTRAL':
                    ml_sig = _legacy['signal']; ml_conf = float(_legacy.get('confidence', 0.0))
                    ml_aligned = (ml_sig == 'LONG' and is_long) or (ml_sig == 'SHORT' and not is_long)
                    if ml_aligned:
                        if   ml_conf >= 0.55: ml_score = 8
                        elif ml_conf >= 0.45: ml_score = 5
                        elif ml_conf >= 0.35: ml_score = 2
                    else:
                        if   ml_conf >= 0.55: ml_score = -5
                        elif ml_conf >= 0.45: ml_score = -3
                        else:                 ml_score = -1
                    factors['ml_ensemble'] = {
                        'score': ml_score, 'max': 8,
                        'value': f"LEGACY:{ml_sig}@{ml_conf:.2f}",
                    }
                else:
                    factors['ml_ensemble'] = {'score': 0, 'max': 8, 'value': 'NEUTRAL_OR_NA'}
        except Exception as _mle:
            factors['ml_ensemble'] = {'score': 0, 'max': 8, 'value': f'ERR:{type(_mle).__name__}'}

        # ══════════════════════════════════════════════════════════════
        # Factor 12: SMC Market Structure — CHoCH / BOS (−4 to +8 pts)
        # CHoCH aligned = trend reversal confirmation (highest value).
        # BOS aligned   = continuation confirmation.
        # Opposing structure = penalty. Decays with bars_ago.
        # ══════════════════════════════════════════════════════════════
        smc_score = 0
        try:
            smc = detect_market_structure(df)
            smc_type = smc.get('type')
            smc_dir  = smc.get('direction')
            smc_bars = smc.get('bars_ago')
            if smc_type and smc_dir and smc_bars is not None:
                aligned = (smc_dir == 'BULL' and is_long) or (smc_dir == 'BEAR' and not is_long)
                # Decay: fresh event (< 5 bars) = full, 5-20 = half, 20-50 = quarter
                decay = 1.0 if smc_bars < 5 else 0.5 if smc_bars < 20 else 0.25 if smc_bars < 50 else 0.0
                if aligned:
                    base = 8 if smc_type == 'CHoCH' else 5
                    smc_score = int(base * decay)
                    if smc_score >= 4:
                        flags.append(f'SMC_{smc_type}:{smc_dir}({smc_bars}bars)')
                else:
                    base = -4 if smc_type == 'CHoCH' else -2
                    smc_score = int(base * min(decay + 0.25, 1.0))  # penalty decays slower
                    flags.append(f'SMC_AGAINST:{smc_type}:{smc_dir}')
            factors['smc_structure'] = {
                'score': smc_score, 'max': 8,
                'value': f"{smc_type or 'NONE'}:{smc_dir or '-'}@{smc_bars}bars"
            }
        except Exception:
            factors['smc_structure'] = {'score': 0, 'max': 8, 'value': None}

        # ══════════════════════════════════════════════════════════════
        # Factor 14: Money Flow Index — MFI (−5 to +7 pts)
        # MFI = volume-weighted RSI. Extreme zones confirm or oppose direction.
        # Aligned extreme (oversold for LONG, overbought for SHORT) → +7
        # Aligned approaching extreme (30/70) → +3
        # Opposing extreme (overbought LONG, oversold SHORT) → −5
        # ══════════════════════════════════════════════════════════════
        mfi_score = 0
        try:
            mfi_col = next((c for c in ('MFI', 'MFI_14') if c in df.columns), None)
            if mfi_col:
                mfi_val = float(df[mfi_col].iloc[-1])
                if not __import__('math').isnan(mfi_val):
                    if is_long:
                        if mfi_val <= 20:
                            mfi_score = 7    # deeply oversold — spring loaded
                        elif mfi_val <= 30:
                            mfi_score = 3    # approaching oversold
                        elif mfi_val >= 80:
                            mfi_score = -5   # overbought buying = chasing
                            flags.append(f'MFI_OB_LONG:{mfi_val:.0f}')
                    else:
                        if mfi_val >= 80:
                            mfi_score = 7    # deeply overbought — exhaustion
                        elif mfi_val >= 70:
                            mfi_score = 3    # approaching overbought
                        elif mfi_val <= 20:
                            mfi_score = -5   # oversold shorting = chasing
                            flags.append(f'MFI_OS_SHORT:{mfi_val:.0f}')
                    factors['mfi'] = {'score': mfi_score, 'max': 7, 'value': round(mfi_val, 1)}
                else:
                    factors['mfi'] = {'score': 0, 'max': 7, 'value': None}
            else:
                factors['mfi'] = {'score': 0, 'max': 7, 'value': None}
        except Exception:
            factors['mfi'] = {'score': 0, 'max': 7, 'value': None}

        # ══════════════════════════════════════════════════════════════
        # Factor 15: CVD Order Flow (−6 to +8 pts)
        # Real-time Cumulative Volume Delta from aggTrade stream.
        # CVD 5m aligned with direction = confirmation (+8 strong, +4 moderate)
        # CVD 5m opposing direction = penalty  (−6 strong, −3 moderate)
        # Falls back to 0 if no live CVD data available.
        # ══════════════════════════════════════════════════════════════
        cvd_score = 0
        try:
            if cvd_data and isinstance(cvd_data, dict):
                dp5 = float(cvd_data.get('delta_pct_5m', 0.0))   # −1.0 to +1.0
                dp1 = float(cvd_data.get('delta_pct_1m', 0.0))
                # Weight: 70% 5m, 30% 1m — 1m more reactive but noisier
                dp  = dp5 * 0.70 + dp1 * 0.30
                trades = int(cvd_data.get('trades_5m', 0))
                if trades >= 10:                                   # need minimum activity
                    favourable = (dp > 0 and is_long) or (dp < 0 and not is_long)
                    magnitude  = abs(dp)
                    if favourable:
                        if   magnitude >= 0.20: cvd_score = 8
                        elif magnitude >= 0.10: cvd_score = 5
                        elif magnitude >= 0.05: cvd_score = 2
                    else:
                        if   magnitude >= 0.20:
                            cvd_score = -6
                            flags.append(f'CVD_OPPOSE:{dp:+.3f}')
                        elif magnitude >= 0.10:
                            cvd_score = -3
                            flags.append(f'CVD_WEAK_OPPOSE:{dp:+.3f}')
                    if favourable and magnitude >= 0.15:
                        flags.append(f'CVD_CONFIRM:{dp:+.3f}')
                factors['cvd'] = {
                    'score': cvd_score, 'max': 8,
                    'value': f"dp5={dp5:+.3f} dp1={dp1:+.3f} trades={trades}"
                }
            else:
                factors['cvd'] = {'score': 0, 'max': 8, 'value': 'NO_DATA'}
        except Exception:
            factors['cvd'] = {'score': 0, 'max': 8, 'value': None}

        # ══════════════════════════════════════════════════════════════
        # Composite SQI v6  (max: 30+15+15+10+20+5+8+8+8+7+8 = 134)
        # Dropped Factors 2, 5, 8, 10, 13 (Volume, ATR regime, Candlestick,
        # RSI divergence, Wyckoff). ML ensemble (Factor 11) already sees the
        # underlying features — no longer double-counted in SQI.
        # ══════════════════════════════════════════════════════════════
        sqi = (rr_score + ce_score + ext_score + mom_score + pos_score
               + hunt_bonus + beast_score + ml_score + smc_score
               + mfi_score + cvd_score)

        # Grade (calibrated for 0-134 SQI v6 range)
        # S=80% → 107 | A=64% → 86 | B=48% → 64 | C=32% → 43
        if sqi >= 107:
            grade = 'S'
        elif sqi >= 86:
            grade = 'A'
        elif sqi >= 64:
            grade = 'B'
        elif sqi >= 43:
            grade = 'C'
        else:
            grade = 'D'

        return {
            'sqi': sqi,
            'grade': grade,
            'factors': factors,
            'flags': flags,
        }

    except Exception as e:
        log_message(f"SQI calculation error: {e}")
        return {
            'sqi': 50,
            'grade': 'C',
            'factors': {},
            'flags': ['CALC_ERROR'],
        }


def sqi_to_leverage(sqi, base_leverage):
    """
    Map SQI to leverage adjustment.

    SQI v6 → Leverage multiplier (0-134 scale):
      107+  (S) → 1.0× (full leverage)
       86–106 (A) → 0.8×
       64–85  (B) → 0.6×
       43–63  (C) → 0.4×
        0–42  (D) → 0.25× (minimum)
    """
    if sqi >= 107:
        mult = 1.0
    elif sqi >= 86:
        mult = 0.8
    elif sqi >= 64:
        mult = 0.6
    elif sqi >= 43:
        mult = 0.4
    else:
        mult = 0.25

    return max(2, int(base_leverage * mult))


def sqi_to_size(sqi, base_size):
    """
    Map SQI to position size adjustment.

    SQI v6 → Size multiplier (0-134 scale):
      107+  (S) → 100% of base
       86–106 (A) → 80%
       64–85  (B) → 60%
       43–63  (C) → 40%
        0–42  (D) → 25%
    """
    if sqi >= 107:
        mult = 1.0
    elif sqi >= 86:
        mult = 0.8
    elif sqi >= 64:
        mult = 0.6
    elif sqi >= 43:
        mult = 0.4
    else:
        mult = 0.25

    return max(1, int(base_size * mult))
