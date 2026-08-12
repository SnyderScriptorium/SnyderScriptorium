def post_worker_init(worker):
    app = worker.wsgi

    # Always initialize the database for the actual Render/Gunicorn process.
    # Render starts `gunicorn app:app`, so run.py is not imported automatically.
    from database import init_db
    init_db()

    # Recover/create the Sandbox membership plan if the configured plan ID is
    # stale. The valid plan ID is then injected into the running app config.
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

    # The Admin template still references this older endpoint name. Keep the
    # URL endpoint compatible without weakening its @admin_required guard.
    if "get_published_posts" not in app.view_functions and "get_published" in app.view_functions:
        app.add_url_rule(
            "/api/published",
            endpoint="get_published_posts",
            view_func=app.view_functions["get_published"],
            methods=["GET"],
        )

    # Ensure the analytics table exists even on an older Postgres database
    # that predates the analytics migration.
    from database import get_db
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

    # Keep the original endpoint name available to existing templates and
    # redirects while the protected entry route uses the fresh-login handler.
    if "kwsnyderwriting" not in app.view_functions and "kwsnyderwriting_entry" in app.view_functions:
        app.add_url_rule("/kwsnyderwriting", endpoint="kwsnyderwriting", view_func=app.view_functions["kwsnyderwriting_entry"])
