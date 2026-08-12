def post_worker_init(worker):
    app = worker.wsgi
    from paypal_member_routes import register_paypal_member
    register_paypal_member(app)
    from member_auth_guard import register_member_auth_guard
    register_member_auth_guard(app)
