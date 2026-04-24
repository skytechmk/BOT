"""
backtest_engine.py — Historical-replay backtesting for Aladdin signals.
========================================================================

Phase 3 deliverable from proposals/2026-04-24_backtesting-engine.md.

MODEL: Historical replay (model B in design notes).

    Take every signal the live engine actually fired in `signal_registry.db`
    within the chosen window, walk the cached OHLCV forward bar-by-bar
    from entry, and determine the exit price using the caller's chosen
    TP/SL policy. Aggregate the trades into standard institutional
    performance metrics.

    We do NOT re-run `signal_generator.py` — that would require replaying
    live correlation + macro state which is not stored and does not
    reproduce deterministically.

STORAGE

    Runs and per-trade results live in a new `backtests.db` (separate
    from everything else — no risk of schema contention with live data).

    backtest_runs:
        id, user_id, params_json, status, created_at, finished_at,
        stats_json, error

    backtest_trades:
        run_id, signal_id, pair, direction, entry_price, exit_price,
        exit_reason, exit_ts, pnl_pct, pnl_usd, equity_after

PUBLIC API
    run_backtest(user_id, params) -> int (run_id)           # sync, returns immediately
    get_backtest(run_id)          -> Optional[dict]
    list_backtests(user_id)       -> list[dict]

PARAMS SHAPE
    {
      "start":           1711900000,      # epoch seconds (inclusive)
      "end":             1714579200,      # epoch seconds (inclusive)
      "pairs":           ["BTCUSDT", ...] # optional — None = all
      "initial_capital": 10000.0,          # USD
      "risk_pct":        2.0,              # % of equity per trade (position sizing)
      "leverage":        10,
      "fee_pct":         0.05,             # taker fee per side (Binance default)
      "sl_mode":         "strict",         # "strict" | "none" (future: "trailing")
      "tp_mode":         "first",          # "first" | "weighted" | "last"
      "max_hold_hours":  48                # force-close if no TP/SL hit in N hours
    }
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("anw.backtest")

_ROOT = Path(__file__).resolve().parent.parent
_BT_DB   = Path(__file__).parent / "backtests.db"
_SIG_DB  = _ROOT / "signal_registry.db"
_OHLCV   = _ROOT / "ohlcv_cache.db"


# ───────────────────────────────── schema ─────────────────────────────

def _bt_conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(_BT_DB), timeout=10, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL;")
    c.execute("PRAGMA synchronous=NORMAL;")
    return c


def _init_schema() -> None:
    c = _bt_conn()
    try:
        c.execute("""
            CREATE TABLE IF NOT EXISTS backtest_runs (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id      INTEGER NOT NULL,
                params_json  TEXT    NOT NULL,
                status       TEXT    NOT NULL DEFAULT 'pending',  -- pending|running|done|error
                created_at   REAL    NOT NULL,
                finished_at  REAL,
                stats_json   TEXT,
                error        TEXT
            );
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS backtest_trades (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id        INTEGER NOT NULL,
                signal_id     TEXT    NOT NULL,
                pair          TEXT    NOT NULL,
                direction     TEXT    NOT NULL,  -- LONG|SHORT
                entry_ts      REAL    NOT NULL,
                entry_price   REAL    NOT NULL,
                exit_ts       REAL    NOT NULL,
                exit_price    REAL    NOT NULL,
                exit_reason   TEXT    NOT NULL,  -- tp|sl|timeout
                pnl_pct       REAL    NOT NULL,  -- gross % move on entry, signed
                pnl_usd       REAL    NOT NULL,  -- net of fees + leverage
                equity_after  REAL    NOT NULL,
                FOREIGN KEY (run_id) REFERENCES backtest_runs(id) ON DELETE CASCADE
            );
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_bt_runs_user    ON backtest_runs(user_id);")
        c.execute("CREATE INDEX IF NOT EXISTS idx_bt_trades_run   ON backtest_trades(run_id);")
    finally:
        c.close()


_init_schema()


# ───────────────────────────── data loaders ───────────────────────────

def _load_signals(start_ts: float, end_ts: float,
                  pairs: Optional[List[str]]) -> List[sqlite3.Row]:
    """All signals fired in [start_ts, end_ts]. Optionally filtered by pair."""
    c = sqlite3.connect(str(_SIG_DB), timeout=5)
    c.row_factory = sqlite3.Row
    try:
        if pairs:
            placeholders = ",".join("?" * len(pairs))
            q = (f"SELECT * FROM signals WHERE timestamp >= ? AND timestamp <= ? "
                 f"AND pair IN ({placeholders}) ORDER BY timestamp ASC")
            return c.execute(q, [start_ts, end_ts, *pairs]).fetchall()
        return c.execute(
            "SELECT * FROM signals WHERE timestamp >= ? AND timestamp <= ? "
            "ORDER BY timestamp ASC",
            (start_ts, end_ts)
        ).fetchall()
    finally:
        c.close()


