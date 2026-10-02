"""Web Push notifications for the Snyder Scriptorium admin PWA.

Sends a phone push notification to every subscribed admin device when
something needs her attention (new order, new inbox message).

Setup: set VAPID_PRIVATE_KEY in the Render environment. The public key is
derived from it at runtime and served to the admin JS for subscriptions.
VAPID contact: snyderscriptorium@gmail.com.

Everything here is defensive: push must never break checkout, inbox
writes, or app boot. pywebpush is imported lazily so a missing library
can never take the site down.
"""

import base64
import json
import os


def vapid_private_key():
    return (os.environ.get("VAPID_PRIVATE_KEY") or "").strip()


def vapid_public_key():
    """Derive the public key from the private key (uncompressed P-256 point)."""
    priv_b64 = vapid_private_key()
    if not priv_b64:
        return ""
    try:
        from cryptography.hazmat.primitives.asymmetric import ec
        raw = base64.urlsafe_b64decode(priv_b64 + "=" * (-len(priv_b64) % 4))
        private_value = int.from_bytes(raw, "big")
        key = ec.derive_private_key(private_value, ec.SECP256R1())
        pub = key.public_key().public_numbers()
        point = b"\x04" + pub.x.to_bytes(32, "big") + pub.y.to_bytes(32, "big")
        return base64.urlsafe_b64encode(point).rstrip(b"=").decode()
    except Exception:
        return ""


def _prune_dead_subscription(endpoint):
    try:
        from database import get_db
        conn = get_db()
        conn.execute("DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint,))
        conn.commit()
        conn.close()
    except Exception:
        pass


def send_push(title, body, url="/admin#tab-inbox", tag=None):
    """Push a notification to all subscribed admin devices. Never raises.

    Returns True if at least one push was accepted for delivery.
    """
    try:
        priv = vapid_private_key()
        if not priv:
            return False
        from database import get_db
        conn = get_db()
        try:
            subs = [dict(r) for r in conn.execute(
                "SELECT endpoint, p256dh, auth FROM push_subscriptions").fetchall()]
        finally:
            conn.close()
        if not subs:
            return False
        from pywebpush import webpush, WebPushException
        payload = json.dumps({
            "title": title, "body": body,
            "url": url, "tag": tag or "snyder-admin",
        })
        claims = {"sub": "mailto:snyderscriptorium@gmail.com"}
        sent = False
        for sub in subs:
            try:
                webpush(
                    subscription_info={
                        "endpoint": sub["endpoint"],
                        "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]},
                    },
                    data=payload,
                    vapid_private_key=priv,
                    vapid_claims=claims,
                )
                sent = True
            except WebPushException as exc:
                status = exc.response.status_code if exc.response is not None else None
                if status in (404, 410):
                    _prune_dead_subscription(sub["endpoint"])
                print("[push] delivery failed (%s): %r" % (status, exc), flush=True)
        return sent
    except Exception as exc:
        print("[push] send_push failed: %r" % (exc,), flush=True)
        return False
