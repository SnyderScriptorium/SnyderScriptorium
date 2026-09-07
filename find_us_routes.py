"""Find Us public events and authenticated admin management."""

from datetime import datetime

from flask import jsonify, redirect, render_template, request, url_for

from app import app, admin_required, get_db, now_string


FIND_US_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS find_us_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    event_date TEXT NOT NULL,
    location TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    link TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'published',
    created_at TEXT NOT NULL DEFAULT ''
)
"""


def ensure_find_us_table():
    conn = get_db()
    try:
        conn.execute(FIND_US_TABLE_SQL)
        conn.commit()
    finally:
        conn.close()


ensure_find_us_table()


@app.route("/find-us")
def find_us():
    conn = get_db()
    events = conn.execute(
        "SELECT * FROM find_us_events WHERE status = 'published' "
        "ORDER BY event_date ASC, id ASC"
    ).fetchall()
    conn.close()
    return render_template("find_us.html", events=events)


@app.route("/admin/find-us")
@admin_required
def admin_find_us():
    return render_template("admin_find_us.html")


@app.route("/api/find-us", methods=["GET"])
@admin_required
def get_find_us_events():
    conn = get_db()
    events = conn.execute(
        "SELECT * FROM find_us_events ORDER BY event_date ASC, id ASC"
    ).fetchall()
    conn.close()
    return jsonify([dict(event) for event in events])


@app.route("/api/find-us", methods=["POST"])
@admin_required
def create_find_us_event():
    data = request.get_json() or {}
    title = str(data.get("title", "")).strip()
    event_date = str(data.get("event_date", "")).strip()
    location = str(data.get("location", "")).strip()
    description = str(data.get("description", "")).strip()
    link = str(data.get("link", "")).strip()
    status = "published" if str(data.get("status", "published")).strip() == "published" else "draft"

    if not title or not event_date or not location:
        return jsonify({"error": "Title, date and location are required."}), 400

    try:
        datetime.fromisoformat(event_date)
    except ValueError:
        return jsonify({"error": "Please provide a valid event date and time."}), 400

    conn = get_db()
    cur = conn.execute(
        "INSERT INTO find_us_events(title, event_date, location, description, link, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (title, event_date, location, description, link, status, now_string()),
    )
    conn.commit()
    event_id = cur.lastrowid
    conn.close()
    return jsonify({"success": True, "id": event_id}), 201


@app.route("/api/find-us/<int:event_id>", methods=["PUT"])
@admin_required
def update_find_us_event(event_id):
    data = request.get_json() or {}
    title = str(data.get("title", "")).strip()
    event_date = str(data.get("event_date", "")).strip()
    location = str(data.get("location", "")).strip()
    description = str(data.get("description", "")).strip()
    link = str(data.get("link", "")).strip()
    status = "published" if str(data.get("status", "published")).strip() == "published" else "draft"

    if not title or not event_date or not location:
        return jsonify({"error": "Title, date and location are required."}), 400
    try:
        datetime.fromisoformat(event_date)
    except ValueError:
        return jsonify({"error": "Please provide a valid event date and time."}), 400

    conn = get_db()
    row = conn.execute("SELECT id FROM find_us_events WHERE id = ?", (event_id,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Event not found."}), 404
    conn.execute(
        "UPDATE find_us_events SET title = ?, event_date = ?, location = ?, description = ?, link = ?, status = ? WHERE id = ?",
        (title, event_date, location, description, link, status, event_id),
    )
    conn.commit()
    conn.close()
    return jsonify({"success": True})


@app.route("/api/find-us/<int:event_id>", methods=["DELETE"])
@admin_required
def delete_find_us_event(event_id):
    conn = get_db()
    cur = conn.execute("DELETE FROM find_us_events WHERE id = ?", (event_id,))
    conn.commit()
    conn.close()
    if cur.rowcount == 0:
        return jsonify({"error": "Event not found."}), 404
    return jsonify({"success": True})
