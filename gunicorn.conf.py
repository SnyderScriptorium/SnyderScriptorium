def post_worker_init(worker):
    app = worker.wsgi

    from database import init_db, get_db, using_postgres
    init_db()

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

    # Compatibility aliases for older admin-template endpoint names.
    if "get_published_posts" not in app.view_functions and "get_published" in app.view_functions:
        app.add_url_rule("/api/published", endpoint="get_published_posts", view_func=app.view_functions["get_published"], methods=["GET"])
    if "create_published_post" not in app.view_functions and "create_published" in app.view_functions:
        app.add_url_rule("/api/published", endpoint="create_published_post", view_func=app.view_functions["create_published"], methods=["POST"])

    # Admin API failures must not redirect through /admin. Return JSON instead,
    # so an expired/invalid admin session cannot create an AJAX redirect loop.
    from flask import jsonify, request

    @app.before_request
    def admin_api_requires_auth_json():
        path = request.path
        admin_api_prefixes = (
            "/api/drafts",
            "/api/published",
            "/api/manuscripts",
            "/api/about",
            "/api/inbox",
            "/api/analytics",
        )
        if not path.startswith(admin_api_prefixes):
            return None
        try:
            from app import require_admin
            if require_admin():
                return None
        except Exception:
            pass
        return jsonify({"error": "Admin authentication required."}), 401

    if using_postgres():
        conn = get_db()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS page_views (
                    id BIGSERIAL PRIMARY KEY,
                    path TEXT NOT NULL,
                    page_type TEXT NOT NULL DEFAULT 'page',
                    content_id BIGINT,
                    category TEXT,
                    viewed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("ALTER TABLE page_views ADD COLUMN IF NOT EXISTS page_type TEXT NOT NULL DEFAULT 'page'")
            conn.execute("ALTER TABLE page_views ADD COLUMN IF NOT EXISTS content_id BIGINT")
            conn.execute("ALTER TABLE page_views ADD COLUMN IF NOT EXISTS category TEXT")
            conn.execute("ALTER TABLE page_views ADD COLUMN IF NOT EXISTS viewed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP")
            conn.commit()
        finally:
            conn.close()

    @app.after_request
    def no_cache_admin(response):
        if request.path.startswith("/admin"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        elif request.path == "/api/published" and request.method == "GET":
            response.headers["Cache-Control"] = "private, max-age=5, must-revalidate"
            response.headers["Vary"] = "Cookie"
        return response

    if "kwsnyderwriting" not in app.view_functions and "kwsnyderwriting_entry" in app.view_functions:
        app.add_url_rule("/kwsnyderwriting", endpoint="kwsnyderwriting", view_func=app.view_functions["kwsnyderwriting_entry"])
