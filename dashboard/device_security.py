"""
Anunnaki Dashboard — Device Security, Email Verification & Site Settings
=========================================================================
- Device fingerprint registration & enforcement (Plus=1, Pro=2, Ultra=3)
- Extra-device paid monthly slots (admin grant or user purchase)
- Email verification tokens & resend
- Site-wide settings (maintenance mode, dev banner)
- IP geolocation (free public API with local cache)
- Device-access email notifications (sent once per new fingerprint)
"""
from __future__ import annotations

import os
import json
import time
import smtplib
import hashlib
import secrets
import sqlite3
import threading
from pathlib import Path
from typing import Optional
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests

DB_PATH = Path(__file__).parent / "users.db"

# ── Tier → base device limit ──────────────────────────────────────────
# Canonical tier names (free/plus/pro/ultra) post-Phase-2 rename.
# Legacy values ('pro'=Plus, 'elite'=Pro) are routed through
# canonicalize_tier() in _tier_device_base so stale JWTs keep working.
TIER_DEVICE_LIMIT = {
    "free":  1,
    "plus":  1,   # cheapest paid
    "pro":   2,   # mid paid
    "ultra": 3,   # top paid
}

# Extra-device monthly price (USDT) — same canonical key scheme.
EXTRA_DEVICE_MONTHLY_PRICE = {
    "plus":  16,
    "pro":   33,
    "ultra": 60,
}


def _tier_device_base(tier: str) -> int:
    """Look up base device limit with canonical tier resolution.  Accepts
    legacy values ('pro'=Plus, 'elite'=Pro) via canonicalize_tier and maps
    them to the new canonical names before the dict lookup.
    """
    try:
        from auth import canonicalize_tier
        canon = canonicalize_tier(tier)
    except Exception:
        canon = (tier or "free").lower()
    return TIER_DEVICE_LIMIT.get(canon, 1)

# ── SMTP config (shared with auth.py) ─────────────────────────────────
_GMAIL_USER = os.getenv("GMAIL_USER", "nikola@skytech.mk")
_GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")
_DASHBOARD_URL = os.getenv("DASHBOARD_URL", "https://anunnakiworld.com")
_SUPPORT_EMAIL = os.getenv("SUPPORT_EMAIL", "nikola@skytech.mk")

_VERIFY_TOKEN_TTL = 7 * 86400  # 7 days
_GEO_CACHE: dict[str, dict] = {}
_GEO_CACHE_LOCK = threading.Lock()
_GEO_CACHE_TTL = 24 * 3600


