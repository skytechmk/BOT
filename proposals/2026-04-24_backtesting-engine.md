# Proposal: Backtesting System Architecture

## Context & Problem
Currently, performance tracking happens entirely implicitly via `performance_tracker.py` iterating forward over live signals. Professional-grade platforms require the ability to run historical data backward to validate strategy changes (e.g., changes to XGBoost hyperparameters, MACD weights, or grid structures) before pushing to live money parameters.

## Proposed Architecture: Dedicated Backtest API & Sandbox

We will construct a new internal toolkit allowing users to sweep historical SQLite / TimescaleDB databases against the active `signal_generator.py` algorithm.

### 1. Backend: Historical Sweep Microservice
Extract historical klines from `ohlcv_cache.db` or fetch direct from Binance `klines` API for a specified range (e.g., 2024-01-01 to 2024-06-01).

```python
# new endpoint in dashboard/app.py
@app.post("/api/backtest/run")
async def run_backtest(params: dict):
    # 1. Fetch historical OHLCV data
    # 2. Invoke signal_generator.py sequentially over chunks
    # 3. Simulate TP/SL trailing via trailing_engine.py logic
    # 4. Return PnL, Win-Rate, Maximum Drawdown
    pass
```

### 2. Frontend: Strategy Builder UI
Introduce a new view `dashboard/static/js/backtest.js` mapped to a `<div id="backtest-container">`.

- **Control Panel**: Select Timeframe (15m, 1h, 4h), Asset Pair, Leverage, and Date Range.
- **Results Canvas**: Utilize existing `lightweight-charts.standalone.production.js` (currently used for screener overlays) to plot the PnL equity curve linearly.
- **Metrics Dashboard**: Display key institutional metrics:
    - Net PnL %
    - Win / Loss Ratio
    - Maximum Drawdown (MDD)
    - Sharpe Ratio Estimate

## Risk Assessment
**Zero Risk to Production**: The backtesting engine is entirely isolated. It uses read-only access to historical data and executes on simulated accounts without linking to live Binance copy-trading credentials.
