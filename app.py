import os
import re
import sqlite3
from datetime import datetime
from functools import wraps
from urllib.parse import urljoin

from flask import Flask, render_template, request, redirect, url_for, session, jsonify, abort
from werkzeug.security import check_password_hash, generate_password_hash

from database import get_db as database_get_db, init_db as database_init_db, migrate_sqlite_to_postgres, IntegrityError

basedir = os.path.abspath(os.path.dirname(__file__))
DATABASE = os.path.join(basedir, "scriptorium.db")

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

ADMIN_AUTH_VERSION = "2026-08-10-3"


def get_db():
    return database_get_db()


def now_string():
    return datetime.now().strftime("%m/%d/%Y %I:%M %p")


def table_columns(conn, table):
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def add_column_if_missing(conn, table, column, definition):
    if column not in table_columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


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
            return redirect(url_for("admin_dashboard"))
        return view(*args, **kwargs)
    return wrapped


def member_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not member_has_access():
            return redirect(url_for("kwsnyderwriting_membership"))
        return view(*args, **kwargs)
    return wrapped


def record_page_view(path, page_type="page", content_id=None, category=None):
    if path.startswith("/static/") or path.startswith("/api/") or path.startswith("/admin"):
        return
    conn = None
    try:
        conn = get_db()
        conn.execute("INSERT INTO page_views(path, page_type, content_id, category) VALUES (?, ?, ?, ?)", (path, page_type, content_id, category))
        conn.commit()
    except Exception:
        pass
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def category_label(category):
    return {"curations": "Book Curations", "reviews": "Book Reviews", "curiosity": "Curiosity Cabinet", "kwsnyderwriting": "K. W. Snyder Writing", "kw_short_stories": "Short Stories", "kw_poems": "Poems", "kw_vignettes": "Vignettes"}.get(category, "Journal")


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
    if request.path == "/":
        return redirect(url_for("member_login"))
    return None


@app.before_request
def analytics_request_tracker():
    path = request.path
    if path.startswith("/static/") or path.startswith("/api/") or path.startswith("/admin"):
        return None
    page_type = "page"
    category = None
    content_id = None
    if path == "/blog":
        page_type, category = "section", "blog"
    elif path.startswith("/blog/bookcurations"):
        page_type, category = "section", "curations"
    elif path.startswith("/blog/bookreviews"):
        page_type, category = "section", "reviews"
    elif path.startswith("/blog/curiosity_cabinet"):
        page_type, category = "section", "curiosity"
    elif path.startswith("/blog/post/"):
        match = re.match(r"^/blog/post/(\d+)", path)
        if match:
            page_type, content_id = "post", int(match.group(1))
    elif path == "/kwsnyderwriting":
        if not member_has_access():
            return None
        page_type, category = "member_section", "kwsnyderwriting"
    elif path.startswith("/kwsnyderwriting/post/"):
        if not member_has_access():
            return None
        match = re.match(r"^/kwsnyderwriting/post/(\d+)", path)
        if match:
            page_type, content_id, category = "member_post", int(match.group(1)), "kwsnyderwriting"
    elif path.startswith("/kwsnyderwriting/novel/") and "/chapter/" not in path:
        if not member_has_access():
            return None
        match = re.match(r"^/kwsnyderwriting/novel/(\d+)", path)
        if match:
            page_type, content_id, category = "novel", int(match.group(1)), "kwsnyderwriting"
    elif "/kwsnyderwriting/novel/" in path and "/chapter/" in path:
        if not member_has_access():
            return None
        match = re.match(r"^/kwsnyderwriting/novel/(\d+)/chapter/(\d+)", path)
        if match:
            page_type, content_id, category = "chapter", int(match.group(2)), "kwsnyderwriting"
    else:
        category = "site"
    record_page_view(path, page_type, content_id, category)
    return None


@app.route("/")
def the_hearth():
    return render_template("index.html")


@app.route("/about")
def about():
    conn = get_db()
    row = conn.execute("SELECT value FROM site_content WHERE key = 'about_content'").fetchone()
    conn.close()
    return render_template("about.html", about_content=row["value"] if row else "")


@app.route("/blog")
def the_blog():
    return render_template("blog_templates/theblog.html")


def public_category(category, template):
    conn = get_db()
    posts = conn.execute("SELECT * FROM published_posts WHERE category = ? AND access_level = 'public' ORDER BY id DESC", (category,)).fetchall()
    conn.close()
    return render_template(template, posts=posts, category_name=category_label(category))


@app.route("/blog/bookcurations")
def book_curations():
    return public_category("curations", "blog_templates/book_curations.html")


@app.route("/blog/bookreviews")
def bookreviews():
    return public_category("reviews", "blog_templates/bookreviews.html")


@app.route("/blog/curiosity_cabinet")
def curiosity_cabinet():
    return public_category("curiosity", "blog_templates/curiosity_cabinet.html")


@app.route("/blog/post/<int:post_id>")
def view_post(post_id):
    conn = get_db()
    post = conn.execute("SELECT * FROM published_posts WHERE id = ?", (post_id,)).fetchone()
    conn.close()
    if not post or post["access_level"] != "public":
        abort(404)
    return render_template("post.html", post=post, back_url=url_for("the_blog"))


