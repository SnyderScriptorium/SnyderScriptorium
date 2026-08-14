from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from flask import jsonify, render_template, request, session
from database import get_db

EASTERN = ZoneInfo("America/New_York")

PATH_LABELS = {
    "/": "Homepage",
    "/about": "About",
    "/blog": "Blog",
    "/blog/bookcurations": "Book Curations",
    "/blog/bookreviews": "Book Reviews",
    "/blog/curiosity_cabinet": "Curiosity Cabinet",
    "/kwsnyderwriting": "K. W. Snyder Writing",
    "/kwsnyderwriting/membership": "K. W. Snyder Writing Membership",
    "/contact": "Contact",
}

CATEGORY_LABELS = {
    "curations": "Book Curations",
    "reviews": "Book Reviews",
    "curiosity": "Curiosity Cabinet",
    "kwsnyderwriting": "K. W. Snyder Writing",
    "kw_short_stories": "K. W. Snyder Writing — Short Stories",
    "kw_poems": "K. W. Snyder Writing — Poems",
    "kw_vignettes": "K. W. Snyder Writing — Vignettes",
    "blog": "Blog",
    "site": "Site Pages",
}


def _admin_ok():
    return session.get("admin_logged_in") is True and session.get("admin_auth_version") == "2026-08-10-3"


def _period_start(period):
    now = datetime.now(EASTERN)
    if period in {"day", "1d", "today"}:
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "7d":
        return now - timedelta(days=7)
    if period in {"30d", "month"}:
        return now - timedelta(days=30)
    if period in {"90d", "3m"}:
        return now - timedelta(days=90)
    if period == "6m":
        return now - timedelta(days=182)
    if period in {"1y", "365d"}:
        return now - timedelta(days=365)
    return None


def _label(path, page_type, category, title):
    if title and str(title).strip():
        return str(title).strip()
    if path in PATH_LABELS:
        return PATH_LABELS[path]
    if category in CATEGORY_LABELS:
        return CATEGORY_LABELS[category]
    if page_type == "post":
        return "Blog Post"
    if page_type == "member_post":
        return "K. W. Snyder Writing Post"
    if page_type == "novel":
        return "Novel"
    if page_type == "chapter":
        return "Book Chapter"
    return path or "Site Page"


def build_report(period="30d"):
    start = _period_start(period)
    conn = get_db()
    try:
        where = ""
        params = []
        if start:
            where = " WHERE pv.viewed_at >= ?"
            params = [start.isoformat()]

        total = conn.execute(f"SELECT COUNT(*) FROM page_views pv{where}", params).fetchone()[0]
        unique = conn.execute(
            f"SELECT COUNT(DISTINCT pv.visitor_key) FROM page_views pv{where}{' AND' if where else ' WHERE'} pv.visitor_key IS NOT NULL AND pv.visitor_key <> ''",
            params,
        ).fetchone()[0]

        if period in {"day", "1d", "today"}:
            time_rows = conn.execute(
                f"SELECT substr(CAST(pv.viewed_at AS TEXT),1,13) AS bucket, COUNT(*) AS views, COUNT(DISTINCT pv.visitor_key) AS visitors FROM page_views pv{where} GROUP BY bucket ORDER BY bucket",
                params,
            ).fetchall()
            series = []
            for row in time_rows:
                try:
                    dt = datetime.fromisoformat(str(row[0]) + ":00:00")
                    label = dt.strftime("%I %p").lstrip("0")
                except Exception:
                    label = str(row[0])[-2:] + ":00"
                series.append({"bucket": row[0], "label": label, "views": int(row[1]), "visitors": int(row[2])})
            series_granularity = "hour"
        else:
            time_rows = conn.execute(
                f"SELECT substr(CAST(pv.viewed_at AS TEXT),1,10) AS bucket, COUNT(*) AS views, COUNT(DISTINCT pv.visitor_key) AS visitors FROM page_views pv{where} GROUP BY bucket ORDER BY bucket",
                params,
            ).fetchall()
            series = [{"bucket": row[0], "label": row[0], "views": int(row[1]), "visitors": int(row[2])} for row in time_rows]
            series_granularity = "day"

        rows = conn.execute(
            f"""SELECT pv.path, pv.page_type, pv.content_id, pv.category,
                       COALESCE(pp.title, mb.title, mc.title) AS content_title,
                       COUNT(*) AS views, COUNT(DISTINCT pv.visitor_key) AS visitors
                FROM page_views pv
                LEFT JOIN published_posts pp ON pp.id = pv.content_id AND pv.page_type IN ('post','member_post')
                LEFT JOIN manuscript_books mb ON mb.id = pv.content_id AND pv.page_type = 'novel'
                LEFT JOIN manuscript_chapters mc ON mc.id = pv.content_id AND pv.page_type = 'chapter'
                {where}
                GROUP BY pv.path, pv.page_type, pv.content_id, pv.category, pp.title, mb.title, mc.title
                ORDER BY views DESC, pv.path ASC""",
            params,
        ).fetchall()

        pages = []
        for row in rows:
            pages.append({
                "title": _label(row[0], row[1], row[3], row[4]),
                "path": row[0],
                "type": row[1],
                "category": CATEGORY_LABELS.get(row[3], row[3] or "Site Pages"),
                "views": int(row[5]),
                "visitors": int(row[6]),
            })

        all_views = conn.execute("SELECT COUNT(*) FROM page_views").fetchone()[0]
        all_unique = conn.execute("SELECT COUNT(DISTINCT visitor_key) FROM page_views WHERE visitor_key IS NOT NULL AND visitor_key <> ''").fetchone()[0]
        member_counts = conn.execute("SELECT subscription_status, COUNT(*) FROM members GROUP BY subscription_status").fetchall()
        members = {str(r[0] or "inactive"): int(r[1]) for r in member_counts}

        return {
            "period": period,
            "total_views": int(total),
            "unique_visitors": int(unique),
            "all_time_views": int(all_views),
            "all_time_unique": int(all_unique),
            "series": series,
            "series_granularity": series_granularity,
            "pages": pages,
            "members": {
                "total": sum(members.values()),
                "active": members.get("active", 0),
                "past_due": members.get("past_due", 0),
                "paused": members.get("paused", 0),
                "cancelled": members.get("cancelled", 0),
                "expired": members.get("expired", 0),
                "inactive": members.get("inactive", 0),
            },
        }
    finally:
        conn.close()


def register_analytics_dashboard(app):
    @app.get("/admin/analytics")
    def analytics_dashboard():
        if not _admin_ok():
            return app.view_functions["admin_dashboard"]()
        return render_template("analytics_dashboard.html", **build_report(request.args.get("period", "30d")))

    def api():
        if not _admin_ok():
            return jsonify({"error": "Unauthorized"}), 401
        return jsonify(build_report(request.args.get("period", "30d")))

    if "analytics_dashboard_api_v2" not in app.view_functions:
        app.add_url_rule("/api/analytics-v2", endpoint="analytics_dashboard_api_v2", view_func=api, methods=["GET"])
