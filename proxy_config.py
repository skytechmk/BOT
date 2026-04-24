"""
proxy_config.py — Webshare Proxy Pool Manager (API-driven, health-aware)

Architecture:
  1. On first use: fetch full proxy list from Webshare REST API (valid=true only)
  2. Round-robin across all valid direct proxies (true per-IP rotation)
  3. Per-proxy failure cooldown — mark_failed(url) skips it for 5 min
  4. Background thread refreshes pool every REFRESH_INTERVAL_HOURS
  5. Fallback: if no API key, uses backbone endpoint (p.webshare.io:80)
     which also rotates IPs at the connection level

.env keys required:
  PROXY_ENABLED=true
  PROXY_USER=gttoqywr-rotate       ← backbone fallback username
  PROXY_PASS=<password>            ← backbone + direct proxy password
  PROXY_HOST=p.webshare.io         ← backbone host
  PROXY_PORT=80                    ← backbone port
  WEBSHARE_API_KEY=<token>         ← from dashboard.webshare.io/userapi/keys
                                     (enables full direct proxy pool)

Usage:
    from proxy_config import configure_session, get_proxy_dict, is_enabled

    configure_session(client.session)           # Binance client
    requests.get(url, proxies=get_proxy_dict()) # per-request rotation
    session = build_session()                   # fresh session
    mark_failed(proxy_url)                      # after connection error
"""

import os
import time
import threading
import requests
from requests.adapters import HTTPAdapter
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

# ─── Env vars ────────────────────────────────────────────────────────────────
_ENABLED  = os.getenv("PROXY_ENABLED", "false").lower() in ("true", "1", "yes")
_USER     = os.getenv("PROXY_USER", "")
_PASS     = os.getenv("PROXY_PASS", "")
_HOST     = os.getenv("PROXY_HOST", "p.webshare.io")
_PORT     = os.getenv("PROXY_PORT", "80")
_API_KEY  = os.getenv("WEBSHARE_API_KEY", "")
_API_BASE = "https://proxy.webshare.io/api/v2"

FAIL_COOLDOWN_MINUTES  = 5
REFRESH_INTERVAL_HOURS = 1


# ─── Proxy Pool ──────────────────────────────────────────────────────────────

class WebshareProxyPool:
    """
    Rotating pool of Webshare direct proxies, fetched from their REST API.

    Pool lifecycle:
      refresh(force=True)  → API call → fills _pool with valid proxy URLs
      get_next()           → round-robin, skips cooled-down failures
      mark_failed(url)     → cooldown that proxy for FAIL_COOLDOWN_MINUTES
      background thread    → refresh(force=True) every REFRESH_INTERVAL_HOURS
    """

    def __init__(self):
        self._lock         = threading.Lock()
        self._pool         : list[str] = []
        self._idx          = 0
        self._failed       : dict[str, datetime] = {}
        self._last_refresh : float = 0.0
        self._backbone     = (f"http://{_USER}:{_PASS}@{_HOST}:{_PORT}/"
                              if _USER and _PASS else None)

    # ── API fetch ────────────────────────────────────────────────────────────

    def _fetch_from_api(self) -> list[str]:
        """Fetch all valid direct proxies from Webshare API. Returns list of URLs."""
        if not _API_KEY:
            return []
        urls = []
        page = 1
        while True:
            try:
                r = requests.get(
                    f"{_API_BASE}/proxy/list/",
                    params={"mode": "direct", "page": page, "page_size": 100},
                    headers={"Authorization": f"Token {_API_KEY}"},
                    timeout=15,
                )
                if r.status_code != 200:
                    print(f"  ⚠️ Webshare API HTTP {r.status_code}: {r.text[:120]}")
                    break
                data = r.json()
                for p in data.get("results", []):
                    if not p.get("valid", False):
                        continue
                    url = (f"http://{p['username']}:{p['password']}"
                           f"@{p['proxy_address']}:{p['port']}/")
                    urls.append(url)
                if data.get("next") is None:
                    break
                page += 1
            except Exception as e:
                print(f"  ⚠️ Proxy list API error: {e}")
                break
        return urls

    # ── Refresh ──────────────────────────────────────────────────────────────

    def refresh(self, force: bool = False) -> int:
        now = time.time()
        if not force and (now - self._last_refresh) < REFRESH_INTERVAL_HOURS * 3600:
            return len(self._pool)

        new_pool = self._fetch_from_api()
        with self._lock:
            if new_pool:
                self._pool = new_pool
                self._failed.clear()
                print(f"  🌐 Proxy pool refreshed: {len(new_pool)} valid direct IPs")
            elif self._backbone and not self._pool:
                self._pool = [self._backbone]
                print(f"  🌐 Proxy pool: no API key — using backbone endpoint")
            self._idx = 0
            self._last_refresh = now
        return len(self._pool)

    def start_background_refresh(self):
        def _loop():
            while True:
                time.sleep(REFRESH_INTERVAL_HOURS * 3600)
                try:
                    self.refresh(force=True)
                except Exception:
                    pass
        t = threading.Thread(target=_loop, daemon=True, name="proxy-refresh")
        t.start()

    # ── Routing ──────────────────────────────────────────────────────────────

    def get_next(self) -> str | None:
        """
        Return the next available proxy URL (round-robin, skip cooled-down).
        Lazy-initialises pool on first call.
        """
        if not _ENABLED:
            return None

        # Lazy init
        if not self._last_refresh:
            self.refresh(force=True)
            if _API_KEY:
                self.start_background_refresh()

        with self._lock:
            if not self._pool:
                return self._backbone

            now = datetime.utcnow()
            n = len(self._pool)
            for _ in range(n):
                url = self._pool[self._idx % n]
                self._idx += 1
                retry_at = self._failed.get(url)
                if retry_at is None or now >= retry_at:
                    return url

            # All proxies in cooldown — fall back to backbone
            return self._backbone

    def mark_failed(self, proxy_url: str,
                    cooldown: int = FAIL_COOLDOWN_MINUTES):
        with self._lock:
            self._failed[proxy_url] = (datetime.utcnow()
                                       + timedelta(minutes=cooldown))

    # ── Introspection ────────────────────────────────────────────────────────

    def status(self) -> dict:
        return {
            "enabled":        _ENABLED,
            "pool_size":      len(self._pool),
            "failed_count":   len(self._failed),
            "api_key_set":    bool(_API_KEY),
            "backbone":       self._backbone,
            "last_refresh":   (datetime.utcfromtimestamp(self._last_refresh).isoformat()
                               if self._last_refresh else None),
        }


