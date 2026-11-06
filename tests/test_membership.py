"""Automated tests for the K. W. Snyder Writing membership system.

Covers the 18 scenarios from the repair brief, against the real Flask
application with a throwaway SQLite database and a mocked PayPal API
(no network, no real payments, no real customer accounts).

Run:  python3 tests/run_membership_tests.py
Exit code 0 = every scenario passed.
"""

import os
import sys
import tempfile

# --- Test database: throwaway SQLite file, never the real scriptorium.db ---
TMP = tempfile.mkdtemp(prefix="snyder_member_tests_")
DB_PATH = os.path.join(TMP, "scriptorium.db")
os.environ.pop("DATABASE_URL", None)
os.environ.pop("RENDER", None)
os.environ["PAYPAL_PLAN_INTRO_1"] = "P-TESTPLAN1"
os.environ.pop("PAYPAL_CLIENT_ID", None)
os.environ.pop("PAYPAL_CLIENT_SECRET", None)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database

database.DATABASE = DB_PATH
from database import init_db, get_db

init_db()

from app import ADMIN_AUTH_VERSION, app

app.config.update(TESTING=True, SECRET_KEY="test-secret")

from paypal_member_routes import register_paypal_member

register_paypal_member(app)
from member_auth_guard import register_member_auth_guard

register_member_auth_guard(app)
from canonical_analytics_tracker import register as register_tracker

register_tracker(app)
from analytics_dashboard_v3 import register as register_analytics

register_analytics(app)
import inbox_admin_routes  # noqa: F401  (registers blocked-member bounce)
# Templates reference the storefront blueprint (base.html nav), so it must
# exist for page renders, exactly as wsgi.py registers it in production.
from store import store_bp, ensure_store_tables

if "store" not in app.blueprints:
    app.register_blueprint(store_bp)
ensure_store_tables()
from store_reviews import reviews_bp, ensure_review_tables

if "reviews" not in app.blueprints:
    app.register_blueprint(reviews_bp)
ensure_review_tables()

import paypal_member_routes
import paypal_subscriptions

UA = {"User-Agent": "Mozilla/5.0 (Test)"}


class FakePayPal:
    """Minimal PayPal Subscriptions stand-in."""

    PLAN_ID = "P-TESTPLAN1"

    def __init__(self):
        self.subscriptions = {}
        self.transactions = {}
        self.verify_ok = True
        self.cancelled = []

    def plan(self):
        return {
            "id": self.PLAN_ID,
            "status": "ACTIVE",
            "billing_cycles": [{
                "tenure_type": "REGULAR",
                "pricing_scheme": {"fixed_price": {"value": "1.00", "currency_code": "USD"}},
            }],
        }

    def make_sub(self, sub_id, status="ACTIVE",
                 start="2026-11-01T00:00:00Z", next_billing="2026-12-01T00:00:00Z"):
        sub = {
            "id": sub_id, "plan_id": self.PLAN_ID, "status": status,
            "start_time": start, "create_time": start,
            "billing_info": {"next_billing_time": next_billing} if next_billing else {},
        }
        self.subscriptions[sub_id] = sub
        # A (re)created subscription starts with no transactions, exactly
        # as on PayPal; otherwise one test's payment leaks into the next.
        self.transactions.pop(sub_id, None)
        return sub

    def add_txn(self, sub_id, txn_id, time, value="1.00", currency="USD", status="COMPLETED"):
        self.transactions.setdefault(sub_id, []).append({
            "id": txn_id, "status": status, "time": time,
            "amount_with_breakdown": {"gross_amount": {"value": value, "currency_code": currency}},
        })

    def paypal_request(self, method, path, payload=None, headers=None):
        if path.startswith("/v1/billing/plans/"):
            return self.plan()
        if "/transactions" in path:
            sub_id = path.split("/v1/billing/subscriptions/")[1].split("/transactions")[0]
            return {"transactions": self.transactions.get(sub_id, [])}
        if path.startswith("/v1/billing/subscriptions/"):
            rest = path.split("/v1/billing/subscriptions/")[1]
            sub_id = rest.split("/")[0].split("?")[0]
            if rest.endswith("/cancel"):
                if sub_id in self.subscriptions:
                    self.subscriptions[sub_id]["status"] = "CANCELLED"
                    self.subscriptions[sub_id]["billing_info"] = {}
                    self.cancelled.append(sub_id)
                return {}
            if sub_id not in self.subscriptions:
                raise RuntimeError("subscription not found: " + sub_id)
            return self.subscriptions[sub_id]
        if method == "POST" and path == "/v1/billing/subscriptions":
            self.make_sub("I-NEWTESTSUB", status="APPROVAL_PENDING")
            return {"id": "I-NEWTESTSUB",
                    "links": [{"rel": "approve", "href": "https://paypal.test/approve"}]}
        raise RuntimeError("unexpected paypal_request: %s %s" % (method, path))

    def get_subscription(self, sub_id):
        return self.paypal_request("GET", "/v1/billing/subscriptions/" + sub_id)

    def verify_webhook(self, headers, event):
        return self.verify_ok


FAKE = FakePayPal()
paypal_member_routes.paypal_request = FAKE.paypal_request
paypal_member_routes.get_subscription = FAKE.get_subscription
paypal_member_routes.verify_webhook = FAKE.verify_webhook
paypal_subscriptions.paypal_request = FAKE.paypal_request
paypal_subscriptions.get_subscription = FAKE.get_subscription


# --- DB helpers ------------------------------------------------------------

def conn():
    return get_db()


