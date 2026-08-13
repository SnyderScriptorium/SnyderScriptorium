import os
import logging
from datetime import datetime, timezone

from flask import Blueprint, current_app, jsonify, request, session

from database import get_db
from paypal_subscriptions import get_subscription, paypal_request, verify_webhook

paypal_member = Blueprint("paypal_member", __name__)
logger = logging.getLogger(__name__)


def configured_plan_id(app=None):
    """Return the current runtime PayPal membership plan ID.

    The PayPal bootstrap can replace a stale Sandbox plan ID at startup. The
    runtime Flask config is therefore authoritative whenever it contains a
    plan ID; environment variables are only the fallback for direct startup.
    """
    if app is None:
        try:
            app = current_app._get_current_object()
        except RuntimeError:
            app = None

    if app is not None:
        runtime_plan = str(app.config.get("PAYPAL_PLAN_ID") or "").strip()
        if runtime_plan:
            return runtime_plan

    for name in ("PAYPAL_PLAN_FOUNDING_3", "PAYPAL_PLAN_STANDARD_4", "PAYPAL_PLAN_STANDARD_5", "PAYPAL_PLAN_ID"):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


def _iso_or_now(value=None):
    return value or datetime.now(timezone.utc).isoformat()


def _status_for_member(paypal_status):
    return "active" if paypal_status == "ACTIVE" else "inactive"


def _save_subscription(member_id, subscription_id, status, started=None, ends=None):
    conn = get_db()
    try:
        existing = conn.execute("SELECT id FROM subscriptions WHERE member_id = ? ORDER BY id DESC LIMIT 1", (member_id,)).fetchone()
        if existing:
            conn.execute("UPDATE subscriptions SET provider = ?, subscription_id = ?, status = ?, date_started = ?, date_ends = ? WHERE id = ?", ("paypal", subscription_id, status, started, ends, existing["id"]))
        else:
            conn.execute("INSERT INTO subscriptions(member_id, provider, subscription_id, status, date_started, date_ends) VALUES (?, ?, ?, ?, ?, ?)", (member_id, "paypal", subscription_id, status, started, ends))
        conn.execute("UPDATE members SET subscription_status = ? WHERE id = ?", (status, member_id))
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()


@paypal_member.post("/api/paypal/attach-subscription")
def attach_subscription():
    if not session.get("member_logged_in") or not session.get("member_id"):
        return jsonify({"ok": False, "error": "Please sign in to your K. W. Snyder Writing account first."}), 401

    payload = request.get_json(silent=True) or {}
    subscription_id = str(payload.get("subscriptionID") or "").strip()
    if not subscription_id:
        return jsonify({"ok": False, "error": "PayPal did not return a subscription ID."}), 400

    try:
        subscription = get_subscription(subscription_id)
    except Exception as exc:
        logger.exception("PayPal subscription verification failed")
        return jsonify({"ok": False, "error": f"PayPal could not verify the subscription yet: {exc}"}), 502

    plan_id = configured_plan_id()
    if not plan_id:
        return jsonify({"ok": False, "error": "The PayPal membership plan is not configured on the server."}), 503
    if subscription.get("plan_id") != plan_id:
        return jsonify({"ok": False, "error": "The PayPal subscription does not match the K. W. Snyder Writing membership plan."}), 400

    paypal_status = str(subscription.get("status") or "").upper()
    if paypal_status not in {"APPROVAL_PENDING", "APPROVED", "ACTIVE", "SUSPENDED", "CANCELLED", "EXPIRED"}:
        return jsonify({"ok": False, "error": "PayPal returned an unexpected subscription status."}), 400

    status = _status_for_member(paypal_status)
    started = subscription.get("start_time") or subscription.get("create_time") or _iso_or_now()
    ends = (subscription.get("billing_info") or {}).get("next_billing_time")
    _save_subscription(session["member_id"], subscription_id, status, started, ends)

    return jsonify({"ok": True, "subscriptionID": subscription_id, "paypalStatus": paypal_status, "memberStatus": status, "active": status == "active"})