def _load_ohlcv_forward(pair: str, from_ts: float,
                        horizon_hours: int = 48,
                        prefer_tfs: Tuple[str, ...] = ("15m", "1h", "5m")
                        ) -> List[Tuple[float, float, float, float, float]]:
    """Return a list of (ts, open, high, low, close) bars starting at the
    first bar with timestamp >= from_ts, up to `horizon_hours` later.
    Probes timeframe tables in preference order; uses whichever has data.
    """
    end_ts = from_ts + horizon_hours * 3600
    c = sqlite3.connect(str(_OHLCV), timeout=5)
    try:
        for tf in prefer_tfs:
            table = f'"{pair}_{tf}"'
            try:
                rows = c.execute(
                    f"SELECT timestamp, open, high, low, close FROM {table} "
                    f"WHERE timestamp >= ? AND timestamp <= ? "
                    f"ORDER BY timestamp ASC",
                    (int(from_ts * 1000), int(end_ts * 1000))
                ).fetchall()
                if rows:
                    # ohlcv_cache stores ms timestamps; normalise to seconds for caller.
                    return [(r[0] / 1000.0, r[1], r[2], r[3], r[4]) for r in rows]
            except sqlite3.OperationalError:
                continue
        return []
    finally:
        c.close()


# ─────────────────────── per-trade simulation ─────────────────────────

def _pick_tp(targets: List[float], entry: float, direction: str,
             tp_mode: str) -> Optional[float]:
    """Select the take-profit price we're aiming for given the user's
    TP mode. Returns None if no valid targets.

    * "first"  — use the nearest TP
    * "last"   — use the farthest TP
    * "weighted"— midpoint of nearest + farthest (rough proxy for partials)
    """
    if not targets:
        return None
    # Sort by distance from entry in the trade direction.
    if direction == "LONG":
        ts = sorted([t for t in targets if t > entry])
    else:
        ts = sorted([t for t in targets if t < entry], reverse=True)
    if not ts:
        return None
    if tp_mode == "first":   return ts[0]
    if tp_mode == "last":    return ts[-1]
    if tp_mode == "weighted":return (ts[0] + ts[-1]) / 2.0
    return ts[0]


