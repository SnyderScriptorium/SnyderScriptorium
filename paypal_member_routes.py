import os
import logging
from datetime import datetime, timezone

from flask import Blueprint, current_app, jsonify, redirect, request, session

from database import get_db
from member_payments import (
    fmt_utc,
    get_member_access,
    utcnow,
    verify_and_record_subscription_payments,
    void_payment,
)
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

    for name in ("PAYPAL_PLAN_INTRO_1", "PAYPAL_PLAN_FOUNDING_3", "PAYPAL_PLAN_STANDARD_4", "PAYPAL_PLAN_STANDARD_5", "PAYPAL_PLAN_ID"):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


def _iso_or_now(value=None):
    return value or datetime.now(timezone.utc).isoformat()


def _save_subscription(member_id, subscription_id, status, started=None, ends=None):
    """Upsert the member's subscription record and status string.

    The paid-through date lives in the verified payment ledger, never in
    this status string. When a caller passes no start/end (cancellation
    and failure events carry no billing dates), the previously stored
    dates are preserved rather than overwritten with NULL, so a
    cancellation can never erase the paid period it follows.
    """
    conn = get_db()
    try:
        existing = conn.execute("SELECT id, date_started, date_ends FROM subscriptions WHERE member_id = ? ORDER BY id DESC LIMIT 1", (member_id,)).fetchone()
        if existing:
            if started is None:
                started = existing["date_started"]
            if ends is None:
                ends = existing["date_ends"]
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


def _verified_intro_plan_id():
    """Fail-closed resolution of the $1 intro membership plan.

    Only the intro_1 plan is ever acceptable here. The candidate plan ID is
    fetched live from PayPal's API and its REGULAR billing cycle must price
    at exactly 1.00 USD. Returns the plan ID, or None when anything does not
    check out. The legacy $3/$4/$5 plans are never consulted, so a stale or
    missing $1 plan can never silently fall back to charging $3.
    """
    candidates = []
    env_plan = os.environ.get("PAYPAL_PLAN_INTRO_1", "").strip()
    if env_plan:
        candidates.append(env_plan)
    try:
        conn = get_db()
        try:
            row = conn.execute("SELECT value FROM site_content WHERE key = 'paypal_intro_plan_id'").fetchone()
            if row and str(row["value"] or "").strip():
                candidates.append(str(row["value"]).strip())
        finally:
            conn.close()
    except Exception:
        logger.exception("Could not read stored intro plan ID")

    seen = set()
    for plan_id in candidates:
        if not plan_id or plan_id in seen:
            continue
        seen.add(plan_id)
        try:
            plan = paypal_request("GET", f"/v1/billing/plans/{plan_id}")
        except Exception:
            logger.warning("Intro plan %s could not be retrieved from PayPal", plan_id)
            continue
        if str(plan.get("status", "")).upper() != "ACTIVE":
            logger.warning("Intro plan %s is not ACTIVE (status=%s); refusing.", plan_id, plan.get("status"))
            continue
        price_ok = False
        for cycle in plan.get("billing_cycles") or []:
            if str(cycle.get("tenure_type", "")).upper() != "REGULAR":
                continue
            fixed = ((cycle.get("pricing_scheme") or {}).get("fixed_price") or {})
            try:
                price_val = float(str(fixed.get("value", "")).strip())
            except (ValueError, TypeError):
                price_val = None
            if price_val == 1.0 and str(fixed.get("currency_code", "")).upper() == "USD":
                price_ok = True
                break
        if not price_ok:
            logger.warning("Intro plan %s does not bill $1.00 USD monthly; refusing.", plan_id)
            continue
        return plan_id
    return None


