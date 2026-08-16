import os
from datetime import datetime
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, session, jsonify, abort
from werkzeug.security import check_password_hash, generate_password_hash

from database import get_db as database_get_db, init_db as database_init_db, IntegrityError

basedir = os.path.abspath(os.path.dirname(__file__))

app = Flask(__name__, template_folder=os.path.join(basedir, "templates"))
app.secret_key = os.environ.get("SECRET_KEY", "snyder-scriptorium-development-key")
app.config.update(
    SESSION_COOKIE_NAME="snyder_scriptorium_session",
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("RENDER", "").lower() == "true" or os.environ.get("FLASK_ENV") == "production",
    SESSION_PERMANENT=False,
    MAIN_DOMAIN=os.environ.get("MAIN_DOMAIN", "snyderscriptorium.com").strip().lower(),
    KWSNYDER_DOMAIN=os.environ.get("KWSNYDER_DOMAIN", "kwsnyderwriting.com").strip().lower(),
)

ADMIN_AUTH_VERSION = "2026-08-16-1"


def get_db():
    return database_get_db()


def now_string():
    return datetime.now().strftime("%m/%d/%Y %I:%M %p")


def init_db():
    database_init_db()


def require_admin():
    return bool(session.get("admin_logged_in") is True and session.get("admin_auth_version") == ADMIN_AUTH_VERSION)


def require_member():
    return bool(session.get("member_logged_in"))


def member_has_access():
    if session.get("member_preview") is True and require_admin():
        return True
    if not require_member():
        return False
    member_id = session.get("member_id")
    if not member_id:
        return False
    conn = get_db()
    row = conn.execute("SELECT subscription_status FROM members WHERE id = ?", (member_id,)).fetchone()
    conn.close()
    return bool(row and row["subscription_status"] == "active")


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not require_admin():
            session.pop("admin_logged_in", None)
            session.pop("admin_auth_version", None)
            return redirect(url_for("admin_login_page"))
        return view(*args, **kwargs)
    return wrapped


def member_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not member_has_access():
            return redirect(url_for("kwsnyderwriting_membership"))
        return view(*args, **kwargs)
    return wrapped


def category_label(category):
    return {"curations": "Book Curations", "reviews": "Book Reviews", "curiosity": "Curiosity Cabinet", "kwsnyderwriting": "K. W. Snyder Writing", "kw_short_stories": "Short Stories", "kw_poems": "Poems", "kw_vignettes": "Vignettes"}.get(category, "Site Page")


def is_kw_domain():
    configured = app.config.get("KWSNYDER_DOMAIN", "").strip().lower()
    if not configured:
        return False
    host = request.host.split(":")[0].lower()
    return host in {configured, f"www.{configured}"}


def main_site_url(path="/"):
    path = str(path or "/")
    if not path.startswith("/"):
        path = "/" + path
    return f"https://{app.config['MAIN_DOMAIN']}{path}"


def kw_site_url(path="/"):
    path = str(path or "/")
    if not path.startswith("/"):
        path = "/" + path
    return f"https://{app.config['KWSNYDER_DOMAIN']}{path}"


@app.context_processor
def domain_urls():
    return {"main_site_url": main_site_url, "kw_site_url": kw_site_url, "is_kw_domain": is_kw_domain}


@app.before_request
def route_kw_domain():
    if not is_kw_domain() or request.path.startswith("/static/"):
        return None
    if request.path.startswith("/kwsnyderwriting"):
        return None
    if request.path == "/":
        return redirect(url_for("member_login"))
    return None


@app.before_request
def enforce_admin_gate():
    """Defense in depth: no /admin URL is reachable without the admin session."""
    if not request.path.startswith("/admin"):
        return None
    if request.path == "/admin/login":
        return None
    if request.path.startswith("/static/"):
        return None
    if not require_admin():
        session.pop("admin_logged_in", None)
        session.pop("admin_auth_version", None)
        return redirect(url_for("admin_login_page"))
    return None


@app.route("/")
def the_hearth():
    return render_template("index.html")