def make_member(email, status="active", subscription_status="inactive"):
    c = conn()
    cur = c.execute(
        "INSERT INTO members(email, password_hash, subscription_status, date_created, status) "
        "VALUES (?, ?, ?, ?, ?)",
        (email, "x", subscription_status, "11/03/2026 09:00 PM", status))
    mid = cur.lastrowid
    c.commit()
    c.close()
    return mid


def attach_sub(member_id, sub_id, status="active",
               started="2026-11-01T00:00:00Z", ends="2026-12-01T00:00:00Z"):
    c = conn()
    c.execute(
        "INSERT INTO subscriptions(member_id, provider, subscription_id, status, date_started, date_ends) "
        "VALUES (?, 'paypal', ?, ?, ?, ?)",
        (member_id, sub_id, status, started, ends))
    c.execute("UPDATE members SET subscription_status = ? WHERE id = ?", (status, member_id))
    c.commit()
    c.close()


def add_payment(member_id, sub_id, txn_id, start, end, status="verified"):
    c = conn()
    c.execute(
        "INSERT INTO member_payments(member_id, subscription_id, paypal_transaction_id, amount, currency, "
        "status, event_type, period_start, period_end, source, created_at) "
        "VALUES (?, ?, ?, '1.00', 'USD', ?, 'PAYMENT_VERIFIED', ?, ?, 'test', ?)",
        (member_id, sub_id, txn_id, status, start, end, start))
    # Mirror production's _refresh_paid_through denormalization.
    c.execute(
        "UPDATE members SET paid_through_at = "
        "(SELECT MAX(period_end) FROM member_payments WHERE member_id = ? AND status = 'verified') "
        "WHERE id = ?",
        (member_id, member_id))
    c.commit()
    c.close()


def member_status(member_id):
    c = conn()
    row = c.execute("SELECT subscription_status, paid_through_at FROM members WHERE id = ?",
                    (member_id,)).fetchone()
    c.close()
    return dict(row) if row else None


def member_id(email):
    c = conn()
    row = c.execute("SELECT id FROM members WHERE email = ?", (email,)).fetchone()
    c.close()
    return dict(row)["id"] if row else None


def member_exists(email):
    return member_id(email) is not None


def pending_exists(email):
    c = conn()
    row = c.execute("SELECT id FROM pending_signups WHERE email = ?", (email,)).fetchone()
    c.close()
    return row is not None


def member_session(client, member_id):
    with client.session_transaction() as sess:
        sess["member_logged_in"] = True
        sess["member_id"] = member_id


def clear_session(client):
    """Drop any session left by an earlier scenario (member login,
    pending signup). The signup scenarios must start as a stranger."""
    with client.session_transaction() as sess:
        sess.clear()


def admin_session(client):
    with client.session_transaction() as sess:
        sess["admin_logged_in"] = True
        sess["admin_auth_version"] = ADMIN_AUTH_VERSION


def seed_content():
    c = conn()
    cur = c.execute(
        "INSERT INTO published_posts(title, category, category_name, content, date_published, access_level) "
        "VALUES ('Secret Story', 'kwsnyderwriting', 'K. W. Snyder Writing', 'SECRET MEMBER CONTENT HERE', '11/03/2026', 'members')")
    post_id = cur.lastrowid
    cur = c.execute(
        "INSERT INTO published_posts(title, category, category_name, content, date_published, access_level) "
        "VALUES ('Public Post', 'curations', 'Book Curations', 'PUBLIC CONTENT HERE', '11/03/2026', 'public')")
    public_id = cur.lastrowid
    cur = c.execute(
        "INSERT INTO manuscript_books(title, description, date_created, access_level) "
        "VALUES ('Secret Novel', '', '11/03/2026', 'members')")
    book_id = cur.lastrowid
    cur = c.execute(
        "INSERT INTO manuscript_chapters(book_id, chapter_number, title, content, date_created, published) "
        "VALUES (?, 1, 'Chapter One', 'SECRET CHAPTER CONTENT', '11/03/2026', 1)", (book_id,))
    chapter_id = cur.lastrowid
    c.commit()
    c.close()
    return post_id, public_id, book_id, chapter_id


POST_ID, PUBLIC_ID, BOOK_ID, CHAPTER_ID = seed_content()

# A paid interval covering "now" (tests run Nov 2026) and an expired one.
PAID_START = "2026-11-01T00:00:00+00:00"
PAID_END = "2026-12-01T00:00:00+00:00"
OLD_START = "2026-09-01T00:00:00+00:00"
OLD_END = "2026-10-01T00:00:00+00:00"


def check(name, condition, detail=""):
    if not condition:
        raise AssertionError("%s -- %s" % (name, detail))


def webhook(client, event_id, event_type, resource):
    return client.post("/api/paypal/webhook", json={
        "id": event_id, "event_type": event_type, "resource": resource,
    }, headers=UA)


# --- Scenarios -------------------------------------------------------------

def t01_new_account_no_payment(client):
    """1. New account with no payment gets no private content."""
    mid = make_member("t01@example.com")
    member_session(client, mid)
    r = client.get("/kwsnyderwriting/post/%d" % POST_ID, headers=UA)
    check("t01 post denied", r.status_code == 302 and "SECRET MEMBER CONTENT" not in r.get_data(as_text=True),
          "status=%s" % r.status_code)
    r = client.get("/kwsnyderwriting/novel/%d/chapter/%d" % (BOOK_ID, CHAPTER_ID), headers=UA)
    check("t01 chapter denied", r.status_code == 302, "status=%s" % r.status_code)
    r = client.get("/kwsnyderwriting", headers=UA)
    check("t01 entry denied", r.status_code == 302, "status=%s" % r.status_code)