@paypal_member.post("/api/paypal/create-subscription")
def create_subscription():
    """Create a PayPal subscription on the $1 intro plan; return the approval URL.

    Fail-closed: refuses with 503 unless the intro_1 plan is verified live
    against PayPal's API at exactly $1.00 USD/month. The legacy $3/$4/$5
    plans are never used here, so the terms page can never promise $1 while
    PayPal charges $3. The buyer approves on PayPal's site and returns to
    /kwsnyderwriting/membership/return.
    """
    member_id = session.get("member_id")
    if not session.get("member_logged_in") or not member_id:
        return jsonify({"ok": False, "error": "Please sign in to your K. W. Snyder Writing account first."}), 401

    conn = get_db()
    try:
        row = conn.execute("SELECT subscription_status, status FROM members WHERE id = ?", (member_id,)).fetchone()
    finally:
        conn.close()
    if row and row["status"] == "blocked":
        return jsonify({"ok": False, "error": "This account has been blocked."}), 403
    try:
        access = get_member_access(member_id)
    except Exception:
        access = {"has_access": False}
    if access["has_access"]:
        return jsonify({"ok": False, "error": "This account already has an active membership."}), 409
    if row and row["subscription_status"] == "pending_payment":
        return jsonify({"ok": False, "error": "A subscription is already waiting for PayPal to confirm its payment. Please allow a moment, then refresh the membership page."}), 409

    plan_id = _verified_intro_plan_id()
    if not plan_id:
        return jsonify({"ok": False, "error": "The $1 membership plan is not verified with PayPal right now. Please try again later."}), 503

    base = request.host_url.rstrip("/")
    try:
        subscription = paypal_request("POST", "/v1/billing/subscriptions", {
            "plan_id": plan_id,
            "application_context": {
                "brand_name": "Snyder Scriptorium",
                "return_url": base + "/kwsnyderwriting/membership/return",
                "cancel_url": base + "/kwsnyderwriting/membership/cancel",
                "user_action": "SUBSCRIBE_NOW",
                "shipping_preference": "NO_SHIPPING",
            },
        })
    except Exception as exc:
        logger.exception("PayPal subscription creation failed")
        return jsonify({"ok": False, "error": f"PayPal could not start the subscription: {exc}"}), 502

    approval_url = ""
    for link in subscription.get("links", []) or []:
        if link.get("rel") == "approve" and link.get("href"):
            approval_url = link["href"]
            break
    subscription_id = str(subscription.get("id") or "").strip()
    if not approval_url or not subscription_id:
        logger.warning("PayPal subscription creation returned no approval link: %s", subscription)
        return jsonify({"ok": False, "error": "PayPal did not return an approval link. Please try again."}), 502
    return jsonify({"ok": True, "approval_url": approval_url, "subscription_id": subscription_id})


@paypal_member.get("/kwsnyderwriting/membership/return")
def membership_return():
    """PayPal sends the buyer back here after approving the subscription.

    A browser redirect is never proof of payment. The subscription is
    fetched from PayPal, its plan must be the verified $1 plan, and a
    captured $1.00 USD payment must be found in the subscription's
    transactions before the account is activated. If the payment has not
    cleared yet, the account waits in pending_payment: the membership page
    rechecks on the next visit and the payment webhook completes it.
    """
    if not session.get("member_logged_in") or not session.get("member_id"):
        return redirect("/kwsnyderwriting/login")
    subscription_id = request.args.get("subscription_id", "").strip()
    if not subscription_id:
        return redirect("/kwsnyderwriting/membership?error=missing_subscription")
    plan_id = _verified_intro_plan_id()
    if not plan_id:
        return redirect("/kwsnyderwriting/membership?error=plan_unverified")
    try:
        subscription = get_subscription(subscription_id)
    except Exception:
        logger.exception("Could not verify subscription after PayPal return")
        return redirect("/kwsnyderwriting/membership?error=verify_failed")
    if subscription.get("plan_id") != plan_id:
        logger.warning("Subscription %s is not on the verified $1 plan; not attaching.", subscription_id)
        return redirect("/kwsnyderwriting/membership?error=wrong_plan")
    member_id = session["member_id"]
    started = subscription.get("start_time") or subscription.get("create_time") or _iso_or_now()
    ends = (subscription.get("billing_info") or {}).get("next_billing_time")
    try:
        verify_and_record_subscription_payments(member_id, subscription_id, subscription=subscription, source="return")
    except Exception:
        logger.exception("Could not verify payment after PayPal return")
        return redirect("/kwsnyderwriting/membership?error=verify_failed")
    try:
        access = get_member_access(member_id)
    except Exception:
        access = {"has_access": False}
    status = "active" if access["has_access"] else "pending_payment"
    try:
        _save_subscription(member_id, subscription_id, status, started, ends)
    except Exception:
        logger.exception("Could not save subscription after PayPal return")
        return redirect("/kwsnyderwriting/membership?error=save_failed")
    if status == "active":
        return redirect("/kwsnyderwriting/membership?subscribed=1")
    return redirect("/kwsnyderwriting/membership?verifying=1")


