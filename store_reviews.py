"""Verified-purchase customer reviews for the bookstore.

Lives in its own module (not store.py) so the store.py auto-restore
workflow can never touch it.

Flow: after an order ships, the owner sends review invitations from the
admin panel. Each buyer gets an email with a personal, single-use link
(/store/review/<token>). That link is the ONLY way to submit a review —
there is no public form. Reviews land as 'pending'; nothing appears on
the storefront until the owner approves it in /admin/store.
"""

import json as _json
import os
import secrets
import urllib.request as _urlreq
from datetime import datetime, timezone

from flask import Blueprint, jsonify, render_template, request

from app import require_admin
from database import get_db, using_postgres

reviews_bp = Blueprint("reviews", __name__)


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def ensure_review_tables():
    """Create the reviews tables if they do not exist. Safe to run on boot."""
    conn = get_db()
    try:
        if using_postgres():
            conn.execute(
                "CREATE TABLE IF NOT EXISTS store_reviews ("
                "id BIGSERIAL PRIMARY KEY, "
                "order_id BIGINT NOT NULL UNIQUE REFERENCES store_orders(id) ON DELETE CASCADE, "
                "customer_name TEXT NOT NULL DEFAULT '', "
                "rating INTEGER NOT NULL DEFAULT 5, "
                "title TEXT NOT NULL DEFAULT '', "
                "body TEXT NOT NULL DEFAULT '', "
                "status TEXT NOT NULL DEFAULT 'pending', "
                "date_created TEXT NOT NULL, "
                "date_updated TEXT NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS store_review_tokens ("
                "token TEXT PRIMARY KEY, "
                "order_id BIGINT NOT NULL UNIQUE REFERENCES store_orders(id) ON DELETE CASCADE, "
                "used INTEGER NOT NULL DEFAULT 0, "
                "date_created TEXT NOT NULL)"
            )
        else:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS store_reviews ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "order_id INTEGER NOT NULL UNIQUE REFERENCES store_orders(id) ON DELETE CASCADE, "
                "customer_name TEXT NOT NULL DEFAULT '', "
                "rating INTEGER NOT NULL DEFAULT 5, "
                "title TEXT NOT NULL DEFAULT '', "
                "body TEXT NOT NULL DEFAULT '', "
                "status TEXT NOT NULL DEFAULT 'pending', "
                "date_created TEXT NOT NULL, "
                "date_updated TEXT NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS store_review_tokens ("
                "token TEXT PRIMARY KEY, "
                "order_id INTEGER NOT NULL UNIQUE REFERENCES store_orders(id) ON DELETE CASCADE, "
                "used INTEGER NOT NULL DEFAULT 0, "
                "date_created TEXT NOT NULL)"
            )
        conn.commit()
    finally:
        conn.close()


