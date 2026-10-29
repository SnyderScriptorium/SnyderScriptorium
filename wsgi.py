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

# Register the same canonical pageview writer used by Gunicorn. Its
# registration guard prevents accidental duplicate callbacks if startup paths
# are ever composed in tests or deployment tooling.
from canonical_analytics_tracker import register as register_canonical_analytics  # noqa: E402
register_canonical_analytics(app)
