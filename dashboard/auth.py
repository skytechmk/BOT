"""
Aladdin Dashboard — Authentication & User Management
JWT-based auth with SQLite user store.
Tiers: free, plus (53 USDT/mo), pro (109 USDT/mo), ultra (200 USDT/mo — in development)
"""
import os
import re
import sqlite3
import secrets
import smtplib
import time
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

from jose import jwt, JWTError
import bcrypt
from pydantic import BaseModel
from fastapi import Request, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from dotenv import load_dotenv

load_dotenv()

# ── Config ──────────────────────────────────────────────────────────
SECRET_KEY = os.getenv("DASHBOARD_JWT_SECRET", secrets.token_hex(32))
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 72  # 3 days

TIERS = {"free": 0, "plus": 1, "pro": 2, "ultra": 3}
TIER_PRICES = {"plus": 53, "pro": 109, "ultra": 200}  # USDT/month
# Telegram invite for Pro+ subscribers.  Legacy name kept as alias so external
# imports don't break; prefer PRO_TELEGRAM_INVITE in new code.
PRO_TELEGRAM_INVITE = "https://t.me/+-UgYFIj-gqk2MWE0"
ELITE_TELEGRAM_INVITE = PRO_TELEGRAM_INVITE  # deprecated alias

# ── Tier naming canonicalization (Phase 1 of rename rollout) ─────────
# Marketing names differ from legacy DB values:
#    legacy DB   →  new canonical
#    -----------------------------
#    free        →  free
#    pro         →  plus      (rank 1, cheapest paid)
#    elite       →  pro       (rank 2, mid paid)
#    ultra       →  ultra     (rank 3, top paid)
# Until Phase 2 flips the DB + payment product IDs + frontend literals,
# TIER_RENAME_APPLIED stays 'false' and canonicalize_tier() maps legacy
# → new at every read point so Python code can be written in new names.
TIER_RENAME_APPLIED = os.getenv("TIER_RENAME_APPLIED", "false").lower() == "true"
TIERS_CANONICAL = {"free": 0, "plus": 1, "pro": 2, "ultra": 3}

def canonicalize_tier(tier: Optional[str]) -> str:
    """Map any tier value (legacy or new) to the new canonical name.
    Safe to call on None/empty strings (returns 'free').
    """
    if not tier:
        return "free"
    t = str(tier).strip().lower()
    if TIER_RENAME_APPLIED:
        # Post-migration: DB already stores new names; legacy values are
        # only seen on stale JWTs or typo'd API inputs.
        if t == "elite":       # legacy fallback (old admin invite, etc.)
            return "pro"
        return t if t in TIERS_CANONICAL else "free"
    # Phase-1 legacy phase: DB still stores 'pro' (= Plus) and 'elite' (= Pro)
    if t == "pro":
        return "plus"
    if t == "elite":
        return "pro"
    if t in TIERS_CANONICAL:   # 'free', 'plus', 'ultra' — already canonical
        return t
    return "free"

def tier_rank(tier: Optional[str]) -> int:
    """Canonical numeric rank — use for >= comparisons in gates."""
    return TIERS_CANONICAL.get(canonicalize_tier(tier), 0)

DB_PATH = Path(__file__).parent / "users.db"

security = HTTPBearer(auto_error=False)

def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt(rounds=10)).decode('utf-8')

def _verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))


# ── Validation helpers ─────────────────────────────────────────────
_EMAIL_RE = re.compile(
    r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$'
)
_DISPOSABLE_DOMAINS = {
    'mailinator.com', 'guerrillamail.com', 'tempmail.com', 'throwaway.email',
    'yopmail.com', 'sharklasers.com', '10minutemail.com', 'trashmail.com',
    'fakeinbox.com', 'mailnull.com', 'spamgourmet.com', 'dispostable.com',
}


def validate_email_format(email: str) -> Optional[str]:
    """Returns error string or None if valid."""
    email = email.strip().lower()
    if not email:
        return 'Email is required'
    if len(email) > 254:
        return 'Email address too long'
    if not _EMAIL_RE.match(email):
        return 'Enter a valid email address (e.g. name@example.com)'
    domain = email.split('@')[1]
    if domain in _DISPOSABLE_DOMAINS:
        return 'Disposable email addresses are not accepted'
    return None


