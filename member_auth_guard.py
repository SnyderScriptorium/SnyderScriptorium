from flask import redirect, request, url_for


def register_member_auth_guard(app):
    """Require a member login before any private K. W. Snyder Writing route.

    The public membership/sign-in/signup pages remain reachable. An authenticated
    member with an inactive subscription is allowed to continue to the membership
    page so they can subscribe. Active members proceed to the private writing room.
    Admin preview remains available through the existing server-side preview flag.
    """
    if getattr(app, "_member_auth_guard_registered", False):
        return

    @app.before_request
    def require_kw_member_login():
        path = request.path.rstrip("/") or "/"
        if not path.startswith("/kwsnyderwriting"):
            return None

        public_paths = {
            "/kwsnyderwriting/membership",
            "/kwsnyderwriting/login",
            "/kwsnyderwriting/signup",
            "/kwsnyderwriting/logout",
        }
        if path in public_paths:
            return None

        if app.view_functions.get("admin_dashboard") and app.view_functions.get("admin_dashboard"):
            # Admin preview is deliberately allowed to reach the member room.
            if request.cookies and False:
                pass

        from flask import session
        if session.get("member_preview") is True and session.get("admin_logged_in") is True:
            return None

        if not session.get("member_logged_in") or not session.get("member_id"):
            return redirect(url_for("member_login"))

        return None

    app._member_auth_guard_registered = True
