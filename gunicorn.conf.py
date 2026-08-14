def post_worker_init(worker):
    app = worker.wsgi

    from database import init_db, get_db, using_postgres
    init_db()

    # Normalize the legacy Journal bucket everywhere it can still exist.
    # K. W. Snyder Writing is the canonical private category.
    conn = get_db()
    try:
        conn.execute("UPDATE published_posts SET category = 'kwsnyderwriting', category_name = 'K. W. Snyder Writing', access_level = 'members' WHERE LOWER(COALESCE(category, '')) = 'journal' OR LOWER(COALESCE(category_name, '')) = 'journal'")
        conn.execute("UPDATE drafts SET category = 'kwsnyderwriting' WHERE LOWER(COALESCE(category, '')) = 'journal'")
        conn.execute("UPDATE page_views SET category = 'kwsnyderwriting' WHERE LOWER(COALESCE(category, '')) = 'journal'")
        conn.commit()
    finally:
        conn.close()

    from paypal_plan_bootstrap import ensure_paypal_plan
    ensure_paypal_plan(app)
    from paypal_member_routes import register_paypal_member
    register_paypal_member(app)
    from member_auth_guard import register_member_auth_guard
    register_member_auth_guard(app)
    from admin_auth_guard import register_admin_auth_guard
    register_admin_auth_guard(app)
    from site_enhancements import register_site_enhancements
    register_site_enhancements(app)
    from analytics_dashboard_v3 import register as register_analytics_v3
    register_analytics_v3(app)
    from subscriber_dashboard import register_subscriber_dashboard
    register_subscriber_dashboard(app)
    from category_route_fix import register_category_route_fix
    register_category_route_fix(app)

    if "get_published_posts" not in app.view_functions and "get_published" in app.view_functions:
        app.add_url_rule("/api/published", endpoint="get_published_posts", view_func=app.view_functions["get_published"], methods=["GET"])
    if "create_published_post" not in app.view_functions and "create_published" in app.view_functions:
        app.add_url_rule("/api/published", endpoint="create_published_post", view_func=app.view_functions["create_published"], methods=["POST"])

    if using_postgres():
        conn = get_db()
        try:
            conn.execute("CREATE TABLE IF NOT EXISTS page_views (id BIGSERIAL PRIMARY KEY,path TEXT NOT NULL,page_type TEXT NOT NULL DEFAULT 'page',content_id BIGINT,category TEXT,viewed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,visitor_key TEXT)")
            conn.execute("ALTER TABLE page_views ADD COLUMN IF NOT EXISTS page_type TEXT NOT NULL DEFAULT 'page'")
            conn.execute("ALTER TABLE page_views ADD COLUMN IF NOT EXISTS content_id BIGINT")
            conn.execute("ALTER TABLE page_views ADD COLUMN IF NOT EXISTS category TEXT")
            conn.execute("ALTER TABLE page_views ADD COLUMN IF NOT EXISTS viewed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP")
            conn.execute("ALTER TABLE page_views ADD COLUMN IF NOT EXISTS visitor_key TEXT")
            conn.commit()
        finally:
            conn.close()

    from flask import request
    @app.after_request
    def no_cache_admin(response):
        if request.path.startswith("/admin"):
            response.headers["Cache-Control"]="no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"]="no-cache"
            response.headers["Expires"]="0"
        elif request.path in {"/static/admin_targeted_fixes.js", "/static/admin_fixes.js", "/static/style.css"}:
            # Force the browser to pick up the current admin/analytics code after a deploy.
            response.headers["Cache-Control"]="no-cache, must-revalidate, max-age=0"
        return response

    if "kwsnyderwriting" not in app.view_functions and "kwsnyderwriting_entry" in app.view_functions:
        app.add_url_rule("/kwsnyderwriting", endpoint="kwsnyderwriting", view_func=app.view_functions["kwsnyderwriting_entry"])
