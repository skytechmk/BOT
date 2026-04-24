# Proposal: Extreme Mode Volume Gate & MTF Trend Veto

## Introduction
Following the integration of "Extreme Mode" to catch V-Bottom capitulation reversals, we need to protect against fakeouts. Low-liquidity "scam wicks" can trigger the Chandelier Exit (CE) while the TSI is at the floor, generating a false Extreme Mode signal. 

## Proposed Changes

### 1. Volume Gate for Extreme Mode
**File:** `reverse_hunt.py`

**Description:** Modifies the Extreme Mode block to ensure the signal only fires if the current candle's volume is significantly higher than average (e.g., > 150% or 200% of the 20-period Simple Moving Average of volume).

```diff
-        if ce_flipped and zone_now in ('OS_L2',) and ce_dir_now == 1:
+        # Calculate volume surge: current volume vs 20-period SMA of volume
+        vol_now = df['volume'].iloc[-1]
+        vol_sma_20 = df['volume'].rolling(20).mean().iloc[-1]
+        is_vol_surge = vol_now > (1.5 * vol_sma_20) if not pd.isna(vol_sma_20) else False
+
+        if ce_flipped and zone_now in ('OS_L2',) and ce_dir_now == 1 and is_vol_surge:
             # Extreme oversold + CE flipped LONG = capitulation reversal
             signal = 'LONG'
             signal_bar = bar_idx
             zone_used = zone_now
             state['tsi_zone'] = zone_used
             from utils_logger import log_message
-            log_message(f"⚡ EXTREME MODE [{pair}]: TSI still in {zone_now}, CE flipped LONG — capitulation reversal")
+            log_message(f"⚡ EXTREME MODE [{pair}]: {zone_now} + CE LONG + Vol Surge ({vol_now/vol_sma_20:.1f}x) — capitulation reversal")
 
-        elif ce_flipped and zone_now in ('OB_L2',) and ce_dir_now == -1:
+        elif ce_flipped and zone_now in ('OB_L2',) and ce_dir_now == -1 and is_vol_surge:
             # Extreme overbought + CE flipped SHORT = blow-off top reversal
             signal = 'SHORT'
             signal_bar = bar_idx
             zone_used = zone_now
             state['tsi_zone'] = zone_used
             from utils_logger import log_message
-            log_message(f"⚡ EXTREME MODE [{pair}]: TSI still in {zone_now}, CE flipped SHORT — blow-off top reversal")
+            log_message(f"⚡ EXTREME MODE [{pair}]: {zone_now} + CE SHORT + Vol Surge ({vol_now/vol_sma_20:.1f}x) — blow-off top reversal")
```

### 2. De-obfuscate Internal Zone Naming
**File:** `reverse_hunt.py`

**Description:** Renames the confusing `OS_L2` (which actually means explosive bullish trend pump) to `TREND_PUMP_L2` internally, to prevent future developer misinterpretation. (This is a low-priority cosmetic cleanup that can be bundled in).

## Risk Assessment
**Low Risk.** This strictly *reduces* the number of trades the bot will take by filtering out low-volume noise. It ensures that Extreme Mode only acts on true whale-driven capitulation events. The downstream filters (Monte Carlo EV) act as a secondary safety net.

## Next Steps
Review the diff above. If approved, I will deploy the `multi_replace_file_content` script to patch `reverse_hunt.py` while the bot continues to run.
