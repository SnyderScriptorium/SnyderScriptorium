from app import app, init_db
from store import store_bp, ensure_store_tables

# Keep the bookstore modular: it is registered here instead of being mixed into
# the existing application routes. Flask blueprints are designed for this kind
# of component separation.
app.register_blueprint(store_bp)

# Ensure the independent bookstore schema exists on deployment/startup.
init_db()
ensure_store_tables()


@app.after_request
def add_store_admin_link(response):
    """Add a small Store link to the existing admin panel without editing it.

    This keeps the Phase 1 bookstore changes isolated from the large admin
    template while still making the new Store Manager reachable from /admin.
    """
    if request_path_is_admin(response):
        content_type = response.headers.get("Content-Type", "")
        if "text/html" in content_type and response.is_streamed is False:
            body = response.get_data(as_text=True)
            marker = '<button type="button" class="light" onclick="location.href=\'/admin/store\'">Book Store</button>'
            if marker not in body and "id=\"dashboard\"" in body:
                body = body.replace('<div class="tabs">', '<div class="tabs">' + marker, 1)
                response.set_data(body)
    return response


def request_path_is_admin(response):
    # Flask does not expose the request object through the response. Importing
    # it here avoids changing the existing app.py just for this UI link.
    from flask import request
    return request.path == "/admin"