@app.route("/kwsnyderwriting/membership")
def kwsnyderwriting_membership():
    if session.pop("member_reauth_ok", False) is not True:
        session.clear()
        return redirect(url_for("member_login"))
    return render_template("blog_templates/kwsnyderwriting_membership.html")


@app.route("/kwsnyderwriting/login", methods=["GET", "POST"])
def member_login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        conn = get_db()
        member = conn.execute("SELECT * FROM members WHERE email = ?", (email,)).fetchone()
        conn.close()
        if member and check_password_hash(member["password_hash"], password):
            session.clear()
            session.permanent = False
            session["member_logged_in"] = True
            session["member_id"] = member["id"]
            session["member_reauth_ok"] = True
            if member["subscription_status"] == "active":
                return redirect(url_for("kwsnyderwriting"))
            return redirect(url_for("kwsnyderwriting_membership"))
        return render_template("blog_templates/kwsnyderwriting_login.html", error="The email or password was not recognized.")
    return render_template("blog_templates/kwsnyderwriting_login.html")


@app.route("/kwsnyderwriting/signup", methods=["GET", "POST"])
def member_signup():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if not email or len(password) < 8:
            return render_template("blog_templates/kwsnyderwriting_signup.html", error="Please provide an email and a password of at least 8 characters.")
        conn = get_db()
        try:
            conn.execute("INSERT INTO members(email, password_hash, subscription_status, date_created) VALUES (?, ?, 'inactive', ?)", (email, generate_password_hash(password), now_string()))
            conn.commit()
        except IntegrityError:
            conn.close()
            return render_template("blog_templates/kwsnyderwriting_signup.html", error="An account with that email already exists.")
        conn.close()
        return redirect(url_for("member_login"))
    return render_template("blog_templates/kwsnyderwriting_signup.html")


@app.route("/kwsnyderwriting/logout")
def member_logout():
    session.clear()
    return redirect(url_for("member_login"))


@app.route("/membership-terms")
def membership_terms():
    return render_template("blog_templates/membership_terms.html")


@app.route("/kwsnyderwriting")
def kwsnyderwriting_entry():
    if session.get("member_reauth_ok") is not True:
        session.clear()
        return redirect(url_for("member_login"))
    session.pop("member_reauth_ok", None)
    if not member_has_access():
        return redirect(url_for("kwsnyderwriting_membership"))
    return kwsnyderwriting_content()


def kwsnyderwriting_content():
    conn = get_db()
    posts = conn.execute("SELECT * FROM published_posts WHERE category IN ('kwsnyderwriting', 'kw_short_stories', 'kw_poems', 'kw_vignettes') AND access_level = 'members' ORDER BY id DESC").fetchall()
    books = conn.execute("SELECT b.*, COUNT(c.id) AS chapter_count FROM manuscript_books b LEFT JOIN manuscript_chapters c ON c.book_id = b.id AND c.published = 1 GROUP BY b.id ORDER BY b.id DESC").fetchall()
    conn.close()
    return render_template("blog_templates/kwsnyderwriting.html", posts=posts, books=books, member_logged_in=True, member_preview=session.get("member_preview") is True)


@app.route("/kwsnyderwriting/post/<int:post_id>")
@member_required
def view_member_post(post_id):
    conn = get_db()
    post = conn.execute("SELECT * FROM published_posts WHERE id = ? AND category IN ('kwsnyderwriting', 'kw_short_stories', 'kw_poems', 'kw_vignettes') AND access_level = 'members'", (post_id,)).fetchone()
    conn.close()
    if not post:
        abort(404)
    return render_template("post.html", post=post, back_url=url_for("kwsnyderwriting_section", section=post["category"]))


@app.route("/kwsnyderwriting/<section>")
@member_required
def kwsnyderwriting_section(section):
    section_map = {"short-stories": ("kw_short_stories", "Short Stories"), "poems": ("kw_poems", "Poems"), "vignettes": ("kw_vignettes", "Vignettes")}
    if section not in section_map:
        abort(404)
    category, title = section_map[section]
    conn = get_db()
    posts = conn.execute("SELECT * FROM published_posts WHERE category = ? AND access_level = 'members' ORDER BY id DESC", (category,)).fetchall()
    conn.close()
    return render_template("blog_templates/kwsnyderwriting_section.html", posts=posts, section_title=title, section_slug=section)


@app.route("/admin/preview-member")
@admin_required
def admin_preview_member():
    session["member_preview"] = True
    return redirect(url_for("kwsnyderwriting"))


@app.route("/admin/preview-member/exit")
@admin_required
def admin_exit_member_preview():
    session.pop("member_preview", None)
    return redirect(url_for("admin_dashboard"))


@app.route("/kwsnyderwriting/novel/<int:book_id>")
@member_required
def view_novel(book_id):
    conn = get_db()
    book = conn.execute("SELECT * FROM manuscript_books WHERE id = ?", (book_id,)).fetchone()
    chapters = conn.execute("SELECT * FROM manuscript_chapters WHERE book_id = ? AND published = 1 ORDER BY chapter_number", (book_id,)).fetchall()
    conn.close()
    if not book:
        abort(404)
    return render_template("blog_templates/novel.html", book=book, chapters=chapters)