def t02_verified_initial_payment(client):
    """2. New account with a verified initial $1 payment can read."""
    mid = make_member("t02@example.com")
    attach_sub(mid, "I-T02", status="pending_payment")
    FAKE.make_sub("I-T02", status="ACTIVE")
    FAKE.add_txn("I-T02", "TXN-T02", "2026-11-01T00:00:00Z")
    member_session(client, mid)
    r = client.get("/kwsnyderwriting/membership/return?subscription_id=I-T02", headers=UA)
    check("t02 return activates", r.status_code == 302 and "subscribed=1" in (r.headers.get("Location") or ""),
          "status=%s loc=%s" % (r.status_code, r.headers.get("Location")))
    st = member_status(mid)
    check("t02 status active", st["subscription_status"] == "active", str(st))
    r = client.get("/kwsnyderwriting/post/%d" % POST_ID, headers=UA)
    check("t02 post open", r.status_code == 200 and "SECRET MEMBER CONTENT" in r.get_data(as_text=True),
          "status=%s" % r.status_code)


def t03_active_but_no_payment(client):
    """3. PayPal ACTIVE with no verified payment grants nothing."""
    mid = make_member("t03@example.com")
    attach_sub(mid, "I-T03", status="pending_payment")
    FAKE.make_sub("I-T03", status="ACTIVE")  # ACTIVE, but zero transactions
    member_session(client, mid)
    r = client.get("/kwsnyderwriting/membership/return?subscription_id=I-T03", headers=UA)
    check("t03 return pending", r.status_code == 302 and "verifying=1" in (r.headers.get("Location") or ""),
          "status=%s loc=%s" % (r.status_code, r.headers.get("Location")))
    st = member_status(mid)
    check("t03 status pending", st["subscription_status"] == "pending_payment", str(st))
    r = client.get("/kwsnyderwriting/post/%d" % POST_ID, headers=UA)
    check("t03 post denied", r.status_code == 302, "status=%s" % r.status_code)
    # ACTIVATED webhook alone must not activate either.
    r = webhook(client, "WH-T03", "BILLING.SUBSCRIPTION.ACTIVATED", {"id": "I-T03"})
    check("t03 webhook ok", r.status_code == 200, "status=%s" % r.status_code)
    st = member_status(mid)
    check("t03 still pending", st["subscription_status"] == "pending_payment", str(st))


def t04_successful_renewal(client):
    """4. A renewal payment extends the paid period."""
    mid = make_member("t04@example.com")
    attach_sub(mid, "I-T04", status="active")
    add_payment(mid, "I-T04", "TXN-T04-OLD", OLD_START, "2026-11-01T00:00:00+00:00")
    FAKE.make_sub("I-T04", status="ACTIVE", next_billing="2026-12-01T00:00:00Z")
    FAKE.add_txn("I-T04", "TXN-T04-OLD", "2026-10-01T00:00:00Z")
    FAKE.add_txn("I-T04", "TXN-T04-NEW", "2026-11-01T00:00:00Z")
    r = webhook(client, "WH-T04", "PAYMENT.SALE.COMPLETED",
                {"id": "SALE-T04", "billing_agreement_id": "I-T04"})
    check("t04 webhook ok", r.status_code == 200, "status=%s body=%s" % (r.status_code, r.get_data(as_text=True)))
    member_session(client, mid)
    r = client.get("/kwsnyderwriting/post/%d" % POST_ID, headers=UA)
    check("t04 post open after renewal", r.status_code == 200, "status=%s" % r.status_code)
    st = member_status(mid)
    check("t04 paid through Dec", (st["paid_through_at"] or "").startswith("2026-12-01"), str(st))


def t05_failed_renewal(client):
    """5. A failed renewal keeps the current paid period, extends nothing."""
    mid = make_member("t05@example.com")
    attach_sub(mid, "I-T05", status="active")
    add_payment(mid, "I-T05", "TXN-T05", PAID_START, PAID_END)
    r = webhook(client, "WH-T05", "BILLING.SUBSCRIPTION.PAYMENT.FAILED", {"id": "I-T05"})
    check("t05 webhook ok", r.status_code == 200, "status=%s" % r.status_code)
    st = member_status(mid)
    check("t05 past due", st["subscription_status"] == "past_due", str(st))
    member_session(client, mid)
    r = client.get("/kwsnyderwriting/post/%d" % POST_ID, headers=UA)
    check("t05 still reads paid period", r.status_code == 200, "status=%s" % r.status_code)


def t06_cancelled_with_time_left(client):
    """6. Cancelled with time left keeps access through the paid period."""
    mid = make_member("t06@example.com")
    attach_sub(mid, "I-T06", status="active")
    add_payment(mid, "I-T06", "TXN-T06", PAID_START, PAID_END)
    FAKE.make_sub("I-T06", status="ACTIVE")
    member_session(client, mid)
    r = client.post("/api/paypal/cancel-subscription", headers=UA)
    check("t06 cancel ok", r.status_code == 200, "status=%s body=%s" % (r.status_code, r.get_data(as_text=True)))
    st = member_status(mid)
    check("t06 status cancelled", st["subscription_status"] == "cancelled", str(st))
    check("t06 paid through kept", (st["paid_through_at"] or "").startswith("2026-12-01"), str(st))
    r = client.get("/kwsnyderwriting/post/%d" % POST_ID, headers=UA)
    check("t06 still reads", r.status_code == 200, "status=%s" % r.status_code)