def validate_password_strength(password: str) -> Optional[str]:
    """Returns error string or None if strong enough."""
    if len(password) < 8:
        return 'Password must be at least 8 characters'
    if not re.search(r'[A-Z]', password):
        return 'Password must contain at least one uppercase letter'
    if not re.search(r'[a-z]', password):
        return 'Password must contain at least one lowercase letter'
    if not re.search(r'[0-9]', password):
        return 'Password must contain at least one number'
    if not re.search(r'[^A-Za-z0-9]', password):
        return 'Password must contain at least one special character (!@#$%^&* etc.)'
    # No 3+ consecutive identical characters (e.g. 'aaa', '111')
    if re.search(r'(.)(\1{2,})', password):
        return 'Password must not contain 3 or more repeating characters (e.g. aaa, 111)'
    # No sequential runs of 4+ (e.g. 1234, abcd)
    s = password.lower()
    for i in range(len(s) - 3):
        a, b, c, d = ord(s[i]), ord(s[i+1]), ord(s[i+2]), ord(s[i+3])
        if a+1 == b and b+1 == c and c+1 == d:
            return 'Password must not contain sequential characters (e.g. 1234, abcd)'
    return None


# ── Models ──────────────────────────────────────────────────────────
class UserRegister(BaseModel):
    email: str
    password: str
    username: str = ""

class UserLogin(BaseModel):
    email: str = ""       # kept for backward compat; can be empty if username is set
    username: str = ""    # login by username
    password: str

class UserInfo(BaseModel):
    id: int
    email: str
    username: str
    tier: str
    tier_expires: Optional[float] = None
    api_key: Optional[str] = None
    created_at: float

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    tier: str
    expires_in: int
    user: UserInfo


# ── Database ────────────────────────────────────────────────────────
def _get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

ADMIN_EMAILS = {'admin@skytech.mk', 'kicko@admin.skytech.mk'}  # Users with admin panel access
ADMIN_DEFAULT_USER = 'admin'
ADMIN_DEFAULT_PASS = 'qwerty'
ADMIN_DEFAULT_EMAIL = 'admin@skytech.mk'