@paypal_member.post("/api/paypal/cancel-subscription")
def cancel_subscription():
    """Cancel only the PayPal subscription belonging to the signed-in member."""
    member_id = session.get("member_id")
    if not session.get("member_logged_in") or not member_id:
        return jsonify({"ok": False, "error": "Please sign in to your K. W. Snyder Writing account first."}), 401

    conn = get_db()
    try:
        row = conn.execute(
            "SELECT id, subscription_id, status FROM subscriptions WHERE member_id = ? AND provider = 'paypal' ORDER BY id DESC LIMIT 1",
            (member_id,),
        ).fetchone()
    finally:
        conn.close()

    if not row or not row["subscription_id"]:
        return jsonify({"ok": False, "error": "No PayPal subscription is attached to this account."}), 404

    subscription_id = str(row["subscription_id"]).strip()
    try:
        current = get_subscription(subscription_id)
    except Exception as exc:
        logger.exception("Could not retrieve PayPal subscription before cancellation")
        return jsonify({"ok": False, "error": f"PayPal could not verify your subscription: {exc}"}), 502

    if current.get("plan_id") != configured_plan_id():
        return jsonify({"ok": False, "error": "This subscription does not match the K. W. Snyder Writing membership plan."}), 400

    paypal_status = str(current.get("status") or "").upper()
    if paypal_status in {"CANCELLED", "EXPIRED"}:
        _save_subscription(member_id, subscription_id, "cancelled" if paypal_status == "CANCELLED" else "expired", current.get("start_time"), (current.get("billing_info") or {}).get("next_billing_time"))
        return jsonify({"ok": True, "cancelled": True, "alreadyCancelled": True})

    if paypal_status not in {"ACTIVE", "APPROVAL_PENDING", "APPROVED", "SUSPENDED"}:
        return jsonify({"ok": False, "error": "PayPal returned an unexpected subscription status."}), 400

    try:
        paypal_request(
            "POST",
            f"/v1/billing/subscriptions/{subscription_id}/cancel",
            {"reason": "Cancelled by member from K. W. Snyder Writing account"},
        )
    except Exception as exc:
        logger.exception("PayPal subscription cancellation failed")
        return jsonify({"ok": False, "error": f"PayPal could not cancel the subscription: {exc}"}), 502

    started = current.get("start_time") or current.get("create_time")
    ends = (current.get("billing_info") or {}).get("next_billing_time")
    _save_subscription(member_id, subscription_id, "cancelled", started, ends)
    return jsonify({"ok": True, "cancelled": True})


@paypal_member.post("/api/paypal/webhook")
def paypal_webhook():
    event = request.get_json(silent=True) or {}
    if not event:
        return jsonify({"ok": False, "error": "Missing PayPal webhook payload."}), 400
    if not verify_webhook(request.headers, event):
        return jsonify({"ok": False, "error": "PayPal webhook verification failed."}), 400

    event_type = str(event.get("event_type") or "").strip()
    resource = event.get("resource") or {}
    subscription_id = str(resource.get("id") or resource.get("billing_agreement_id") or resource.get("subscription_id") or "").strip()
    if not subscription_id:
        return jsonify({"ok": True, "handled": False}), 200

    status_map = {
        "BILLING.SUBSCRIPTION.ACTIVATED": "active",
        "PAYMENT.SALE.COMPLETED": "active",
        "BILLING.SUBSCRIPTION.PAYMENT.FAILED": "past_due",
        "BILLING.SUBSCRIPTION.SUSPENDED": "paused",
        "BILLING.SUBSCRIPTION.CANCELLED": "cancelled",
        "BILLING.SUBSCRIPTION.EXPIRED": "expired",
    }

    if event_type == "BILLING.SUBSCRIPTION.UPDATED":
        paypal_status = str(resource.get("status") or "").upper()
        status = {"SUSPENDED": "paused", "CANCELLED": "cancelled", "EXPIRED": "expired", "ACTIVE": "active"}.get(paypal_status, "past_due" if paypal_status else None)
    else:
        status = status_map.get(event_type)
    if status is None:
        return jsonify({"ok": True, "handled": False}), 200

    try:
        subscription = get_subscription(subscription_id)
    except Exception:
        logger.exception("Could not retrieve PayPal subscription for webhook")
        return jsonify({"ok": False, "error": "Could not retrieve the PayPal subscription."}), 502
    if subscription.get("plan_id") != configured_plan_id():
        return jsonify({"ok": True, "handled": False}), 200

    conn = get_db()
    try:
        row = conn.execute("SELECT member_id FROM subscriptions WHERE provider = ? AND subscription_id = ? ORDER BY id DESC LIMIT 1", ("paypal", subscription_id)).fetchone()
    finally:
        conn.close()
    if not row:
        return jsonify({"ok": True, "handled": False, "reason": "subscription_not_attached"}), 200

    started = subscription.get("start_time") or subscription.get("create_time")
    ends = (subscription.get("billing_info") or {}).get("next_billing_time")
    _save_subscription(row["member_id"], subscription_id, status, started, ends)
    return jsonify({"ok": True, "handled": True, "event": event_type, "status": status}), 200


def register_paypal_member(app):
    if "paypal_member.attach_subscription" not in app.view_functions:
        app.register_blueprint(paypal_member)
    client_id = os.environ.get("PAYPAL_CLIENT_ID", "").strip()
    app.config["PAYPAL_CLIENT_ID"] = client_id

    # Preserve the plan ID selected by the bootstrap if it already established
    # a valid/replacement plan in app.config. Only fall back to environment
    # variables when no runtime plan has been selected yet.
    plan_id = configured_plan_id(app)
    if plan_id:
        app.config["PAYPAL_PLAN_ID"] = plan_id

    if client_id and os.environ.get("PAYPAL_CLIENT_SECRET", "").strip():
        if not plan_id:
            logger.error("PayPal membership plan is not configured on the server.")
        else:
            try:
                plan = paypal_request("GET", f"/v1/billing/plans/{plan_id}")
                logger.info("PayPal membership plan verified: status=%s product_id=%s plan_id=%s", plan.get("status"), plan.get("product_id"), plan_id)
            except Exception as exc:
                logger.warning("PayPal membership plan verification deferred for %s: %s", plan_id, exc)
    else:
        logger.warning("PayPal credentials are incomplete: PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET are required.")
