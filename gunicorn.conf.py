def post_worker_init(worker):
    app = worker.wsgi
    # Render starts app.py directly with Gunicorn, so initialize/migrate the
    # database here before any analytics or membership requests arrive.
    from database import init_db
    init_db()
    from paypal_member_routes import register_paypal_member
    register_paypal_member(app)
    from member_auth_guard import register_member_auth_guard
    register_member_auth_guard(app)
    from admin_auth_guard import register_admin_auth_guard
    register_admin_auth_guard(app)
    from site_enhancements import register_site_enhancements
    register_site_enhancements(app)