def t07_cancelled_after_period(client):
    """7. Cancelled after the paid period ends: no access."""
    mid = make_member("t07@example.com")
    attach_sub(mid, "I-T07", status="cancelled", ends="2026-10-01T00:00:00Z")
    add_payment(mid, "I-T07", "TXN-T07", OLD_START, OLD_END)
    member_session(client, mid)
    r = client.get("/kwsnyderwriting/post/%d" % POST_ID, headers=UA)
    check("t07 denied", r.status_code == 302, "status=%s" % r.status_code)


def t08_expired(client):
    """8. Expired subscription: no access."""
    mid = make_member("t08@example.com")
    attach_sub(mid, "I-T08", status="expired", ends="2026-10-01T00:00:00Z")
    add_payment(mid, "I-T08", "TXN-T08", OLD_START, OLD_END)
    member_session(client, mid)
    r = client.get("/kwsnyderwriting/novel/%d" % BOOK_ID, headers=UA)
    check("t08 denied", r.status_code == 302, "status=%s" % r.status_code)


def t09_refunded_payment(client):
    """9. A refunded payment voids its interval and ends access."""
    mid = make_member("t09@example.com")
    attach_sub(mid, "I-T09", status="active")
    add_payment(mid, "I-T09", "TXN-T09", PAID_START, PAID_END)
    member_session(client, mid)
    r = client.get("/kwsnyderwriting/post/%d" % POST_ID, headers=UA)
    check("t09 reads before refund", r.status_code == 200, "status=%s" % r.status_code)
    r = webhook(client, "WH-T09", "PAYMENT.SALE.REFUNDED",
                {"id": "RF-T09", "sale_id": "TXN-T09"})
    check("t09 webhook ok", r.status_code == 200, "status=%s body=%s" % (r.status_code, r.get_data(as_text=True)))
    r = client.get("/kwsnyderwriting/post/%d" % POST_ID, headers=UA)
    check("t09 denied after refund", r.status_code == 302, "status=%s" % r.status_code)


def t10_forged_webhook(client):
    """10. An invalid/forged webhook changes nothing."""
    mid = make_member("t10@example.com")
    attach_sub(mid, "I-T10", status="pending_payment")
    FAKE.verify_ok = False
    try:
        r = webhook(client, "WH-T10", "BILLING.SUBSCRIPTION.ACTIVATED", {"id": "I-T10"})
    finally:
        FAKE.verify_ok = True
    check("t10 rejected", r.status_code == 400, "status=%s" % r.status_code)
    st = member_status(mid)
    check("t10 unchanged", st["subscription_status"] == "pending_payment", str(st))


def t11_duplicate_webhook(client):
    """11. A duplicate webhook records the payment once, extends once."""
    mid = make_member("t11@example.com")
    attach_sub(mid, "I-T11", status="pending_payment")
    FAKE.make_sub("I-T11", status="ACTIVE", next_billing="2026-12-01T00:00:00Z")
    FAKE.add_txn("I-T11", "TXN-T11", "2026-11-01T00:00:00Z")
    event = {"id": "WH-T11", "event_type": "PAYMENT.SALE.COMPLETED",
             "resource": {"id": "SALE-T11", "billing_agreement_id": "I-T11"}}
    r1 = client.post("/api/paypal/webhook", json=event, headers=UA)
    r2 = client.post("/api/paypal/webhook", json=event, headers=UA)
    check("t11 both 200", r1.status_code == 200 and r2.status_code == 200,
          "%s %s" % (r1.status_code, r2.status_code))
    check("t11 second is duplicate", r2.get_json().get("duplicate") is True, r2.get_data(as_text=True))
    c = conn()
    n = c.execute("SELECT COUNT(*) AS n FROM member_payments WHERE member_id = ?",
                  (mid,)).fetchone()
    c.close()
    check("t11 one payment row", dict(n)["n"] == 1, str(dict(n)))
    st = member_status(mid)
    check("t11 paid through Dec once", (st["paid_through_at"] or "").startswith("2026-12-01"), str(st))


def t12_blocked_member(client):
    """12. A blocked member cannot log in and cannot read."""
    mid = make_member("t12@example.com", status="blocked")
    attach_sub(mid, "I-T12", status="active")
    add_payment(mid, "I-T12", "TXN-T12", PAID_START, PAID_END)
    # Direct session injection (as if an old session survived the block).
    member_session(client, mid)
    r = client.get("/kwsnyderwriting/post/%d" % POST_ID, headers=UA)
    check("t12 session bounced", r.status_code == 302 and "SECRET MEMBER CONTENT" not in r.get_data(as_text=True),
          "status=%s" % r.status_code)
    # Login with a correct password must also refuse a blocked account.
    c = conn()
    from werkzeug.security import generate_password_hash
    c.execute("UPDATE members SET password_hash = ? WHERE id = ?",
              (generate_password_hash("password123"), mid))
    c.commit()
    c.close()
    r = client.post("/kwsnyderwriting/login",
                    data={"email": "t12@example.com", "password": "password123"}, headers=UA)
    check("t12 login refused", r.status_code == 200 and b"blocked" in r.data.lower(),
          "status=%s" % r.status_code)