def init_user_db():
    """Create user tables if they don't exist."""
    conn = _get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            username TEXT DEFAULT '',
            password_hash TEXT NOT NULL,
            tier TEXT DEFAULT 'free',
            tier_expires REAL DEFAULT 0,
            api_key TEXT UNIQUE,
            stripe_customer_id TEXT,
            created_at REAL NOT NULL,
            last_login REAL DEFAULT 0,
            is_admin INTEGER DEFAULT 0,
            reminder_sent INTEGER DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
        CREATE INDEX IF NOT EXISTS idx_users_api_key ON users(api_key);

        CREATE TABLE IF NOT EXISTS payment_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount_usd REAL NOT NULL,
            crypto_currency TEXT,
            crypto_amount REAL,
            payment_id TEXT UNIQUE,
            status TEXT DEFAULT 'pending',
            tier_granted TEXT,
            duration_days INTEGER DEFAULT 30,
            created_at REAL NOT NULL,
            completed_at REAL DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS api_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            endpoint TEXT NOT NULL,
            timestamp REAL NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS password_reset_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            token TEXT UNIQUE NOT NULL,
            expires_at REAL NOT NULL,
            used INTEGER DEFAULT 0,
            created_at REAL NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_reset_token ON password_reset_tokens(token);
    """)
    conn.commit()
    conn.close()
    _seed_admin()


def _seed_admin():
    """Ensure the default admin account exists."""
    conn = _get_db()
    existing = conn.execute('SELECT id FROM users WHERE LOWER(email)=?',
                            (ADMIN_DEFAULT_EMAIL.lower(),)).fetchone()
    if not existing:
        api_key = f"ak_{secrets.token_hex(24)}"
        pw_hash = _hash_password(ADMIN_DEFAULT_PASS)
        conn.execute(
            'INSERT INTO users (email, username, password_hash, tier, tier_expires, '
            'api_key, created_at, is_admin) VALUES (?, ?, ?, ?, ?, ?, ?, 1)',
            (ADMIN_DEFAULT_EMAIL, ADMIN_DEFAULT_USER, pw_hash, 'pro',
             time.time() + 365*10*86400, api_key, time.time())
        )
        conn.commit()
        print(f'[auth] Default admin account created: {ADMIN_DEFAULT_USER}')
    else:
        conn.execute('UPDATE users SET is_admin=1 WHERE id=?', (existing['id'],))
        conn.commit()
    conn.close()


# ── User Operations ─────────────────────────────────────────────────
def send_welcome_email(to_email: str, username: str, password: str) -> bool:
    """Send a welcome email to a new user containing their credentials."""
    if not _GMAIL_APP_PASSWORD:
        print(f'[auth] Welcome email skipped — GMAIL_APP_PASSWORD not set')
        return False
    display_name = username if username else to_email.split('@')[0]
    subject = 'Welcome to Anunnaki World Signals'
    html_body = f"""
    <div style="font-family:Inter,Arial,sans-serif;max-width:520px;margin:0 auto;background:#0d0d0f;color:#e8e8e8;border-radius:12px;overflow:hidden">
      <div style="background:#1a1a1f;padding:28px 32px;border-bottom:1px solid #2a2a30">
        <div style="font-size:22px;font-weight:800;color:#f4a236">👋 Welcome to Anunnaki World</div>
        <div style="font-size:13px;color:#888;margin-top:4px">Your account has been created</div>
      </div>
      <div style="padding:28px 32px">
        <p style="margin:0 0 16px;font-size:14px;line-height:1.6">Hi <strong style="color:#f4a236">{display_name}</strong>, your account is ready.</p>
        <div style="background:#1a1a1f;border:1px solid #2a2a30;border-radius:10px;padding:18px 20px;margin-bottom:20px">
          <div style="font-size:12px;color:#888;margin-bottom:10px;text-transform:uppercase;letter-spacing:.05em">Your Login Credentials</div>
          <div style="margin-bottom:8px"><span style="color:#888;font-size:12px">Email:</span><br><span style="color:#f4a236;font-weight:600">{to_email}</span></div>
          <div><span style="color:#888;font-size:12px">Password:</span><br><span style="color:#f4a236;font-weight:600;font-family:monospace;font-size:15px">{password}</span></div>
        </div>
        <div style="background:rgba(255,77,106,0.08);border:1px solid rgba(255,77,106,0.25);border-radius:8px;padding:14px 16px;margin-bottom:20px">
          <div style="font-size:13px;font-weight:700;color:#ff6b85;margin-bottom:4px">⚠️ Important — Save This Password</div>
          <div style="font-size:12px;color:#ccc;line-height:1.6">We store only an encrypted hash of your password — we <strong>cannot recover it</strong> if lost. Save it now, then delete this email. If you forget it, use the password reset link on the login page.</div>
        </div>
        <a href="{_DASHBOARD_URL}" style="display:inline-block;background:#f4a236;color:#000;font-weight:700;font-size:14px;padding:12px 28px;border-radius:8px;text-decoration:none">Go to Dashboard →</a>
      </div>
      <div style="padding:16px 32px;border-top:1px solid #1a1a1f;font-size:11px;color:#444">
        Anunnaki World Signals · If you didn't create this account, ignore this email.
      </div>
    </div>
    """
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = 'Anunnaki World <nikola@skytech.mk>'
        msg['Reply-To'] = 'nikola@skytech.mk'
        msg['To'] = to_email
        msg.attach(MIMEText(html_body, 'html', 'utf-8'))
        with smtplib.SMTP('smtp.gmail.com', 587) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(_GMAIL_USER, _GMAIL_APP_PASSWORD)
            smtp.sendmail(_GMAIL_USER, to_email, msg.as_string())
        print(f'[auth] Welcome email sent to {to_email}')
        return True
    except Exception as e:
        print(f'[auth] Failed to send welcome email to {to_email}: {e}')
        return False


def create_user(email: str, password: str, username: str = "", ref_code: str = "") -> dict:
    """Register a new user. Returns user dict or raises."""
    conn = _get_db()
    try:
        now = time.time()
        api_key = f"ak_{secrets.token_hex(24)}"
        password_hash = _hash_password(password)
        conn.execute(
            "INSERT INTO users (email, username, password_hash, api_key, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (email.lower().strip(), username.strip(), password_hash, api_key, now)
        )
        conn.commit()
        user = conn.execute("SELECT * FROM users WHERE email=?", (email.lower().strip(),)).fetchone()
        user_dict = dict(user)

        # Wire referral if code provided
        if ref_code:
            try:
                from referrals import resolve_code, register_referral
                referrer_id = resolve_code(ref_code)
                if referrer_id:
                    register_referral(user_dict['id'], referrer_id)
            except Exception as _ref_err:
                print(f"[auth] referral hook error: {_ref_err}")
        
        # --- Send Telegram Notification ---
        try:
            import requests
            import os
            bot_token = os.getenv("OPS_TELEGRAM_TOKEN", "")
            chat_id = "-5286675274"
            if bot_token and chat_id:
                text = (
                    f"👤 <b>New User Registered!</b>\n\n"
                    f"<b>Username:</b> {username if username else 'N/A'}\n"
                    f"<b>Email:</b> {email}\n"
                    f"<b>Tier:</b> free\n"
                )
                url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
                resp = requests.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"}, timeout=5)
                if resp.status_code != 200:
                    print(f"Telegram Notification Failed: {resp.text}")
        except Exception as e:
            print(f"Failed to send Telegram notification: {e}")
        # ----------------------------------
        
        # Send welcome email in background (non-blocking — fire and forget)
        import threading
        threading.Thread(
            target=send_welcome_email,
            args=(email.lower().strip(), username.strip(), password),
            daemon=True
        ).start()
        # Send verification email in background
        try:
            from device_security import issue_and_send_verification
            threading.Thread(
                target=issue_and_send_verification,
                args=(user_dict,),
                daemon=True
            ).start()
        except Exception as _e:
            print(f"[auth] verification email hook error: {_e}")
        return user_dict
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="Email already registered")
    finally:
        conn.close()


def authenticate_user(email: str, password: str, username: str = "") -> Optional[dict]:
    """Verify credentials by username OR email. Returns user dict or None."""
    conn = _get_db()
    # Prefer username lookup, fall back to email
    if username.strip():
        user = conn.execute("SELECT * FROM users WHERE LOWER(username)=?", (username.strip().lower(),)).fetchone()
    else:
        user = conn.execute("SELECT * FROM users WHERE email=?", (email.lower().strip(),)).fetchone()
    if not user:
        conn.close()
        return None
    if not _verify_password(password, user['password_hash']):
        conn.close()
        return None
    # Update last login
    conn.execute("UPDATE users SET last_login=? WHERE id=?", (time.time(), user['id']))
    conn.commit()
    conn.close()
    return dict(user)


def get_user_by_id(user_id: int) -> Optional[dict]:
    conn = _get_db()
    user = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    conn.close()
    return dict(user) if user else None


def get_user_by_api_key(api_key: str) -> Optional[dict]:
    conn = _get_db()
    user = conn.execute("SELECT * FROM users WHERE api_key=?", (api_key,)).fetchone()
    conn.close()
    return dict(user) if user else None


def get_effective_tier(user: dict) -> str:
    """Get user's effective tier (checks expiration)."""
    tier = user.get('tier', 'free')
    if tier == 'free':
        return 'free'
    expires = user.get('tier_expires', 0)
    if expires and time.time() > expires:
        # Expired — downgrade to free
        conn = _get_db()
        conn.execute("UPDATE users SET tier='free' WHERE id=?", (user['id'],))
        conn.commit()
        conn.close()
        return 'free'
    return tier


