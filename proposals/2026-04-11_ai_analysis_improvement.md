# Proposal: AI Analysis — Smarter Usage

**Date**: 2026-04-11  
**Status**: PROPOSAL  
**Priority**: Low — enhancement, not fix

## Problem

The DeepSeek/OpenRouter AI gate was running on EVERY signal with confidence > 70%,
adding 2-5s latency per signal, rate-limit risk on free models, and non-deterministic
rejections. It was correctly disabled.

## Proposal: Use AI for POST-TRADE Analysis, Not Pre-Trade Gates

Instead of blocking signals in real-time, use AI for:

### 1. Daily Signal Review (async, non-blocking)
```
Every 24h → Collect all signals sent that day →
AI summarizes: "5 signals sent, 3 won, 2 lost.
Pattern: SHORT signals in ranging market had 0% win rate.
Suggestion: Tighten SHORT criteria when ADX < 20."
```
- Runs once per day, not per signal
- No latency impact on signal pipeline
- Sends summary to Ops Telegram channel
- Uses the stored features from `signal_registry.db`

### 2. Weekly Strategy Audit
```
Every Sunday → AI reviews last 7 days of signals →
Identifies: regime shifts, pair clusters that underperformed,
threshold suggestions (e.g., "L1 at 1.3 missed 4 good entries,
consider lowering to 1.1 for next week")
```

### 3. Emergency Regime Detection
```
When BTC drops > 5% in 1h → AI checks macro context →
"Flash crash detected. Binance had 3 liquidation cascades in
the last hour. Recommend pausing SHORT signals for 6h."
```
- Only triggers on extreme events (not every signal)
- Uses the existing `analyze_systemic_fragility()` function
- Rate limit risk is negligible (runs ~1-2 times per month)

### 4. Signal Narrative for Telegram
```
After signal is SENT → AI generates a 1-line explanation:
"LONG #SOL/USDT: TSI bounced from -2.3 OS_L2, CE flipped
bullish with 3.2x volume surge. VP POC at $148 is TP1 magnet."
```
- Non-blocking: appended as a reply to the signal message
- Adds context for human traders following the channel
- If AI fails/timeouts, signal was already sent — no impact

## Implementation

All 4 features use the EXISTING `OPENROUTER_INTEL` infrastructure
and 7-key pool. No new dependencies needed.

### File Changes
| File | Change |
|------|--------|
| `main.py` | Add daily/weekly review tasks to main loop |
| `openrouter_intelligence.py` | Add `review_daily_signals()` and `generate_signal_narrative()` |
| `telegram_handler.py` | Add `send_signal_narrative()` as reply to original message |

## Risk Assessment
- **Zero impact on signal pipeline** (all async, post-trade)
- **Rate limit risk: minimal** (1-2 AI calls per day, not per signal)
- **Failure mode: graceful** (if AI fails, signals still work)
