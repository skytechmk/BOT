"""
Aladdin Dashboard — Referral Program

Both referrer and referred user earn 7 free days when the referred user's first payment is verified.
Manual admin grants do NOT trigger the referrer bonus.

Flow:
  1. Each user has a unique 8-char referral code (generated on first access).
  2. New user registers via /?ref=CODE — referred_by stored on their account.
  3. When admin confirms their first payment → credit_referral() fires.
  4. Both users receive bonus days added to tier_expires.
"""
import time
import secrets
import sqlite3
import logging
from typing import Optional, Dict, List

from auth import DB_PATH, _get_db, upgrade_user_tier

log = logging.getLogger("referrals")

# ── Constants ────────────────────────────────────────────────────────
REFERRED_BONUS_DAYS = 7  # Bonus days for both referrer and referred on verified payment


# ── DB Bootstrap ─────────────────────────────────────────────────────
def _ensure_tables():
    conn = _get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS referral_codes (
            user_id     INTEGER PRIMARY KEY,
            code        TEXT UNIQUE NOT NULL,
            created_at  REAL NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS referral_events (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id     INTEGER NOT NULL,
            referred_id     INTEGER NOT NULL,
            payment_id      TEXT,
            payment_amount  REAL DEFAULT 0,
            bonus_days      INTEGER DEFAULT 0,
            status          TEXT DEFAULT 'pending',
            created_at      REAL NOT NULL,
            credited_at     REAL DEFAULT 0,
            FOREIGN KEY (referrer_id) REFERENCES users(id),
            FOREIGN KEY (referred_id) REFERENCES users(id)
        );

        CREATE INDEX IF NOT EXISTS idx_ref_events_referrer ON referral_events(referrer_id);
        CREATE INDEX IF NOT EXISTS idx_ref_events_referred ON referral_events(referred_id);
        CREATE INDEX IF NOT EXISTS idx_ref_code ON referral_codes(code);
    """)
    # Add referred_by column to users if missing
    try:
        conn.execute("ALTER TABLE users ADD COLUMN referred_by INTEGER DEFAULT NULL")
        conn.commit()
    except Exception:
        pass  # Column already exists
    conn.commit()
    conn.close()


_ensure_tables()


# ── Code Management ──────────────────────────────────────────────────
def get_or_create_code(user_id: int) -> str:
    """Return existing referral code for user, or generate a new one."""
    conn = _get_db()
    row = conn.execute(
        "SELECT code FROM referral_codes WHERE user_id=?", (user_id,)
    ).fetchone()
    if row:
        conn.close()
        return row['code']
    # Generate unique 8-char uppercase alphanumeric code
    while True:
        code = secrets.token_urlsafe(6).upper()[:8]
        exists = conn.execute(
            "SELECT 1 FROM referral_codes WHERE code=?", (code,)
        ).fetchone()
        if not exists:
            break
    conn.execute(
        "INSERT INTO referral_codes (user_id, code, created_at) VALUES (?, ?, ?)",
        (user_id, code, time.time())
    )
    conn.commit()
    conn.close()
    return code


def resolve_code(code: str) -> Optional[int]:
    """Resolve a referral code to the referrer's user_id. Returns None if invalid."""
    if not code or len(code) < 4:
        return None
    conn = _get_db()
    row = conn.execute(
        "SELECT user_id FROM referral_codes WHERE code=?", (code.upper().strip(),)
    ).fetchone()
    conn.close()
    return row['user_id'] if row else None


# ── Registration Hook ─────────────────────────────────────────────────
def register_referral(referred_id: int, referrer_id: int) -> bool:
    """
    Called when a new user registers via a referral link.
    Stores referred_by on the user record and creates a pending referral event.
    Returns False if user already has a referrer or they are the same person.
    """
    if referred_id == referrer_id:
        return False
    conn = _get_db()
    try:
        # Check if already referred
        row = conn.execute(
            "SELECT referred_by FROM users WHERE id=?", (referred_id,)
        ).fetchone()
        if row and row['referred_by']:
            return False  # Already has a referrer

        # Record referrer on user
        conn.execute(
            "UPDATE users SET referred_by=? WHERE id=?",
            (referrer_id, referred_id)
        )
        # Create pending referral event
        conn.execute(
            """INSERT INTO referral_events
               (referrer_id, referred_id, status, created_at)
               VALUES (?, ?, 'pending', ?)""",
            (referrer_id, referred_id, time.time())
        )
        conn.commit()
        log.info(f"[referral] User {referred_id} registered via referral from {referrer_id}")
        return True
    except Exception as e:
        log.error(f"[referral] register_referral error: {e}")
        return False
    finally:
        conn.close()


# ── Payment Credit Hook ───────────────────────────────────────────────
def credit_referral(referred_id: int, payment_id: str,
                    amount_usd: float, tier: str, days: int) -> Optional[Dict]:
    """
    Called after admin confirms a payment for a referred user.
    Only fires on the FIRST confirmed payment (status='pending' event required).

    Credits:
      - Referrer: 20% of payment → bonus days on their subscription
      - Referred: 7 free bonus days added to their subscription
    Returns dict with credit details, or None if no referral on record.
    """
    conn = _get_db()
    try:
        # Find pending referral event for this user (only first payment)
        event = conn.execute(
            """SELECT re.id, re.referrer_id FROM referral_events re
               WHERE re.referred_id=? AND re.status='pending'
               ORDER BY re.created_at ASC LIMIT 1""",
            (referred_id,)
        ).fetchone()
        if not event:
            return None  # No referral on record or already credited

        event_id   = event['id']
        referrer_id = event['referrer_id']

        # ── Referrer always gets a flat 7-day bonus on verified payment ──
        bonus_days_referrer = REFERRED_BONUS_DAYS  # same flat 7 days

        # ── Apply bonus days to referrer ──────────────────────────────
        _extend_subscription(conn, referrer_id, bonus_days_referrer)

        # ── Apply bonus days to referred user ─────────────────────────
        _extend_subscription(conn, referred_id, REFERRED_BONUS_DAYS)

        # ── Mark event credited ───────────────────────────────────────
        conn.execute(
            """UPDATE referral_events
               SET status='credited', payment_id=?, payment_amount=?,
                   bonus_days=?, credited_at=?
               WHERE id=?""",
            (payment_id, amount_usd, bonus_days_referrer, time.time(), event_id)
        )
        conn.commit()

        log.info(
            f"[referral] Credited: referrer={referrer_id} +{bonus_days_referrer}d | "
            f"referred={referred_id} +{REFERRED_BONUS_DAYS}d | payment=${amount_usd:.2f}"
        )
        return {
            "referrer_id":         referrer_id,
            "bonus_days_referrer": bonus_days_referrer,
            "bonus_days_referred": REFERRED_BONUS_DAYS,
        }

    except Exception as e:
        log.error(f"[referral] credit_referral error: {e}")
        return None
    finally:
        conn.close()


def _extend_subscription(conn: sqlite3.Connection, user_id: int, days: int):
    """Add bonus days to a user's tier_expires. Extends from now if expired."""
    row = conn.execute(
        "SELECT tier, tier_expires FROM users WHERE id=?", (user_id,)
    ).fetchone()
    if not row:
        return
    now = time.time()
    current_expires = row['tier_expires'] or 0
    # Extend from whichever is later: now or current expiry
    base = max(now, current_expires)
    new_expires = base + (days * 86400)
    conn.execute(
        "UPDATE users SET tier_expires=? WHERE id=?",
        (new_expires, user_id)
    )


# ── Stats ─────────────────────────────────────────────────────────────
def get_referral_stats(user_id: int) -> Dict:
    """Return referral stats for a user's dashboard display."""
    code = get_or_create_code(user_id)
    conn = _get_db()

    # Count events
    total = conn.execute(
        "SELECT COUNT(*) FROM referral_events WHERE referrer_id=?", (user_id,)
    ).fetchone()[0]
    credited = conn.execute(
        "SELECT COUNT(*), SUM(bonus_days), SUM(payment_amount) FROM referral_events "
        "WHERE referrer_id=? AND status='credited'", (user_id,)
    ).fetchone()
    pending = conn.execute(
        "SELECT COUNT(*) FROM referral_events WHERE referrer_id=? AND status='pending'",
        (user_id,)
    ).fetchone()[0]

    # Recent events
    events = conn.execute(
        """SELECT re.status, re.bonus_days, re.payment_amount, re.credited_at,
                  u.email, u.tier, u.created_at as joined_at
           FROM referral_events re
           JOIN users u ON re.referred_id = u.id
           WHERE re.referrer_id=?
           ORDER BY re.created_at DESC LIMIT 10""",
        (user_id,)
    ).fetchall()
    conn.close()

    return {
        "code":            code,
        "total_referred":  total,
        "total_credited":  credited[0] or 0,
        "total_bonus_days": credited[1] or 0,
        "total_volume_usd": round(credited[2] or 0, 2),
        "pending":         pending,
        "events": [
            {
                "status":       e['status'],
                "bonus_days":   e['bonus_days'],
                "amount_usd":   e['payment_amount'],
                "credited_at":  e['credited_at'],
                "user_email":   e['email'][:3] + "***" + e['email'][e['email'].find('@'):],
                "user_tier":    e['tier'],
            }
            for e in events
        ],
    }


# ── Admin Manual Credit ───────────────────────────────────────────────
def force_mark_credited(referred_id: int, note: str = "manual_grant") -> bool:
    """
    Mark a pending referral event as credited with NO bonus days.
    Used when admin manually grants tier access — no real payment was made
    so the referrer earns nothing (bonus only applies to verified payments).
    """
    conn = _get_db()
    try:
        event = conn.execute(
            "SELECT id, referrer_id FROM referral_events WHERE referred_id=? AND status='pending' "
            "ORDER BY created_at ASC LIMIT 1",
            (referred_id,)
        ).fetchone()
        if not event:
            return False
        conn.execute(
            """UPDATE referral_events
               SET status='credited', payment_id=?, credited_at=?, bonus_days=0
               WHERE id=?""",
            (note, time.time(), event['id'])
        )
        conn.commit()
        log.info(
            f"[referral] force_mark_credited (no bonus — manual grant): "
            f"referred_id={referred_id} referrer_id={event['referrer_id']}"
        )
        return True
    except Exception as e:
        log.error(f"[referral] force_mark_credited error: {e}")
        return False
    finally:
        conn.close()


# ── Admin Stats ───────────────────────────────────────────────────────
def get_admin_referral_stats() -> List[Dict]:
    """Admin view: all referrers with their performance."""
    conn = _get_db()
    rows = conn.execute(
        """SELECT u.id, u.email, u.username,
                  COUNT(re.id) as total,
                  SUM(CASE WHEN re.status='credited' THEN 1 ELSE 0 END) as credited,
                  SUM(CASE WHEN re.status='pending'  THEN 1 ELSE 0 END) as pending,
                  SUM(re.bonus_days) as total_bonus_days,
                  SUM(re.payment_amount) as total_volume
           FROM referral_events re
           JOIN users u ON re.referrer_id = u.id
           GROUP BY re.referrer_id
           ORDER BY total_volume DESC""",
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
