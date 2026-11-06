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

        # Only the authentication entry points and the membership page
        # itself remain public, so a visitor can see the subscription
        # offer and subscribe. Only the private library stays behind login.
        # The PayPal return/cancel/resume paths are public too: a pending
        # signup has no member session yet -- the account is only made on
        # the return, once the $1 payment is verified -- so the guard must
        # let the buyer back in to finish (or abandon) checkout.
        public_paths = {
            "/kwsnyderwriting/login",
            "/kwsnyderwriting/signup",
            "/kwsnyderwriting/logout",
            "/kwsnyderwriting/membership",
            "/kwsnyderwriting/signup-subscribe",
            "/kwsnyderwriting/signup-resume",
            "/kwsnyderwriting/membership/return",
            "/kwsnyderwriting/membership/cancel",
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
