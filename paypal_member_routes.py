import os
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request, session

from database import get_db
from paypal_subscriptions import get_subscription

paypal_member = Blueprint("paypal_member", __name__)

PLAN_ID = "P-9KV03116ML843823PNJ5TDHA"


def _iso_or_now(value=None):
    return value or datetime.now(timezone.utc).isoformat()


def _status_for_member(paypal_status):
    return "active" if paypal_status == "ACTIVE" else "inactive"


@paypal_member.post("/api/paypal/attach-subscription")
def attach_subscription():
    if not session.get("member_logged_in") or not session.get("member_id"):
        return jsonify({"ok": False, "error": "Please sign in to your Scriptorium member account first."}), 401

    payload = request.get_json(silent=True) or {}
    subscription_id = str(payload.get("subscriptionID") or "").strip()
    if not subscription_id:
        return jsonify({"ok": False, "error": "PayPal did not return a subscription ID."}), 400

    try:
        subscription = get_subscription(subscription_id)
    except Exception as exc:
        return jsonify({"ok": False, "error": f"PayPal could not verify the subscription yet: {exc}"}), 502

    if subscription.get("plan_id") != PLAN_ID:
        return jsonify({"ok": False, "error": "The PayPal subscription does not match the Scriptorium membership plan."}), 400

    paypal_status = str(subscription.get("status") or "").upper()
    if paypal_status not in {"APPROVAL_PENDING", "APPROVED", "ACTIVE", "SUSPENDED", "CANCELLED", "EXPIRED"}:
        return jsonify({"ok": False, "error": "PayPal returned an unexpected subscription status."}), 400

    member_id = session["member_id"]
    status = _status_for_member(paypal_status)
    started = subscription.get("start_time") or subscription.get("create_time") or _iso_or_now()
    ends = (subscription.get("billing_info") or {}).get("next_billing_time")

    conn = get_db()
    try:
        existing = conn.execute(
            "SELECT id FROM subscriptions WHERE member_id = ? ORDER BY id DESC LIMIT 1",
            (member_id,),
        ).fetchone()

        if existing:
            conn.execute(
                "UPDATE subscriptions SET provider = ?, subscription_id = ?, status = ?, date_started = ?, date_ends = ? WHERE id = ?",
                ("paypal", subscription_id, status, started, ends, existing["id"]),
            )
        else:
            conn.execute(
                "INSERT INTO subscriptions(member_id, provider, subscription_id, status, date_started, date_ends) VALUES (?, ?, ?, ?, ?, ?)",
                (member_id, "paypal", subscription_id, status, started, ends),
            )

        conn.execute(
            "UPDATE members SET subscription_status = ? WHERE id = ?",
            (status, member_id),
        )
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        conn.close()
        raise
    conn.close()

    return jsonify({
        "ok": True,
        "subscriptionID": subscription_id,
        "paypalStatus": paypal_status,
        "memberStatus": status,
        "active": status == "active",
    })


def register_paypal_member(app):
    """Register the PayPal member blueprint during Gunicorn application setup."""
    if "paypal_member.attach_subscription" not in app.view_functions:
        app.register_blueprint(paypal_member)
    app.config["PAYPAL_CLIENT_ID"] = os.environ.get("PAYPAL_CLIENT_ID", "").strip()
    app.config["PAYPAL_PLAN_ID"] = PLAN_ID
