from datetime import datetime

from flask import jsonify, render_template, request, session
from database import get_db

ADMIN_AUTH_VERSION = "2026-08-10-3"


def _admin_ok():
    return session.get("admin_logged_in") is True and session.get("admin_auth_version") == ADMIN_AUTH_VERSION


def _label_for(category, supplied=None):
    supplied = str(supplied or "").strip()
    defaults = {
        "curations": "Book Curations",
        "reviews": "Book Reviews",
        "curiosity": "Curiosity Cabinet",
        "kwsnyderwriting": "K. W. Snyder Writing",
        "kw_short_stories": "K. W. Snyder Writing — Short Stories",
        "kw_poems": "K. W. Snyder Writing — Poems",
        "kw_vignettes": "K. W. Snyder Writing — Vignettes",
        "blog": "The Blog",
        "site": "Site Pages",
    }
    return supplied or defaults.get(category, "Site Pages")


def _public_category(category, template, title, filter_name):
    conn = get_db()
    try:
        labels = conn.execute(
            "SELECT DISTINCT category_name FROM published_posts "
            "WHERE category = ? AND access_level = 'public' "
            "AND category_name IS NOT NULL AND TRIM(category_name) <> '' "
            "ORDER BY LOWER(category_name)",
            (category,),
        ).fetchall()

        selected = str(request.args.get(filter_name, "")).strip()
        search = str(request.args.get("q", "")).strip()
        sql = "SELECT * FROM published_posts WHERE category = ? AND access_level = 'public'"
        params = [category]

        if selected:
            sql += " AND category_name = ?"
            params.append(selected)
        if search:
            sql += " AND (LOWER(title) LIKE LOWER(?) OR LOWER(content) LIKE LOWER(?))"
            like = f"%{search}%"
            params.extend([like, like])

        posts = conn.execute(sql + " ORDER BY id DESC", params).fetchall()
        return render_template(
            template,
            posts=posts,
            category_name=title,
            filter_labels=[row["category_name"] for row in labels],
            selected_label=selected,
            search_query=search,
        )
    finally:
        conn.close()


def _create_published_post():
    if not _admin_ok():
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json() or {}
    title = str(data.get("title", "")).strip()
    category = str(data.get("category", "")).strip()
    content = str(data.get("content", ""))
    access = str(data.get("accessLevel", "public"))

    if not title or not content.strip():
        return jsonify({"error": "A title and content are required."}), 400

    # K. W. Snyder Writing has no public fallback. Every KWS category is
    # member-only, including its subcategories.
    if category == "kwsnyderwriting" or category.startswith("kw_"):
        access = "members"

    if access not in {"public", "members"}:
        access = "public"

    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT INTO published_posts(title,category,category_name,content,date_published,access_level) "
            "VALUES (?,?,?,?,?,?)",
            (
                title,
                category,
                _label_for(category, data.get("categoryName")),
                content,
                str(data.get("date", "")).strip() or datetime.now().strftime("%m/%d/%Y %I:%M %p"),
                access,
            ),
        )
        conn.commit()
        return jsonify({"success": True, "id": cur.lastrowid, "access_level": access}), 201
    finally:
        conn.close()


def _update_published_post(post_id):
    if not _admin_ok():
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json() or {}
    title = str(data.get("title", "")).strip()
    category = str(data.get("category", "")).strip()
    content = str(data.get("content", ""))
    access = str(data.get("accessLevel", "public"))

    if not title or not content.strip():
        return jsonify({"error": "A title and content are required."}), 400

    if category == "kwsnyderwriting" or category.startswith("kw_"):
        access = "members"

    if access not in {"public", "members"}:
        access = "public"

    conn = get_db()
    try:
        row = conn.execute(
            "SELECT id,category_name FROM published_posts WHERE id=?", (post_id,)
        ).fetchone()
        if not row:
            return jsonify({"error": "Post not found"}), 404

        label = _label_for(category, data.get("categoryName"))
        if not data.get("categoryName") and category == row["category_name"]:
            label = row["category_name"]

        conn.execute(
            "UPDATE published_posts SET title=?,category=?,category_name=?,content=?,access_level=? WHERE id=?",
            (title, category, label, content, access, post_id),
        )
        conn.commit()
        return jsonify({"success": True})
    finally:
        conn.close()


def register_site_enhancements(app):
    """Register non-analytics site enhancements.

    Analytics is intentionally NOT registered here. The canonical analytics
    tracker and analytics dashboard are registered exactly once by the
    production Gunicorn configuration. Keeping this module limited to content
    routing/publishing prevents duplicate trackers and competing /api/analytics
    implementations.
    """

    app.view_functions["bookreviews"] = lambda: _public_category(
        "reviews", "blog_templates/bookreviews.html", "Book Reviews", "genre"
    )
    app.view_functions["curiosity_cabinet"] = lambda: _public_category(
        "curiosity", "blog_templates/curiosity_cabinet.html", "Curiosity Cabinet", "topic"
    )
    app.view_functions["create_published_post"] = _create_published_post
    app.view_functions["update_published_post"] = _update_published_post