def upgrade_user_tier(user_id: int, tier: str, duration_days: int = 30):
    """Upgrade a user's tier for N days."""
    conn = _get_db()
    expires = time.time() + (duration_days * 86400)
    conn.execute(
        "UPDATE users SET tier=?, tier_expires=? WHERE id=?",
        (tier, expires, user_id)
    )
    conn.commit()
    conn.close()


def get_user_count() -> dict:
    conn = _get_db()
    total = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    plus  = conn.execute("SELECT COUNT(*) FROM users WHERE tier='plus'  AND tier_expires > ?", (time.time(),)).fetchone()[0]
    pro   = conn.execute("SELECT COUNT(*) FROM users WHERE tier='pro'   AND tier_expires > ?", (time.time(),)).fetchone()[0]
    ultra = conn.execute("SELECT COUNT(*) FROM users WHERE tier='ultra' AND tier_expires > ?", (time.time(),)).fetchone()[0]
    conn.close()
    # Legacy keys 'pro' and 'elite' kept for admin UI backward compatibility
    # until the frontend sweep lands (Phase 2 — Python-side only).
    return {
        "total": total,
        "plus":  plus,
        "pro":   pro,
        "ultra": ultra,
        "free":  total - plus - pro - ultra,
        # Deprecated legacy keys (same values under new canonical names)
        "elite": pro,      # legacy 'elite' == new 'pro'
    }


