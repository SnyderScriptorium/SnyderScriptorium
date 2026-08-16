def post_worker_init(worker):
    app = worker.wsgi

    from database import init_db
    init_db()

    from draft_request_guard import register as register_draft_guard
    register_draft_guard(app)

    from paypal_plan_bootstrap import ensure_paypal_plan
    ensure_paypal_plan(app)

    from paypal_member_routes import register_paypal_member
    register_paypal_member(app)

    from member_auth_guard import register_member_auth_guard
    register_member_auth_guard(app)

    from canonical_analytics_tracker import register as register_canonical_analytics
    register_canonical_analytics(app)

    from analytics_dashboard_v3 import register as register_analytics_v3
    register_analytics_v3(app)

    from subscriber_dashboard import register_subscriber_dashboard
    register_subscriber_dashboard(app)

    @app.after_request
    def no_cache_admin(response):
        from flask import request
        if request.path.startswith("/admin"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        elif request.path in {
            "/static/admin_targeted_fixes.js",
            "/static/admin_editor.js",
            "/static/about_editor.js",
            "/static/admin_navigation.js",
            "/static/style.css",
        }:
            response.headers["Cache-Control"] = "no-cache, must-revalidate, max-age=0"
        return response