def _simulate(sig: sqlite3.Row, cfg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Replay a single signal bar-by-bar and return a trade dict (or None
    if we have insufficient data to simulate)."""
    try:
        pair      = sig["pair"]
        direction = sig["signal"].upper()
        if direction not in ("LONG", "SHORT"):
            return None
        entry     = float(sig["price"] or 0)
        if entry <= 0:
            return None
        sl        = float(sig["stop_loss"] or 0) if cfg["sl_mode"] == "strict" else 0.0
        targets   = []
        try:
            targets = [float(x) for x in json.loads(sig["targets_json"] or "[]") if x]
        except Exception:
            targets = []
        tp = _pick_tp(targets, entry, direction, cfg["tp_mode"])
        entry_ts = float(sig["timestamp"])
        bars = _load_ohlcv_forward(pair, entry_ts, horizon_hours=cfg["max_hold_hours"])
        if not bars:
            return None

        exit_price = None
        exit_reason = None
        exit_ts = None
        # Walk bars from the first one AFTER entry (avoid entry-bar peek).
        for ts, _o, hi, lo, _c in bars:
            if ts <= entry_ts:
                continue
            if direction == "LONG":
                # SL hits before TP if both would be touched in the same bar
                # (conservative intrabar assumption favouring losers — the
                # institutional default, never the bookmaker default).
                if sl and lo <= sl:
                    exit_price, exit_reason, exit_ts = sl, "sl", ts; break
                if tp and hi >= tp:
                    exit_price, exit_reason, exit_ts = tp, "tp", ts; break
            else:  # SHORT
                if sl and hi >= sl:
                    exit_price, exit_reason, exit_ts = sl, "sl", ts; break
                if tp and lo <= tp:
                    exit_price, exit_reason, exit_ts = tp, "tp", ts; break
        if exit_price is None:
            # Timed out — close at final bar's close price.
            last_ts, _, _, _, last_close = bars[-1]
            exit_price, exit_reason, exit_ts = last_close, "timeout", last_ts

        # PnL mechanics
        raw_pct = (exit_price - entry) / entry * 100.0
        if direction == "SHORT":
            raw_pct = -raw_pct
        lev = max(1, int(cfg["leverage"]))
        fee_total_pct = float(cfg["fee_pct"]) * 2.0  # open + close
        net_pct_on_notional = raw_pct - fee_total_pct
        # Position-sizing: risk_pct of equity at the time of the trade.
        # (The caller passes `equity_before` in cfg at iteration time.)
        equity_before = cfg["__equity"]
        size_usd = equity_before * (float(cfg["risk_pct"]) / 100.0) * lev
        pnl_usd  = size_usd * (net_pct_on_notional / 100.0)
        return {
            "signal_id":   sig["signal_id"],
            "pair":        pair,
            "direction":   direction,
            "entry_ts":    entry_ts,
            "entry_price": entry,
            "exit_ts":     exit_ts,
            "exit_price":  exit_price,
            "exit_reason": exit_reason,
            "pnl_pct":     round(raw_pct, 4),
            "pnl_usd":     round(pnl_usd, 4),
        }
    except Exception as e:
        log.debug(f"[backtest] simulate failed for {sig['signal_id']}: {e!r}")
        return None


# ─────────────────────────── aggregation ──────────────────────────────

def _aggregate(trades: List[Dict[str, Any]], initial: float) -> Dict[str, Any]:
    """Compute institutional-grade stats from the trade list."""
    if not trades:
        return {
            "trades": 0, "wins": 0, "losses": 0,
            "win_rate": 0.0, "profit_factor": 0.0, "net_pnl_usd": 0.0,
            "net_pnl_pct": 0.0, "max_drawdown_pct": 0.0,
            "sharpe": 0.0, "sortino": 0.0, "final_equity": initial,
            "best_trade_usd": 0.0, "worst_trade_usd": 0.0,
            "avg_win_usd": 0.0, "avg_loss_usd": 0.0,
        }
    wins = [t for t in trades if t["pnl_usd"] > 0]
    losses = [t for t in trades if t["pnl_usd"] <= 0]
    gross_win = sum(t["pnl_usd"] for t in wins)
    gross_loss = abs(sum(t["pnl_usd"] for t in losses)) or 1e-9
    equity = initial
    peak = initial
    max_dd = 0.0
    rets: List[float] = []   # per-trade return on equity (%)
    for t in trades:
        equity += t["pnl_usd"]
        t["equity_after"] = round(equity, 4)
        rets.append(t["pnl_usd"] / max(initial, 1e-9) * 100.0)
        if equity > peak: peak = equity
        dd = (peak - equity) / peak * 100.0 if peak > 0 else 0.0
        if dd > max_dd: max_dd = dd

    # Sharpe / Sortino (treating each trade as a sample; no risk-free
    # assumption — returns are already net of fees).
    import statistics as _stats
    mean = _stats.mean(rets)
    stdev = _stats.pstdev(rets) or 1e-9
    downside = [r for r in rets if r < 0]
    dstdev = _stats.pstdev(downside) or 1e-9 if downside else 1e-9
    sharpe  = mean / stdev
    sortino = mean / dstdev if downside else 0.0

    return {
        "trades":          len(trades),
        "wins":            len(wins),
        "losses":          len(losses),
        "win_rate":        round(100.0 * len(wins) / len(trades), 2),
        "profit_factor":   round(gross_win / gross_loss, 3),
        "net_pnl_usd":     round(equity - initial, 2),
        "net_pnl_pct":     round((equity - initial) / initial * 100.0, 2),
        "max_drawdown_pct":round(max_dd, 2),
        "sharpe":          round(sharpe, 3),
        "sortino":         round(sortino, 3),
        "final_equity":    round(equity, 2),
        "best_trade_usd":  round(max(t["pnl_usd"] for t in trades), 2),
        "worst_trade_usd": round(min(t["pnl_usd"] for t in trades), 2),
        "avg_win_usd":     round(gross_win / len(wins), 2) if wins else 0.0,
        "avg_loss_usd":    round(-gross_loss / len(losses), 2) if losses else 0.0,
    }


# ───────────────────────────── public API ─────────────────────────────

DEFAULT_PARAMS = {
    "start":           None,
    "end":             None,
    "pairs":           None,
    "initial_capital": 10_000.0,
    "risk_pct":        2.0,
    "leverage":        10,
    "fee_pct":         0.05,
    "sl_mode":         "strict",
    "tp_mode":         "first",
    "max_hold_hours":  48,
}


def _normalise_params(p: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(DEFAULT_PARAMS)
    out.update({k: p[k] for k in p if k in DEFAULT_PARAMS and p[k] is not None})
    # Safety bounds — silently clamp rather than reject; users may type
    # wild numbers and deserve a sane run.
    out["initial_capital"] = max(100.0,    min(1e7,  float(out["initial_capital"])))
    out["risk_pct"]        = max(0.1,      min(50.0, float(out["risk_pct"])))
    out["leverage"]        = max(1,        min(125,  int(out["leverage"])))
    out["fee_pct"]         = max(0.0,      min(0.5,  float(out["fee_pct"])))
    out["max_hold_hours"]  = max(1,        min(24*7, int(out["max_hold_hours"])))
    out["sl_mode"]         = "strict" if out["sl_mode"] not in ("strict", "none") else out["sl_mode"]
    out["tp_mode"]         = out["tp_mode"] if out["tp_mode"] in ("first", "last", "weighted") else "first"
    return out


def run_backtest(user_id: int, params: Dict[str, Any]) -> int:
    """Execute a backtest synchronously. Returns the new `run_id`.
    Callers should run this in a thread (via `asyncio.to_thread`) to
    avoid blocking the event loop — replaying ~1000 signals against
    OHLCV bars typically completes in under ~2 seconds, but a large
    window could take longer.
    """
    cfg = _normalise_params(params)
    now = time.time()
    c = _bt_conn()
    try:
        cur = c.execute(
            "INSERT INTO backtest_runs (user_id, params_json, status, created_at) "
            "VALUES (?,?,?,?)",
            (user_id, json.dumps(cfg), "running", now)
        )
        run_id = cur.lastrowid
    finally:
        c.close()

    try:
        sigs = _load_signals(cfg["start"], cfg["end"], cfg["pairs"])
        equity = float(cfg["initial_capital"])
        trades: List[Dict[str, Any]] = []
        for s in sigs:
            cfg["__equity"] = equity
            t = _simulate(s, cfg)
            if t is None:
                continue
            equity += t["pnl_usd"]
            trades.append(t)
        stats = _aggregate(trades, float(cfg["initial_capital"]))

        # Persist
        c = _bt_conn()
        try:
            c.executemany(
                """INSERT INTO backtest_trades
                   (run_id, signal_id, pair, direction, entry_ts, entry_price,
                    exit_ts, exit_price, exit_reason, pnl_pct, pnl_usd, equity_after)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                [(run_id, t["signal_id"], t["pair"], t["direction"],
                  t["entry_ts"], t["entry_price"], t["exit_ts"], t["exit_price"],
                  t["exit_reason"], t["pnl_pct"], t["pnl_usd"], t["equity_after"])
                 for t in trades]
            )
            c.execute(
                "UPDATE backtest_runs SET status='done', finished_at=?, stats_json=? "
                "WHERE id=?",
                (time.time(), json.dumps(stats), run_id)
            )
        finally:
            c.close()
        return run_id
    except Exception as e:
        log.exception("[backtest] run failed")
        c = _bt_conn()
        try:
            c.execute(
                "UPDATE backtest_runs SET status='error', finished_at=?, error=? "
                "WHERE id=?",
                (time.time(), str(e), run_id)
            )
        finally:
            c.close()
        return run_id


