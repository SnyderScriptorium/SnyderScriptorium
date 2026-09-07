"""Public Find Us page and authenticated admin event management."""

from datetime import datetime
from functools import wraps

from flask import Blueprint, abort, redirect, render_template, request, session, url_for

from app import get_db, require_admin


find_us_bp = Blueprint("find_us", __name__)


def admin_only(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not require_admin():
            session.pop("admin_logged_in", None)
            session.pop("admin_auth_version", None)
            return redirect(url_for("admin_login_page"))
        return view(*args, **kwargs)
    return wrapped


def ensure_find_us_tables():
    conn = get_db()
    try:
        # The application supports both SQLite locally and PostgreSQL on Render.
        from database import using_postgres
        if using_postgres():
            conn.execute(
                """CREATE TABLE IF NOT EXISTS find_us_events (
                    id BIGSERIAL PRIMARY KEY,
                    title TEXT NOT NULL,
                    event_date TEXT NOT NULL,
                    event_time TEXT NOT NULL DEFAULT '',
                    venue TEXT NOT NULL DEFAULT '',
                    city TEXT NOT NULL DEFAULT '',
                    state TEXT NOT NULL DEFAULT '',
                    description TEXT NOT NULL DEFAULT '',
                    link_url TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'published',
                    date_created TEXT NOT NULL
                )"""
            )
        else:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS find_us_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    event_date TEXT NOT NULL,
                    event_time TEXT NOT NULL DEFAULT '',
                    venue TEXT NOT NULL DEFAULT '',
                    city TEXT NOT NULL DEFAULT '',
                    state TEXT NOT NULL DEFAULT '',
                    description TEXT NOT NULL DEFAULT '',
                    link_url TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'published',
                    date_created TEXT NOT NULL
                )"""
            )
        conn.commit()
    finally:
        conn.close()


@find_us_bp.route("/find-us")
def find_us_page():
    conn = get_db()
    events = conn.execute(
        "SELECT * FROM find_us_events WHERE status = 'published' ORDER BY event_date ASC, event_time ASC, id ASC"
    ).fetchall()
    conn.close()
    return render_template("find_us.html", events=events)


@find_us_bp.route("/admin/find-us")
@admin_only
def admin_find_us():
    conn = get_db()
    events = conn.execute("SELECT * FROM find_us_events ORDER BY event_date ASC, event_time ASC, id ASC").fetchall()
    conn.close()
    return render_template("admin_find_us.html", events=events)


@find_us_bp.route("/admin/find-us/create", methods=["POST"])
@admin_only
def create_find_us_event():
    title = request.form.get("title", "").strip()
    event_date = request.form.get("event_date", "").strip()
    event_time = request.form.get("event_time", "").strip()
    venue = request.form.get("venue", "").strip()
    city = request.form.get("city", "").strip()
    state = request.form.get("state", "").strip()
    description = request.form.get("description", "").strip()
    link_url = request.form.get("link_url", "").strip()
    status = request.form.get("status", "published").strip().lower()
    if status not in {"published", "draft"}:
        status = "draft"

    if not title or not event_date:
        return redirect(url_for("find_us.admin_find_us", error="Event name and date are required."))

    try:
        datetime.strptime(event_date, "%Y-%m-%d")
    except ValueError:
        return redirect(url_for("find_us.admin_find_us", error="Please enter a valid event date."))

    conn = get_db()
    conn.execute(
        "INSERT INTO find_us_events(title,event_date,event_time,venue,city,state,description,link_url,status,date_created) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (title, event_date, event_time, venue, city, state, description, link_url, status, datetime.now().strftime("%m/%d/%Y %I:%M %p")),
    )
    conn.commit()
    conn.close()
    return redirect(url_for("find_us.admin_find_us", saved="1"))


@find_us_bp.route("/admin/find-us/<int:event_id>/update", methods=["POST"])
@admin_only
def update_find_us_event(event_id):
    title = request.form.get("title", "").strip()
    event_date = request.form.get("event_date", "").strip()
    event_time = request.form.get("event_time", "").strip()
    venue = request.form.get("venue", "").strip()
    city = request.form.get("city", "").strip()
    state = request.form.get("state", "").strip()
    description = request.form.get("description", "").strip()
    link_url = request.form.get("link_url", "").strip()
    status = request.form.get("status", "published").strip().lower()
    if status not in {"published", "draft"}:
        status = "draft"
    if not title or not event_date:
        return redirect(url_for("find_us.admin_find_us", error="Event name and date are required."))

    try:
        datetime.strptime(event_date, "%Y-%m-%d")
    except ValueError:
        return redirect(url_for("find_us.admin_find_us", error="Please enter a valid event date."))

    conn = get_db()
    existing = conn.execute("SELECT id FROM find_us_events WHERE id = ?", (event_id,)).fetchone()
    if not existing:
        conn.close()
        abort(404)
    conn.execute(
        "UPDATE find_us_events SET title=?,event_date=?,event_time=?,venue=?,city=?,state=?,description=?,link_url=?,status=? WHERE id=?",
        (title, event_date, event_time, venue, city, state, description, link_url, status, event_id),
    )
    conn.commit()
    conn.close()
    return redirect(url_for("find_us.admin_find_us", saved="1"))


@find_us_bp.route("/admin/find-us/<int:event_id>/delete", methods=["POST"])
@admin_only
def delete_find_us_event(event_id):
    conn = get_db()
    conn.execute("DELETE FROM find_us_events WHERE id = ?", (event_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("find_us.admin_find_us", deleted="1"))
