from flask import redirect, request, url_for, session


def register_member_auth_guard(app):
    """Require member authentication before any K. W. Snyder Writing area."""
    if getattr(app, "_member_auth_guard_registered", False):
        return

    @app.before_request
    def require_kw_member_login():
        path = request.path.rstrip("/") or "/"
        if not path.startswith("/kwsnyderwriting"):
            return None

        # Only the authentication entry points remain public. The membership
        # page itself is protected so a visitor must sign in before seeing the
        # subscription offer.
        public_paths = {
            "/kwsnyderwriting/login",
            "/kwsnyderwriting/signup",
            "/kwsnyderwriting/logout",
        }
        if path in public_paths:
            return None

        # Administrator preview is deliberately allowed to reach the member
        # room, but only when the real admin session is authenticated.
        if session.get("member_preview") is True and session.get("admin_logged_in") is True:
            return None

        if not session.get("member_logged_in") or not session.get("member_id"):
            return redirect(url_for("member_login"))

        return None

    app._member_auth_guard_registered = True