def get_backtest(run_id: int) -> Optional[Dict[str, Any]]:
    """Full run payload including all trades."""
    c = _bt_conn()
    try:
        run = c.execute("SELECT * FROM backtest_runs WHERE id=?", (run_id,)).fetchone()
        if not run:
            return None
        trades = c.execute(
            "SELECT * FROM backtest_trades WHERE run_id=? ORDER BY entry_ts ASC",
            (run_id,)
        ).fetchall()
    finally:
        c.close()
    d = dict(run)
    d["params"] = json.loads(d.pop("params_json") or "{}")
    d["stats"]  = json.loads(d.pop("stats_json")  or "{}")
    d["trades"] = [dict(t) for t in trades]
    return d


def list_backtests(user_id: int, limit: int = 25) -> List[Dict[str, Any]]:
    c = _bt_conn()
    try:
        rows = c.execute(
            "SELECT id, status, created_at, finished_at, params_json, stats_json, error "
            "FROM backtest_runs WHERE user_id=? ORDER BY id DESC LIMIT ?",
            (user_id, limit)
        ).fetchall()
    finally:
        c.close()
    out = []
    for r in rows:
        d = dict(r)
        d["params"] = json.loads(d.pop("params_json") or "{}")
        d["stats"]  = json.loads(d.pop("stats_json")  or "{}")
        out.append(d)
    return out
