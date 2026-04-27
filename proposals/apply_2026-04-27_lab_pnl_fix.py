#!/usr/bin/env python3
from pathlib import Path

ROOT = Path('/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA')
APP = ROOT / 'dashboard' / 'app.py'
LAB = ROOT / 'dashboard' / 'static' / 'js' / 'lab.js'
PERF = ROOT / 'performance_tracker.py'


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    if new in text:
        print(f'OK already patched: {path}')
        return
    if old not in text:
        raise SystemExit(f'Pattern not found in {path}')
    path.write_text(text.replace(old, new, 1))
    print(f'Patched: {path}')


replace_once(
    APP,
    '''            "stop_loss, leverage, timestamp, status, pnl, targets_hit, "
            "zone_used, signal_tier "''',
    '''            "stop_loss, leverage, timestamp, status, pnl, targets_hit, "
            "zone_used, signal_tier, close_reason, closed_timestamp "'''
)

replace_once(
    APP,
    '''            signals.append({
                "signal_id":   row["signal_id"],
                "pair":        row["pair"],
                "signal":      row["signal"],
                "price":       row["price"],
                "confidence":  row["confidence"],
                "targets":     targets,
                "stop_loss":   row["stop_loss"],
                "leverage":    row["leverage"],
                "timestamp":   row["timestamp"],
                "status":      row["status"],
                "pnl":         row["pnl"],
                "targets_hit": t_hit,
                "zone_used":   row["zone_used"],
            })''',
    '''            pnl_value = row["pnl"]
            close_reason = row["close_reason"]
            status_upper = (row["status"] or "").upper()
            pnl_missing = (
                status_upper in ("CLOSED", "CANCELLED")
                and (pnl_value is None or float(pnl_value or 0) == 0.0)
                and close_reason not in ("SL_HIT", "TP1_HIT", "TP2_HIT", "TP3_HIT")
            )

            signals.append({
                "signal_id":   row["signal_id"],
                "pair":        row["pair"],
                "signal":      row["signal"],
                "price":       row["price"],
                "confidence":  row["confidence"],
                "targets":     targets,
                "stop_loss":   row["stop_loss"],
                "leverage":    row["leverage"],
                "timestamp":   row["timestamp"],
                "status":      row["status"],
                "pnl":         pnl_value,
                "pnl_missing": pnl_missing,
                "targets_hit": t_hit,
                "zone_used":   row["zone_used"],
                "close_reason": close_reason,
                "closed_timestamp": row["closed_timestamp"],
            })'''
)

replace_once(
    LAB,
    '''function _labFmtPnl(v) {
    if (v === null || v === undefined || isNaN(v)) return '—';
    const n = Number(v);
    const cls = n > 0 ? 'color:#00c853' : n < 0 ? 'color:#ff5252' : 'color:var(--text-dim)';
    const sign = n > 0 ? '+' : '';
    return `<span style="${cls}">${sign}${n.toFixed(2)}%</span>`;
}''',
    '''function _labFmtPnl(v) {
    if (v === null || v === undefined || isNaN(v)) return '—';
    const n = Number(v);
    const cls = n > 0 ? 'color:#00c853' : n < 0 ? 'color:#ff5252' : 'color:var(--text-dim)';
    const sign = n > 0 ? '+' : '';
    return `<span style="${cls}">${sign}${n.toFixed(2)}%</span>`;
}

function _labFmtSignalPnl(s) {
    if (s && s.pnl_missing) {
        return '<span style="color:var(--text-dim)" title="Closed without computed outcome PnL">—</span>';
    }
    return _labFmtPnl(s ? s.pnl : null);
}'''
)

replace_once(
    LAB,
    '''                            <td style="text-align:right;padding:8px 14px;font-weight:700">${_labFmtPnl(s.pnl)}</td>''',
    '''                            <td style="text-align:right;padding:8px 14px;font-weight:700">${_labFmtSignalPnl(s)}</td>'''
)

replace_once(
    PERF,
    '''        # Remove expired signals
        for signal_id in expired_signals:
            close_open_signal(signal_id, "EXPIRED")
            log_message(f"Expired signal {signal_id} removed from open signals")''',
    '''        # Remove expired signals
        for signal_id in expired_signals:
            sig = OPEN_SIGNALS_TRACKER.get(signal_id, {})
            estimated_pnl = _estimate_pnl(sig)
            close_open_signal(signal_id, "EXPIRED", pnl=estimated_pnl)
            log_message(f"Expired signal {signal_id} removed from open signals")'''
)

replace_once(
    PERF,
    '''                SIGNAL_REGISTRY.update_signal(signal_id, {
                    'status': 'CLOSED',
                    'close_reason': close_reason,
                    'pnl': pnl,
                    'closed_timestamp': time.time()
                })''',
    '''                update_payload = {
                    'status': 'CLOSED',
                    'close_reason': close_reason,
                    'closed_timestamp': time.time()
                }
                if pnl is not None:
                    update_payload['pnl'] = pnl
                SIGNAL_REGISTRY.update_signal(signal_id, update_payload)'''
)

print('Done. Recommended verification: python -m py_compile dashboard/app.py performance_tracker.py')
