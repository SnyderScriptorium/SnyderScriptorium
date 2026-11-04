"""Verified-payment membership access for K. W. Snyder Writing.

This module is the single source of truth for "does this member currently
have paid access to the private library?"

The rule, in full:

* Access follows VERIFIED PAYMENTS, never a PayPal subscription status
  string. A subscription that PayPal reports as ACTIVE but that has no
  captured $1.00 USD payment behind it grants nothing.
* Each verified $1.00 USD payment buys one coverage interval
  [payment_time, period_end]. A member has access exactly when the current
  UTC moment falls inside at least one non-voided verified interval.
* Cancelling stops future billing but never revokes an already-paid
  interval. Access ends only when the last covering interval passes, or
  when its payment is refunded/reversed (which voids that interval).
* Blocked accounts never have access, whatever their payments say.
* Members who were already 'active' before this module existed have no
  payment ledger rows. For them only, the legacy fallback applies: the
  stored subscriptions.date_ends (PayPal's next-billing time from the last
  fetch) is treated as the end of their current paid period. The first
  verified payment event for such a member moves them onto the ledger and
  the fallback stops applying.

All timestamps stored here are UTC ISO strings (``+00:00`` suffix), so
string and datetime comparisons agree across SQLite and PostgreSQL.
"""

import logging
from datetime import datetime, timezone, timedelta

import paypal_subscriptions
from database import get_db

logger = logging.getLogger(__name__)

MEMBER_PRICE = 1.00
MEMBER_CURRENCY = "USD"


def utcnow():
    return datetime.now(timezone.utc)