def t13_direct_url_unpaid(client):
    """13. An unpaid member opening private writing by direct URL is denied."""
    mid = make_member("t13@example.com")
    member_session(client, mid)
    for url in ("/kwsnyderwriting/post/%d" % POST_ID,
                "/kwsnyderwriting/novel/%d" % BOOK_ID,
                "/kwsnyderwriting/novel/%d/chapter/%d" % (BOOK_ID, CHAPTER_ID),
                "/kwsnyderwriting/short-stories"):
        r = client.get(url, headers=UA)
        check("t13 denied %s" % url, r.status_code == 302, "status=%s" % r.status_code)


def t14_unauthenticated_api(client):
    """14. An unauthenticated visitor gets no private content from APIs."""
    r = client.get("/api/published/%d" % POST_ID, headers=UA)
    check("t14 published api denied", r.status_code in (302, 401, 403) and b"SECRET MEMBER CONTENT" not in r.data,
          "status=%s" % r.status_code)
    r = client.get("/api/manuscripts/%d" % BOOK_ID, headers=UA)
    check("t14 manuscripts api denied", r.status_code in (302, 401, 403) and b"SECRET CHAPTER" not in r.data,
          "status=%s" % r.status_code)
    r = client.get("/kwsnyderwriting/post/%d" % POST_ID, headers=UA)
    check("t14 member post denied", r.status_code == 302, "status=%s" % r.status_code)


def t15_authorized_member_reads_all(client):
    """15. An authorized member opens a post, a novel, and a chapter."""
    mid = make_member("t15@example.com")
    attach_sub(mid, "I-T15", status="active")
    add_payment(mid, "I-T15", "TXN-T15", PAID_START, PAID_END)
    member_session(client, mid)
    r = client.get("/kwsnyderwriting/post/%d" % POST_ID, headers=UA)
    check("t15 post", r.status_code == 200 and "SECRET MEMBER CONTENT" in r.get_data(as_text=True),
          "status=%s" % r.status_code)
    r = client.get("/kwsnyderwriting/novel/%d" % BOOK_ID, headers=UA)
    check("t15 novel", r.status_code == 200 and "Chapter One" in r.get_data(as_text=True),
          "status=%s" % r.status_code)
    r = client.get("/kwsnyderwriting/novel/%d/chapter/%d" % (BOOK_ID, CHAPTER_ID), headers=UA)
    check("t15 chapter", r.status_code == 200 and "SECRET CHAPTER CONTENT" in r.get_data(as_text=True),
          "status=%s" % r.status_code)


def t16_member_readership_analytics(client):
    """16. Reads carry the member id; blocked attempts are separate."""
    mid = make_member("t16@example.com")
    attach_sub(mid, "I-T16", status="active")
    add_payment(mid, "I-T16", "TXN-T16", PAID_START, PAID_END)
    member_session(client, mid)
    client.get("/kwsnyderwriting/post/%d" % POST_ID, headers=UA)
    client.get("/kwsnyderwriting/novel/%d/chapter/%d" % (BOOK_ID, CHAPTER_ID), headers=UA)
    mid2 = make_member("t16b@example.com")
    member_session(client, mid2)
    client.get("/kwsnyderwriting/post/%d" % POST_ID, headers=UA)  # blocked
    c = conn()
    reads = c.execute(
        "SELECT member_id, content_id, page_type FROM page_views "
        "WHERE category = 'kwsnyderwriting' AND access_result = 'ok' AND member_id = ?",
        (mid,)).fetchall()
    blocked = c.execute(
        "SELECT member_id, content_id FROM page_views "
        "WHERE category = 'kwsnyderwriting' AND access_result = 'blocked' AND member_id = ?",
        (mid2,)).fetchall()
    c.close()
    reads = [dict(r) for r in reads]
    blocked = [dict(r) for r in blocked]
    check("t16 two reads with member id", len(reads) == 2, str(reads))
    check("t16 read ids", {r["content_id"] for r in reads} == {POST_ID, CHAPTER_ID}, str(reads))
    check("t16 one blocked row", len(blocked) == 1 and blocked[0]["content_id"] == POST_ID, str(blocked))


def t17_admin_readership_report(client):
    """17. Admins see the readership report; non-admins do not."""
    mid = make_member("t17@example.com")
    attach_sub(mid, "I-T17", status="active")
    add_payment(mid, "I-T17", "TXN-T17", PAID_START, PAID_END)
    member_session(client, mid)
    client.get("/kwsnyderwriting/post/%d" % POST_ID, headers=UA)
    admin_session(client)
    r = client.get("/admin/member-reads", headers=UA)
    body = r.get_data(as_text=True)
    check("t17 admin sees report", r.status_code == 200 and "t17@example.com" in body and "Secret Story" in body,
          "status=%s" % r.status_code)
    check("t17 tracking notice", "Reliable member-level tracking began" in body, "notice missing")
    with client.session_transaction() as sess:
        sess.clear()
    member_session(client, mid)
    r = client.get("/admin/member-reads", headers=UA)
    check("t17 member denied", r.status_code == 302, "status=%s" % r.status_code)


def t18_public_writing_public(client):
    """18. Public writing stays public; member posts stay out of search."""
    r = client.get("/blog/post/%d" % PUBLIC_ID, headers=UA)
    check("t18 public post open", r.status_code == 200 and "PUBLIC CONTENT" in r.get_data(as_text=True),
          "status=%s" % r.status_code)
    r = client.get("/search?q=Secret+Story", headers=UA)
    body = r.get_data(as_text=True)
    # The page echoes the query itself, so the leak check is the member
    # post's link and content, not the searched words.
    check("t18 member post not in search",
          ("/kwsnyderwriting/post/%d" % POST_ID) not in body and "SECRET MEMBER CONTENT" not in body,
          "leaked into search")
    r = client.get("/sitemap-blog.xml", headers=UA)
    check("t18 member post not in sitemap",
          ("/kwsnyderwriting/post/%d" % POST_ID) not in r.get_data(as_text=True), "leaked into sitemap")


