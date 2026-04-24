"""
server_ip.py — Server Public IP Fetcher (no proxy, direct connection)

Used by the copy-trading setup guide to show users which IP address to
whitelist on their Binance API key.

The server IP is DYNAMIC — it can change after restarts or ISP reassignment.
Cache TTL is 30 minutes. If the cache is stale and the fetch fails, the last
known IP is returned with a `stale=True` flag so the UI can warn the user.
"""

import time
import requests

_CACHE: dict = {"ip": None, "ts": 0.0}
_TTL = 1800  # 30 minutes

# Multiple sources — tried in order until one succeeds
_SOURCES = [
    "https://api4.my-ip.io/ip",
    "https://ipv4.webshare.io/",
    "https://api.ipify.org",
    "https://ifconfig.me/ip",
    "https://checkip.amazonaws.com",
]


def get_server_public_ip(timeout: int = 5) -> str | None:
    """
    Fetch the server's public IPv4 directly, bypassing any proxy.
    Tries multiple services in order. Returns None if all fail.
    """
    for url in _SOURCES:
        try:
            r = requests.get(url, timeout=timeout, proxies={})
            ip = r.text.strip().split()[0]  # some services add newlines
            # Basic sanity: valid-looking IPv4 or IPv6
            if ip and len(ip) <= 45 and ("." in ip or ":" in ip):
                return ip
        except Exception:
            continue
    return None


def get_cached_server_ip() -> dict:
    """
    Return the server's public IP, refreshing if the cache is older than TTL.

    Returns:
        {
            "ip":    "185.6.20.65",
            "fresh": True,          # just fetched
            "stale": False,         # returned stale value after failed refresh
            "error": None           # message if completely unavailable
        }
    """
    now = time.time()
    cached_age = now - _CACHE["ts"]

    # Cache hit
    if _CACHE["ip"] and cached_age < _TTL:
        return {"ip": _CACHE["ip"], "fresh": False, "stale": False, "error": None}

    # Cache miss or expired — try to refresh
    ip = get_server_public_ip()
    if ip:
        _CACHE["ip"] = ip
        _CACHE["ts"] = now
        return {"ip": ip, "fresh": True, "stale": False, "error": None}

    # Fetch failed — return stale value if we have one
    if _CACHE["ip"]:
        return {
            "ip": _CACHE["ip"],
            "fresh": False,
            "stale": True,
            "error": "Refresh failed — showing last known IP"
        }

    return {"ip": None, "fresh": False, "stale": False, "error": "Could not determine server IP"}


def force_refresh_ip() -> dict:
    """Force a cache bypass and fetch fresh IP immediately."""
    _CACHE["ts"] = 0.0
    return get_cached_server_ip()