def is_admin(user: Optional[dict]) -> bool:
    """Check if user has admin privileges."""
    if not user:
        return False
    return (user.get('is_admin', 0) == 1 or
            user.get('email', '').lower() in ADMIN_EMAILS)


def get_all_users() -> list:
    """Admin: get all users with subscription + device + verification details."""
    conn = _get_db()
    # Tolerate DBs created before device_security migration
    cols = {r['name'] for r in conn.execute('PRAGMA table_info(users)')}
    ev_col = 'email_verified' if 'email_verified' in cols else '0 AS email_verified'
    dlo_col = 'device_limit_override' if 'device_limit_override' in cols else 'NULL AS device_limit_override'
    rows = conn.execute(
        f'SELECT id, email, username, tier, tier_expires, created_at, last_login, is_admin, '
        f'reminder_sent, {ev_col}, {dlo_col} FROM users ORDER BY created_at DESC'
    ).fetchall()

    # Device counts per user
    device_counts = {}
    try:
        for r in conn.execute(
            "SELECT user_id, COUNT(*) AS c FROM user_devices WHERE revoked=0 GROUP BY user_id"
        ).fetchall():
            device_counts[r['user_id']] = r['c']
    except sqlite3.OperationalError:
        pass
    conn.close()
    now = time.time()
    users = []
    for r in rows:
        r = dict(r)
        tier = r['tier']
        expires = r.get('tier_expires', 0) or 0
        if tier != 'free' and expires and now > expires:
            tier = 'free (expired)'
        days_left = max(0, int((expires - now) / 86400)) if expires and expires > now else 0
        users.append({
            'id': r['id'],
            'email': r['email'],
            'username': r.get('username', ''),
            'tier': tier,
            'tier_raw': r['tier'],
            'tier_expires': expires,
            'days_left': days_left,
            'created_at': r['created_at'],
            'last_login': r.get('last_login', 0),
            'is_admin': r.get('is_admin', 0),
            'email_verified': bool(r.get('email_verified', 0)),
            'device_limit_override': r.get('device_limit_override'),
            'device_count': int(device_counts.get(r['id'], 0)),
        })
    return users


def admin_set_tier(user_id: int, tier: str, days: int = 30) -> dict:
    """Admin: set a user's tier with duration. Blocks changing admin tier."""
    conn = _get_db()
    user = conn.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone()
    if not user:
        conn.close()
        return {'error': 'User not found'}
    if user['is_admin']:
        conn.close()
        return {'error': "Admin accounts don't carry subscription tiers — no change made."}
    if tier == 'free':
        conn.execute('UPDATE users SET tier=?, tier_expires=0, reminder_sent=0 WHERE id=?', (tier, user_id))
    else:
        expires = time.time() + (days * 86400)
        conn.execute('UPDATE users SET tier=?, tier_expires=?, reminder_sent=0 WHERE id=?', (tier, expires, user_id))
    conn.commit()
    conn.close()
    return {'success': True, 'user_id': user_id, 'tier': tier, 'days': days}


def admin_deactivate_user(user_id: int) -> dict:
    """Admin: deactivate user (downgrade to free). Blocks on admin rows."""
    conn = _get_db()
    u = conn.execute('SELECT is_admin FROM users WHERE id=?', (user_id,)).fetchone()
    conn.close()
    if u and u['is_admin']:
        return {'error': 'Admin accounts cannot be deactivated.'}
    return admin_set_tier(user_id, 'free', 0)