def fmt_utc(dt):
    """Canonical storage format: aware UTC datetime -> ISO string."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def parse_time(value):
    """Parse a stored/PayPal timestamp into an aware UTC datetime, or None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if not text:
            return None
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            for fmt in ("%m/%d/%Y %I:%M %p", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                try:
                    dt = datetime.strptime(text, fmt)
                    break
                except ValueError:
                    continue
            else:
                return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_month(dt):
    """Add one calendar month, clamping the day to the target month."""
    import calendar as _calendar

    month = dt.month + 1
    year = dt.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    last_day = _calendar.monthrange(year, month)[1]
    return dt.replace(year=year, month=month, day=min(dt.day, last_day))


def _row_dict(row):
    try:
        return dict(row)
    except (TypeError, ValueError):
        return row


def get_member_access(member_id):
    """Return the access verdict for a member.

    Returns a dict: has_access (bool), blocked (bool), paid_through_at
    (ISO string or None), legacy (bool — True when the legacy fallback,
    not a verified payment, is what grants access).
    """
    result = {"has_access": False, "blocked": False, "paid_through_at": None, "legacy": False}
    if not member_id:
        return result
    conn = get_db()
    try:
        member = conn.execute(
            "SELECT status, blocked_at, subscription_status FROM members WHERE id = ?", (member_id,)
        ).fetchone()
        if not member:
            return result
        member = _row_dict(member)
        if member.get("status") == "blocked" or member.get("blocked_at"):
            result["blocked"] = True
            return result
        now = utcnow()
        rows = conn.execute(
            "SELECT period_start, period_end, status FROM member_payments "
            "WHERE member_id = ? ORDER BY period_end",
            (member_id,),
        ).fetchall()
        rows = [_row_dict(r) for r in rows]
        paid_through = None
        for row in rows:
            if row.get("status") != "verified":
                continue
            start = parse_time(row.get("period_start"))
            end = parse_time(row.get("period_end"))
            if end and (paid_through is None or end > paid_through):
                paid_through = end
            if start and end and start <= now <= end:
                result["has_access"] = True
        if rows:
            # A ledger exists, so it governs — even when every interval
            # was voided by a refund. The legacy fallback below must never
            # resurrect access for a member whose payments were all voided.
            result["paid_through_at"] = fmt_utc(paid_through)
            return result
        # Legacy fallback: no ledger rows yet, so this member predates
        # verified-payment tracking. Honor the stored next-billing time
        # from the last PayPal fetch as the paid period — but ONLY for
        # members whose status shows a real subscription history
        # (active/cancelled/past_due/paused). A freshly attached member
        # is inactive/pending_payment with a future next-billing time
        # and must NOT gain access from this fallback: that would let a
        # PayPal ACTIVE status alone open the library again.
        if member.get("subscription_status") in {"active", "cancelled", "past_due", "paused"}:
            sub = conn.execute(
                "SELECT date_ends FROM subscriptions WHERE member_id = ? "
                "AND provider = 'paypal' ORDER BY id DESC LIMIT 1",
                (member_id,),
            ).fetchone()
            if sub:
                ends = parse_time(_row_dict(sub).get("date_ends"))
                if ends:
                    result["paid_through_at"] = fmt_utc(ends)
                    if now <= ends:
                        result["has_access"] = True
                        result["legacy"] = True
        return result
    finally:
        conn.close()


def record_verified_payment(conn, member_id, subscription_id, transaction_id,
                            amount, currency, paid_at, period_end, event_type,
                            source):
    """Record one verified payment interval, idempotently.

    Returns True when a new interval was recorded, False when this
    transaction was already on the ledger (duplicate delivery).
    """
    if transaction_id:
        existing = conn.execute(
            "SELECT id FROM member_payments WHERE paypal_transaction_id = ?",
            (transaction_id,),
        ).fetchone()
        if existing:
            return False
    period_start = fmt_utc(paid_at)
    period_end = fmt_utc(period_end)
    conn.execute(
        "INSERT INTO member_payments(member_id, subscription_id, "
        "paypal_transaction_id, amount, currency, status, event_type, "
        "period_start, period_end, source, created_at) "
        "VALUES (?, ?, ?, ?, ?, 'verified', ?, ?, ?, ?, ?)",
        (member_id, subscription_id, transaction_id, ("%.2f" % float(amount)),
         currency, event_type, period_start, period_end, source, fmt_utc(utcnow())),
    )
    _refresh_paid_through(conn, member_id)
    return True


def void_payment(conn, member_id, transaction_id, new_status):
    """Void a payment interval (refund/reversal). Returns True if voided."""
    row = conn.execute(
        "SELECT id FROM member_payments WHERE member_id = ? "
        "AND paypal_transaction_id = ? AND status = 'verified'",
        (member_id, transaction_id),
    ).fetchone()
    if not row:
        return False
    conn.execute(
        "UPDATE member_payments SET status = ? WHERE id = ?",
        (new_status, _row_dict(row).get("id")),
    )
    _refresh_paid_through(conn, member_id)
    return True


def _refresh_paid_through(conn, member_id):
    """Denormalize members.paid_through_at from the verified ledger."""
    rows = conn.execute(
        "SELECT period_end FROM member_payments "
        "WHERE member_id = ? AND status = 'verified'",
        (member_id,),
    ).fetchall()
    latest = None
    for row in rows:
        end = parse_time(_row_dict(row).get("period_end"))
        if end and (latest is None or end > latest):
            latest = end
    conn.execute(
        "UPDATE members SET paid_through_at = ?, last_verified_payment_at = ? "
        "WHERE id = ?",
        (fmt_utc(latest),
         fmt_utc(utcnow()) if latest else None,
         member_id),
    )


def find_verified_paypal_payments(subscription_id, since, until):
    """Fetch a subscription's transactions from PayPal and keep only
    COMPLETED payments of exactly $1.00 USD.

    Returns a list of dicts: transaction_id, paid_at (datetime), amount,
    currency, raw event id. Raises on PayPal API failure so callers can
    fail closed (and let PayPal retry a webhook) instead of guessing.
    """
    since_iso = fmt_utc(since) if isinstance(since, datetime) else since
    until_iso = fmt_utc(until) if isinstance(until, datetime) else until
    # PayPal accepts 'Z' and it needs no URL-encoding; a literal '+' in
    # '+00:00' would decode as a space in the query string.
    since_iso = str(since_iso).replace("+00:00", "Z")
    until_iso = str(until_iso).replace("+00:00", "Z")
    data = paypal_subscriptions.paypal_request(
        "GET",
        "/v1/billing/subscriptions/%s/transactions?start_time=%s&end_time=%s&page_size=100"
        % (subscription_id, since_iso, until_iso),
    )
    found = []
    for txn in data.get("transactions") or []:
        status = str(txn.get("status") or "").upper()
        amount_block = txn.get("amount_with_breakdown") or txn.get("amount") or {}
        gross = amount_block.get("gross_amount") or amount_block
        try:
            value = float(str(gross.get("value", "")).strip())
        except (ValueError, TypeError, AttributeError):
            continue
        currency = str(gross.get("currency_code", "")).upper()
        if status != "COMPLETED" or value != MEMBER_PRICE or currency != MEMBER_CURRENCY:
            continue
        paid_at = parse_time(txn.get("time"))
        if paid_at is None:
            continue
        found.append({
            "transaction_id": str(txn.get("id") or "").strip() or None,
            "paid_at": paid_at,
            "amount": value,
            "currency": currency,
        })
    return found


def verify_and_record_subscription_payments(member_id, subscription_id,
                                            subscription=None, source="recheck"):
    """Verify a subscription's captured payments with PayPal and record
    any not yet on the ledger.

    ``subscription`` may be a previously fetched subscription dict (to
    avoid a second API call); otherwise it is fetched here. Returns the
    number of newly recorded payments. Raises on PayPal API failure.
    """
    if subscription is None:
        subscription = paypal_subscriptions.get_subscription(subscription_id)
    since_raw = subscription.get("start_time") or subscription.get("create_time")
    since = parse_time(since_raw) or utcnow()
    # Only recent payments can cover the current moment (each buys about a
    # month), so clamp the lookup window: a multi-year window risks a
    # rejected PayPal query and buys nothing for an access decision.
    floor = utcnow() - timedelta(days=370)
    if since < floor:
        since = floor
    until = utcnow()
    payments = find_verified_paypal_payments(subscription_id, since, until)
    next_billing = parse_time((subscription.get("billing_info") or {}).get("next_billing_time"))
    conn = get_db()
    try:
        recorded = 0
        for payment in payments:
            period_end = next_billing
            if not period_end or period_end <= payment["paid_at"]:
                period_end = add_month(payment["paid_at"])
            if record_verified_payment(
                conn, member_id, subscription_id, payment["transaction_id"],
                payment["amount"], payment["currency"], payment["paid_at"],
                period_end, "PAYMENT_VERIFIED", source,
            ):
                recorded += 1
        conn.commit()
        return recorded
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()


def recheck_member_payments(member_id):
    """Best-effort re-verification for a member with a PayPal subscription
    attached. Returns newly recorded payment count, or 0 on any failure
    (callers treat failure as 'still unverified', never as proof either way).
    """
    try:
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT subscription_id FROM subscriptions WHERE member_id = ? "
                "AND provider = 'paypal' ORDER BY id DESC LIMIT 1",
                (member_id,),
            ).fetchone()
        finally:
            conn.close()
        if not row:
            return 0
        subscription_id = _row_dict(row).get("subscription_id")
        if not subscription_id:
            return 0
        return verify_and_record_subscription_payments(
            member_id, subscription_id, source="recheck")
    except Exception:
        logger.exception("Payment recheck failed for member %s", member_id)
        return 0
