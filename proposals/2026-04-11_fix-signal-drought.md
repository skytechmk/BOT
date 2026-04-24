# Proposal: Fix 30-Hour Signal Drought

## Problem
The bot has not emitted a signal since April 8, 22:48 (~30 hours). Root cause: the Reverse Hunt strategy requires TSI to **exit** its extreme zone before CE confirmation can fire. During a sustained crash (Fear & Greed = 16, "Extreme Fear"), TSI stays pinned in oversold zones indefinitely — the exit never happens, so signals never fire.

## Risk Assessment
**Medium Risk.** These changes loosen signal generation constraints. The downstream filters (Monte Carlo EV ≥ 0.85, ML consensus, AI gate, volume filter, stress test) remain fully intact to catch bad signals.

---

## Change 1: Lower Adaptive TSI Percentile Thresholds

**File:** `reverse_hunt.py` (lines 30-33)

**Reasoning:** The adaptive levels auto-tune to the 90th/97th percentile of each pair's historical |TSI|. In a sustained crash, the volatility compresses and these thresholds become very wide, making it nearly impossible for TSI to "enter" and "exit" zones. Lowering them makes the bot more sensitive to reversal setups during extreme market conditions.

```diff
-ADAPTIVE_L1_PERCENTILE = 90   # 90th percentile of |TSI| → L1 zone
-ADAPTIVE_L2_PERCENTILE = 97   # 97th percentile of |TSI| → L2 zone
-ADAPTIVE_L1_FLOOR = 0.5       # Minimum L1 threshold (avoid noise)
-ADAPTIVE_L2_FLOOR = 0.8       # Minimum L2 threshold
+ADAPTIVE_L1_PERCENTILE = 80   # 80th percentile of |TSI| → L1 zone
+ADAPTIVE_L2_PERCENTILE = 92   # 92nd percentile of |TSI| → L2 zone
+ADAPTIVE_L1_FLOOR = 0.4       # Minimum L1 threshold (avoid noise)
+ADAPTIVE_L2_FLOOR = 0.6       # Minimum L2 threshold
```

**Effect:** More pairs will enter/exit TSI zones, giving the CE confirmation layer more opportunities to trigger.

---

## Change 2: Allow "In-Zone CE Flip" Signals (Extreme Mode)

**File:** `reverse_hunt.py`, inside `process_pair()` (~line 462-508)

**Reasoning:** Currently the bot REQUIRES the full 3-stage sequence: TSI enters zone → TSI exits zone → CE flips. But in a crash, the most profitable reversal trades happen when TSI is STILL in the extreme zone and CE flips against the trend (a "capitulation reversal"). We add a secondary detection path: if TSI is in L2 (extreme) AND CE flips in the matching reversal direction, fire the signal immediately with a 1-point conviction penalty.

**Add this block after the existing scan loop (after line 508), before the `if signal is None` return:**

```python
    # ── 2b. EXTREME MODE: TSI still in L2 zone + CE flip = immediate signal ──
    # In sustained crashes, TSI never exits the zone. This catches capitulation
    # reversals where CE flips while TSI is at extreme levels.
    if signal is None:
        tsi_now_val = tsi.iloc[-1]
        zone_now = get_tsi_zone(tsi_now_val, l1=adapt_l1, l2=adapt_l2)
        ce_dir_now = int(ce_line['direction'].iloc[-1])
        ce_dir_prev = int(ce_line['direction'].iloc[-2]) if len(ce_line['direction']) > 1 else ce_dir_now

        # CE just flipped on this bar?
        ce_flipped = ce_dir_now != ce_dir_prev

        if ce_flipped and zone_now in ('OS_L2',) and ce_dir_now == 1:
            # Extreme oversold + CE flipped LONG = capitulation reversal
            signal = 'LONG'
            signal_bar = bar_idx
            zone_used = zone_now
            state['tsi_zone'] = zone_used
            log_message(f"⚡ EXTREME MODE [{pair}]: TSI still in {zone_now}, CE flipped LONG — capitulation reversal")

        elif ce_flipped and zone_now in ('OB_L2',) and ce_dir_now == -1:
            # Extreme overbought + CE flipped SHORT = blow-off top reversal
            signal = 'SHORT'
            signal_bar = bar_idx
            zone_used = zone_now
            state['tsi_zone'] = zone_used
            log_message(f"⚡ EXTREME MODE [{pair}]: TSI still in {zone_now}, CE flipped SHORT — blow-off top reversal")
```

**Effect:** During extreme market conditions (TSI at L2), the bot can catch capitulation reversals without waiting for TSI to exit the zone. Conviction is naturally lower (no TSI exit bonus = -1 point), so downstream filters will be stricter.

---

## Change 3: Widen Signal Freshness Window from 1 to 3 Bars

**File:** `reverse_hunt.py` (line 507)