def admin_delete_user(user_id: int) -> dict:
    """Admin: permanently delete a user. Hard-blocks deletion of any admin."""
    conn = _get_db()
    user = conn.execute('SELECT id, email, username, is_admin FROM users WHERE id=?', (user_id,)).fetchone()
    if not user:
        conn.close()
        return {'error': 'User not found'}
    if user['is_admin']:
        conn.close()
        return {'error': 'Admin accounts cannot be deleted from the panel.'}
    conn.execute('DELETE FROM payment_history WHERE user_id=?', (user_id,))
    conn.execute('DELETE FROM users WHERE id=?', (user_id,))
    conn.commit()
    conn.close()
    return {'success': True, 'deleted_user': user['email']}


def check_subscription_expiry() -> dict:
    """Check all users for upcoming/past expiry. Returns actions taken."""
    conn = _get_db()
    now = time.time()
    three_days = 3 * 86400
    actions = {'reminders_sent': [], 'deactivated': []}

    # Find users with paid tiers
    rows = conn.execute(
        "SELECT id, email, username, tier, tier_expires, reminder_sent "
        "FROM users WHERE tier != 'free' AND tier_expires > 0"
    ).fetchall()

    for r in rows:
        r = dict(r)
        expires = r['tier_expires']
        time_left = expires - now

        # Already expired → deactivate
        if time_left <= 0:
            conn.execute('UPDATE users SET tier=?, tier_expires=0, reminder_sent=0 WHERE id=?',
                         ('free', r['id']))
            actions['deactivated'].append({
                'id': r['id'], 'email': r['email'], 'username': r['username'],
                'old_tier': r['tier']
            })
            _send_expiry_notification(r, 'expired')

        # Within 3 days → send reminder (once)
        elif time_left <= three_days and not r.get('reminder_sent', 0):
            conn.execute('UPDATE users SET reminder_sent=1 WHERE id=?', (r['id'],))
            actions['reminders_sent'].append({
                'id': r['id'], 'email': r['email'], 'username': r['username'],
                'days_left': round(time_left / 86400, 1)
            })
            _send_expiry_notification(r, 'reminder', round(time_left / 86400, 1))

    conn.commit()
    conn.close()
    return actions


def _send_expiry_notification(user: dict, event_type: str, days_left: float = 0):
    """Send Telegram notification about subscription expiry."""
    try:
        import requests as req
        bot_token = os.getenv('OPS_TELEGRAM_TOKEN', '')
        chat_id = '-5286675274'
        if not bot_token:
            return
        if event_type == 'reminder':
            text = (
                f"⏰ <b>Subscription Expiring Soon!</b>\n\n"
                f"👤 <b>User:</b> {user.get('username', 'N/A')} ({user['email']})\n"
                f"📦 <b>Tier:</b> {user['tier'].upper()}\n"
                f"⏳ <b>Expires in:</b> {days_left} days\n\n"
                f"<i>User will be auto-deactivated if no renewal.</i>"
            )
        else:  # expired
            text = (
                f"🚫 <b>Subscription Expired — User Deactivated</b>\n\n"
                f"👤 <b>User:</b> {user.get('username', 'N/A')} ({user['email']})\n"
                f"📦 <b>Was:</b> {user['tier'].upper()}\n"
                f"🔻 <b>Now:</b> FREE\n\n"
                f"<i>User must renew to regain access.</i>"
            )
        url = f'https://api.telegram.org/bot{bot_token}/sendMessage'
        req.post(url, json={'chat_id': chat_id, 'text': text, 'parse_mode': 'HTML'}, timeout=5)
    except Exception as e:
        print(f'Expiry notification failed: {e}')


# ── Password Reset ──────────────────────────────────────────────────
_GMAIL_USER = os.getenv('GMAIL_USER', 'nikola@skytech.mk')
_GMAIL_APP_PASSWORD = os.getenv('GMAIL_APP_PASSWORD', '')
_DASHBOARD_URL = os.getenv('DASHBOARD_URL', 'https://anunnakiworld.com')
_RESET_TOKEN_TTL = 3600  # 1 hour