def t20_signup_creates_no_account(client):
    """20. Signup sends the buyer to PayPal; no account exists yet."""
    clear_session(client)
    r = client.post("/kwsnyderwriting/signup-subscribe",
                    data={"email": "t20@example.com", "password": "password123", "terms_agreed": "yes"}, headers=UA)
    check("t20 to paypal", r.status_code == 302 and "paypal.test/approve" in (r.headers.get("Location") or ""),
          "status=%s loc=%s" % (r.status_code, r.headers.get("Location")))
    check("t20 no member row", not member_exists("t20@example.com"))
    check("t20 pending row", pending_exists("t20@example.com"))
    with client.session_transaction() as sess:
        check("t20 not logged in", not sess.get("member_logged_in"))
        check("t20 pending session", bool(sess.get("pending_signup_id")))
    # The abandoned signup cannot read anything or log in.
    r = client.get("/kwsnyderwriting", headers=UA)
    check("t20 entry denied", r.status_code == 302, "status=%s" % r.status_code)
    r = client.post("/kwsnyderwriting/login",
                    data={"email": "t20@example.com", "password": "password123"}, headers=UA)
    check("t20 login refused", r.status_code == 200 and b"not recognized" in r.data.lower(),
          "status=%s" % r.status_code)


def t21_return_with_payment_creates_account(client):
    """21. PayPal return with a verified $1 payment creates the account."""
    clear_session(client)
    client.post("/kwsnyderwriting/signup-subscribe",
                data={"email": "t21@example.com", "password": "password123", "terms_agreed": "yes"}, headers=UA)
    FAKE.make_sub("I-NEWTESTSUB", status="ACTIVE")
    FAKE.add_txn("I-NEWTESTSUB", "TXN-T21", "2026-11-01T00:00:00Z")
    r = client.get("/kwsnyderwriting/membership/return?subscription_id=I-NEWTESTSUB", headers=UA)
    check("t21 return subscribes", r.status_code == 302 and "subscribed=1" in (r.headers.get("Location") or ""),
          "status=%s loc=%s" % (r.status_code, r.headers.get("Location")))
    check("t21 member now exists", member_exists("t21@example.com"))
    mid = member_id("t21@example.com")
    st = member_status(mid)
    check("t21 status active", st["subscription_status"] == "active", str(st))
    check("t21 pending gone", not pending_exists("t21@example.com"))
    r = client.get("/kwsnyderwriting/post/%d" % POST_ID, headers=UA)
    check("t21 post open", r.status_code == 200 and "SECRET MEMBER CONTENT" in r.get_data(as_text=True),
          "status=%s" % r.status_code)


def t22_return_without_payment_no_account(client):
    """22. PayPal return with no cleared payment creates no account yet;
    the membership page finishes activation when the payment lands."""
    clear_session(client)
    client.post("/kwsnyderwriting/signup-subscribe",
                data={"email": "t22@example.com", "password": "password123", "terms_agreed": "yes"}, headers=UA)
    FAKE.make_sub("I-NEWTESTSUB", status="ACTIVE")  # no transactions
    r = client.get("/kwsnyderwriting/membership/return?subscription_id=I-NEWTESTSUB", headers=UA)
    check("t22 return verifying", r.status_code == 302 and "verifying=1" in (r.headers.get("Location") or ""),
          "status=%s loc=%s" % (r.status_code, r.headers.get("Location")))
    check("t22 no member yet", not member_exists("t22@example.com"))
    check("t22 pending kept", pending_exists("t22@example.com"))
    # Payment lands; the next membership visit completes activation.
    FAKE.add_txn("I-NEWTESTSUB", "TXN-T22", "2026-11-01T00:00:00Z")
    r = client.get("/kwsnyderwriting/membership?verifying=1", headers=UA)
    check("t22 membership activates", r.status_code == 302 and "subscribed=1" in (r.headers.get("Location") or ""),
          "status=%s loc=%s" % (r.status_code, r.headers.get("Location")))
    check("t22 member now exists", member_exists("t22@example.com"))
    mid = member_id("t22@example.com")
    st = member_status(mid)
    check("t22 status active", st["subscription_status"] == "active", str(st))
    r = client.get("/kwsnyderwriting/post/%d" % POST_ID, headers=UA)
    check("t22 post open", r.status_code == 200 and "SECRET MEMBER CONTENT" in r.get_data(as_text=True),
          "status=%s" % r.status_code)


def t23_plain_signup_creates_no_account(client):
    """23. The plain signup route also goes to PayPal with no account."""
    clear_session(client)
    r = client.post("/kwsnyderwriting/signup",
                    data={"email": "t23@example.com", "password": "password123", "terms_agreed": "yes"}, headers=UA)
    check("t23 to paypal", r.status_code == 302 and "paypal.test/approve" in (r.headers.get("Location") or ""),
          "status=%s loc=%s" % (r.status_code, r.headers.get("Location")))
    check("t23 no member row", not member_exists("t23@example.com"))
    check("t23 pending row", pending_exists("t23@example.com"))


