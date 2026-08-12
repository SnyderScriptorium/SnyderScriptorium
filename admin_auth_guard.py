from flask import redirect, request, url_for, session


def register_admin_auth_guard(app):
    """Keep every administrative route behind the existing admin session."""
    if getattr(app, "_admin_auth_guard_registered", False):
        return

    @app.before_request
    def require_admin_login():
        path = request.path.rstrip("/") or "/"
        if not path.startswith("/admin"):
            return None

        # The login POST and logout route must remain reachable without an
        # authenticated session. /admin itself renders the login form.
        if path in {"/admin/login", "/admin/logout"}:
            return None

        if session.get("admin_logged_in") is True and session.get("admin_auth_version") == getattr(app, "ADMIN_AUTH_VERSION", None):
            return None

        session.pop("admin_logged_in", None)
        session.pop("admin_auth_version", None)
        return redirect(url_for("admin_dashboard"))

    app._admin_auth_guard_registered = True