def _send_reset_email(to_email: str, token: str) -> bool:
    """Send password reset email via Gmail SMTP with App Password."""
    if not _GMAIL_APP_PASSWORD:
        print('[auth] GMAIL_APP_PASSWORD not set — cannot send reset email')
        return False
    reset_url = f'{_DASHBOARD_URL}/reset-password?token={token}'
    subject = 'Anunnaki World — Password Reset'
    html_body = f"""
    <div style="font-family:Inter,Arial,sans-serif;max-width:480px;margin:0 auto;background:#0d0d0f;color:#e8e8e8;border-radius:12px;overflow:hidden">
      <div style="background:#1a1a1f;padding:28px 32px;border-bottom:1px solid #2a2a30">
        <div style="font-size:22px;font-weight:800;color:#f4a236">🔐 Password Reset</div>
        <div style="font-size:13px;color:#888;margin-top:4px">Anunnaki World Signals</div>
      </div>
      <div style="padding:28px 32px">
        <p style="margin:0 0 16px;font-size:14px;line-height:1.6">You requested a password reset for your account (<strong style="color:#f4a236">{to_email}</strong>).</p>
        <p style="margin:0 0 24px;font-size:14px;line-height:1.6">Click the button below to set a new password. This link expires in <strong>1 hour</strong>.</p>
        <a href="{reset_url}" style="display:inline-block;background:#f4a236;color:#000;font-weight:700;font-size:14px;padding:12px 28px;border-radius:8px;text-decoration:none">Reset My Password</a>
        <p style="margin:24px 0 0;font-size:12px;color:#666">If you didn't request this, ignore this email — your password won't change.</p>
        <p style="margin:8px 0 0;font-size:11px;color:#444;word-break:break-all">Or copy this link: {reset_url}</p>
      </div>
    </div>
    """
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = 'Anunnaki World <nikola@skytech.mk>'
        msg['Reply-To'] = 'nikola@skytech.mk'
        msg['To'] = to_email
        msg.attach(MIMEText(html_body, 'html', 'utf-8'))
        with smtplib.SMTP('smtp.gmail.com', 587) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(_GMAIL_USER, _GMAIL_APP_PASSWORD)
            smtp.sendmail(_GMAIL_USER, to_email, msg.as_string())
        print(f'[auth] Reset email sent to {to_email}')
        return True
    except Exception as e:
        print(f'[auth] Failed to send reset email to {to_email}: {e}')
        print(f'[auth] MANUAL FALLBACK — share this link with the user: {reset_url}')
        return False


def request_password_reset(email: str) -> dict:
    """Generate a reset token and send email. Always returns success to prevent user enumeration."""
    conn = _get_db()
    user = conn.execute(
        'SELECT id, email FROM users WHERE email=?', (email.lower().strip(),)
    ).fetchone()
    if user:
        # Invalidate any existing unused tokens for this user
        conn.execute(
            'UPDATE password_reset_tokens SET used=1 WHERE user_id=? AND used=0',
            (user['id'],)
        )
        token = secrets.token_urlsafe(32)
        expires_at = time.time() + _RESET_TOKEN_TTL
        conn.execute(
            'INSERT INTO password_reset_tokens (user_id, token, expires_at, created_at) VALUES (?,?,?,?)',
            (user['id'], token, expires_at, time.time())
        )
        conn.commit()
        conn.close()
        _send_reset_email(user['email'], token)
    else:
        conn.close()
    # Always return the same response to prevent email enumeration
    return {'ok': True, 'message': 'If that email exists, a reset link has been sent.'}


def reset_password_with_token(token: str, new_password: str) -> dict:
    """Validate token and set new password."""
    if len(new_password) < 6:
        return {'error': 'Password must be at least 6 characters'}
    conn = _get_db()
    row = conn.execute(
        'SELECT prt.id, prt.user_id, prt.expires_at, prt.used '
        'FROM password_reset_tokens prt WHERE prt.token=?',
        (token,)
    ).fetchone()
    if not row:
        conn.close()
        return {'error': 'Invalid or expired reset link'}
    if row['used']:
        conn.close()
        return {'error': 'This reset link has already been used'}
    if time.time() > row['expires_at']:
        conn.execute('UPDATE password_reset_tokens SET used=1 WHERE id=?', (row['id'],))
        conn.commit()
        conn.close()
        return {'error': 'Reset link has expired — please request a new one'}
    pw_hash = _hash_password(new_password)
    conn.execute('UPDATE users SET password_hash=? WHERE id=?', (pw_hash, row['user_id']))
    conn.execute('UPDATE password_reset_tokens SET used=1 WHERE id=?', (row['id'],))
    conn.commit()
    conn.close()
    return {'ok': True, 'message': 'Password updated successfully. You can now log in.'}


