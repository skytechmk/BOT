"""
Aladdin Dashboard — Performance Analytics Engine
Computes win rates, PnL metrics, equity curves, and heatmaps
from the signal_registry.db data.
"""
import sqlite3
import time
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
from collections import defaultdict

_SIGNAL_DB = Path(__file__).resolve().parent.parent / "signal_registry.db"
_LANDING_STATS_CACHE = {}
_OPEN_SIGNAL_STATUSES = ('SENT', 'OPEN', 'ACTIVE', 'TP1_HIT', 'TP2_HIT')


def _get_signal_db():
    if not _SIGNAL_DB.exists():
        return None
    conn = sqlite3.connect(f"file:{_SIGNAL_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def get_public_overview_stats(ttl_seconds: float = 15.0, since_ts=None) -> dict:
    """Fast public KPI snapshot for landing surfaces.

    Returns production-tier aggregate metrics across live + archived signals:
      - total_signals
      - open_positions
      - win_rate
      - total_pnl

    If `since_ts` is provided, only signals opened at/after that unix timestamp
    are included (e.g. public production scope since Apr 16, 2026).

    The result is cached in-process for `ttl_seconds` to keep landing-page
    rendering cheap under traffic spikes.
    """
    now = time.time()
    ttl = max(1.0, float(ttl_seconds or 15.0))
    scope_key = str(int(float(since_ts or 0.0)))
    cache_row = _LANDING_STATS_CACHE.get(scope_key)
    if cache_row and (now - cache_row.get("ts", 0.0)) < ttl:
        return dict(cache_row.get("data") or {})

    fallback = {
        "total_signals": 0,
        "open_positions": 0,
        "closed_signals": 0,
        "wins": 0,
        "losses": 0,
        "win_rate": 0.0,
        "total_pnl": 0.0,
        "scope_since_ts": float(since_ts or 0.0),
    }

    conn = _get_signal_db()
    if not conn:
        _LANDING_STATS_CACHE[scope_key] = {"ts": now, "data": dict(fallback)}
        return dict(fallback)

    open_statuses_sql = "','".join(_OPEN_SIGNAL_STATUSES)
    since_filter_sql = ""
    params = []
    if since_ts is not None:
        try:
            since_ts_val = float(since_ts)
            since_filter_sql = " AND timestamp >= ?"
            params.append(since_ts_val)
        except (TypeError, ValueError):
            since_filter_sql = ""
            params = []

    union_sql = f"""
        WITH all_signals AS (
            SELECT status, pnl, timestamp, COALESCE(signal_tier,'production') AS signal_tier FROM signals
            UNION ALL
            SELECT status, pnl, timestamp, COALESCE(signal_tier,'production') AS signal_tier FROM archived_signals
        )
        SELECT
            COUNT(*) AS total_signals,
            SUM(CASE WHEN upper(status) IN ('{open_statuses_sql}') THEN 1 ELSE 0 END) AS open_positions,
            SUM(CASE WHEN pnl IS NOT NULL AND upper(status) NOT IN ('{open_statuses_sql}') THEN 1 ELSE 0 END) AS closed_signals,
            SUM(CASE WHEN pnl > 0 AND upper(status) NOT IN ('{open_statuses_sql}') THEN 1 ELSE 0 END) AS wins,
            SUM(CASE WHEN pnl IS NOT NULL AND upper(status) NOT IN ('{open_statuses_sql}') THEN pnl ELSE 0 END) AS total_pnl
        FROM all_signals
        WHERE signal_tier = 'production'{since_filter_sql}
    """

    live_only_sql = f"""
        SELECT
            COUNT(*) AS total_signals,
            SUM(CASE WHEN upper(status) IN ('{open_statuses_sql}') THEN 1 ELSE 0 END) AS open_positions,
            SUM(CASE WHEN pnl IS NOT NULL AND upper(status) NOT IN ('{open_statuses_sql}') THEN 1 ELSE 0 END) AS closed_signals,
            SUM(CASE WHEN pnl > 0 AND upper(status) NOT IN ('{open_statuses_sql}') THEN 1 ELSE 0 END) AS wins,
            SUM(CASE WHEN pnl IS NOT NULL AND upper(status) NOT IN ('{open_statuses_sql}') THEN pnl ELSE 0 END) AS total_pnl
        FROM signals
        WHERE COALESCE(signal_tier,'production') = 'production'{since_filter_sql}
    """

    try:
        try:
            row = conn.execute(union_sql, tuple(params)).fetchone()
        except sqlite3.Error:
            row = conn.execute(live_only_sql, tuple(params)).fetchone()

        total_signals = int((row['total_signals'] if row else 0) or 0)
        open_positions = int((row['open_positions'] if row else 0) or 0)
        closed_signals = int((row['closed_signals'] if row else 0) or 0)
        wins = int((row['wins'] if row else 0) or 0)
        losses = max(closed_signals - wins, 0)
        win_rate = round((wins / closed_signals) * 100, 2) if closed_signals > 0 else 0.0
        total_pnl = round(float((row['total_pnl'] if row else 0) or 0.0), 2)

        data = {
            "total_signals": total_signals,
            "open_positions": open_positions,
            "closed_signals": closed_signals,
            "wins": wins,
            "losses": losses,
            "win_rate": win_rate,
            "total_pnl": total_pnl,
            "scope_since_ts": float(since_ts or 0.0),
        }
    except Exception:
        data = dict(fallback)
    finally:
        conn.close()

    _LANDING_STATS_CACHE[scope_key] = {"ts": now, "data": dict(data)}
    return data


def get_performance_summary(days: int = 30) -> dict:
    """Comprehensive performance summary for the last N days."""
    conn = _get_signal_db()
    if not conn:
        return {"error": "No signal database"}

    cutoff = time.time() - (days * 86400)
    rows = conn.execute(
        "SELECT * FROM signals WHERE timestamp > ? ORDER BY timestamp DESC",
        (cutoff,)
    ).fetchall()
    conn.close()

    if not rows:
        return {"total_signals": 0, "period_days": days}

    total = len(rows)
    closed = [r for r in rows if r['status'] == 'CLOSED' and r['pnl'] is not None]
    open_signals = [r for r in rows if r['status'] in ('SENT', 'OPEN', 'ACTIVE')]

    wins = [r for r in closed if r['pnl'] > 0]
    losses = [r for r in closed if r['pnl'] < 0]
    breakeven = [r for r in closed if r['pnl'] == 0]

    total_pnl = sum(r['pnl'] for r in closed)
    avg_win = sum(r['pnl'] for r in wins) / len(wins) if wins else 0
    avg_loss = sum(r['pnl'] for r in losses) / len(losses) if losses else 0

    # ── Alternative PnL interpretations ──────────────────────────────
    # 1) Unleveraged sum — divide each pnl by its leverage (fall back to 1)
    total_pnl_unleveraged = sum(
        r['pnl'] / (r['leverage'] if r['leverage'] and r['leverage'] > 0 else 1)
        for r in closed
    )
    # 2) Average leveraged % per trade
    avg_pnl_per_trade = (total_pnl / len(closed)) if closed else 0
    # 3) Compounded equity % (start=$1000, 1 % sizing per trade — standard risk-per-trade)
    _equity = 1000.0
    for r in sorted(closed, key=lambda x: x['timestamp']):
        _equity += _equity * 0.01 * (r['pnl'] / 100.0)
        if _equity < 0:
            _equity = 0.0
    compounded_equity_pct = ((_equity / 1000.0) - 1.0) * 100.0

    # Win rate
    win_rate = len(wins) / len(closed) * 100 if closed else 0

    # Profit factor
    gross_profit = sum(r['pnl'] for r in wins)
    gross_loss = abs(sum(r['pnl'] for r in losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')

    # Best and worst trades
    best_trade = max(closed, key=lambda r: r['pnl']) if closed else None
    worst_trade = min(closed, key=lambda r: r['pnl']) if closed else None

    # Streak tracking
    max_win_streak = max_loss_streak = current_streak = 0
    streak_type = None
    for r in sorted(closed, key=lambda x: x['timestamp']):
        if r['pnl'] > 0:
            if streak_type == 'win':
                current_streak += 1
            else:
                current_streak = 1
                streak_type = 'win'
            max_win_streak = max(max_win_streak, current_streak)
        elif r['pnl'] < 0:
            if streak_type == 'loss':
                current_streak += 1
            else:
                current_streak = 1
                streak_type = 'loss'
            max_loss_streak = max(max_loss_streak, current_streak)

    # Direction breakdown
    long_signals = [r for r in closed if r['signal'] in ('LONG', 'BUY')]
    short_signals = [r for r in closed if r['signal'] in ('SHORT', 'SELL')]
    long_wins = [r for r in long_signals if r['pnl'] > 0]
    short_wins = [r for r in short_signals if r['pnl'] > 0]

    # TP and SL hit percentages
    tp1_hit = sum(1 for r in closed if r['targets_hit'] >= 1)
    tp2_hit = sum(1 for r in closed if r['targets_hit'] >= 2)
    tp3_hit = sum(1 for r in closed if r['targets_hit'] == 3)
    sl_hit = sum(1 for r in closed if r['close_reason'] and 'SL_HIT' in r['close_reason'])
    tp1_hit_pct = round((tp1_hit / len(closed) * 100) if closed else 0, 1)
    tp2_hit_pct = round((tp2_hit / len(closed) * 100) if closed else 0, 1)
    tp3_hit_pct = round((tp3_hit / len(closed) * 100) if closed else 0, 1)
    sl_hit_pct = round((sl_hit / len(closed) * 100) if closed else 0, 1)

    return {
        "period_days": days,
        "total_signals": total,
        "closed_signals": len(closed),
        "open_signals": len(open_signals),
        "wins": len(wins),
        "losses": len(losses),
        "breakeven": len(breakeven),
        "win_rate": round(win_rate, 1),
        "total_pnl": round(total_pnl, 2),
        "total_pnl_unleveraged": round(total_pnl_unleveraged, 2),
        "avg_pnl_per_trade": round(avg_pnl_per_trade, 2),
        "compounded_equity_pct": round(compounded_equity_pct, 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "profit_factor": round(profit_factor, 2) if profit_factor != float('inf') else 999,
        "best_trade": {"pair": best_trade['pair'], "pnl": best_trade['pnl']} if best_trade else None,
        "worst_trade": {"pair": worst_trade['pair'], "pnl": worst_trade['pnl']} if worst_trade else None,
        "max_win_streak": max_win_streak,
        "max_loss_streak": max_loss_streak,
        "long_signals": len(long_signals),
        "long_win_rate": round(len(long_wins) / len(long_signals) * 100, 1) if long_signals else 0,
        "short_signals": len(short_signals),
        "short_win_rate": round(len(short_wins) / len(short_signals) * 100, 1) if short_signals else 0,
        "tp1_hit": tp1_hit,
        "tp2_hit": tp2_hit,
        "tp3_hit": tp3_hit,
        "sl_hit": sl_hit,
        "tp1_hit_pct": tp1_hit_pct,
        "tp2_hit_pct": tp2_hit_pct,
        "tp3_hit_pct": tp3_hit_pct,
        "sl_hit_pct": sl_hit_pct,
    }


def get_equity_curve(days: int = 30, starting_capital: float = 1000) -> list:
    """Simulate equity curve as if following all signals."""
    conn = _get_signal_db()
    if not conn:
        return []

    cutoff = time.time() - (days * 86400)
    rows = conn.execute(
        "SELECT * FROM signals WHERE status='CLOSED' AND pnl IS NOT NULL "
        "AND timestamp > ? ORDER BY timestamp ASC",
        (cutoff,)
    ).fetchall()
    conn.close()

    equity = starting_capital
    curve = [{"timestamp": cutoff, "equity": equity}]

    for r in rows:
        # pnl is already leveraged (stored as leveraged % since Apr 2026 fix)
        position_size = 0.1  # 10% of portfolio per trade
        pnl_impact = equity * position_size * (r['pnl'] / 100)
        equity += pnl_impact
        equity = max(0, equity)  # Can't go below 0

        curve.append({
            "timestamp": r['timestamp'],
            "equity": round(equity, 2),
            "pair": r['pair'],
            "pnl": r['pnl'],
        })

    return curve


def get_pair_performance(days: int = 30) -> list:
    """Performance breakdown by pair."""
    conn = _get_signal_db()
    if not conn:
        return []

    cutoff = time.time() - (days * 86400)
    rows = conn.execute(
        "SELECT * FROM signals WHERE status='CLOSED' AND pnl IS NOT NULL "
        "AND timestamp > ? ORDER BY timestamp DESC",
        (cutoff,)
    ).fetchall()
    conn.close()

    pairs = defaultdict(lambda: {"signals": 0, "wins": 0, "total_pnl": 0, "trades": []})
    for r in rows:
        p = pairs[r['pair']]
        p['signals'] += 1
        if r['pnl'] > 0:
            p['wins'] += 1
        p['total_pnl'] += r['pnl']
        p['trades'].append(r['pnl'])

    result = []
    for pair, data in pairs.items():
        result.append({
            "pair": pair,
            "signals": data['signals'],
            "win_rate": round(data['wins'] / data['signals'] * 100, 1) if data['signals'] else 0,
            "total_pnl": round(data['total_pnl'], 2),
            "avg_pnl": round(data['total_pnl'] / data['signals'], 2) if data['signals'] else 0,
        })

    result.sort(key=lambda x: x['total_pnl'], reverse=True)
    return result


def get_public_pair_summary(pair: str, limit: int = 8) -> dict:
    """Public-safe aggregate summary for a single pair.

    Designed for SEO pages only. Returns historical / aggregate data and does
    not expose live premium entry, TP, or stop-loss levels.
    """
    conn = _get_signal_db()
    if not conn:
        return {"exists": False, "pair": pair}

    try:
        live_rows = conn.execute(
            "SELECT signal_id, pair, signal, confidence, timestamp, status, pnl, targets_hit "
            "FROM signals WHERE pair=? AND COALESCE(signal_tier,'production')='production'",
            (pair,)
        ).fetchall()
        try:
            archived_rows = conn.execute(
                "SELECT signal_id, pair, signal, confidence, timestamp, status, pnl, targets_hit "
                "FROM archived_signals WHERE pair=? AND COALESCE(signal_tier,'production')='production'",
                (pair,)
            ).fetchall()
        except sqlite3.Error:
            archived_rows = []
    finally:
        conn.close()

    rows = sorted(list(live_rows) + list(archived_rows), key=lambda r: r['timestamp'], reverse=True)
    if not rows:
        return {"exists": False, "pair": pair}

    closed = [r for r in rows if r['status'] == 'CLOSED' and r['pnl'] is not None]
    wins = [r for r in closed if r['pnl'] > 0]
    best_trade = max(closed, key=lambda r: r['pnl']) if closed else None
    worst_trade = min(closed, key=lambda r: r['pnl']) if closed else None
    latest = rows[0]

    recent_closed = []
    for r in closed[:limit]:
        ts_utc = datetime.fromtimestamp(r['timestamp'], tz=timezone.utc)
        recent_closed.append({
            "direction": r['signal'],
            "timestamp": r['timestamp'],
            "time_local": ts_utc.strftime('%d %b %H:%M UTC'),
            "pnl": round(r['pnl'], 2),
            "targets_hit": int(r['targets_hit']) if isinstance(r['targets_hit'], (int, float)) else 0,
        })

    return {
        "exists": True,
        "pair": pair,
        "total_signals": len(rows),
        "closed_signals": len(closed),
        "win_rate": round(len(wins) / len(closed) * 100, 1) if closed else 0,
        "avg_pnl": round(sum(r['pnl'] for r in closed) / len(closed), 2) if closed else 0,
        "best_trade": round(best_trade['pnl'], 2) if best_trade else None,
        "worst_trade": round(worst_trade['pnl'], 2) if worst_trade else None,
        "last_signal": {
            "direction": latest['signal'],
            "status": latest['status'],
            "timestamp": latest['timestamp'],
            "confidence": round((latest['confidence'] or 0) * 100, 1),
        },
        "recent_closed": recent_closed,
    }


def get_hourly_heatmap(days: int = 30) -> list:
    """Signal distribution and win rate by hour of day."""
    conn = _get_signal_db()
    if not conn:
        return []

    cutoff = time.time() - (days * 86400)
    rows = conn.execute(
        "SELECT * FROM signals WHERE status='CLOSED' AND pnl IS NOT NULL "
        "AND timestamp > ?",
        (cutoff,)
    ).fetchall()
    conn.close()

    hours = defaultdict(lambda: {"count": 0, "wins": 0, "pnl": 0})
    for r in rows:
        h = datetime.fromtimestamp(r['timestamp'], tz=timezone.utc).hour
        hours[h]['count'] += 1
        if r['pnl'] > 0:
            hours[h]['wins'] += 1
        hours[h]['pnl'] += r['pnl']

    return [{
        "hour": h,
        "signals": data['count'],
        "win_rate": round(data['wins'] / data['count'] * 100, 1) if data['count'] else 0,
        "total_pnl": round(data['pnl'], 2),
    } for h, data in sorted(hours.items())]


def get_signal_breakdown(days: int = 30) -> list:
    """Detailed per-signal breakdown with entry/SL/TP/R:R."""
    conn = _get_signal_db()
    if not conn:
        return []

    cutoff = time.time() - (days * 86400)
    rows = conn.execute(
        "SELECT signal_id, pair, signal, price, confidence, targets_json, "
        "stop_loss, leverage, timestamp, status, pnl "
        "FROM signals WHERE timestamp > ? ORDER BY timestamp DESC",
        (cutoff,)
    ).fetchall()
    conn.close()

    result = []
    for r in rows:
        targets = []
        if r['targets_json']:
            try:
                targets = json.loads(r['targets_json'])
            except (json.JSONDecodeError, TypeError):
                pass

        entry = r['price']
        sl = r['stop_loss']
        rr = None
        if entry and sl and targets:
            risk = abs(entry - sl)
            if risk > 0:
                best_tp = targets[-1] if targets else entry
                reward = abs(best_tp - entry)
                rr = round(reward / risk, 2)

        ts_utc = datetime.fromtimestamp(r['timestamp'], tz=timezone.utc)
        result.append({
            "signal_id": r['signal_id'][:8],
            "pair": r['pair'],
            "direction": r['signal'],
            "entry": entry,
            "stop_loss": sl,
            "targets": targets,
            "leverage": r['leverage'],
            "confidence": round(r['confidence'] * 100, 1) if r['confidence'] else 0,
            "rr": rr,
            "status": r['status'] or 'SENT',
            "pnl": round(r['pnl'], 2) if r['pnl'] else 0,
            "timestamp": r['timestamp'],
            "time_local": ts_utc.strftime('%d %b %H:%M UTC'),  # fallback; JS localizes
        })

    return result


def get_daily_pnl(days: int = 30) -> list:
    """Daily PnL breakdown."""
    conn = _get_signal_db()
    if not conn:
        return []

    cutoff = time.time() - (days * 86400)
    rows = conn.execute(
        "SELECT * FROM signals WHERE status='CLOSED' AND pnl IS NOT NULL "
        "AND timestamp > ? ORDER BY timestamp ASC",
        (cutoff,)
    ).fetchall()
    conn.close()

    daily = defaultdict(lambda: {"pnl": 0, "signals": 0, "wins": 0})
    for r in rows:
        day = datetime.fromtimestamp(r['timestamp'], tz=timezone.utc).strftime('%Y-%m-%d')
        daily[day]['pnl'] += r['pnl']
        daily[day]['signals'] += 1
        if r['pnl'] > 0:
            daily[day]['wins'] += 1

    return [{
        "date": day,
        "pnl": round(data['pnl'], 2),
        "signals": data['signals'],
        "win_rate": round(data['wins'] / data['signals'] * 100, 1) if data['signals'] else 0,
    } for day, data in sorted(daily.items())]


def get_indicator_attribution(days: int = 30) -> dict:
    """
    Analyze which SQI factors correlate with wins vs losses.
    Returns per-factor average scores for wins and losses.
    """
    conn = _get_signal_db()
    if not conn:
        return {}

    cutoff = time.time() - (days * 86400)
    rows = conn.execute(
        "SELECT pnl, features_json FROM signals "
        "WHERE status='CLOSED' AND pnl IS NOT NULL AND features_json IS NOT NULL "
        "AND timestamp > ?",
        (cutoff,)
    ).fetchall()
    conn.close()

    sqi_factors = ['sqi_rr', 'sqi_volume', 'sqi_ce_alignment',
                   'sqi_extension', 'sqi_atr_regime', 'sqi_momentum',
                   'sqi_positioning', 'sqi_stop_hunt']
    factor_maxes = {'sqi_rr': 30, 'sqi_volume': 20, 'sqi_ce_alignment': 15,
                    'sqi_extension': 15, 'sqi_atr_regime': 10, 'sqi_momentum': 10,
                    'sqi_positioning': 20, 'sqi_stop_hunt': 5}

    win_factors = defaultdict(list)
    loss_factors = defaultdict(list)
    sqi_wins = []
    sqi_losses = []

    for r in rows:
        try:
            feat = json.loads(r['features_json'])
        except (json.JSONDecodeError, TypeError):
            continue

        is_win = r['pnl'] > 0
        sqi = feat.get('sqi_score')
        if sqi is not None:
            (sqi_wins if is_win else sqi_losses).append(sqi)

        for f in sqi_factors:
            val = feat.get(f)
            if val is not None:
                (win_factors[f] if is_win else loss_factors[f]).append(val)

    result = {'factors': [], 'sqi_correlation': {}}

    for f in sqi_factors:
        label = f.replace('sqi_', '').replace('_', ' ').title()
        w_avg = round(sum(win_factors[f]) / len(win_factors[f]), 1) if win_factors[f] else 0
        l_avg = round(sum(loss_factors[f]) / len(loss_factors[f]), 1) if loss_factors[f] else 0
        result['factors'].append({
            'name': label,
            'key': f,
            'max': factor_maxes.get(f, 10),
            'win_avg': w_avg,
            'loss_avg': l_avg,
            'delta': round(w_avg - l_avg, 1),
            'win_count': len(win_factors[f]),
            'loss_count': len(loss_factors[f]),
        })

    # SQI overall correlation
    if sqi_wins and sqi_losses:
        result['sqi_correlation'] = {
            'win_avg_sqi': round(sum(sqi_wins) / len(sqi_wins), 1),
            'loss_avg_sqi': round(sum(sqi_losses) / len(sqi_losses), 1),
            'total_with_sqi': len(sqi_wins) + len(sqi_losses),
        }

    return result


def get_regime_performance(days: int = 30) -> dict:
    """
    Performance breakdown by market regime indicators:
    - Leverage buckets
    - Confidence buckets
    - R:R buckets
    - Extension from EMA21
    """
    conn = _get_signal_db()
    if not conn:
        return {}

    cutoff = time.time() - (days * 86400)
    rows = conn.execute(
        "SELECT pnl, leverage, confidence, features_json, targets_json, "
        "price, stop_loss, signal FROM signals "
        "WHERE status='CLOSED' AND pnl IS NOT NULL AND timestamp > ?",
        (cutoff,)
    ).fetchall()
    conn.close()

    def bucket_stats(items):
        if not items:
            return {'count': 0, 'wr': 0, 'avg_pnl': 0}
        wins = [r for r in items if r['pnl'] > 0]
        return {
            'count': len(items),
            'wr': round(len(wins) / len(items) * 100, 1),
            'avg_pnl': round(sum(r['pnl'] for r in items) / len(items), 2),
        }

    # Leverage buckets
    lev_buckets = {'2-5x': [], '5-10x': [], '10-18x': [], '18-25x': []}
    for r in rows:
        lev = r['leverage'] or 0
        if lev <= 5: lev_buckets['2-5x'].append(r)
        elif lev <= 10: lev_buckets['5-10x'].append(r)
        elif lev <= 18: lev_buckets['10-18x'].append(r)
        else: lev_buckets['18-25x'].append(r)

    # R:R buckets
    rr_buckets = {'<0.5': [], '0.5-1': [], '1-2': [], '2-5': [], '5+': []}
    for r in rows:
        tgts = json.loads(r['targets_json']) if r['targets_json'] else []
        if not tgts or not r['price'] or not r['stop_loss']:
            continue
        risk = abs(r['price'] - r['stop_loss'])
        reward = abs(tgts[-1] - r['price'])
        rr = reward / risk if risk > 0 else 0
        if rr < 0.5: rr_buckets['<0.5'].append(r)
        elif rr < 1.0: rr_buckets['0.5-1'].append(r)
        elif rr < 2.0: rr_buckets['1-2'].append(r)
        elif rr < 5.0: rr_buckets['2-5'].append(r)
        else: rr_buckets['5+'].append(r)

    # Direction
    dir_buckets = {'LONG': [], 'SHORT': []}
    for r in rows:
        d = r['signal'].upper()
        if d in ('LONG', 'BUY'):
            dir_buckets['LONG'].append(r)
        else:
            dir_buckets['SHORT'].append(r)

    # Extension buckets (from features)
    ext_buckets = {'0-2%': [], '2-5%': [], '5-10%': [], '10%+': []}
    for r in rows:
        try:
            feat = json.loads(r['features_json']) if r['features_json'] else {}
            ext = feat.get('ext_from_ema21', None)
            if ext is None:
                continue
            if ext <= 2: ext_buckets['0-2%'].append(r)
            elif ext <= 5: ext_buckets['2-5%'].append(r)
            elif ext <= 10: ext_buckets['5-10%'].append(r)
            else: ext_buckets['10%+'].append(r)
        except (json.JSONDecodeError, TypeError):
            continue

    # PREDATOR regime buckets
    regime_buckets = {}
    for r in rows:
        try:
            feat = json.loads(r['features_json']) if r['features_json'] else {}
            regime = feat.get('pred_regime')
            if regime:
                regime_buckets.setdefault(regime, []).append(r)
        except (json.JSONDecodeError, TypeError):
            continue

    # PREDATOR positioning alignment
    pos_buckets = {'aligned': [], 'against': [], 'unknown': []}
    for r in rows:
        try:
            feat = json.loads(r['features_json']) if r['features_json'] else {}
            aligned = feat.get('pred_pos_aligned')
            if aligned is True:
                pos_buckets['aligned'].append(r)
            elif aligned is False:
                pos_buckets['against'].append(r)
            else:
                pos_buckets['unknown'].append(r)
        except (json.JSONDecodeError, TypeError):
            continue

    return {
        'leverage': {k: bucket_stats(v) for k, v in lev_buckets.items()},
        'rr': {k: bucket_stats(v) for k, v in rr_buckets.items()},
        'direction': {k: bucket_stats(v) for k, v in dir_buckets.items()},
        'extension': {k: bucket_stats(v) for k, v in ext_buckets.items()},
        'regime': {k: bucket_stats(v) for k, v in regime_buckets.items()},
        'positioning': {k: bucket_stats(v) for k, v in pos_buckets.items()},
    }
