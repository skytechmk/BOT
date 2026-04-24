#!/usr/bin/env python3
"""Generate a VAPID key-pair for Web Push.

Run once and append the output to .env:

    python3 scripts/generate_vapid_keys.py >> .env

Then restart the dashboard service. `dashboard/push_notifications.py`
will detect the keys and activate the push pipeline.
"""
import base64
from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid

v = Vapid()
v.generate_keys()

pub_bytes = v.public_key.public_bytes(
    serialization.Encoding.X962,
    serialization.PublicFormat.UncompressedPoint,
)
priv_int = v.private_key.private_numbers().private_value

pub = base64.urlsafe_b64encode(pub_bytes).decode().rstrip("=")
priv = base64.urlsafe_b64encode(priv_int.to_bytes(32, "big")).decode().rstrip("=")

print("# Web Push (VAPID) — generated " + __import__("datetime").datetime.utcnow().isoformat() + "Z")
print(f"VAPID_PUBLIC_KEY={pub}")
print(f"VAPID_PRIVATE_KEY={priv}")
print("VAPID_SUBJECT=mailto:security@anunnakiworld.com")
