"""Pending signups: PayPal is a necessary part of making the account.

A visitor who signs up does NOT get a member row (or a login session)
until they have been through PayPal checkout. Their email + password
hash wait in ``pending_signups``, server-side -- never in a client
cookie -- keyed by id, with the PayPal subscription id attached once
checkout starts.

Rules, in full:

* ``prepare_signup``: an email that already belongs to a member WITH a
  PayPal subscription or a payment on the ledger is taken (log in
  instead). An email whose member row never got through PayPal -- no
  subscription, no payments, created by the old signup flow -- is
  stale: the row is deleted so the same email can sign up properly.
* ``try_activate_pending``: the subscription is fetched from PayPal,
  its plan must be the verified $1 plan, and a captured $1.00 USD
  payment must be found in its transactions before the member row is
  created. If the payment has not cleared yet, no row is created at
  all: the signup stays pending and the membership page rechecks on the
  next visit.
* A buyer who approved on PayPal and then closed the tab is still
  activatable: re-submitting signup with the same email finds the
  pending row and activates from the already-paid subscription instead
  of charging twice.
"""

import logging
from datetime import timedelta

import paypal_subscriptions
from database import get_db
from member_payments import (
    find_verified_paypal_payments,
    fmt_utc,
    get_member_access,
    parse_time,
    utcnow,
    verify_and_record_subscription_payments,
)

logger = logging.getLogger(__name__)

PENDING_TTL_DAYS = 7


class SignupEmailTaken(Exception):
    """The email already belongs to a member with PayPal history."""


class PendingActivationError(Exception):
    """Activation cannot proceed (wrong plan, PayPal failure)."""


def _row_dict(row):
    try:
        return dict(row)
    except (TypeError, ValueError):
        return row


def _delete_stale_pending(conn):
    """Drop pending rows older than the TTL; they never became accounts."""
    cutoff = fmt_utc(utcnow() - timedelta(days=PENDING_TTL_DAYS))
    try:
        conn.execute(
            "DELETE FROM pending_signups WHERE created_at != '' AND created_at < ?",
            (cutoff,),
        )
    except Exception:
        logger.exception("Could not clean up stale pending signups")


def member_has_paypal_history(member_id):
    """True when a member has ever been through PayPal: a subscription
    row or a payment ledger row. A member with neither never completed
    (or even started) checkout."""
    conn = get_db()
    try:
        sub = conn.execute(
            "SELECT id FROM subscriptions WHERE member_id = ? LIMIT 1",
            (member_id,),
        ).fetchone()
        if sub:
            return True
        pay = conn.execute(
            "SELECT id FROM member_payments WHERE member_id = ? LIMIT 1",
            (member_id,),
        ).fetchone()
        return bool(pay)
    finally:
        conn.close()


def prepare_signup(email, password_hash):
    """Reserve an email for signup. Returns the pending signup id.

    Raises SignupEmailTaken when the email belongs to a member with
    PayPal history. Deletes a stale never-activated member row for the
    same email so it can sign up properly.
    """
    conn = get_db()
    try:
        _delete_stale_pending(conn)
        conn.commit()
        member = conn.execute(
            "SELECT id FROM members WHERE email = ?", (email,)
        ).fetchone()
        if member:
            member_id = _row_dict(member)["id"]
            sub = conn.execute(
                "SELECT id FROM subscriptions WHERE member_id = ? LIMIT 1",
                (member_id,),
            ).fetchone()
            pay = None
            if not sub:
                pay = conn.execute(
                    "SELECT id FROM member_payments WHERE member_id = ? LIMIT 1",
                    (member_id,),
                ).fetchone()
            if sub or pay:
                raise SignupEmailTaken(email)
            # Never-activated row from the old flow: remove it so the
            # same email can sign up through PayPal now.
            conn.execute("DELETE FROM members WHERE id = ?", (member_id,))
        # Keep an earlier subscription id for this email: a buyer who
        # approved on PayPal and then closed the tab re-submits signup,
        # and activation must find the already-paid subscription instead
        # of starting (and charging) a second checkout.
        old = conn.execute(
            "SELECT subscription_id FROM pending_signups WHERE email = ?", (email,)
        ).fetchone()
        old_sub = _row_dict(old).get("subscription_id") if old else None
        conn.execute("DELETE FROM pending_signups WHERE email = ?", (email,))
        cur = conn.execute(
            "INSERT INTO pending_signups(email, password_hash, subscription_id, created_at) "
            "VALUES (?, ?, ?, ?)",
            (email, password_hash, old_sub, fmt_utc(utcnow())),
        )
        pending_id = cur.lastrowid
        conn.commit()
        return pending_id
    finally:
        try:
            conn.close()
        except Exception:
            pass


def get_pending(pending_id):
    if not pending_id:
        return None
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM pending_signups WHERE id = ?", (pending_id,)
        ).fetchone()
        return _row_dict(row) if row else None
    finally:
        conn.close()


def get_pending_by_email(email):
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM pending_signups WHERE email = ? ORDER BY id DESC LIMIT 1",
            (email,),
        ).fetchone()
        return _row_dict(row) if row else None
    finally:
        conn.close()


