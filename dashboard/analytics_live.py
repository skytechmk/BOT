"""Live analytics helpers: run_backtest and get_live_kpis
Uses only real data from signal_registry.db (no mock figures).
"""
from __future__ import annotations
import sqlite3, time, math, statistics
from pathlib import Path
from typing import List, Dict

_DB = Path(__file__).resolve().parent.parent / "signal_registry.db"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _query(sql: str, params: tuple = ()) -> List[sqlite3.Row]:
    conn = sqlite3.connect(f"file:{_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    rows = cur.execute(sql, params).fetchall()
    conn.close()
    return rows


def get_live_kpis(days: int = 30) -> Dict:
    """Return quick KPI snapshot for landing page."""
    now = time.time()
    total = _query("SELECT COUNT(*) AS c FROM signals")[0]["c"]
    open_cnt = _query(
        "SELECT COUNT(*) AS c FROM signals WHERE upper(status) IN "
        "('SENT','OPEN','ACTIVE','TP1_HIT','TP2_HIT')",
    )[0]["c"]
    closed_cnt = total - open_cnt
    last30 = _query("SELECT COUNT(*) AS c FROM signals WHERE timestamp>?", (now - 30 * 86400,))[0]["c"]
    closed_rows = _query(
        "SELECT pnl FROM signals WHERE pnl IS NOT NULL AND upper(status) IN "
        "('CLOSED','LOSS','WIN','TP1_HIT','TP2_HIT','TP3_HIT','SL_HIT','CANCELLED')"
    )
    win_rows = [r for r in closed_rows if r["pnl"] > 0]
    win_rate = round(len(win_rows) / closed_cnt * 100, 2) if closed_cnt else 0
    total_pnl = round(sum(r["pnl"] for r in closed_rows), 2) if closed_rows else 0
    avg_pnl = round(statistics.mean([r["pnl"] for r in closed_rows]), 2) if closed_rows else 0
    return {
        "total_signals": total,
        "open_signals": open_cnt,
        "closed_signals": closed_cnt,
        "signals_last_30d": last30,
        "win_rate": win_rate,
        "total_pnl": total_pnl,
        "avg_pnl": avg_pnl,
    }


def run_backtest(days: int = 365, *, starting_capital: float = 1000.0, position_pct: float = 1.0) -> Dict:
    """Simple equity-curve back-test using realised trade outcomes.

    position_pct is % of equity risked per trade (leveraged PnL already stored).
    """
    now = time.time()
    cutoff = now - days * 86400
    rows = _query(
        "SELECT pnl, timestamp FROM signals WHERE timestamp>? AND pnl IS NOT NULL "
        "AND upper(status) IN ('CLOSED','LOSS','WIN','TP1_HIT','TP2_HIT','TP3_HIT','SL_HIT','CANCELLED') "
        "ORDER BY timestamp ASC",
        (cutoff,),
    )
    if not rows:
        return {"error": "no_data", "days": days}

    equity = starting_capital
    peak = equity
    max_dd = 0.0
    curve: List[Dict] = []

    for r in rows:
        ts = r["timestamp"]
        pnl_pct = r["pnl"]  # already leveraged
        impact = equity * (position_pct / 100.0) * (pnl_pct / 100.0)
        equity += impact
        curve.append({"timestamp": ts, "equity": round(equity, 2)})
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak * 100
        max_dd = max(max_dd, dd)

    total_return = (equity / starting_capital - 1.0) * 100.0
    yrs = days / 365.0
    cagr = ((equity / starting_capital) ** (1 / yrs) - 1) * 100 if yrs > 0 else 0

    win_trades = [r for r in rows if r["pnl"] > 0]
    win_rate = round(len(win_trades) / len(rows) * 100, 2)

    # optional down-sampling to <= 2000 pts
    if len(curve) > 2000:
        step = math.ceil(len(curve) / 2000)
        curve = curve[::step]

    return {
        "days": days,
        "trade_count": len(rows),
        "win_rate": win_rate,
        "total_return_pct": round(total_return, 2),
        "cagr_pct": round(cagr, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "equity_curve": curve,
    }