def _send_resend_email(to_email, subject, html_body, text_body):
    """Send one email via Resend. Never raises; returns True on success."""
    try:
        resend_key = (os.environ.get("RESEND_API_KEY") or "").strip()
        if not resend_key or not to_email:
            return False
        resend_from = (os.environ.get("NOTIFY_EMAIL_FROM") or "").strip() or "orders@snyderscriptorium.com"
        payload = _json.dumps({
            "from": resend_from,
            "to": [to_email],
            "subject": subject,
            "html": html_body,
            "text": text_body,
        }).encode("utf-8")
        req = _urlreq.Request(
            "https://api.resend.com/emails",
            data=payload,
            headers={
                "Authorization": "Bearer " + resend_key,
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with _urlreq.urlopen(req, timeout=20) as resp:
            return 200 <= resp.status < 300
    except Exception as e:
        print("[reviews] invite email failed: %s" % e, flush=True)
        return False


def _get_token_order(token):
    """Return the order row for a valid unused token, else None."""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT o.* FROM store_review_tokens t "
            "JOIN store_orders o ON o.id = t.order_id "
            "WHERE t.token = ? AND t.used = 0",
            (token,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Storefront: approved reviews (read-only list)
# ---------------------------------------------------------------------------

@reviews_bp.route("/api/store/reviews", methods=["GET"])
def public_reviews():
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT id, customer_name, rating, title, body, date_created "
            "FROM store_reviews WHERE status = 'approved' ORDER BY id DESC LIMIT 50"
        ).fetchall()
    finally:
        conn.close()
    return jsonify([
        {
            "id": r["id"] if isinstance(r, dict) else r[0],
            "name": (r["customer_name"] if isinstance(r, dict) else r[1]) or "A reader",
            "rating": r["rating"] if isinstance(r, dict) else r[2],
            "title": r["title"] if isinstance(r, dict) else r[3],
            "body": r["body"] if isinstance(r, dict) else r[4],
            "date": r["date_created"] if isinstance(r, dict) else r[5],
        }
        for r in rows
    ])


# ---------------------------------------------------------------------------
# Buyer review form (token link from the invitation email — the only way in)
# ---------------------------------------------------------------------------

@reviews_bp.route("/store/review/<token>", methods=["GET"])
def review_form(token):
    order = _get_token_order(token)
    if not order:
        return render_template("store_review.html", valid=False), 404
    return render_template(
        "store_review.html",
        valid=True,
        token=token,
        buyer_name=order.get("customer_name") or "",
    )


@reviews_bp.route("/api/store/review/<token>", methods=["POST"])
def submit_review(token):
    order = _get_token_order(token)
    if not order:
        return jsonify({"error": "This review link is invalid or has already been used."}), 404
    data = request.get_json(force=True, silent=True) or {}
    try:
        rating = int(data.get("rating") or 0)
    except (TypeError, ValueError):
        rating = 0
    if rating < 1 or rating > 5:
        return jsonify({"error": "Please choose a star rating."}), 400
    name = str(data.get("name") or "").strip()[:80]
    title = str(data.get("title") or "").strip()[:160]
    body = str(data.get("body") or "").strip()
    if not body:
        return jsonify({"error": "Please write a few words about your experience."}), 400
    if len(body) > 5000:
        return jsonify({"error": "Review is too long (5,000 characters max)."}), 400

    conn = get_db()
    try:
        existing = conn.execute(
            "SELECT id FROM store_reviews WHERE order_id = ?", (order["id"],)
        ).fetchone()
        if existing:
            return jsonify({"error": "A review has already been left for this order."}), 400
        now = _now()
        conn.execute(
            "INSERT INTO store_reviews(order_id, customer_name, rating, title, body, status, date_created, date_updated) "
            "VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)",
            (order["id"], name or order.get("customer_name") or "A reader",
             rating, title, body, now, now),
        )
        conn.execute(
            "UPDATE store_review_tokens SET used = 1 WHERE token = ?", (token,)
        )
        conn.commit()
    finally:
        conn.close()
    return jsonify({"message": "Thank you! Your review was received and will appear once approved."})


# ---------------------------------------------------------------------------
# Admin moderation
# ---------------------------------------------------------------------------

@reviews_bp.route("/api/store/admin/reviews", methods=["GET"])
def admin_list_reviews():
    if not require_admin():
        return jsonify({"error": "Admin login required."}), 401
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT r.id, r.order_id, r.customer_name, r.rating, r.title, r.body, "
            "r.status, r.date_created, o.customer_email "
            "FROM store_reviews r LEFT JOIN store_orders o ON o.id = r.order_id "
            "ORDER BY r.id DESC LIMIT 200"
        ).fetchall()
    finally:
        conn.close()

    def val(r, key, idx):
        return r[key] if isinstance(r, dict) else r[idx]

    return jsonify([
        {
            "id": val(r, "id", 0),
            "order_id": val(r, "order_id", 1),
            "name": val(r, "customer_name", 2) or "A reader",
            "rating": val(r, "rating", 3),
            "title": val(r, "title", 4),
            "body": val(r, "body", 5),
            "status": val(r, "status", 6),
            "date": val(r, "date_created", 7),
            "email": val(r, "customer_email", 8) or "",
        }
        for r in rows
    ])


@reviews_bp.route("/api/store/admin/reviews/<int:review_id>/approve", methods=["POST"])
def admin_approve_review(review_id):
    if not require_admin():
        return jsonify({"error": "Admin login required."}), 401
    conn = get_db()
    try:
        cur = conn.execute(
            "UPDATE store_reviews SET status = 'approved', date_updated = ? WHERE id = ?",
            (_now(), review_id),
        )
        conn.commit()
        if cur.rowcount == 0:
            return jsonify({"error": "Review not found."}), 404
    finally:
        conn.close()
    return jsonify({"ok": True})


@reviews_bp.route("/api/store/admin/reviews/<int:review_id>/reject", methods=["POST"])
def admin_reject_review(review_id):
    if not require_admin():
        return jsonify({"error": "Admin login required."}), 401
    conn = get_db()
    try:
        cur = conn.execute("DELETE FROM store_reviews WHERE id = ?", (review_id,))
        conn.commit()
        if cur.rowcount == 0:
            return jsonify({"error": "Review not found."}), 404
    finally:
        conn.close()
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Review invitations (owner sends these from the admin panel after shipping)
# ---------------------------------------------------------------------------

@reviews_bp.route("/api/store/admin/review-invites/send", methods=["POST"])
def admin_send_invites():
    """Create tokens and email review invitations for paid+shipped orders
    that do not have one yet. Idempotent — safe to run repeatedly."""
    if not require_admin():
        return jsonify({"error": "Admin login required."}), 401
    conn = get_db()
    try:
        orders = conn.execute(
            "SELECT o.id, o.customer_name, o.customer_email "
            "FROM store_orders o "
            "LEFT JOIN store_review_tokens t ON t.order_id = o.id "
            "WHERE o.payment_status = 'paid' AND o.order_status = 'shipped' "
            "AND t.token IS NULL "
            "AND o.customer_email IS NOT NULL AND o.customer_email != '' "
            "ORDER BY o.id DESC LIMIT 100"
        ).fetchall()
        sent = 0
        skipped = 0
        for o in orders:
            order = dict(o)
            token = secrets.token_urlsafe(32)
            conn.execute(
                "INSERT INTO store_review_tokens(token, order_id, used, date_created) "
                "VALUES (?, ?, 0, ?)",
                (token, order["id"], _now()),
            )
            link = "https://www.snyderscriptorium.com/store/review/" + token
            buyer = (order.get("customer_name") or "reader").strip() or "reader"
            subject = "How was your book? Leave a review for Snyder Scriptorium"
            text_body = (
                "Hi %s,\n\n"
                "Thanks for your order from Snyder Scriptorium! Once your book arrives, "
                "we'd love to hear how it went.\n\n"
                "Leave your verified review here (personal link, one per order):\n%s\n\n"
                "Thank you for supporting an independent bookshop.\n"
                "— K.W. Snyder, Snyder Scriptorium" % (buyer, link)
            )
            html_body = (
                "<p>Hi %s,</p>"
                "<p>Thanks for your order from <strong>Snyder Scriptorium</strong>! "
                "Once your book arrives, we'd love to hear how it went.</p>"
                "<p><a href=\"%s\">Leave your verified review</a> "
                "(personal link, one per order).</p>"
                "<p>Thank you for supporting an independent bookshop.<br>"
                "— K.W. Snyder, Snyder Scriptorium</p>" % (buyer, link)
            )
            if _send_resend_email(order["customer_email"], subject, html_body, text_body):
                sent += 1
            else:
                skipped += 1
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok": True, "invites_sent": sent, "skipped": skipped})