# ─── Global singleton ────────────────────────────────────────────────────────
_POOL = WebshareProxyPool()


# ─── Public API ──────────────────────────────────────────────────────────────

def is_enabled() -> bool:
    return _ENABLED and (_POOL._backbone is not None or bool(_API_KEY))


def get_proxy_url() -> str | None:
    """Next proxy URL from pool, or None if disabled."""
    return _POOL.get_next()


def get_proxy_dict() -> dict:
    """
    Returns proxies dict for requests.get(..., proxies=get_proxy_dict()).
    Each call returns the NEXT proxy in the round-robin sequence.
    Returns {} when proxy is disabled.
    """
    url = _POOL.get_next()
    if url is None:
        return {}
    return {"http": url, "https": url}


def mark_failed(proxy_url: str):
    """Call this after a connection error to cool down that specific proxy."""
    _POOL.mark_failed(proxy_url)


def proxy_status() -> dict:
    """Return pool diagnostics dict."""
    return _POOL.status()


def _install_geo_fallback(session: requests.Session) -> None:
    """
    Wrap session.request so that when Binance rejects the proxy IP with
    HTTP 451 / 'Service unavailable from a restricted location', the same
    request is retried automatically with proxies={} (server's direct public
    IP). This makes every python-binance call (futures_ticker, futures_klines,
    futures_mark_price, etc.) resilient to geo-blocked proxy IPs.
    """
    if getattr(session, '_geo_fallback_installed', False):
        return
    _orig_request = session.request

    def _request_with_geo_fallback(method, url, **kwargs):
        resp = _orig_request(method, url, **kwargs)
        # Fast path: only inspect body on suspicious status
        if resp.status_code == 451 or (400 <= resp.status_code < 500):
            try:
                body = resp.text or ''
            except Exception:
                body = ''
            if 'restricted location' in body.lower():
                # Retry without proxy
                kwargs['proxies'] = {}
                try:
                    return _orig_request(method, url, **kwargs)
                except Exception:
                    return resp  # direct-IP attempt failed — return original
        return resp

    session.request = _request_with_geo_fallback
    session._geo_fallback_installed = True


def configure_session(session: requests.Session,
                      pool_connections: int = 30,
                      pool_maxsize: int = 30) -> requests.Session:
    """
    Mount proxy + connection pool on an existing requests.Session in-place.
    Used for the Binance client — backbone endpoint rotates at TCP level.
    Safe to call when proxy is disabled (only sets pool size).
    Also installs the geo-restriction fallback wrapper (see
    _install_geo_fallback) so that per-request proxy blocks transparently
    fall back to the server's direct public IP.
    """
    adapter = HTTPAdapter(pool_connections=pool_connections,
                          pool_maxsize=pool_maxsize)
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    url = _POOL.get_next()
    if url:
        session.proxies.update({"http": url, "https": url})
        host_display = url.split("@")[-1].rstrip("/")
        print(f"🌐 Proxy active: {host_display} (pool={_POOL.status()['pool_size']})")

    _install_geo_fallback(session)
    return session


def build_session(pool_connections: int = 10,
                  pool_maxsize: int = 10) -> requests.Session:
    """
    Fresh requests.Session with proxy + pool configured.
    Note: for per-request IP rotation pass proxies=get_proxy_dict() per call.
    """
    session = requests.Session()
    return configure_session(session, pool_connections, pool_maxsize)


def test_proxy(n: int = 3) -> bool:
    """
    Test proxy connectivity. Fires n requests and reports unique IPs seen.
    Returns True if at least one request succeeds.
    """
    if not _ENABLED:
        print("⚠️  Proxy disabled (PROXY_ENABLED != true)")
        return False
    ips, ok = [], False
    for i in range(n):
        try:
            pd = get_proxy_dict()
            r = requests.get("https://ipv4.webshare.io/", proxies=pd, timeout=10)
            ip = r.text.strip()
            ips.append(ip)
            ok = True
        except Exception as e:
            ips.append(f"ERR:{e}")
    unique = len(set(i for i in ips if not i.startswith("ERR")))
    print(f"✅ Proxy test ({n} requests): {ips} — {unique} unique IPs")
    st = proxy_status()
    print(f"   Pool: {st['pool_size']} proxies | API key: {st['api_key_set']} | Backbone: {st['backbone']}")
    return ok
