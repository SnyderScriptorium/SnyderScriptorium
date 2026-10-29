"""Production WSGI entry point for Snyder Scriptorium."""

from app import app, init_db
from store import store_bp, ensure_store_tables

if "store" not in app.blueprints:
    app.register_blueprint(store_bp)

# Customer reviews live in their own module so the store.py
# auto-restore workflow can never touch them.
from store_reviews import reviews_bp, ensure_review_tables

if "reviews" not in app.blueprints:
    app.register_blueprint(reviews_bp)

ensure_review_tables()

# Build the base schema first; the inbox module then adds its member/blocking
# columns against tables that are guaranteed to exist.
init_db()

# Wire the live admin inbox/member actions after app.py and the base database
# have been loaded.
import inbox_admin_routes  # noqa: F401,E402

ensure_store_tables()

# Repair bookstore ID sequences after the tables exist. This is deliberately
# in the production WSGI path so stale PostgreSQL sequences cannot block a new
# book, image, order, or gallery insert.
import repair_store_sequences  # noqa: F401,E402

# Register analytics in the WSGI entry point so the routes exist both in
# production and when the application is loaded directly by CI/smoke tests.
from analytics_dashboard_v3 import register as register_analytics_v3  # noqa: E402
register_analytics_v3(app)

# Match Gunicorn's runtime registrations so CI/local smoke tests exercise
# the same route and request-guard surface as production.
from draft_request_guard import register as register_draft_guard  # noqa: E402
register_draft_guard(app)

from paypal_plan_bootstrap import ensure_paypal_plan  # noqa: E402
ensure_paypal_plan(app)

from paypal_member_routes import register_paypal_member  # noqa: E402
register_paypal_member(app)

from member_auth_guard import register_member_auth_guard  # noqa: E402
register_member_auth_guard(app)

# One canonical pageview writer shared by all startup paths.
from canonical_analytics_tracker import register as register_canonical_analytics  # noqa: E402
register_canonical_analytics(app)

from subscriber_dashboard import register_subscriber_dashboard  # noqa: E402
if "subscriber_dashboard" not in app.view_functions:
    register_subscriber_dashboard(app)

# Match production's cache protections for admin responses and selected
# frequently edited admin assets.
from flask import request  # noqa: E402

@app.after_request
def no_cache_admin(response):
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
