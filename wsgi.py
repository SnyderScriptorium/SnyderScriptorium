"""Production WSGI entry point for Snyder Scriptorium."""

from app import app, init_db
from store import store_bp, ensure_store_tables

if "store" not in app.blueprints:
    app.register_blueprint(store_bp)

# Build the base schema first; the inbox module then adds its member/blocking
# columns against tables that are guaranteed to exist.
init_db()

# Wire the live admin inbox/member actions after app.py and the base database
# have been loaded.
import inbox_admin_routes  # noqa: F401,E402

ensure_store_tables()

# Register analytics in the WSGI entry point so the routes exist both in
# production and when the application is loaded directly by CI/smoke tests.
from analytics_dashboard_v3 import register as register_analytics_v3  # noqa: E402
register_analytics_v3(app)
