"""
trading_sessions.py — Trading session definitions, active detection, and signal gating.
All times in UTC.

Sessions (UTC):
  Sydney    : 22:00 – 07:00  (overnight, spans midnight)
  Asia/Tokyo: 00:00 – 09:00
  London    : 07:00 – 16:00
  New York  : 13:30 – 20:00  (09:30-16:00 EDT/EST)

Overlaps:
  Asia+London : 07:00 – 09:00  (medium liquidity boost)
  London+NY   : 13:30 – 16:00  (peak liquidity — 2.5h window)
  Dead Zone   : 22:00 – 00:00  (thin, avoid low-cap)
"""

from datetime import datetime, timezone, time as dtime
from typing import Dict, List, Tuple

# ── Session definitions ────────────────────────────────────────────────
# Each session: (open_utc_h, open_utc_m, close_utc_h, close_utc_m, spans_midnight)
_SESSION_DEF = {
    'Sydney': {
        'open':  (22, 0), 'close': (7, 0), 'midnight': True,
        'emoji': '🦘', 'color': '#9c27b0', 'city': 'Sydney', 'tz': 'AEDT',
        'liquidity_base': 'low',
    },
    'Asia': {
        'open':  (0, 0),  'close': (9, 0), 'midnight': False,
        'emoji': '🗼', 'color': '#ff6b35', 'city': 'Tokyo', 'tz': 'JST',
        'liquidity_base': 'medium',
    },
    'London': {
        'open':  (7, 0),  'close': (16, 0), 'midnight': False,
        'emoji': '🏦', 'color': '#2196f3', 'city': 'London', 'tz': 'BST',
        'liquidity_base': 'high',
    },
    'New York': {
        'open':  (13, 30), 'close': (20, 0), 'midnight': False,
        'emoji': '🗽', 'color': '#4caf50', 'city': 'New York', 'tz': 'EDT',
        'liquidity_base': 'high',
    },
}

# Dead zone: 22:00 – 00:00 UTC (Sydney open but NY/London/Asia all closed)
_DEAD_ZONE = (22, 0)   # only Sydney active → very thin


def _minutes_utc(dt: datetime) -> int:
    """Convert UTC datetime to minutes since midnight."""
    return dt.hour * 60 + dt.minute


def is_session_active(name: str, dt: datetime) -> bool:
    s = _SESSION_DEF[name]
    m = _minutes_utc(dt)
    o = s['open'][0] * 60 + s['open'][1]
    c = s['close'][0] * 60 + s['close'][1]
    if s['midnight']:          # spans midnight
        return m >= o or m < c
    return o <= m < c


def get_active_sessions(dt: datetime = None) -> List[str]:
    if dt is None:
        dt = datetime.now(timezone.utc)
    return [n for n in _SESSION_DEF if is_session_active(n, dt)]


def get_liquidity_level(dt: datetime = None) -> str:
    """
    Returns current liquidity tier:
      peak   — London + NY overlap (13:00–16:00 UTC)
      high   — London or NY active (but not both)
      medium — Asia active, London/NY not
      low    — Sydney only (22:00–00:00 UTC)
      dead   — 22:00–00:00 UTC window (transitional, thinnest)
    """
    if dt is None:
        dt = datetime.now(timezone.utc)
    active = get_active_sessions(dt)
    if 'London' in active and 'New York' in active:
        return 'peak'
    if 'London' in active or 'New York' in active:
        return 'high'
    if 'Asia' in active:
        m = _minutes_utc(dt)
        if m >= 7 * 60:    # London just opened — Asia/London overlap
            return 'high'
        return 'medium'
    return 'low'          # Sydney only or dead zone


def can_trade_session(pair_tier: str, dt: datetime = None) -> Tuple[bool, str]:
    """
    Session-based signal gate.
    Returns (allowed: bool, reason: str)

    Rules:
      - blue_chip / large_cap : always allowed (24/7 deep liquidity)
      - mid_cap               : blocked in dead zone only (22:00–00:00)
      - small_cap / high_risk : require London or NY session active
    """
    if dt is None:
        dt = datetime.now(timezone.utc)
    liq = get_liquidity_level(dt)
    active = get_active_sessions(dt)

    if pair_tier in ('blue_chip', 'large_cap'):
        return True, 'unrestricted'

    if pair_tier == 'mid_cap':
        if liq == 'low':
            return False, f'mid_cap blocked in low-liquidity window (active={active or ["none"]})'
        return True, f'mid_cap ok — {liq} liquidity'

    # small_cap / high_risk / unknown
    london_ny = 'London' in active or 'New York' in active
    if not london_ny:
        return False, (
            f'{pair_tier} blocked outside London/NY session '
            f'(active={active or ["none"]}, liquidity={liq})'
        )
    return True, f'{pair_tier} ok — London/NY active'


def get_session_state(dt: datetime = None) -> Dict:
    """Full session state dict — consumed by API endpoint and frontend."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    active = get_active_sessions(dt)
    liq = get_liquidity_level(dt)
    m = _minutes_utc(dt)

    sessions_out = []
    for name, s in _SESSION_DEF.items():
        is_active = name in active
        o_min = s['open'][0] * 60 + s['open'][1]
        c_min = s['close'][0] * 60 + s['close'][1]

        if is_active:
            if s['midnight'] and m >= o_min:     # pre-midnight side
                mins_left = (24 * 60 - m) + c_min
            elif s['midnight']:                   # post-midnight side
                mins_left = c_min - m
            else:
                mins_left = c_min - m
            status_label = 'OPEN'
        else:
            if s['midnight']:
                if m < o_min and m >= c_min:      # between close and open
                    mins_left = o_min - m
                else:
                    mins_left = (24 * 60 - m) + o_min
            else:
                if m < o_min:
                    mins_left = o_min - m
                else:
                    mins_left = (24 * 60 - m) + o_min
            status_label = 'CLOSED'

        # Hours/minutes until open or close
        h, mn = divmod(abs(mins_left), 60)
        countdown = f'{int(h)}h {int(mn)}m'

        sessions_out.append({
            'name':       name,
            'city':       s['city'],
            'tz':         s['tz'],
            'emoji':      s['emoji'],
            'color':      s['color'],
            'active':     is_active,
            'status':     status_label,
            'countdown':  countdown,
            'open_utc':   f"{s['open'][0]:02d}:{s['open'][1]:02d}",
            'close_utc':  f"{s['close'][0]:02d}:{s['close'][1]:02d}",
            'liquidity':  s['liquidity_base'] if is_active else 'closed',
            'open_h':     s['open'][0],
            'open_m':     s['open'][1],
            'close_h':    s['close'][0],
            'close_m':    s['close'][1],
            'midnight':   s['midnight'],
        })

    # Overlaps
    overlaps = []
    if 'Asia' in active and 'London' in active:
        overlaps.append({'name': 'Asia/London Overlap', 'color': '#ff9800', 'liquidity': 'high'})
    if 'London' in active and 'New York' in active:
        overlaps.append({'name': 'London/NY Overlap', 'color': '#00d68f', 'liquidity': 'peak'})

    return {
        'utc_time':  dt.strftime('%H:%M UTC'),
        'active':    active,
        'liquidity': liq,
        'sessions':  sessions_out,
        'overlaps':  overlaps,
    }
