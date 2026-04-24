# Proposal: Critical Codebase Audit Fixes

**Date**: 2026-04-07  
**Priority**: CRITICAL  
**Auditor**: S.P.E.C.T.R.E. Deep Audit  

---

## Changes Required (main.py)

### Fix 1: `current_risk_level` AttributeError (L203-208)

**Before**:
```python
        risk_level = MACRO_RISK_ENGINE.current_risk_level
        if not MACRO_RISK_ENGINE.should_allow_trading()[0]: return
        _allow_trade, _reason = MACRO_RISK_ENGINE.should_allow_trading()
        if not _allow_trade:
            log_message(f"⚪ No Trade: {pair} — Macro Risk Engine blocked: {_reason}")
            return
```

**After**:
```python
        risk_level = MACRO_RISK_ENGINE.state
        _allow_trade, _reason = MACRO_RISK_ENGINE.should_allow_trading()
        if not _allow_trade:
            log_message(f"⚪ No Trade: {pair} — Macro Risk Engine blocked: {_reason}")
            return
```

**Reasoning**: `MacroRiskEngine` has no `current_risk_level` property. This throws `AttributeError` caught by the outer try/except, silently skipping ALL pairs.

---

### Fix 2: Restore `base_size` Ternary (L437)

**Before**:
```python
        base_size = 25         # 4. Final Risk-Adjusted Leverage (Dynamic Scaling)
```

**After**:
```python
        # Position sizing by conviction tier
        base_size = 25 if adj_confidence < 0.6 else 50 if adj_confidence < 0.8 else 100
```

**Reasoning**: The ternary was accidentally destroyed during the leverage refactor. All signals use base_size=25 regardless of confidence.

---

### Fix 3: Remove Duplicate BTC Filter (L412-419)

**Delete these lines**:
```python
        # BTC HTF Trend Filter: reject counter-trend signals (proposal risk-tightening)
        btc_regime = get_btc_htf_regime(client)
        if btc_regime == 'bullish' and final_signal.upper() == 'SHORT':
            log_message(f"🚫 Signal Rejected for {pair}: SHORT blocked — BTC 1h regime is BULLISH")
            return
        if btc_regime == 'bearish' and final_signal.upper() == 'LONG':
            log_message(f"🚫 Signal Rejected for {pair}: LONG blocked — BTC 1h regime is BEARISH")
            return
```

**Reasoning**: Lines 245-251 already do this exact filter. This is a duplicate from the proposal merge.

---

### Fix 4: Remove Duplicate Feature Snapshot (L447-457)

**Delete these lines**:
```python
        # 5. Capture Institutional Feature Snapshot (Persistence Fix)
        feature_snapshot = df.iloc[-1].to_dict()
        def is_keepable(v):
            """Institutional filter for persistent technical context"""
            if isinstance(v, (int, float, bool, str)):
                return len(str(v)) < 100
            if isinstance(v, (np.integer, np.floating)):
                return True # numpy scalars are compact
            return False

        feature_snapshot = {k: v for k, v in feature_snapshot.items() if is_keepable(v)}
```

**Reasoning**: Lines 545-550 already do this (and do it better — they convert numpy to native Python first). The block at L447 is dead code that gets overwritten.

---

### Fix 5: Remove Duplicate Comment (L619)

**Delete**:
```python
    # ── WebSocket kline stream for top-20 pairs ──────────────────────────
```

**Keep**:
```python
    # ── WebSocket kline stream for top-50 pairs ──────────────────────────
```

---

## Changes Required (signal_generator.py)

### Fix 6: Signal Case Normalization

**Lines 578, 599**: Change `'Neutral'` → `'NEUTRAL'`

```diff
-                            df.loc[df.index[-1], 'Signal'] = 'Neutral'
+                            df.loc[df.index[-1], 'Signal'] = 'NEUTRAL'
```

---

## Changes Required (news_monitor.py)

### Fix 7: Telegram Parse Mode Safety

Change Markdown formatting to HTML to prevent RSS content from breaking the parser.

---

## Risk Assessment

All changes are localized to filtering and formatting logic. No changes to indicator calculation, ML models, or Telegram message content. Rollback is trivial — revert the 5 line changes in main.py.

## Expected Impact

- **BUG-4 fix**: Pairs will actually be processed instead of silently skipped
- **BUG-2 fix**: High-confidence signals get proper position sizing (50-100%)
- **BUG-3 fix**: ~150 fewer API calls per cycle
- **Signal normalization**: Consistent case prevents filter bypass
