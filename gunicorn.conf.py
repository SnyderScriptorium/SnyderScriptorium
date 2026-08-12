def post_worker_init(worker):
    app = worker.wsgi
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

    # Keep the original endpoint name available to existing templates and
    # redirects while the protected entry route uses the fresh-login handler.
    if "kwsnyderwriting" not in app.view_functions and "kwsnyderwriting_entry" in app.view_functions:
        app.add_url_rule("/kwsnyderwriting", endpoint="kwsnyderwriting", view_func=app.view_functions["kwsnyderwriting_entry"])