def t24_never_activated_login_refused(client):
    """24. A never-activated member (old flow) cannot log in; re-signup
    with the same email replaces the stale row and completes."""
    clear_session(client)
    mid = make_member("t24@example.com")  # inactive, no subscription, no payments
    c = conn()
    from werkzeug.security import generate_password_hash
    c.execute("UPDATE members SET password_hash = ? WHERE id = ?",
              (generate_password_hash("password123"), mid))
    c.commit()
    c.close()
    r = client.post("/kwsnyderwriting/login",
                    data={"email": "t24@example.com", "password": "password123"}, headers=UA)
    check("t24 login refused", r.status_code == 200 and b"never activated" in r.data.lower(),
          "status=%s" % r.status_code)
    r = client.post("/kwsnyderwriting/signup-subscribe",
                    data={"email": "t24@example.com", "password": "password123", "terms_agreed": "yes"}, headers=UA)
    check("t24 re-signup to paypal", r.status_code == 302 and "paypal.test/approve" in (r.headers.get("Location") or ""),
          "status=%s loc=%s" % (r.status_code, r.headers.get("Location")))
    check("t24 stale row replaced", member_id("t24@example.com") is None)
    check("t24 pending row", pending_exists("t24@example.com"))
    FAKE.make_sub("I-NEWTESTSUB", status="ACTIVE")
    FAKE.add_txn("I-NEWTESTSUB", "TXN-T24", "2026-11-01T00:00:00Z")
    r = client.get("/kwsnyderwriting/membership/return?subscription_id=I-NEWTESTSUB", headers=UA)
    check("t24 return subscribes", r.status_code == 302 and "subscribed=1" in (r.headers.get("Location") or ""),
          "status=%s loc=%s" % (r.status_code, r.headers.get("Location")))
    check("t24 member active", member_exists("t24@example.com")
          and member_status(member_id("t24@example.com"))["subscription_status"] == "active")


def t25_approved_then_closed_tab_no_double_charge(client):
    """25. Buyer approves on PayPal then closes the tab: re-submitting
    signup with the same email activates from the paid subscription
    instead of starting a second checkout."""
    clear_session(client)
    client.post("/kwsnyderwriting/signup-subscribe",
                data={"email": "t25@example.com", "password": "password123", "terms_agreed": "yes"}, headers=UA)
    FAKE.make_sub("I-NEWTESTSUB", status="ACTIVE")
    FAKE.add_txn("I-NEWTESTSUB", "TXN-T25", "2026-11-01T00:00:00Z")
    # Buyer never returned; the payment is on PayPal's books. They sign
    # up again with the same email instead of coming back via the link.
    with client.session_transaction() as sess:
        sess.clear()
    r = client.post("/kwsnyderwriting/signup-subscribe",
                    data={"email": "t25@example.com", "password": "password123", "terms_agreed": "yes"}, headers=UA)
    check("t25 activates, no second checkout", r.status_code == 302 and "subscribed=1" in (r.headers.get("Location") or ""),
          "status=%s loc=%s" % (r.status_code, r.headers.get("Location")))
    check("t25 member active", member_exists("t25@example.com")
          and member_status(member_id("t25@example.com"))["subscription_status"] == "active")
    c = conn()
    n = c.execute("SELECT COUNT(*) AS n FROM members WHERE email = ?",
                  ("t25@example.com",)).fetchone()
    c.close()
    check("t25 exactly one member row", dict(n)["n"] == 1, str(dict(n)))


def t19_postgres_sql_compatibility():
    """Postgres dialect check: every new SQL string translates cleanly."""
    from database import PostgresConnection

    class _Dummy:
        pass

    translator = PostgresConnection.__new__(PostgresConnection)
    statements = [
        "SELECT period_start, period_end FROM member_payments WHERE member_id = ? AND status = 'verified' ORDER BY period_end",
        "INSERT INTO member_payments(member_id, subscription_id, paypal_transaction_id, amount, currency, status, event_type, period_start, period_end, source, created_at) VALUES (?, ?, ?, ?, ?, 'verified', ?, ?, ?, ?, ?)",
        "UPDATE member_payments SET status = ? WHERE id = ?",
        "INSERT INTO paypal_webhook_events(paypal_event_id, event_type, subscription_id, received_at) VALUES (?, ?, ?, ?)",
        "SELECT id FROM paypal_webhook_events WHERE paypal_event_id = ?",
        "CREATE TABLE IF NOT EXISTS pending_signups (id BIGSERIAL PRIMARY KEY,email TEXT UNIQUE NOT NULL,password_hash TEXT NOT NULL,subscription_id TEXT,created_at TEXT NOT NULL DEFAULT '')",
        "CREATE TABLE IF NOT EXISTS pending_signups (id INTEGER PRIMARY KEY AUTOINCREMENT,email TEXT UNIQUE NOT NULL,password_hash TEXT NOT NULL,subscription_id TEXT,created_at TEXT NOT NULL DEFAULT '')",
        "SELECT * FROM pending_signups WHERE id = ?",
        "SELECT * FROM pending_signups WHERE subscription_id = ? ORDER BY id DESC LIMIT 1",
        "INSERT INTO pending_signups(email, password_hash, subscription_id, created_at) VALUES (?, ?, ?, ?)",
        "DELETE FROM pending_signups WHERE created_at != '' AND created_at < ?",
        "SELECT m.id FROM members m JOIN subscriptions s ON s.member_id = m.id WHERE m.email = ? AND s.subscription_id = ? AND s.provider = 'paypal' ORDER BY m.id DESC LIMIT 1",
        "INSERT INTO page_views(path,page_type,content_id,category,visitor_key,referrer,traffic_source,classified,member_id,access_result) VALUES (?,?,?,?,?,?,?,?,?,?)",
        "SELECT path, page_type, content_id, viewed_at, member_id FROM page_views WHERE category = 'kwsnyderwriting' AND access_result = ? ORDER BY viewed_at DESC LIMIT 200",
        "SELECT COUNT(*) AS n FROM page_views WHERE category = 'kwsnyderwriting' AND access_result = 'ok'",
        "SELECT MAX(p.period_end) FROM member_payments p WHERE p.member_id = m.id AND p.status = 'verified'",
    ]
    for sql in statements:
        out = translator._translate(sql)
        check("t19 no ? left: %s" % sql[:60], "?" not in out, out)
        if "?" in sql:
            check("t19 has %%s: %s" % sql[:60], "%s" in out, out)


