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

# Find Us: public event page plus authenticated admin event management.
from find_us_routes import find_us_bp, ensure_find_us_tables  # noqa: E402
ensure_find_us_tables()
if "find_us" not in app.blueprints:
    app.register_blueprint(find_us_bp)
