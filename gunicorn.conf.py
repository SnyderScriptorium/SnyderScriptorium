def post_worker_init(worker):
    app = worker.wsgi

    from database import init_db, get_db, using_postgres
    init_db()

    # Disable the legacy tracker defined in app.py. Analytics now has exactly
    # one active request tracker: canonical_analytics_tracker.py.
    legacy = app.before_request_funcs.get(None, [])
    app.before_request_funcs[None] = [fn for fn in legacy if getattr(fn, '__name__', '') != 'analytics_request_tracker']

    # Normalize the legacy Journal bucket everywhere it can still exist.
    conn = get_db()
    try:
        conn.execute("UPDATE published_posts SET category = 'kwsnyderwriting', category_name = 'K. W. Snyder Writing', access_level = 'members' WHERE LOWER(COALESCE(category, '')) = 'journal' OR LOWER(COALESCE(category_name, '')) = 'journal'")
        conn.execute("UPDATE drafts SET category = 'kwsnyderwriting' WHERE LOWER(COALESCE(category, '')) = 'journal'")
        conn.execute("UPDATE page_views SET category = 'kwsnyderwriting' WHERE LOWER(COALESCE(category, '')) = 'journal'")
        conn.execute("UPDATE published_posts SET access_level = 'members' WHERE category NOT IN ('curations', 'reviews', 'curiosity')")
        if using_postgres():
            conn.execute("""CREATE OR REPLACE FUNCTION force_safe_access() RETURNS trigger AS $$
                BEGIN
                    IF NEW.category NOT IN ('curations','reviews','curiosity') THEN NEW.access_level := 'members'; END IF;
                    RETURN NEW;
                END;
            $$ LANGUAGE plpgsql""")
            conn.execute("DROP TRIGGER IF EXISTS trg_force_safe_access ON published_posts")
            conn.execute("""CREATE TRIGGER trg_force_safe_access BEFORE INSERT OR UPDATE OF category, access_level ON published_posts FOR EACH ROW EXECUTE FUNCTION force_safe_access()""")
        else:
            conn.execute("DROP TRIGGER IF EXISTS trg_force_safe_access_insert")
            conn.execute("DROP TRIGGER IF EXISTS trg_force_safe_access_update")
            conn.execute("""CREATE TRIGGER trg_force_safe_access_insert AFTER INSERT ON published_posts WHEN NEW.category NOT IN ('curations','reviews','curiosity') AND NEW.access_level != 'members' BEGIN UPDATE published_posts SET access_level='members' WHERE id=NEW.id; END""")
            conn.execute("""CREATE TRIGGER trg_force_safe_access_update AFTER UPDATE OF category, access_level ON published_posts WHEN NEW.category NOT IN ('curations','reviews','curiosity') AND NEW.access_level != 'members' BEGIN UPDATE published_posts SET access_level='members' WHERE id=NEW.id; END""")
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

    # Keep the login endpoint independent of dashboard scripts.
    from flask import request, session, redirect, url_for, render_template
    import os
    from app import ADMIN_AUTH_VERSION
    def isolated_admin_login():
        password = request.form.get("password", "")
        configured_password = os.environ.get("ADMIN_PASSWORD", "").strip()
        if not configured_password:
            return render_template("admin_login.html", login_error="Admin password is not configured on the server.")
        if password == configured_password:
            session.permanent = False
            session["admin_logged_in"] = True
            session["admin_auth_version"] = ADMIN_AUTH_VERSION
            session["admin_reauth_ok"] = True
            return redirect(url_for("admin_dashboard"))
        return render_template("admin_login.html", login_error="The admin password was not recognized.")
    app.view_functions["admin_login"] = isolated_admin_login

    # Single analytics authority: one tracker + one report/dashboard.
    from canonical_analytics_tracker import register as register_canonical_analytics
    register_canonical_analytics(app)
    from analytics_dashboard_v3 import register as register_analytics_v3
    register_analytics_v3(app)
    if "analytics_api_v3" in app.view_functions:
        app.view_functions["analytics_api"] = app.view_functions["analytics_api_v3"]

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
            conn.execute("ALTER TABLE page_views ADD COLUMN IF NOT EXISTS referrer TEXT")
            conn.execute("ALTER TABLE page_views ADD COLUMN IF NOT EXISTS traffic_source TEXT")
            conn.commit()
        finally:
            conn.close()

    @app.after_request
    def no_cache_admin(response):
        from flask import request
        if request.path.startswith("/admin"):
            response.headers["Cache-Control"]="no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"]="no-cache"
            response.headers["Expires"]="0"
            if 'text/html' in response.content_type and session.get("admin_logged_in") is True:
                html=response.get_data(as_text=True)
                marker='</body>'
                scripts=[
                    '<script src="/static/about_editor.js?v=20260814-4"></script>',
                    '<script src="/static/admin_navigation.js?v=20260815-1"></script>'
                ]
                for script in scripts:
                    if script not in html:
                        html=html.replace(marker,script+marker)
                response.set_data(html)
        elif request.path in {"/static/admin_targeted_fixes.js", "/static/admin_fixes.js", "/static/style.css", "/static/about_editor.js", "/static/admin_navigation.js"}:
            response.headers["Cache-Control"]="no-cache, must-revalidate, max-age=0"
        return response
