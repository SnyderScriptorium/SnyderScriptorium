from flask import render_template, redirect, request, session


def register_admin_auth_guard(app):
    """Keep administrative routes behind the existing admin session.

    The unauthenticated /admin page is deliberately served as a login-only
    template. This prevents dashboard JavaScript from loading before login.
    """
    if getattr(app, "_admin_auth_guard_registered", False):
        return

    @app.before_request
    def require_admin_login():
        path = request.path.rstrip("/") or "/"

        if not path.startswith("/admin"):
            return None

        if path == "/admin":
            try:
                from app import ADMIN_AUTH_VERSION
            except Exception:
                ADMIN_AUTH_VERSION = None

            authenticated = bool(
                ADMIN_AUTH_VERSION
                and session.get("admin_logged_in") is True
                and session.get("admin_auth_version") == ADMIN_AUTH_VERSION
            )

            if authenticated:
                return None

            # Root fix: do not render the full dashboard while logged out.
            # The login-only template contains no dashboard HTML or JS.
            session.pop("admin_logged_in", None)
            session.pop("admin_auth_version", None)
            session.pop("admin_reauth_ok", None)
            return render_template("admin_login.html")

        if path in {"/admin/login", "/admin/logout"}:
            return None

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