@paypal_member.get("/kwsnyderwriting/membership/cancel")
def membership_cancel():
    """PayPal sends the buyer back here when they cancel before approving."""
    return redirect("/kwsnyderwriting/membership?cancelled=1")


@paypal_member.post("/api/paypal/attach-subscription")
def attach_subscription():
    if not session.get("member_logged_in") or not session.get("member_id"):
        return jsonify({"ok": False, "error": "Please sign in to your K. W. Snyder Writing account first."}), 401

    member_id = session["member_id"]
    payload = request.get_json(silent=True) or {}
    subscription_id = str(payload.get("subscriptionID") or "").strip()
    if not subscription_id:
        return jsonify({"ok": False, "error": "PayPal did not return a subscription ID."}), 400

    conn = get_db()
    try:
        row = conn.execute("SELECT status FROM members WHERE id = ?", (member_id,)).fetchone()
    finally:
        conn.close()
    if row and row["status"] == "blocked":
        return jsonify({"ok": False, "error": "This account has been blocked."}), 403

    try:
        subscription = get_subscription(subscription_id)
    except Exception as exc:
        logger.exception("PayPal subscription verification failed")
        return jsonify({"ok": False, "error": f"PayPal could not verify the subscription yet: {exc}"}), 502

    # The $1-only rule applies here too: a subscription on any other plan
    # (including the legacy $3/$4/$5 plans) must never attach as a $1
    # membership, whatever the runtime plan config happens to hold.
    plan_id = _verified_intro_plan_id()
    if not plan_id:
        return jsonify({"ok": False, "error": "The $1 membership plan is not verified with PayPal right now. Please try again later."}), 503
    if subscription.get("plan_id") != plan_id:
        return jsonify({"ok": False, "error": "The PayPal subscription does not match the $1 K. W. Snyder Writing membership plan."}), 400

    paypal_status = str(subscription.get("status") or "").upper()
    if paypal_status not in {"APPROVAL_PENDING", "APPROVED", "ACTIVE", "SUSPENDED", "CANCELLED", "EXPIRED"}:
        return jsonify({"ok": False, "error": "PayPal returned an unexpected subscription status."}), 400

    started = subscription.get("start_time") or subscription.get("create_time") or _iso_or_now()
    ends = (subscription.get("billing_info") or {}).get("next_billing_time")
    try:
        verify_and_record_subscription_payments(member_id, subscription_id, subscription=subscription, source="attach")
    except Exception:
        logger.exception("PayPal payment verification failed during attach")
        return jsonify({"ok": False, "error": "PayPal could not verify a payment for this subscription yet."}), 502
    try:
        access = get_member_access(member_id)
    except Exception:
        access = {"has_access": False}
    status = "active" if access["has_access"] else "pending_payment"
    _save_subscription(member_id, subscription_id, status, started, ends)

    return jsonify({"ok": True, "subscriptionID": subscription_id, "paypalStatus": paypal_status, "memberStatus": status, "active": status == "active", "verifying": status == "pending_payment"})