def get_pending_by_subscription(subscription_id):
    if not subscription_id:
        return None
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM pending_signups WHERE subscription_id = ? ORDER BY id DESC LIMIT 1",
            (subscription_id,),
        ).fetchone()
        return _row_dict(row) if row else None
    finally:
        conn.close()


def set_pending_subscription(pending_id, subscription_id):
    conn = get_db()
    try:
        conn.execute(
            "UPDATE pending_signups SET subscription_id = ? WHERE id = ?",
            (subscription_id, pending_id),
        )
        conn.commit()
    finally:
        conn.close()


def delete_pending(pending_id):
    conn = get_db()
    try:
        conn.execute("DELETE FROM pending_signups WHERE id = ?", (pending_id,))
        conn.commit()
    finally:
        conn.close()


def _save_pending_subscription(conn, member_id, subscription_id, status, started, ends):
    """Upsert the subscription row for a member being activated."""
    existing = conn.execute(
        "SELECT id, date_started, date_ends FROM subscriptions WHERE member_id = ? "
        "ORDER BY id DESC LIMIT 1",
        (member_id,),
    ).fetchone()
    if existing:
        existing = _row_dict(existing)
        if started is None:
            started = existing.get("date_started")
        if ends is None:
            ends = existing.get("date_ends")
        conn.execute(
            "UPDATE subscriptions SET provider = ?, subscription_id = ?, status = ?, "
            "date_started = ?, date_ends = ? WHERE id = ?",
            ("paypal", subscription_id, status, started, ends, existing["id"]),
        )
    else:
        conn.execute(
            "INSERT INTO subscriptions(member_id, provider, subscription_id, status, "
            "date_started, date_ends) VALUES (?, ?, ?, ?, ?, ?)",
            (member_id, "paypal", subscription_id, status, started, ends),
        )
    conn.execute(
        "UPDATE members SET subscription_status = ? WHERE id = ?", (status, member_id)
    )


def try_activate_pending(pending_id, plan_id, subscription=None):
    """Create the member account from a pending signup, but only after
    PayPal confirms the $1 payment.

    Returns the new member id when the payment is verified and the
    account is active. Returns None when no verified $1 payment has
    cleared yet -- and in that case NO member row is created at all: the
    signup stays pending and the membership page rechecks on the next
    visit. Raises PendingActivationError on a wrong plan or a PayPal API
    failure (fail closed: no account).
    """
    pending = get_pending(pending_id)
    if not pending:
        return None
    subscription_id = (pending.get("subscription_id") or "").strip()
    if not subscription_id:
        return None
    if not plan_id:
        raise PendingActivationError("plan_unverified")
    if subscription is None:
        try:
            subscription = paypal_subscriptions.get_subscription(subscription_id)
        except Exception as exc:
            raise PendingActivationError("verify_failed") from exc
    if subscription.get("plan_id") != plan_id:
        raise PendingActivationError("wrong_plan")
    started = subscription.get("start_time") or subscription.get("create_time")
    ends = (subscription.get("billing_info") or {}).get("next_billing_time")
    # Payment first: no verified $1 payment, no account at all. The
    # lookup window mirrors verify_and_record_subscription_payments.
    since = parse_time(started) or utcnow()
    floor = utcnow() - timedelta(days=370)
    if since < floor:
        since = floor
    try:
        payments = find_verified_paypal_payments(subscription_id, since, utcnow())
    except Exception as exc:
        raise PendingActivationError("verify_failed") from exc
    if not payments:
        return None
    # Resume: this pending signup may already have created its member row
    # on an earlier visit (payment verified, but its period had lapsed).
    # Never insert a second member row for the same email.
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT m.id FROM members m JOIN subscriptions s ON s.member_id = m.id "
            "WHERE m.email = ? AND s.subscription_id = ? AND s.provider = 'paypal' "
            "ORDER BY m.id DESC LIMIT 1",
            (pending["email"], subscription_id),
        ).fetchone()
        member_id = _row_dict(row)["id"] if row else None
    finally:
        conn.close()
    if member_id is None:
        conn = get_db()
        try:
            cur = conn.execute(
                "INSERT INTO members(email, password_hash, subscription_status, date_created) "
                "VALUES (?, ?, 'pending_payment', ?)",
                (pending["email"], pending["password_hash"], fmt_utc(utcnow())),
            )
            member_id = cur.lastrowid
            _save_pending_subscription(conn, member_id, subscription_id, "pending_payment", started, ends)
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            conn.close()
    try:
        verify_and_record_subscription_payments(
            member_id, subscription_id, subscription=subscription,
            source="pending_activation",
        )
    except Exception as exc:
        raise PendingActivationError("verify_failed") from exc
    try:
        access = get_member_access(member_id)
    except Exception:
        access = {"has_access": False}
    status = "active" if access["has_access"] else "pending_payment"
    conn = get_db()
    try:
        _save_pending_subscription(conn, member_id, subscription_id, status, started, ends)
        conn.commit()
    finally:
        conn.close()
    if status != "active":
        return None
    delete_pending(pending_id)
    return member_id
