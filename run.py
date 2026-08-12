from app import app, DATABASE, init_db
from analytics import init_analytics
from member_auth_guard import register_member_auth_guard
from admin_auth_guard import register_admin_auth_guard

app.config["DATABASE"] = DATABASE
init_db()
init_analytics(app)

# Register authentication guards directly during application import so they
# are active regardless of whether Gunicorn loads an optional config hook.
register_member_auth_guard(app)
register_admin_auth_guard(app)

if __name__ == "__main__":
    app.run()