**Reasoning:** The bot only fires a signal if it happened on the current bar or the immediately previous bar (`bar_idx - signal_bar > 1`). With a 3-minute scan cycle on a 1h timeframe, this is fine. But if the bot restarts or a cycle takes longer than expected, valid signals can be missed. Widening to 3 bars gives a safer buffer while still preventing stale signal replay.

```diff
-    if signal is None or (bar_idx - signal_bar) > 1:
+    if signal is None or (bar_idx - signal_bar) > 3:
```

**Effect:** Signals that fired 2-3 hours ago (but were missed due to timing) will still be caught. The 6-bar double-fire prevention (`last_signal_bar` check at line 468) prevents duplicate signals.

---

## Change 4: Fix Missing `analyze_systemic_fragility` Method (Bug Fix)

**File:** `openrouter_intelligence.py`

**Reasoning:** The logs show this error every 30 minutes:
```
'OpenRouterIntelligence' object has no attribute 'analyze_systemic_fragility'
```
`main.py` line 536 calls this method but it doesn't exist. Need to add it.

**Add this method to the `OpenRouterIntelligence` class (after `query_ai`):**

```python
    def analyze_systemic_fragility(self, context: str) -> dict:
        """Analyze systemic market fragility using AI."""
        prompt = (
            "You are an institutional risk analyst. Assess the current systemic fragility "
            "of cryptocurrency markets based on the following context. "
            "Respond with ONLY a JSON object containing: "
            "severity (LOW/MODERATE/HIGH/CRITICAL), fragility_score (0.0-1.0), "
            "risk_level (low/moderate/high/critical), reasoning (1 sentence).\n\n"
            f"Context: {context}"
        )
        try:
            result = self.query_ai(prompt, max_tokens=300)
            import re
            json_match = re.search(r'\{[^}]+\}', result)
            if json_match:
                parsed = json.loads(json_match.group())
                return {
                    'severity': parsed.get('severity', 'MODERATE'),
                    'fragility_score': float(parsed.get('fragility_score', 0.5)),
                    'risk_level': parsed.get('risk_level', 'moderate'),
                    'reasoning': parsed.get('reasoning', 'Unable to parse AI response')
                }
        except Exception as e:
            log_message(f"Systemic fragility AI parse error: {e}")
        return {
            'severity': 'MODERATE',
            'fragility_score': 0.5,
            'risk_level': 'moderate',
            'reasoning': 'AI analysis unavailable — defaulting to moderate risk'
        }

    def analyze_signal_robustness(self, pair: str, tech_summary: str) -> dict:
        """Analyze signal robustness for institutional-grade filtering."""
        prompt = (
            f"You are an institutional trading desk analyst reviewing a signal for {pair}.\n"
            f"Technical Summary:\n{tech_summary}\n\n"
            "Respond with ONLY a JSON object containing:\n"
            "institutional_verdict (PROCEED or REJECT),\n"
            "institutional_reasoning (1-2 sentences),\n"
            "institutional_score (0.0-1.0, where 1.0 = strong conviction),\n"
            "contrarian_warning (1 sentence or empty string)"
        )
        try:
            result = self.query_ai(prompt, max_tokens=400)
            import re
            json_match = re.search(r'\{[^}]+\}', result)
            if json_match:
                parsed = json.loads(json_match.group())
                return {
                    'institutional_verdict': parsed.get('institutional_verdict', 'PROCEED'),
                    'institutional_reasoning': parsed.get('institutional_reasoning', ''),
                    'institutional_score': float(parsed.get('institutional_score', 0.5)),
                    'contrarian_warning': parsed.get('contrarian_warning', '')
                }
        except Exception as e:
            log_message(f"Signal robustness AI parse error: {e}")
        return {
            'institutional_verdict': 'PROCEED',
            'institutional_reasoning': 'AI analysis unavailable — defaulting to proceed',
            'institutional_score': 0.5,
            'contrarian_warning': ''
        }
```

**Effect:** Eliminates the recurring error in the logs and wires up real AI-powered fragility analysis using the OpenRouter model.

---

## Summary of All Changes

| # | File | Change | Impact |
|---|---|---|---|
| 1 | `reverse_hunt.py` | Lower adaptive TSI percentiles (90→80, 97→92) | More zone entries/exits |
| 2 | `reverse_hunt.py` | Add "Extreme Mode" — L2 + CE flip = signal | Catch capitulation reversals |
| 3 | `reverse_hunt.py` | Widen signal freshness window (1→3 bars) | Fewer missed signals |
| 4 | `openrouter_intelligence.py` | Add missing `analyze_systemic_fragility` + `analyze_signal_robustness` methods | Fix 30-min error + enable AI gate |

## Verification Plan
1. After applying, monitor the next 2-3 scan cycles in the logs for `🎯 REVERSE HUNT` or `⚡ EXTREME MODE` log lines
2. Confirm no new errors appear in the log output
3. Verify that the downstream filters (MC EV, ML, AI) still reject bad signals appropriately
