"""Production WSGI entry point for Snyder Scriptorium.

Gunicorn loads ``app`` from this module.  Application routes remain owned by
``app.py`` and the bookstore routes remain owned by ``store.py``; this module
only wires the two together and performs the database initialization needed at
startup.
"""

from app import app, init_db
from store import store_bp, ensure_store_tables


# Register the bookstore blueprint exactly once at application startup.
# The blueprint owns /store, /store/book/<slug>, and the bookstore API/admin
# routes defined in store.py.
if "store" not in app.blueprints:
    app.register_blueprint(store_bp)


# Initialize the shared application database and the bookstore tables when
# Gunicorn starts the worker.  These functions are idempotent in the current
# database layer, so this is safe on normal Render restarts/deploys.
init_db()
ensure_store_tables()