# ── JWT Token Operations ────────────────────────────────────────────
def create_access_token(user: dict) -> str:
    """Create a JWT access token for a user."""
    tier = get_effective_tier(user)
    expire = datetime.now(timezone.utc) + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    payload = {
        "sub": str(user['id']),
        "email": user['email'],
        "tier": tier,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    """Decode and validate a JWT token. Returns payload or None."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None


# ── FastAPI Dependencies ─────────────────────────────────────────────
async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> Optional[dict]:
    """Extract user from JWT token or API key. Returns None for unauthenticated."""
    # Try JWT token
    if credentials:
        payload = decode_token(credentials.credentials)
        if payload:
            user = get_user_by_id(int(payload['sub']))
            if user:
                user['_effective_tier'] = get_effective_tier(user)
                return user

    # Try API key from header
    api_key = request.headers.get("X-API-Key")
    if api_key:
        user = get_user_by_api_key(api_key)
        if user:
            user['_effective_tier'] = get_effective_tier(user)
            return user

    return None  # Unauthenticated = free tier


def require_tier(minimum_tier: str):
    """Dependency that requires a minimum tier level.
    Admins ALWAYS bypass tier checks — they have access to every feature.
    """
    async def _check(user: Optional[dict] = Depends(get_current_user)):
        if user is None:
            if minimum_tier != "free":
                raise HTTPException(status_code=401, detail="Authentication required")
            return None
        # Admins bypass all tier gates.
        if is_admin(user):
            return user
        tier = user.get('_effective_tier', 'free')
        # Canonical (new-naming) comparison — works for both legacy and new
        # arguments (e.g. require_tier("elite") and require_tier("pro") both
        # resolve to the same rank=2 gate).
        if tier_rank(tier) < tier_rank(minimum_tier):
            raise HTTPException(
                status_code=403,
                detail=f"This feature requires {canonicalize_tier(minimum_tier).upper()} tier. "
                       f"Current: {canonicalize_tier(tier).upper()}"
            )
        return user
    return _check


async def require_admin(user: Optional[dict] = Depends(get_current_user)) -> dict:
    """Dependency that requires admin privileges. Use on admin routes."""
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    if not is_admin(user):
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


def to_user_info(user: dict) -> dict:
    """Convert DB user row to safe public info."""
    admin = is_admin(user)
    tier = get_effective_tier(user)
    # Functional access tier: admin gets 'ultra' (highest tier) so every
    # feature gate in the UI passes. UI uses `is_admin` flag to hide
    # tier/remaining badges so the ULTRA label doesn't show on admin accounts.
    access_tier = 'ultra' if admin else tier
    info = {
        "id": user['id'],
        "email": user['email'],
        "username": user.get('username', ''),
        "tier": access_tier,
        "tier_expires": 0 if admin else user.get('tier_expires', 0),
        # Pro-tier (rank ≥ 2, i.e. legacy 'elite' or new 'pro') + admins get
        # an API key + the Telegram invite.  Canonical compare so Phase 2
        # doesn't require touching this block.
        "api_key": user.get('api_key') if (admin or tier_rank(tier) >= TIERS_CANONICAL['pro']) else None,
        "created_at": user['created_at'],
        "is_admin": admin,
        "email_verified": bool(user.get('email_verified', 0)),
    }
    if admin or tier_rank(tier) >= TIERS_CANONICAL['pro']:
        info['telegram_invite'] = ELITE_TELEGRAM_INVITE
    try:
        from device_security import effective_device_limit
        info['device_limit'] = effective_device_limit({
            **user, 'is_admin': admin, 'tier': tier,
        })
    except Exception:
        info['device_limit'] = {"limit": 1, "base": 1, "extras": 0, "override": None, "unlimited": admin}
    return info
