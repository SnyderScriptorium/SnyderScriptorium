from app import app, DATABASE, init_db
from member_auth_guard import register_member_auth_guard

app.config["DATABASE"] = DATABASE
init_db()

# Analytics and admin authentication are registered by the production
# Gunicorn configuration. Keep this development entrypoint from installing
# duplicate authentication or analytics layers.
register_member_auth_guard(app)

if __name__ == "__main__":
    app.run()
