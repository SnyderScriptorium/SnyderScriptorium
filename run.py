from app import app, DATABASE, init_db
from member_auth_guard import register_member_auth_guard
from admin_auth_guard import register_admin_auth_guard

app.config["DATABASE"] = DATABASE
init_db()

# Analytics is registered by gunicorn.conf.py through the single canonical
# site_enhancements + analytics_dashboard_v3 stack. Do not initialize a
# second analytics tracker here.
register_member_auth_guard(app)
register_admin_auth_guard(app)

if __name__ == "__main__":
    app.run()
