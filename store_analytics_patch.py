"""Live fixes for the storefront analytics dashboard.

The main analytics module is shared with the broader dashboard and is cached
for up to a minute. Store analytics need to be both accurate and immediately
reflect new book views, so this small production patch calculates the store
portion directly and replaces the existing Store-tab API view after the main
analytics routes are registered.
"""

from flask import jsonify, request

from app import app, admin_required
from database import get_db
import analytics_dashboard_v3 as analytics


def _store_period_start(period):
    normalized = analytics.normalize_period(period)
    return normalized, analytics.start_for(normalized)


def _store_data(period):
    normalized, start = _store_period_start(period)
    conn = get_db()
    try:
        where = " WHERE pv.viewed_at >= ?" if start else ""
        params = [start.isoformat()] if start else []
        extra = " AND" if where else " WHERE"

        # Only actual storefront pages count. Do not count /store/image/*,
        # subscribe/unsubscribe actions, checkout APIs, or other assets.
        store_filter = f"{extra} (pv.path = '/store' OR pv.path LIKE '/store/book/%')"

        views_row = conn.execute(
            f"SELECT COUNT(*) AS n FROM page_views pv{where}{store_filter}",
            params,
        ).fetchone()
        unique_row = conn.execute(
            f"SELECT COUNT(DISTINCT pv.visitor_key) AS n FROM page_views pv{where}{store_filter}"
            " AND pv.visitor_key IS NOT NULL AND pv.visitor_key <> ''",
            params,
        ).fetchone()

        store_views = int(views_row["n"] or 0)
        store_unique_visitors = int(unique_row["n"] or 0)

        daily_rows = conn.execute(
            f"""SELECT substr(pv.viewed_at, 1, 10) AS day, COUNT(*) AS n
                FROM page_views pv{where}{store_filter}
                GROUP BY day ORDER BY day""",
            params,
        ).fetchall()
        store_daily = [
            {"date": r["day"], "views": int(r["n"] or 0)} for r in daily_rows
        ]

        # Resolve a book by either its classified content_id OR its canonical
        # URL. The URL fallback is important for historical views that were
        # recorded before content_id classification existed.
        book_rows = conn.execute(
            f"""SELECT sp.id, sp.title, sp.author,
                       COUNT(*) AS views,
                       COUNT(DISTINCT pv.visitor_key) AS uniques
                FROM page_views pv
                LEFT JOIN store_products sp
                  ON sp.id = pv.content_id
                  OR ('/store/book/' || sp.slug) = pv.path
                {where}{extra} pv.path LIKE '/store/book/%'
                GROUP BY sp.id, sp.title, sp.author
                ORDER BY views DESC, LOWER(COALESCE(sp.title, '')), sp.id
                LIMIT 50""",
            params,
        ).fetchall()
        store_books = [
            {
                "id": r["id"],
                "title": r["title"] or "(unknown book)",
                "author": r["author"] or "",
                "views": int(r["views"] or 0),
                "unique_visitors": int(r["uniques"] or 0),
            }
            for r in book_rows
        ]

        return {
            "period": normalized,
            "store_views": store_views,
            "store_unique_visitors": store_unique_visitors,
            "store_daily": store_daily,
            "store_books": store_books,
        }
    finally:
        conn.close()


_original_report = analytics.report


def patched_report(period, content_page=1, source_page=1, drill_path=None):
    """Keep the existing dashboard report, but replace its store metrics."""
    data = _original_report(period, content_page, source_page, drill_path)
    try:
        data.update(_store_data(period))
    except Exception:
        data.setdefault("store_views", 0)
        data.setdefault("store_unique_visitors", 0)
        data.setdefault("store_daily", [])
        data.setdefault("store_books", [])
    return data


analytics.report = patched_report


@admin_required
def api_store_analytics_fixed():
    """Fresh Store-tab data, including every viewed book (up to 50)."""
    period = request.args.get("period", "30d")
    data = _store_data(period)
    # Preserve the existing dashboard's posted/sold counters from the normal
    # report, while replacing only the live store-view metrics.
    try:
        base = _original_report(period, 1, 1, None)
        books_posted = base.get("store_books_posted", 0)
        books_sold = base.get("store_books_sold", 0)
    except Exception:
        books_posted = 0
        books_sold = 0
    return jsonify({
        "books_posted": books_posted,
        "books_sold": books_sold,
        "store_views": data["store_views"],
        "unique_visitors": data["store_unique_visitors"],
        "top_books": data["store_books"],
        "viewed_books": data["store_books"],
    })


# Replace the view function after analytics_dashboard_v3.register() has added
# the route. This preserves the existing URL and existing Store-tab frontend.
if "api_store_analytics" in app.view_functions:
    app.view_functions["api_store_analytics"] = api_store_analytics_fixed
