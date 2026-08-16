from app import app, init_db
from store import store_bp, ensure_store_tables, store_home

# The bookstore is a separate Flask blueprint. Register it here so its routes,
# database setup, and future commerce code stay outside the main application.
app.register_blueprint(store_bp)

# The legacy application already owns the /store endpoint. Delegate that view
# to the bookstore module so the public URL remains unchanged while the actual
# storefront implementation lives entirely in store.py.
app.view_functions["the_scriptorium"] = store_home

# Ensure the independent bookstore schema exists on deployment/startup.
init_db()
ensure_store_tables()


@app.after_request
def add_store_admin_link(response):
    """Expose the Book Store Manager from the existing admin tabs."""
    if request_path_is_admin(response):
        content_type = response.headers.get("Content-Type", "")
        if "text/html" in content_type and not response.is_streamed:
            body = response.get_data(as_text=True)
            marker = '<button type="button" class="light" onclick="location.href=\'/admin/store\'">Book Store</button>'
            if marker not in body and 'id="dashboard"' in body:
                body = body.replace('<div class="tabs">', '<div class="tabs">' + marker, 1)
                response.set_data(body)
    return response


def request_path_is_admin(response):
    from flask import request
    return request.path == "/admin"
