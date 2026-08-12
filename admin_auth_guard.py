from flask import redirect, request, session


def register_admin_auth_guard(app):
    """Keep every administrative route behind the existing admin session."""
    if getattr(app, "_admin_auth_guard_registered", False):
        return

    @app.before_request
    def require_admin_login():
        path = request.path.rstrip("/") or "/"
        if not path.startswith("/admin"):
            return None

        if path == "/admin":
            return None

        if path in {"/admin/login", "/admin/logout"}:
            return None

        # The main app owns the canonical auth version. The guard is
        # registered after the app module has loaded, so importing the
        # constant here avoids maintaining a second copy that can drift.
        try:
            from app import ADMIN_AUTH_VERSION
        except Exception:
            ADMIN_AUTH_VERSION = None

        if ADMIN_AUTH_VERSION and session.get("admin_logged_in") is True and session.get("admin_auth_version") == ADMIN_AUTH_VERSION:
            return None

        session.pop("admin_logged_in", None)
        session.pop("admin_auth_version", None)
        session.pop("admin_reauth_ok", None)
        return redirect("/admin")

    app._admin_auth_guard_registered = True