# ═════════════════════════════════════════════════════════════════════
#  DB initialisation
# ═════════════════════════════════════════════════════════════════════
def _get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_device_security_db():
    """Additive migrations on users.db."""
    conn = _get_db()
    # Column migrations on users ----------------------------------------
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(users)")}
    if "email_verified" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN email_verified INTEGER DEFAULT 0")
    if "device_limit_override" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN device_limit_override INTEGER DEFAULT NULL")
    if "notif_device_emails" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN notif_device_emails INTEGER DEFAULT 1")

    # Tables ------------------------------------------------------------
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS site_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS user_devices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            fingerprint TEXT NOT NULL,
            label TEXT DEFAULT '',
            first_ip TEXT DEFAULT '',
            first_city TEXT DEFAULT '',
            first_country TEXT DEFAULT '',
            first_ua TEXT DEFAULT '',
            last_ip TEXT DEFAULT '',
            last_seen REAL NOT NULL,
            created_at REAL NOT NULL,
            revoked INTEGER DEFAULT 0,
            notified INTEGER DEFAULT 0,
            UNIQUE(user_id, fingerprint),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_ud_user ON user_devices(user_id);

        CREATE TABLE IF NOT EXISTS device_access_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            device_id INTEGER,
            fingerprint TEXT,
            ip TEXT,
            city TEXT,
            country TEXT,
            user_agent TEXT,
            event TEXT,          -- login | new_device | blocked | revoked
            created_at REAL NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_dal_user ON device_access_log(user_id, created_at);

        CREATE TABLE IF NOT EXISTS email_verifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            token TEXT UNIQUE NOT NULL,
            expires_at REAL NOT NULL,
            used INTEGER DEFAULT 0,
            created_at REAL NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_ev_token ON email_verifications(token);

        CREATE TABLE IF NOT EXISTS extra_device_slots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            slot_count INTEGER DEFAULT 1,
            source TEXT DEFAULT 'admin', -- admin | paid
            paid_until REAL DEFAULT 0,   -- 0 = permanent (admin grant)
            note TEXT DEFAULT '',
            created_at REAL NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_eds_user ON extra_device_slots(user_id);
    """)
    # Seed defaults
    if not conn.execute("SELECT 1 FROM site_settings WHERE key='maintenance_mode'").fetchone():
        conn.execute("INSERT INTO site_settings VALUES (?,?,?)",
                     ("maintenance_mode", "0", time.time()))
    if not conn.execute("SELECT 1 FROM site_settings WHERE key='maintenance_message'").fetchone():
        conn.execute("INSERT INTO site_settings VALUES (?,?,?)",
                     ("maintenance_message",
                      "The platform is currently under maintenance. Copy-trading is paused. We'll be back shortly.",
                      time.time()))
    conn.commit()
    conn.close()


# ═════════════════════════════════════════════════════════════════════
#  Site settings
# ═════════════════════════════════════════════════════════════════════
def get_setting(key: str, default: str = "") -> str:
    conn = _get_db()
    r = conn.execute("SELECT value FROM site_settings WHERE key=?", (key,)).fetchone()
    conn.close()
    return r["value"] if r else default


def set_setting(key: str, value: str) -> None:
    conn = _get_db()
    conn.execute(
        "INSERT INTO site_settings (key, value, updated_at) VALUES (?,?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        (key, str(value), time.time())
    )
    conn.commit()
    conn.close()


def is_maintenance_mode() -> bool:
    return get_setting("maintenance_mode", "0") == "1"


def get_maintenance_info() -> dict:
    return {
        "enabled": is_maintenance_mode(),
        "message": get_setting("maintenance_message", ""),
        "updated_at": float(get_setting("maintenance_updated_at", "0") or 0),
    }


def set_maintenance_mode(enabled: bool, message: str = "") -> None:
    set_setting("maintenance_mode", "1" if enabled else "0")
    if message:
        set_setting("maintenance_message", message)
    set_setting("maintenance_updated_at", str(time.time()))


# ═════════════════════════════════════════════════════════════════════
#  IP geolocation
# ═════════════════════════════════════════════════════════════════════
def geolocate_ip(ip: str) -> dict:
    """Lookup IP → {city, region, country, timezone}. Cached 24h."""
    if not ip or ip.startswith(("127.", "10.", "192.168.", "172.")) or ip == "::1":
        return {"city": "Local", "region": "", "country": "", "timezone": ""}
    with _GEO_CACHE_LOCK:
        entry = _GEO_CACHE.get(ip)
        if entry and time.time() - entry.get("_cached_at", 0) < _GEO_CACHE_TTL:
            return entry
    try:
        # ipapi.co free tier: 1000/day, no key needed
        r = requests.get(f"https://ipapi.co/{ip}/json/", timeout=4)
        if r.status_code == 200:
            d = r.json()
            result = {
                "city": d.get("city", "") or "",
                "region": d.get("region", "") or "",
                "country": d.get("country_name", "") or "",
                "country_code": d.get("country_code", "") or "",
                "timezone": d.get("timezone", "") or "",
                "latitude": d.get("latitude"),
                "longitude": d.get("longitude"),
                "_cached_at": time.time(),
            }
            with _GEO_CACHE_LOCK:
                _GEO_CACHE[ip] = result
            return result
    except Exception as e:
        print(f"[device_security] geolocate_ip({ip}) failed: {e}")
    # Fallback
    try:
        r = requests.get(f"http://ip-api.com/json/{ip}", timeout=4)
        if r.status_code == 200:
            d = r.json()
            result = {
                "city": d.get("city", "") or "",
                "region": d.get("regionName", "") or "",
                "country": d.get("country", "") or "",
                "country_code": d.get("countryCode", "") or "",
                "timezone": d.get("timezone", "") or "",
                "latitude": d.get("lat"),
                "longitude": d.get("lon"),
                "_cached_at": time.time(),
            }
            with _GEO_CACHE_LOCK:
                _GEO_CACHE[ip] = result
            return result
    except Exception:
        pass
    return {"city": "", "region": "", "country": "", "timezone": ""}


def client_ip_from_request(request) -> str:
    """Extract real IP from request headers honoring reverse proxy."""
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    real = request.headers.get("x-real-ip", "")
    if real:
        return real.strip()
    return request.client.host if request.client else ""


# ═════════════════════════════════════════════════════════════════════
#  Device fingerprinting
# ═════════════════════════════════════════════════════════════════════
def canonical_fingerprint(raw: str) -> str:
    """Normalize a client-supplied fingerprint to a stable hex digest."""
    if not raw:
        return ""
    return hashlib.sha256(raw.strip().encode()).hexdigest()[:32]


def count_active_extra_slots(user_id: int, conn=None) -> int:
    own = False
    if conn is None:
        conn = _get_db()
        own = True
    now = time.time()
    rows = conn.execute(
        "SELECT slot_count, paid_until FROM extra_device_slots WHERE user_id=?",
        (user_id,)
    ).fetchall()
    total = 0
    for r in rows:
        # paid_until=0 means admin-granted permanent slot
        if r["paid_until"] == 0 or r["paid_until"] > now:
            total += int(r["slot_count"])
    if own:
        conn.close()
    return total


def effective_device_limit(user: dict) -> dict:
    """Return {limit, base, extras, override, unlimited}."""
    conn = _get_db()
    override = user.get("device_limit_override")
    tier = user.get("tier", "free")
    if user.get("is_admin"):
        conn.close()
        return {"limit": 9999, "base": 9999, "extras": 0, "override": None, "unlimited": True}
    base = _tier_device_base(tier)
    extras = count_active_extra_slots(user["id"], conn)
    conn.close()
    if override is not None and override >= 0:
        if override >= 9999:
            return {"limit": 9999, "base": base, "extras": extras, "override": override, "unlimited": True}
        return {"limit": int(override), "base": base, "extras": extras, "override": override, "unlimited": False}
    return {"limit": base + extras, "base": base, "extras": extras, "override": None, "unlimited": False}


def list_devices(user_id: int) -> list:
    conn = _get_db()
    rows = conn.execute(
        "SELECT id, fingerprint, label, first_ip, first_city, first_country, "
        "first_ua, last_ip, last_seen, created_at, revoked "
        "FROM user_devices WHERE user_id=? ORDER BY last_seen DESC",
        (user_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_device(user_id: int, fingerprint: str) -> Optional[dict]:
    conn = _get_db()
    r = conn.execute(
        "SELECT * FROM user_devices WHERE user_id=? AND fingerprint=?",
        (user_id, fingerprint)
    ).fetchone()
    conn.close()
    return dict(r) if r else None


def register_or_touch_device(
    user: dict,
    fingerprint: str,
    ip: str,
    user_agent: str,
    label: str = "",
) -> dict:
    """
    Core enforcement: on every login/session boot, register or touch the
    device. Returns dict with keys {ok, new, device_id, limit, current_count, blocked, reason}.
    """
    if not fingerprint:
        return {"ok": False, "new": False, "blocked": True, "reason": "No device fingerprint provided"}
    fp = canonical_fingerprint(fingerprint)
    conn = _get_db()
    existing = conn.execute(
        "SELECT * FROM user_devices WHERE user_id=? AND fingerprint=?",
        (user["id"], fp)
    ).fetchone()
    now = time.time()
    limit_info = effective_device_limit(user)
    limit = limit_info["limit"]
    active_count = conn.execute(
        "SELECT COUNT(*) FROM user_devices WHERE user_id=? AND revoked=0",
        (user["id"],)
    ).fetchone()[0]

    if existing:
        if existing["revoked"]:
            conn.close()
            return {
                "ok": False, "new": False, "blocked": True,
                "reason": "This device was revoked by the admin. Contact support.",
                "limit": limit, "current_count": active_count,
            }
        conn.execute(
            "UPDATE user_devices SET last_ip=?, last_seen=? WHERE id=?",
            (ip, now, existing["id"])
        )
        conn.execute(
            "INSERT INTO device_access_log (user_id, device_id, fingerprint, ip, user_agent, event, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (user["id"], existing["id"], fp, ip, user_agent[:400], "login", now)
        )
        conn.commit()
        conn.close()
        return {
            "ok": True, "new": False, "device_id": existing["id"],
            "limit": limit, "current_count": active_count, "blocked": False,
        }

    # New device. Check limit first.
    if active_count >= limit:
        conn.execute(
            "INSERT INTO device_access_log (user_id, fingerprint, ip, user_agent, event, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (user["id"], fp, ip, user_agent[:400], "blocked", now)
        )
        conn.commit()
        conn.close()
        return {
            "ok": False, "new": True, "blocked": True,
            "reason": f"Device limit reached ({active_count}/{limit}). "
                      f"Revoke an existing device from the Account panel, or contact admin to purchase an extra device slot.",
            "limit": limit, "current_count": active_count,
        }

    # Register new device
    geo = geolocate_ip(ip)
    cur = conn.execute(
        "INSERT INTO user_devices "
        "(user_id, fingerprint, label, first_ip, first_city, first_country, first_ua, "
        " last_ip, last_seen, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (user["id"], fp, label[:80], ip,
         geo.get("city", ""), geo.get("country", ""), user_agent[:400],
         ip, now, now)
    )
    device_id = cur.lastrowid
    conn.execute(
        "INSERT INTO device_access_log (user_id, device_id, fingerprint, ip, city, country, user_agent, event, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (user["id"], device_id, fp, ip,
         geo.get("city", ""), geo.get("country", ""),
         user_agent[:400], "new_device", now)
    )
    conn.commit()
    conn.close()

    # Fire-and-forget notification email
    if user.get("notif_device_emails", 1):
        threading.Thread(
            target=_send_new_device_email,
            args=(user, fp, ip, geo, user_agent),
            daemon=True,
        ).start()

    return {
        "ok": True, "new": True, "device_id": device_id,
        "limit": limit, "current_count": active_count + 1, "blocked": False,
    }


def revoke_device(user_id: int, device_id: int, by_admin: bool = False) -> dict:
    conn = _get_db()
    r = conn.execute(
        "SELECT id, user_id FROM user_devices WHERE id=?", (device_id,)
    ).fetchone()
    if not r:
        conn.close()
        return {"error": "Device not found"}
    if not by_admin and r["user_id"] != user_id:
        conn.close()
        return {"error": "Not your device"}
    conn.execute("UPDATE user_devices SET revoked=1 WHERE id=?", (device_id,))
    conn.execute(
        "INSERT INTO device_access_log (user_id, device_id, event, created_at) VALUES (?,?,?,?)",
        (r["user_id"], device_id, "revoked", time.time())
    )
    conn.commit()
    conn.close()
    return {"ok": True}


def admin_set_device_override(user_id: int, limit: Optional[int]) -> dict:
    """Admin: set device_limit_override. Pass None for default, -1/9999 for unlimited."""
    conn = _get_db()
    if limit is None:
        conn.execute("UPDATE users SET device_limit_override=NULL WHERE id=?", (user_id,))
    else:
        conn.execute("UPDATE users SET device_limit_override=? WHERE id=?", (int(limit), user_id))
    conn.commit()
    conn.close()
    return {"ok": True}


def admin_grant_extra_slots(user_id: int, slot_count: int, months: int = 0, note: str = "") -> dict:
    """Admin grants extra device slots. months=0 → permanent."""
    conn = _get_db()
    paid_until = 0 if months <= 0 else time.time() + months * 30 * 86400
    conn.execute(
        "INSERT INTO extra_device_slots (user_id, slot_count, source, paid_until, note, created_at) "
        "VALUES (?,?,?,?,?,?)",
        (user_id, int(slot_count), "admin", paid_until, note[:200], time.time())
    )
    conn.commit()
    conn.close()
    return {"ok": True}


# ═════════════════════════════════════════════════════════════════════
#  New-device email notification
# ═════════════════════════════════════════════════════════════════════
def _send_new_device_email(user: dict, fingerprint: str, ip: str, geo: dict, user_agent: str) -> bool:
    if not _GMAIL_APP_PASSWORD:
        print("[device_security] SMTP disabled — skipping new-device email")
        return False
    to_email = user.get("email", "")
    if not to_email:
        return False
    location = ", ".join([x for x in [geo.get("city", ""), geo.get("region", ""), geo.get("country", "")] if x]) or "Unknown"
    when = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
    support = f'<a href="mailto:{_SUPPORT_EMAIL}" style="color:#f4a236">{_SUPPORT_EMAIL}</a>'
    html = f"""
    <div style="font-family:Inter,Arial,sans-serif;max-width:540px;margin:0 auto;background:#0d0d0f;color:#e8e8e8;border-radius:12px;overflow:hidden">
      <div style="background:#1a1a1f;padding:28px 32px;border-bottom:1px solid #2a2a30">
        <div style="font-size:22px;font-weight:800;color:#f4a236">🛡️ New Device Sign-In</div>
        <div style="font-size:13px;color:#888;margin-top:4px">Anunnaki World Signals — security alert</div>
      </div>
      <div style="padding:28px 32px">
        <p style="margin:0 0 16px;font-size:14px;line-height:1.6">
          Your account was just accessed from a <strong>new device</strong>. If this was you, no action is needed.
        </p>
        <div style="background:#1a1a1f;border:1px solid #2a2a30;border-radius:10px;padding:16px 20px;margin-bottom:18px;font-size:13px;line-height:1.8">
          <div><span style="color:#888">Time:</span> <strong style="color:#f4a236">{when}</strong></div>
          <div><span style="color:#888">IP Address:</span> <strong>{ip or 'unknown'}</strong></div>
          <div><span style="color:#888">Location:</span> <strong>{location}</strong></div>
          <div><span style="color:#888">Timezone:</span> <strong>{geo.get('timezone', 'unknown') or 'unknown'}</strong></div>
          <div style="word-break:break-all"><span style="color:#888">Browser:</span> <span style="font-size:12px;color:#aaa">{(user_agent or 'unknown')[:220]}</span></div>
          <div><span style="color:#888">Device ID:</span> <code style="font-size:11px;color:#aaa">{fingerprint[:16]}…</code></div>
        </div>
        <div style="background:rgba(255,77,106,0.08);border:1px solid rgba(255,77,106,0.25);border-radius:8px;padding:14px 16px;margin-bottom:20px">
          <div style="font-size:13px;font-weight:700;color:#ff6b85;margin-bottom:4px">Not you?</div>
          <div style="font-size:12px;color:#ccc;line-height:1.6">
            Change your password immediately and revoke this device from the <em>Account → Devices</em> panel, then contact {support}.
          </div>
        </div>
        <a href="{_DASHBOARD_URL}" style="display:inline-block;background:#f4a236;color:#000;font-weight:700;font-size:14px;padding:12px 28px;border-radius:8px;text-decoration:none">Open Dashboard →</a>
      </div>
      <div style="padding:16px 32px;border-top:1px solid #1a1a1f;font-size:11px;color:#444">
        Anunnaki World Signals · You only receive this email the first time a new device signs in. Manage alerts in Account → Settings.
      </div>
    </div>
    """
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"🛡️ New device sign-in — {location}"
        msg["From"] = "Anunnaki World <nikola@skytech.mk>"
        msg["Reply-To"] = _SUPPORT_EMAIL
        msg["To"] = to_email
        msg.attach(MIMEText(html, "html", "utf-8"))
        with smtplib.SMTP("smtp.gmail.com", 587) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(_GMAIL_USER, _GMAIL_APP_PASSWORD)
            smtp.sendmail(_GMAIL_USER, to_email, msg.as_string())
        # Mark notified
        conn = _get_db()
        conn.execute(
            "UPDATE user_devices SET notified=1 WHERE user_id=? AND fingerprint=?",
            (user["id"], fingerprint)
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"[device_security] new-device email to {to_email} failed: {e}")
        return False


# ═════════════════════════════════════════════════════════════════════
#  Email verification
# ═════════════════════════════════════════════════════════════════════
def create_verification_token(user_id: int) -> str:
    conn = _get_db()
    conn.execute(
        "UPDATE email_verifications SET used=1 WHERE user_id=? AND used=0",
        (user_id,)
    )
    token = secrets.token_urlsafe(32)
    conn.execute(
        "INSERT INTO email_verifications (user_id, token, expires_at, created_at) VALUES (?,?,?,?)",
        (user_id, token, time.time() + _VERIFY_TOKEN_TTL, time.time())
    )
    conn.commit()
    conn.close()
    return token


def verify_email_token(token: str) -> dict:
    conn = _get_db()
    row = conn.execute(
        "SELECT id, user_id, expires_at, used FROM email_verifications WHERE token=?",
        (token,)
    ).fetchone()
    if not row:
        conn.close()
        return {"error": "Invalid or expired verification link"}
    if row["used"]:
        conn.close()
        return {"error": "This verification link has already been used"}
    if time.time() > row["expires_at"]:
        conn.execute("UPDATE email_verifications SET used=1 WHERE id=?", (row["id"],))
        conn.commit()
        conn.close()
        return {"error": "Verification link has expired — please request a new one"}
    conn.execute("UPDATE email_verifications SET used=1 WHERE id=?", (row["id"],))
    conn.execute("UPDATE users SET email_verified=1 WHERE id=?", (row["user_id"],))
    conn.commit()
    conn.close()
    return {"ok": True, "user_id": row["user_id"]}


def is_email_verified(user_id: int) -> bool:
    conn = _get_db()
    r = conn.execute("SELECT email_verified FROM users WHERE id=?", (user_id,)).fetchone()
    conn.close()
    return bool(r and r["email_verified"])


def send_verification_email(to_email: str, username: str, token: str) -> bool:
    if not _GMAIL_APP_PASSWORD:
        print("[device_security] SMTP disabled — skipping verification email")
        return False
    verify_url = f"{_DASHBOARD_URL}/verify-email?token={token}"
    display = username or to_email.split("@")[0]
    html = f"""
    <div style="font-family:Inter,Arial,sans-serif;max-width:520px;margin:0 auto;background:#0d0d0f;color:#e8e8e8;border-radius:12px;overflow:hidden">
      <div style="background:#1a1a1f;padding:28px 32px;border-bottom:1px solid #2a2a30">
        <div style="font-size:22px;font-weight:800;color:#f4a236">✉️ Verify Your Email</div>
        <div style="font-size:13px;color:#888;margin-top:4px">Anunnaki World Signals</div>
      </div>
      <div style="padding:28px 32px">
        <p style="margin:0 0 16px;font-size:14px;line-height:1.6">Hi <strong style="color:#f4a236">{display}</strong>, welcome aboard.</p>
        <p style="margin:0 0 20px;font-size:14px;line-height:1.6">
          Please confirm this email address to unlock <strong>copy-trading, payments, and signal access</strong>.
          Until verification, the dashboard runs in read-only preview mode.
        </p>
        <a href="{verify_url}" style="display:inline-block;background:#f4a236;color:#000;font-weight:700;font-size:14px;padding:12px 28px;border-radius:8px;text-decoration:none">Verify My Email</a>
        <p style="margin:24px 0 0;font-size:12px;color:#666">Link expires in 7 days.</p>
        <p style="margin:6px 0 0;font-size:11px;color:#444;word-break:break-all">Or copy this link: {verify_url}</p>
      </div>
      <div style="padding:16px 32px;border-top:1px solid #1a1a1f;font-size:11px;color:#444">
        Anunnaki World Signals · Ignore this email if you didn't create an account.
      </div>
    </div>
    """
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = "Verify your Anunnaki World account"
        msg["From"] = "Anunnaki World <nikola@skytech.mk>"
        msg["Reply-To"] = _SUPPORT_EMAIL
        msg["To"] = to_email
        msg.attach(MIMEText(html, "html", "utf-8"))
        with smtplib.SMTP("smtp.gmail.com", 587) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(_GMAIL_USER, _GMAIL_APP_PASSWORD)
            smtp.sendmail(_GMAIL_USER, to_email, msg.as_string())
        return True
    except Exception as e:
        print(f"[device_security] verification email to {to_email} failed: {e}")
        return False


def issue_and_send_verification(user: dict) -> bool:
    token = create_verification_token(user["id"])
    return send_verification_email(user["email"], user.get("username", ""), token)