def t26_postgres_returning_id():
    """Postgres must RETURNING id for every INSERT whose lastrowid the
    code reads. Live signup bug, Nov 6 2026: pending_signups was missing
    from the list, so on Postgres the INSERT returned lastrowid None and
    the buyer bounced back to the membership page instead of reaching
    PayPal (silent failure -- no 500, no checkout)."""
    from database import PostgresConnection

    class _StubCursor:
        def __init__(self):
            self.sql = None

        def execute(self, sql, params=()):
            self.sql = sql

        def fetchone(self):
            return {"id": 7}

        @property
        def rowcount(self):
            return 1

    class _StubConn:
        def __init__(self):
            self.cursor_obj = _StubCursor()

        def cursor(self):
            return self.cursor_obj

    cases = {
        "pending_signups": "INSERT INTO pending_signups(email, password_hash, subscription_id, created_at) VALUES (?, ?, ?, ?)",
        "site_sync_tokens": "INSERT INTO site_sync_tokens(token_hash, label, created_at, revoked) VALUES (?, ?, ?, 0)",
        "members": "INSERT INTO members(email, password_hash, subscription_status, date_created) VALUES (?, ?, 'pending_payment', ?)",
    }
    for table, sql in cases.items():
        stub = _StubConn()
        pg = PostgresConnection(stub)
        cur = pg.execute(sql, ("a", "b", "c", "d"))
        check("t26 RETURNING id: %s" % table, "RETURNING id" in (stub.cursor_obj.sql or ""), stub.cursor_obj.sql)
        check("t26 lastrowid: %s" % table, cur.lastrowid == 7, str(cur.lastrowid))


def t27_signup_recovers_without_lastrowid(client):
    """Even if the driver reports lastrowid None (Postgres without
    RETURNING id), prepare_signup finds the row by email and the buyer
    still reaches PayPal."""
    import pending_signups

    class _CursorProxy:
        def __init__(self, real, force_none):
            self._real = real
            self._force_none = force_none

        @property
        def lastrowid(self):
            return None if self._force_none else self._real.lastrowid

        @property
        def rowcount(self):
            return self._real.rowcount

        def fetchone(self):
            return self._real.fetchone()

        def fetchall(self):
            return self._real.fetchall()

        def __iter__(self):
            return iter(self._real)

    class _ConnProxy:
        def __init__(self, real):
            self._real = real

        def execute(self, sql, params=()):
            force_none = sql.strip().upper().startswith("INSERT INTO PENDING_SIGNUPS")
            return _CursorProxy(self._real.execute(sql, params), force_none)

        def commit(self):
            return self._real.commit()

        def rollback(self):
            return self._real.rollback()

        def close(self):
            return self._real.close()

    real_get_db = pending_signups.get_db
    pending_signups.get_db = lambda: _ConnProxy(real_get_db())
    try:
        clear_session(client)
        r = client.post("/kwsnyderwriting/signup-subscribe",
                        data={"email": "t27@example.com", "password": "password123", "terms_agreed": "yes"}, headers=UA)
        check("t27 to paypal", r.status_code == 302 and "paypal.test/approve" in (r.headers.get("Location") or ""),
              "status=%s loc=%s" % (r.status_code, r.headers.get("Location")))
        check("t27 pending row", pending_exists("t27@example.com"))
        with client.session_transaction() as sess:
            check("t27 pending session", bool(sess.get("pending_signup_id")))
    finally:
        pending_signups.get_db = real_get_db


TESTS = [
    t01_new_account_no_payment, t02_verified_initial_payment, t03_active_but_no_payment,
    t04_successful_renewal, t05_failed_renewal, t06_cancelled_with_time_left,
    t07_cancelled_after_period, t08_expired, t09_refunded_payment, t10_forged_webhook,
    t11_duplicate_webhook, t12_blocked_member, t13_direct_url_unpaid,
    t14_unauthenticated_api, t15_authorized_member_reads_all,
    t16_member_readership_analytics, t17_admin_readership_report,
    t18_public_writing_public, t19_postgres_sql_compatibility,
    t20_signup_creates_no_account, t21_return_with_payment_creates_account,
    t22_return_without_payment_no_account, t23_plain_signup_creates_no_account,
    t24_never_activated_login_refused, t25_approved_then_closed_tab_no_double_charge,
    t26_postgres_returning_id, t27_signup_recovers_without_lastrowid,
]


def main():
    client = app.test_client()
    passed, failed = 0, []
    for fn in TESTS:
        try:
            if fn in (t19_postgres_sql_compatibility, t26_postgres_returning_id):
                fn()
            else:
                fn(client)
            passed += 1
            print("PASS %s" % fn.__name__)
        except Exception as exc:  # noqa: BLE001 - report and continue
            failed.append((fn.__name__, str(exc)))
            print("FAIL %s: %s" % (fn.__name__, exc))
    print("\n%d passed, %d failed" % (passed, len(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
