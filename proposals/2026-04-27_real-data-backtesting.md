---
description: Real-data back-testing & landing-page KPI revamp
---

## Problem
Current back-testing screen shows hard-coded examples / mock equity curves.  Landing-page KPI cards (total PnL, win-rate, signals fired) are also fed by fixed JS constants that drift out of sync with the real trading database.

## Goal
1. 100 % database-driven back-testing using only **real closed signals**.
2. Configurable parameters (period, starting capital, position size %).
3. JSON API → front-end renders equity curve, draw-down, CAGR, daily PnL heatmap.
4. Landing page KPI cards (<hero stats>) pull live numbers from the same API – no manual updates.

## Scope of work
- **analytics.py**  
  • new `run_backtest(days:int=365, starting_capital:float=1000, position_pct:float=1.0)` → returns dict with equity curve list, CAGR, max-dd, total_return, win_rate, trade_count.  
  • helper `get_live_kpis()` → { total_signals, signals_last_30d, open_signals, win_rate, total_pnl, avg_pnl }.

- **dashboard/app.py**  
  • `@app.get("/api/backtest")` (query params: days, capital, pos_pct)  
  • `@app.get("/api/kpis")` → wraps `get_live_kpis()`.

- **Front-end**  
  • `static/js/index.js` fetch `/api/kpis` on load and fills the KPI cards.  
  • New Back-test page/component: form → calls `/api/backtest` → renders equity curve (Chart.js), summary table.

## Non-Goals
- No synthetic candle replay; back-test is trade-level, not bar-level.
- Not adding parameterised strategy simulation – strictly historical realised outcomes.

## Risks & Mitigations
- Large JSON (equity curve) → limit length (max 2 000 points) or allow client to request `granularity=daily`.
- API flood → add simple in-memory 5-second cache per param combo.

## Roll-out
1. Implement and unit-test analytics additions. 2. Add API endpoints. 3. Front-end wiring (lazy-load the heavy Chart.js bundle only on back-test page). 4. Replace placeholder KPI spans on landing page with live fetch. 5. QA on staging.

---
**Est. effort**: 1–1.5 dev-days.
