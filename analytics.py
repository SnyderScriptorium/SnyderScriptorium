import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from flask import jsonify, render_template, request, session

EASTERN = ZoneInfo("America/New_York")


def _db(app):
    conn = sqlite3.connect(app.config.get("DATABASE", getattr(app, "DATABASE", "scriptorium.db")))
    conn.row_factory = sqlite3.Row
    return conn


def _database_path(app):
    return getattr(app, "DATABASE", None) or app.config.get("DATABASE") or "scriptorium.db"


def init_analytics(app):
    app.config.setdefault("DATABASE", getattr(app, "DATABASE", "scriptorium.db"))

    conn = sqlite3.connect(_database_path(app))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS page_views (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            viewed_at TEXT NOT NULL,
            path TEXT NOT NULL,
            content_type TEXT NOT NULL DEFAULT 'page',
            content_id INTEGER,
            title TEXT,
            category TEXT,
            visitor_key TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_page_views_viewed_at ON page_views(viewed_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_page_views_content ON page_views(content_type, content_id)")
    conn.commit()
    conn.close()

    @app.before_request
    def record_page_view():
        if request.method != "GET":
            return None
        path = request.path
        if (path.startswith("/static/") or path.startswith("/admin") or
                path.startswith("/api/") or path.startswith("/health")):
            return None

        content_type = "page"
        content_id = None
        title = None
        category = None

        if path.startswith("/blog/post/"):
            try:
                content_id = int(path.rsplit("/", 1)[-1])
            except ValueError:
                content_id = None
            content_type = "post"
            conn = sqlite3.connect(_database_path(app))
            row = conn.execute(
                "SELECT title, category_name FROM published_posts WHERE id = ?",
                (content_id,)
            ).fetchone() if content_id else None
            conn.close()
            if row:
                title, category = row

        elif path.startswith("/kwsnyderwriting/post/"):
            try:
                content_id = int(path.rsplit("/", 1)[-1])
            except ValueError:
                content_id = None
            content_type = "member_post"
            conn = sqlite3.connect(_database_path(app))
            row = conn.execute(
                "SELECT title, category_name FROM published_posts WHERE id = ?",
                (content_id,)
            ).fetchone() if content_id else None
            conn.close()
            if row:
                title, category = row

        elif path.startswith("/kwsnyderwriting/novel/"):
            parts = path.strip("/").split("/")
            if len(parts) >= 3:
                try:
                    content_id = int(parts[2])
                except ValueError:
                    content_id = None
            content_type = "novel" if "/chapter/" not in path else "chapter"
            conn = sqlite3.connect(_database_path(app))
            if content_type == "chapter" and len(parts) >= 5:
                try:
                    chapter_id = int(parts[4])
                    row = conn.execute(
                        "SELECT c.title, b.title FROM manuscript_chapters c JOIN manuscript_books b ON b.id = c.book_id WHERE c.id = ?",
                        (chapter_id,)
                    ).fetchone()
                    content_id = chapter_id
                except ValueError:
                    row = None
            else:
                row = conn.execute("SELECT title FROM manuscript_books WHERE id = ?", (content_id,)).fetchone() if content_id else None
            conn.close()
            if row:
                title = row[0]
                category = "K. W. Snyder Writing"

        if path == "/" or path == "/about" or path == "/blog" or path.startswith("/blog/") or path.startswith("/kwsnyderwriting"):
            now = datetime.now(EASTERN).isoformat()
            conn = sqlite3.connect(_database_path(app))
            conn.execute(
                "INSERT INTO page_views(viewed_at, path, content_type, content_id, title, category, visitor_key) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (now, path, content_type, content_id, title, category, None)
            )
            conn.commit()
            conn.close()
        return None

    @app.route("/admin/analytics")
    def analytics_page():
        if not session.get("admin_logged_in"):
            return render_template("admin.html", logged_in=False)
        period = request.args.get("period", "all")
        data = build_report(app, period)
        return render_template("analytics.html", **data)

    @app.route("/api/analytics")
    def analytics_api():
        if not session.get("admin_logged_in"):
            return jsonify({"error": "Unauthorized"}), 401
        period = request.args.get("period", "all")
        return jsonify(build_report(app, period))


def period_start(period):
    now = datetime.now(EASTERN)
    if period == "day":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "7d":
        return now - timedelta(days=7)
    if period == "month":
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if period == "3m":
        month = now.month - 3
        year = now.year
        while month <= 0:
            month += 12
            year -= 1
        return now.replace(year=year, month=month, day=1, hour=0, minute=0, second=0, microsecond=0)
    if period == "6m":
        month = now.month - 6
        year = now.year
        while month <= 0:
            month += 12
            year -= 1
        return now.replace(year=year, month=month, day=1, hour=0, minute=0, second=0, microsecond=0)
    return None


def build_report(app, period="all"):
    start = period_start(period)
    conn = sqlite3.connect(_database_path(app))
    params = []
    where = ""
    if start:
        where = "WHERE viewed_at >= ?"
        params.append(start.isoformat())

    total = conn.execute(f"SELECT COUNT(*) FROM page_views {where}", params).fetchone()[0]

    rows = conn.execute(f"""
        SELECT content_type, content_id, COALESCE(title, path) AS title,
               COALESCE(category, '') AS category, COUNT(*) AS views
        FROM page_views
        {where}
        GROUP BY content_type, content_id, title, category, path
        ORDER BY views DESC, title ASC
    """, params).fetchall()

    daily = conn.execute(f"""
        SELECT substr(viewed_at, 1, 10) AS day, COUNT(*) AS views
        FROM page_views
        {where}
        GROUP BY day
        ORDER BY day
    """, params).fetchall()

    all_time = conn.execute("SELECT COUNT(*) FROM page_views").fetchone()[0]
    conn.close()

    return {
        "period": period,
        "period_start": start.isoformat() if start else None,
        "total_views": total,
        "all_time_views": all_time,
        "daily_views": [{"day": row[0], "views": row[1]} for row in daily],
        "content_views": [
            {"content_type": row[0], "content_id": row[1], "title": row[2], "category": row[3], "views": row[4]}
            for row in rows
        ],
    }
