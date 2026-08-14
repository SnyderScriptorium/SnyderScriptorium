from datetime import datetime, timedelta, timezone


def install(app):
    """Patch the existing analytics endpoint without disturbing the rest of the app."""
    from functools import wraps

    original_admin_check = app.view_functions.get("get_analytics")
    if original_admin_check is None:
        return

    def analytics_fixed():
        # Preserve the application's existing admin guard.
        if not app.view_functions.get("get_analytics"):
            return original_admin_check()
        # The route is already protected by the original decorator; this replacement
        # performs the same session check before querying analytics.
        from flask import request, jsonify, session
        if not (session.get("admin_logged_in") is True and session.get("admin_auth_version") == getattr(__import__("app"), "ADMIN_AUTH_VERSION", None)):
            return original_admin_check()

        get_db = getattr(__import__("app"), "get_db")
        period = str(request.args.get("period", "30")).strip().lower()
        now = datetime.now(timezone.utc)
        is_today = period in {"day", "today", "1", "1day", "1-day"}

        if period == "all":
            start = None
        elif is_today:
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            try:
                days = max(1, min(int(period), 3650))
            except (TypeError, ValueError):
                days = 30
            start = now - timedelta(days=days)

        conn = get_db()
        try:
            if start is None:
                where = ""
                params = ()
            else:
                where = " WHERE viewed_at >= ?"
                params = (start.isoformat(),)

            total = conn.execute(f"SELECT COUNT(*) AS count FROM page_views{where}", params).fetchone()["count"]
            daily = conn.execute(
                f"SELECT DATE(viewed_at) AS day, COUNT(*) AS views FROM page_views{where} GROUP BY DATE(viewed_at) ORDER BY day",
                params,
            ).fetchall()
            categories = conn.execute(
                f"SELECT category, COUNT(*) AS views FROM page_views WHERE category IS NOT NULL{(' AND viewed_at >= ?' if start is not None else '')} GROUP BY category ORDER BY views DESC",
                params if start is not None else (),
            ).fetchall()
            posts = conn.execute(
                f"SELECT pv.path, pv.content_id, pv.category, COALESCE(pp.title, pv.path) AS title, COUNT(*) AS views FROM page_views pv LEFT JOIN published_posts pp ON pp.id = pv.content_id WHERE pv.page_type IN ('post','member_post','chapter','novel'){(' AND pv.viewed_at >= ?' if start is not None else '')} GROUP BY pv.path, pv.content_id, pv.category, pp.title ORDER BY views DESC",
                params if start is not None else (),
            ).fetchall()

            hourly = []
            if is_today:
                hourly = conn.execute(
                    "SELECT CAST(strftime('%H', viewed_at) AS INTEGER) AS hour, COUNT(*) AS views FROM page_views WHERE viewed_at >= ? GROUP BY CAST(strftime('%H', viewed_at) AS INTEGER) ORDER BY hour",
                    (start.isoformat(),),
                ).fetchall()
        finally:
            conn.close()

        labels = {
            "site": "Home",
            "curations": "Book Curations",
            "reviews": "Book Reviews",
            "curiosity": "Curiosity Cabinet",
            "kwsnyderwriting": "K. W. Snyder Writing",
            "kw_short_stories": "K. W. Snyder Writing — Short Stories",
            "kw_poems": "K. W. Snyder Writing — Poems",
            "kw_vignettes": "K. W. Snyder Writing — Vignettes",
            "blog": "Blog",
            "Journal": "K. W. Snyder Writing",
            "journal": "K. W. Snyder Writing",
        }

        category_rows = []
        for row in categories:
            item = dict(row)
            item["category"] = labels.get(item.get("category"), item.get("category") or "Unknown")
            category_rows.append(item)

        post_rows = []
        for row in posts:
            item = dict(row)
            item["category"] = labels.get(item.get("category"), item.get("category") or "Unknown")
            post_rows.append(item)

        return jsonify({
            "period": "day" if is_today else period,
            "total_views": total,
            "total_views_today": total if is_today else None,
            "daily": [dict(row) for row in daily],
            "hourly": [dict(row) for row in hourly],
            "categories": category_rows,
            "posts": post_rows,
        })

    # Replace the existing endpoint's view function while retaining its URL rule.
    app.view_functions["get_analytics"] = analytics_fixed
