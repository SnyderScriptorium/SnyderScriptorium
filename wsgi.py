"""Production WSGI entry point for Snyder Scriptorium."""

from app import app, init_db
from store import store_bp, ensure_store_tables

if "store" not in app.blueprints:
    app.register_blueprint(store_bp)

# Wire the live admin inbox/member actions after app.py is loaded.
import inbox_admin_routes  # noqa: F401,E402

init_db()
ensure_store_tables()