@paypal_member.post("/api/paypal/cancel-subscription")
def cancel_subscription():
    """Cancel only the PayPal subscription belonging to the signed-in member.

    Cancelling stops future billing. It never revokes the paid period:
    the member keeps access through the end of their verified paid
    interval, and the stored billing dates are preserved, not erased, by
    the cancellation. The subscription is found through this member's own
    record, so it stays cancellable whatever plan it is on (including a
    legacy plan) — the plan check that used to block those cancels is gone.
    """
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
    """Handle PayPal subscription webhooks with verified-payment gating.

    Rules this handler enforces:

    * The webhook signature is verified first; a failed signature is a 400
      and nothing is applied, so a forged event can never move a member.
    * Events are deduplicated by PayPal event id. A redelivery never
      double-records a payment or double-extends a paid period. Events are
      recorded only after successful handling, so a transient PayPal API
      failure (502) still lets PayPal retry the same event later.
    * ACTIVATED alone never grants access. A subscription reported ACTIVE
      with no captured $1.00 USD payment behind it lands the member in
      pending_payment, not active.
    * Payment events grant access only after the subscription's
      transactions are fetched from PayPal and a COMPLETED $1.00 USD
      payment is found and recorded on the ledger.
    * Cancellation, suspension, expiry, and failed-payment events only
      change the status string. They never erase a verified paid interval,
      so a cancelled member keeps access through the paid period.
    * Refunds and reversals void the matching payment interval, ending
      access once that interval was the one covering the member.
    """
    event = request.get_json(silent=True) or {}
    if not event:
        return jsonify({"ok": False, "error": "Missing PayPal webhook payload."}), 400
    if not verify_webhook(request.headers, event):
        return jsonify({"ok": False, "error": "PayPal webhook verification failed."}), 400

    event_type = str(event.get("event_type") or "").strip()
    event_id = str(event.get("id") or "").strip()
    resource = event.get("resource") or {}

    if event_id:
        conn = get_db()
        try:
            seen = conn.execute("SELECT id FROM paypal_webhook_events WHERE paypal_event_id = ?", (event_id,)).fetchone()
        finally:
            conn.close()
        if seen:
            return jsonify({"ok": True, "handled": True, "duplicate": True}), 200

    def _record_event(subscription_id):
        if not event_id:
            return
        conn = get_db()
        try:
            conn.execute(
                "INSERT INTO paypal_webhook_events(paypal_event_id, event_type, subscription_id, received_at) VALUES (?, ?, ?, ?)",
                (event_id, event_type, subscription_id, fmt_utc(utcnow())),
            )
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
        finally:
            conn.close()

    # Refunds/reversals are resolved through the payment ledger, not the
    # subscription table: their resource carries a sale id, not a
    # subscription id.
    if event_type in {"PAYMENT.SALE.REFUNDED", "PAYMENT.SALE.REVERSED"}:
        sale_id = str(resource.get("sale_id") or resource.get("id") or "").strip()
        member_id = None
        subscription_id = ""
        if sale_id:
            conn = get_db()
            try:
                row = conn.execute(
                    "SELECT member_id, subscription_id FROM member_payments WHERE paypal_transaction_id = ? AND status = 'verified' ORDER BY id DESC LIMIT 1",
                    (sale_id,),
                ).fetchone()
            finally:
                conn.close()
            if row:
                member_id = row["member_id"]
                subscription_id = row["subscription_id"] or ""
        if not member_id:
            _record_event(subscription_id)
            return jsonify({"ok": True, "handled": False, "reason": "payment_not_found"}), 200
        conn = get_db()
        try:
            voided = void_payment(conn, member_id, sale_id, "refunded" if event_type == "PAYMENT.SALE.REFUNDED" else "reversed")
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            conn.close()
            return jsonify({"ok": False, "error": "Could not void the payment."}), 502
        conn.close()
        _record_event(subscription_id)
        return jsonify({"ok": True, "handled": True, "event": event_type, "voided": voided}), 200

    # Subscription resolution order matters: for PAYMENT.SALE.* events the
    # resource id is the SALE id, not the subscription id — the
    # subscription lives in billing_agreement_id. For
    # BILLING.SUBSCRIPTION.* events the resource id IS the subscription
    # id and billing_agreement_id is absent, so the same order resolves
    # both. (BILLING.SUBSCRIPTION.PAYMENT.COMPLETED carries no
    # subscription id in its resource; its companion SALE.COMPLETED event
    # does, so an unresolvable PAYMENT.COMPLETED is safely a no-op.)
    subscription_id = str(resource.get("billing_agreement_id") or resource.get("subscription_id") or resource.get("id") or "").strip()
    if not subscription_id:
        return jsonify({"ok": True, "handled": False}), 200

    conn = get_db()
    try:
        row = conn.execute("SELECT member_id FROM subscriptions WHERE provider = ? AND subscription_id = ? ORDER BY id DESC LIMIT 1", ("paypal", subscription_id)).fetchone()
        member_row = conn.execute("SELECT subscription_status FROM members WHERE id = ?", (row["member_id"],)).fetchone() if row else None
    finally:
        conn.close()
    if not row:
        _record_event(subscription_id)
        return jsonify({"ok": True, "handled": False, "reason": "subscription_not_attached"}), 200
    member_id = row["member_id"]
    current_status = member_row["subscription_status"] if member_row else None

    payment_events = {"PAYMENT.SALE.COMPLETED", "BILLING.SUBSCRIPTION.PAYMENT.COMPLETED"}
    revoke_map = {
        "BILLING.SUBSCRIPTION.SUSPENDED": "paused",
        "BILLING.SUBSCRIPTION.CANCELLED": "cancelled",
        "BILLING.SUBSCRIPTION.EXPIRED": "expired",
        "BILLING.SUBSCRIPTION.PAYMENT.FAILED": "past_due",
    }

    if event_type in payment_events or event_type in {"BILLING.SUBSCRIPTION.ACTIVATED", "BILLING.SUBSCRIPTION.UPDATED"}:
        # Granting paths need a live PayPal fetch. Any failure here is a
        # 502 without recording, so PayPal retries the event later.
        try:
            subscription = get_subscription(subscription_id)
        except Exception:
            logger.exception("Could not retrieve PayPal subscription for webhook")
            return jsonify({"ok": False, "error": "Could not retrieve the PayPal subscription."}), 502
        paypal_status = str(subscription.get("status") or "").upper()
        started = subscription.get("start_time") or subscription.get("create_time")
        ends = (subscription.get("billing_info") or {}).get("next_billing_time")

        if event_type in payment_events:
            # A payment for a non-$1 plan never activates a $1 membership.
            plan_id = _verified_intro_plan_id()
            if not plan_id:
                return jsonify({"ok": False, "error": "The $1 membership plan is not verified with PayPal right now."}), 502
            if subscription.get("plan_id") != plan_id:
                _record_event(subscription_id)
                return jsonify({"ok": True, "handled": False, "reason": "wrong_plan"}), 200
            try:
                verify_and_record_subscription_payments(member_id, subscription_id, subscription=subscription, source="webhook")
            except Exception:
                logger.exception("Could not verify payment for webhook")
                return jsonify({"ok": False, "error": "Could not verify the payment."}), 502
            try:
                access = get_member_access(member_id)
            except Exception:
                access = {"has_access": False}
            if not access["has_access"]:
                # The payment has not appeared in PayPal's transactions
                # yet. Leave every status untouched; the membership-page
                # recheck picks it up on the member's next visit.
                _record_event(subscription_id)
                return jsonify({"ok": True, "handled": True, "event": event_type, "status": current_status, "payment_not_verified": True}), 200
            # Never resurrect a cancelled/expired status string with a
            # payment: the ledger already grants access through the paid
            # interval, and the status must keep saying no future billing.
            status = current_status if current_status in {"cancelled", "expired"} else "active"
            _save_subscription(member_id, subscription_id, status, started, ends)
            _record_event(subscription_id)
            return jsonify({"ok": True, "handled": True, "event": event_type, "status": status}), 200

        if event_type == "BILLING.SUBSCRIPTION.ACTIVATED":
            plan_id = _verified_intro_plan_id()
            if not plan_id:
                return jsonify({"ok": False, "error": "The $1 membership plan is not verified with PayPal right now."}), 502
            if subscription.get("plan_id") != plan_id:
                _record_event(subscription_id)
                return jsonify({"ok": True, "handled": False, "reason": "wrong_plan"}), 200
            try:
                verify_and_record_subscription_payments(member_id, subscription_id, subscription=subscription, source="webhook")
            except Exception:
                logger.exception("Could not verify payment for activation webhook")
                return jsonify({"ok": False, "error": "Could not verify the payment."}), 502
            try:
                access = get_member_access(member_id)
            except Exception:
                access = {"has_access": False}
            # ACTIVATED without a captured payment is pending, never active.
            status = "active" if access["has_access"] else "pending_payment"
            _save_subscription(member_id, subscription_id, status, started, ends)
            _record_event(subscription_id)
            return jsonify({"ok": True, "handled": True, "event": event_type, "status": status}), 200

        # BILLING.SUBSCRIPTION.UPDATED: only the status string moves, and
        # an ACTIVE report still needs a verified payment behind it.
        mapped = {"SUSPENDED": "paused", "CANCELLED": "cancelled", "EXPIRED": "expired"}.get(paypal_status)
        if mapped:
            _save_subscription(member_id, subscription_id, mapped, started, ends)
            _record_event(subscription_id)
            return jsonify({"ok": True, "handled": True, "event": event_type, "status": mapped}), 200
        if paypal_status == "ACTIVE":
            plan_id = _verified_intro_plan_id()
            if not plan_id:
                return jsonify({"ok": False, "error": "The $1 membership plan is not verified with PayPal right now."}), 502
            if subscription.get("plan_id") != plan_id:
                _record_event(subscription_id)
                return jsonify({"ok": True, "handled": False, "reason": "wrong_plan"}), 200
            try:
                verify_and_record_subscription_payments(member_id, subscription_id, subscription=subscription, source="webhook")
            except Exception:
                logger.exception("Could not verify payment for update webhook")
                return jsonify({"ok": False, "error": "Could not verify the payment."}), 502
            try:
                access = get_member_access(member_id)
            except Exception:
                access = {"has_access": False}
            if access["has_access"]:
                _save_subscription(member_id, subscription_id, "active", started, ends)
                _record_event(subscription_id)
                return jsonify({"ok": True, "handled": True, "event": event_type, "status": "active"}), 200
            if current_status in {"inactive", None}:
                _save_subscription(member_id, subscription_id, "pending_payment", started, ends)
                _record_event(subscription_id)
                return jsonify({"ok": True, "handled": True, "event": event_type, "status": "pending_payment"}), 200
            _record_event(subscription_id)
            return jsonify({"ok": True, "handled": True, "event": event_type, "status": current_status, "payment_not_verified": True}), 200
        _record_event(subscription_id)
        return jsonify({"ok": True, "handled": False, "reason": "unknown_paypal_status"}), 200

    if event_type in revoke_map:
        # Revoking events need no PayPal fetch: the signature is verified
        # and the subscription is attached to this member, which is enough
        # to move the status string. Paid intervals are untouched.
        _save_subscription(member_id, subscription_id, revoke_map[event_type])
        _record_event(subscription_id)
        return jsonify({"ok": True, "handled": True, "event": event_type, "status": revoke_map[event_type]}), 200

    _record_event(subscription_id)
    return jsonify({"ok": True, "handled": False}), 200


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