@app.route("/kwsnyderwriting/novel/<int:book_id>/chapter/<int:chapter_id>")
@member_required
def view_chapter(book_id, chapter_id):
    conn = get_db()
    chapter = conn.execute("SELECT * FROM manuscript_chapters WHERE id = ? AND book_id = ? AND published = 1", (chapter_id, book_id)).fetchone()
    book = conn.execute("SELECT * FROM manuscript_books WHERE id = ?", (book_id,)).fetchone()
    prev_chapter = conn.execute("SELECT id FROM manuscript_chapters WHERE book_id = ? AND chapter_number < ? AND published = 1 ORDER BY chapter_number DESC LIMIT 1", (book_id, chapter["chapter_number"] if chapter else 0)).fetchone()
    next_chapter = conn.execute("SELECT id FROM manuscript_chapters WHERE book_id = ? AND chapter_number > ? AND published = 1 ORDER BY chapter_number LIMIT 1", (book_id, chapter["chapter_number"] if chapter else 0)).fetchone()
    conn.close()
    if not chapter or not book:
        abort(404)
    return render_template("blog_templates/chapter.html", book=book, chapter=chapter, previous=prev_chapter, next=next_chapter)


@app.route("/kwsnyderwriting/novel/<int:book_id>/chapter/<int:chapter_id>/feedback", methods=["POST"])
@member_required
def submit_reader_feedback(book_id, chapter_id):
    feedback = request.form.get("feedback", "").strip()
    if not feedback:
        return redirect(url_for("view_chapter", book_id=book_id, chapter_id=chapter_id, feedback_error="Please enter your feedback before submitting."))
    if len(feedback) > 20000:
        return redirect(url_for("view_chapter", book_id=book_id, chapter_id=chapter_id, feedback_error="Please keep feedback under 20,000 characters."))
    member_id = session.get("member_id")
    conn = get_db()
    chapter = conn.execute("SELECT id, book_id, chapter_number, title FROM manuscript_chapters WHERE id = ? AND book_id = ? AND published = 1", (chapter_id, book_id)).fetchone()
    book = conn.execute("SELECT id, title FROM manuscript_books WHERE id = ?", (book_id,)).fetchone()
    member = conn.execute("SELECT email FROM members WHERE id = ?", (member_id,)).fetchone()
    if not chapter or not book or not member:
        conn.close()
        abort(404)
    subject = f"Reader Feedback — {book['title']} — Chapter {chapter['chapter_number']}: {chapter['title']}"
    conn.execute("INSERT INTO inbox_messages(message_type, name, email, subject, message, post_id, book_id, chapter_id, member_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", ("reader_feedback", "Subscriber Reader", member["email"], subject, feedback, None, book_id, chapter_id, member_id))
    conn.commit()
    conn.close()
    return redirect(url_for("view_chapter", book_id=book_id, chapter_id=chapter_id, feedback_sent="1"))


@app.route("/contact", methods=["GET", "POST"])
def contact():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        subject = request.form.get("subject", "").strip()
        message = request.form.get("message", "").strip()
        if not name or not email or not message:
            return render_template("contact.html", error="Please provide your name, email, and message.", name=name, email=email, subject=subject, message=message)
        conn = get_db()
        conn.execute("INSERT INTO inbox_messages(message_type, name, email, subject, message) VALUES (?, ?, ?, ?, ?)", ("contact", name, email, subject, message))
        conn.commit()
        conn.close()
        return render_template("contact.html", success="Your message has been sent. Thank you for reaching out.")
    return render_template("contact.html")

@app.route("/store")
def the_scriptorium():
    return render_template("store.html")


@app.route("/merch")
def merch_shop():
    return render_template("merch.html")


@app.route("/admin")
def admin_dashboard():
    if session.pop("admin_reauth_ok", False) is not True:
        session.pop("admin_logged_in", None)
        session.pop("admin_auth_version", None)
        return render_template("admin.html", logged_in=False)
    if not require_admin():
        session.pop("admin_logged_in", None)
        session.pop("admin_auth_version", None)
        return render_template("admin.html", logged_in=False)
    return render_template("admin.html", logged_in=True)


@app.route("/admin/login", methods=["POST"])
def admin_login():
    password = request.form.get("password", "")
    configured_password = os.environ.get("ADMIN_PASSWORD", "").strip()
    if not configured_password:
        return render_template("admin.html", logged_in=False, login_error="Admin password is not configured on the server.")
    if password == configured_password:
        session.clear()
        session.permanent = False
        session["admin_logged_in"] = True
        session["admin_auth_version"] = ADMIN_AUTH_VERSION
        session["admin_reauth_ok"] = True
        return redirect(url_for("admin_dashboard"))
    return render_template("admin.html", logged_in=False, login_error="The admin password was not recognized.")


@app.route("/admin/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/inbox")
@admin_required
def admin_inbox():
    pass


