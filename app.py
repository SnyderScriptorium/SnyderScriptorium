import os
import re
import sqlite3
from datetime import datetime
from functools import wraps

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
)

# Changing this value invalidates any older admin session immediately.
ADMIN_AUTH_VERSION = "2026-08-10-2"


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
    return bool(
        session.get("admin_logged_in") is True
        and session.get("admin_auth_version") == ADMIN_AUTH_VERSION
    )


def require_member():
    return bool(session.get("member_logged_in"))


def member_has_access():
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
    """Persist a visitor view without allowing analytics failures to break the site."""
    if path.startswith("/static/") or path.startswith("/api/") or path.startswith("/admin"):
        return
    conn = None
    try:
        conn = get_db()
        conn.execute(
            "INSERT INTO page_views(path, page_type, content_id, category) VALUES (?, ?, ?, ?)",
            (path, page_type, content_id, category),
        )
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
    return {
        "curations": "Book Curations",
        "reviews": "Book Reviews",
        "curiosity": "Curiosity Cabinet",
        "kwsnyderwriting": "K. W. Snyder Writing",
    }.get(category, "Journal")


def is_kw_domain():
    configured = os.environ.get("KWSNYDER_DOMAIN", "").strip().lower()
    if not configured:
        return False
    host = request.host.split(":")[0].lower()
    return host in {configured, f"www.{configured}"}


@app.before_request
def route_kw_domain():
    if not is_kw_domain() or request.path.startswith("/static/"):
        return None
    if request.path.startswith("/kwsnyderwriting"):
        return None
    if request.path == "/":
        return redirect(url_for("kwsnyderwriting_membership"))
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
    posts = conn.execute("""
        SELECT * FROM published_posts
        WHERE category = ? AND access_level = 'public'
        ORDER BY id DESC
    """, (category,)).fetchall()
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
            session["member_logged_in"] = True
            session["member_id"] = member["id"]
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
    session.pop("member_logged_in", None)
    session.pop("member_id", None)
    return redirect(url_for("kwsnyderwriting_membership"))


@app.route("/kwsnyderwriting")
@member_required
def kwsnyderwriting():
    conn = get_db()
    posts = conn.execute("""
        SELECT * FROM published_posts
        WHERE category = 'kwsnyderwriting' AND access_level = 'members'
        ORDER BY id DESC
    """).fetchall()
    books = conn.execute("""
        SELECT b.*, COUNT(c.id) AS chapter_count
        FROM manuscript_books b
        LEFT JOIN manuscript_chapters c ON c.book_id = b.id AND c.published = 1
        GROUP BY b.id
        ORDER BY b.id DESC
    """).fetchall()
    conn.close()
    return render_template("blog_templates/kwsnyderwriting.html", posts=posts, books=books, member_logged_in=True)


@app.route("/kwsnyderwriting/post/<int:post_id>")
@member_required
def view_member_post(post_id):
    conn = get_db()
    post = conn.execute("SELECT * FROM published_posts WHERE id = ? AND category = 'kwsnyderwriting' AND access_level = 'members'", (post_id,)).fetchone()
    conn.close()
    if not post:
        abort(404)
    return render_template("post.html", post=post, back_url=url_for("kwsnyderwriting"))


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


@app.route("/store")
def the_scriptorium():
    return render_template("store.html")


@app.route("/merch")
def merch_shop():
    return render_template("merch.html")


@app.route("/admin")
def admin_dashboard():
    # Never expose the control panel to an unauthenticated request.
    if not require_admin():
        session.pop("admin_logged_in", None)
        session.pop("admin_auth_version", None)
        return render_template("admin.html", logged_in=False)
    return render_template("admin.html", logged_in=True)


@app.route("/admin/login", methods=["POST"])
def admin_login():
    password = request.form.get("password", "")
    configured_password = os.environ.get("ADMIN_PASSWORD", "")
    configured_password = configured_password.strip()

    if not configured_password:
        return render_template(
            "admin.html",
            logged_in=False,
            login_error="Admin password is not configured on the server."
        )

    if password == configured_password:
        session.clear()
        session.permanent = False
        session["admin_logged_in"] = True
        session["admin_auth_version"] = ADMIN_AUTH_VERSION
        return redirect(url_for("admin_dashboard"))

    return render_template(
        "admin.html",
        logged_in=False,
        login_error="The admin password was not recognized."
    )


@app.route("/admin/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("admin_dashboard"))


@app.route("/api/analytics", methods=["GET"])
@admin_required
def get_analytics():
    from datetime import timedelta, timezone

    period = request.args.get("period", "30")
    now = datetime.now(timezone.utc)
    if period == "all":
        start = None
    else:
        try:
            days = max(1, min(int(period), 3650))
        except (TypeError, ValueError):
            days = 30
        start = now - timedelta(days=days)

    conn = get_db()
    if start is None:
        total = conn.execute("SELECT COUNT(*) AS count FROM page_views").fetchone()["count"]
        daily = conn.execute("SELECT DATE(viewed_at) AS day, COUNT(*) AS views FROM page_views GROUP BY DATE(viewed_at) ORDER BY day").fetchall()
        categories = conn.execute("SELECT category, COUNT(*) AS views FROM page_views WHERE category IS NOT NULL GROUP BY category ORDER BY views DESC").fetchall()
        posts = conn.execute("""SELECT pv.path, pv.content_id, pv.category, COALESCE(pp.title, pv.path) AS title, COUNT(*) AS views
            FROM page_views pv LEFT JOIN published_posts pp ON pp.id = pv.content_id
            WHERE pv.page_type IN ('post', 'member_post', 'chapter', 'novel')
            GROUP BY pv.path, pv.content_id, pv.category, pp.title ORDER BY views DESC""").fetchall()
    else:
        stamp = start.isoformat()
        total = conn.execute("SELECT COUNT(*) AS count FROM page_views WHERE viewed_at >= ?", (stamp,)).fetchone()["count"]
        daily = conn.execute("SELECT DATE(viewed_at) AS day, COUNT(*) AS views FROM page_views WHERE viewed_at >= ? GROUP BY DATE(viewed_at) ORDER BY day", (stamp,)).fetchall()
        categories = conn.execute("SELECT category, COUNT(*) AS views FROM page_views WHERE category IS NOT NULL AND viewed_at >= ? GROUP BY category ORDER BY views DESC", (stamp,)).fetchall()
        posts = conn.execute("""SELECT pv.path, pv.content_id, pv.category, COALESCE(pp.title, pv.path) AS title, COUNT(*) AS views
            FROM page_views pv LEFT JOIN published_posts pp ON pp.id = pv.content_id
            WHERE pv.viewed_at >= ? AND pv.page_type IN ('post', 'member_post', 'chapter', 'novel')
            GROUP BY pv.path, pv.content_id, pv.category, pp.title ORDER BY views DESC""", (stamp,)).fetchall()
    conn.close()

    return jsonify({
        "period": period,
        "total_views": total,
        "daily": [dict(row) for row in daily],
        "categories": [dict(row) for row in categories],
        "posts": [dict(row) for row in posts],
    })


@app.route("/api/drafts", methods=["GET"])
@admin_required
def get_drafts():
    conn = get_db()
    rows = conn.execute("SELECT id, title, category, content, date_created AS date FROM drafts ORDER BY id DESC").fetchall()
    conn.close()
    return jsonify([dict(row) for row in rows])


@app.route("/api/drafts", methods=["POST"])
@admin_required
def create_draft():
    data = request.get_json() or {}
    title = str(data.get("title", "Untitled Draft")).strip() or "Untitled Draft"
    category = str(data.get("category", "curations")).strip()
    content = str(data.get("content", ""))
    date_created = str(data.get("date", "")).strip() or now_string()
    conn = get_db()
    cur = conn.execute("INSERT INTO drafts(title, category, content, date_created) VALUES (?, ?, ?, ?)", (title, category, content, date_created))
    conn.commit()
    draft_id = cur.lastrowid
    conn.close()
    return jsonify({"success": True, "id": draft_id}), 201


@app.route("/api/drafts/<int:draft_id>", methods=["GET"])
@admin_required
def get_draft(draft_id):
    conn = get_db()
    row = conn.execute("SELECT id, title, category, content, date_created AS date FROM drafts WHERE id = ?", (draft_id,)).fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "Draft not found"}), 404
    return jsonify(dict(row))


@app.route("/api/drafts/<int:draft_id>", methods=["PUT"])
@admin_required
def update_draft(draft_id):
    data = request.get_json() or {}
    conn = get_db()
    row = conn.execute("SELECT id FROM drafts WHERE id = ?", (draft_id,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Draft not found"}), 404
    conn.execute("UPDATE drafts SET title = ?, category = ?, content = ? WHERE id = ?", (str(data.get("title", "Untitled Draft")).strip() or "Untitled Draft", str(data.get("category", "curations")), str(data.get("content", "")), draft_id))
    conn.commit()
    conn.close()
    return jsonify({"success": True})


@app.route("/api/drafts/<int:draft_id>", methods=["DELETE"])
@admin_required
def delete_draft(draft_id):
    conn = get_db()
    cur = conn.execute("DELETE FROM drafts WHERE id = ?", (draft_id,))
    conn.commit()
    conn.close()
    if cur.rowcount == 0:
        return jsonify({"error": "Draft not found"}), 404
    return jsonify({"success": True})


@app.route("/api/published", methods=["GET"])
@admin_required
def get_published_posts():
    conn = get_db()
    rows = conn.execute("SELECT id, title, category, category_name AS categoryName, content, date_published AS date, access_level AS accessLevel FROM published_posts ORDER BY id DESC").fetchall()
    conn.close()
    return jsonify([dict(row) for row in rows])


@app.route("/api/published", methods=["POST"])
@admin_required
def create_published_post():
    data = request.get_json() or {}
    title = str(data.get("title", "")).strip()
    category = str(data.get("category", "")).strip()
    content = str(data.get("content", ""))
    access = str(data.get("accessLevel", "public"))
    if not title or not content.strip():
        return jsonify({"error": "A title and content are required."}), 400
    if category == "kwsnyderwriting":
        access = "members"
    if access not in {"public", "members"}:
        access = "public"
    conn = get_db()
    cur = conn.execute("INSERT INTO published_posts(title, category, category_name, content, date_published, access_level) VALUES (?, ?, ?, ?, ?, ?)", (title, category, category_label(category), content, str(data.get("date", "")).strip() or now_string(), access))
    conn.commit()
    post_id = cur.lastrowid
    conn.close()
    return jsonify({"success": True, "id": post_id, "access_level": access}), 201


@app.route("/api/published/<int:post_id>", methods=["GET"])
@admin_required
def get_published_post(post_id):
    conn = get_db()
    row = conn.execute("SELECT id, title, category, category_name AS categoryName, content, date_published AS date, access_level AS accessLevel FROM published_posts WHERE id = ?", (post_id,)).fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "Post not found"}), 404
    return jsonify(dict(row))


@app.route("/api/published/<int:post_id>", methods=["PUT"])
@admin_required
def update_published_post(post_id):
    data = request.get_json() or {}
    title = str(data.get("title", "")).strip()
    category = str(data.get("category", "")).strip()
    content = str(data.get("content", ""))
    access = str(data.get("accessLevel", "public"))
    if not title or not content.strip():
        return jsonify({"error": "A title and content are required."}), 400
    if category == "kwsnyderwriting":
        access = "members"
    if access not in {"public", "members"}:
        access = "public"
    conn = get_db()
    row = conn.execute("SELECT id FROM published_posts WHERE id = ?", (post_id,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Post not found"}), 404
    conn.execute("UPDATE published_posts SET title = ?, category = ?, category_name = ?, content = ?, access_level = ? WHERE id = ?", (title, category, category_label(category), content, access, post_id))
    conn.commit()
    conn.close()
    return jsonify({"success": True})


@app.route("/api/published/<int:post_id>", methods=["DELETE"])
@admin_required
def delete_published_post(post_id):
    conn = get_db()
    cur = conn.execute("DELETE FROM published_posts WHERE id = ?", (post_id,))
    conn.commit()
    conn.close()
    if cur.rowcount == 0:
        return jsonify({"error": "Published post not found"}), 404
    return jsonify({"success": True})


@app.route("/api/published/<int:post_id>/unpublish", methods=["POST"])
@admin_required
def unpublish_post(post_id):
    conn = get_db()
    row = conn.execute("SELECT title, category, content, date_published FROM published_posts WHERE id = ?", (post_id,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Published post not found"}), 404
    conn.execute("INSERT INTO drafts(title, category, content, date_created) VALUES (?, ?, ?, ?)", (row["title"], row["category"], row["content"], row["date_published"]))
    conn.execute("DELETE FROM published_posts WHERE id = ?", (post_id,))
    conn.commit()
    conn.close()
    return jsonify({"success": True})


@app.route("/api/manuscripts", methods=["GET"])
@admin_required
def get_manuscripts():
    conn = get_db()
    books = conn.execute("""
        SELECT b.id, b.title, b.description,
               COUNT(c.id) AS chapter_count,
               SUM(CASE WHEN c.published = 1 THEN 1 ELSE 0 END) AS published_chapter_count
        FROM manuscript_books b
        LEFT JOIN manuscript_chapters c ON c.book_id = b.id
        GROUP BY b.id
        ORDER BY b.id DESC
    """).fetchall()
    conn.close()
    return jsonify({"books": [dict(row) for row in books]})


@app.route("/api/manuscripts", methods=["POST"])
@admin_required
def create_manuscript():
    data = request.get_json() or {}
    title = str(data.get("title", "")).strip()
    description = str(data.get("description", ""))
    if not title:
        return jsonify({"error": "A title is required."}), 400
    conn = get_db()
    cur = conn.execute("INSERT INTO manuscript_books(title, description, date_created) VALUES (?, ?, ?)", (title, description, now_string()))
    conn.commit()
    book_id = cur.lastrowid
    conn.close()
    return jsonify({"success": True, "id": book_id}), 201


@app.route("/api/manuscripts/<int:book_id>", methods=["GET"])
@admin_required
def get_manuscript(book_id):
    conn = get_db()
    book = conn.execute("SELECT * FROM manuscript_books WHERE id = ?", (book_id,)).fetchone()
    chapters = conn.execute("SELECT * FROM manuscript_chapters WHERE book_id = ? ORDER BY chapter_number", (book_id,)).fetchall()
    conn.close()
    if not book:
        return jsonify({"error": "Book not found"}), 404
    return jsonify({"book": dict(book), "chapters": [dict(row) for row in chapters]})


@app.route("/api/manuscripts/<int:book_id>", methods=["PUT"])
@admin_required
def update_manuscript(book_id):
    data = request.get_json() or {}
    conn = get_db()
    row = conn.execute("SELECT id FROM manuscript_books WHERE id = ?", (book_id,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Book not found"}), 404
    conn.execute("UPDATE manuscript_books SET title = ?, description = ? WHERE id = ?", (str(data.get("title", "")).strip(), str(data.get("description", "")), book_id))
    conn.commit()
    conn.close()
    return jsonify({"success": True})


@app.route("/api/manuscripts/<int:book_id>", methods=["DELETE"])
@admin_required
def delete_manuscript(book_id):
    conn = get_db()
    row = conn.execute("SELECT id FROM manuscript_books WHERE id = ?", (book_id,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Book not found"}), 404
    conn.execute("DELETE FROM manuscript_chapters WHERE book_id = ?", (book_id,))
    conn.execute("DELETE FROM manuscript_books WHERE id = ?", (book_id,))
    conn.commit()
    conn.close()
    return jsonify({"success": True})


@app.route("/api/manuscripts/<int:book_id>/chapters", methods=["POST"])
@admin_required
def create_chapter(book_id):
    data = request.get_json() or {}
    chapter_number = int(data.get("chapter_number", 0))
    title = str(data.get("title", "Untitled Chapter")).strip() or "Untitled Chapter"
    content = str(data.get("content", ""))
    published = 1 if data.get("published") else 0
    conn = get_db()
    book = conn.execute("SELECT id FROM manuscript_books WHERE id = ?", (book_id,)).fetchone()
    if not book:
        conn.close()
        return jsonify({"error": "Book not found"}), 404
    cur = conn.execute("INSERT INTO manuscript_chapters(book_id, chapter_number, title, content, published, date_created) VALUES (?, ?, ?, ?, ?, ?)", (book_id, chapter_number, title, content, published, now_string()))
    conn.commit()
    chapter_id = cur.lastrowid
    conn.close()
    return jsonify({"success": True, "id": chapter_id}), 201


@app.route("/api/manuscripts/<int:book_id>/chapters/<int:chapter_id>", methods=["GET"])
@admin_required
def get_chapter(book_id, chapter_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM manuscript_chapters WHERE id = ? AND book_id = ?", (chapter_id, book_id)).fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "Chapter not found"}), 404
    return jsonify(dict(row))


@app.route("/api/manuscripts/<int:book_id>/chapters/<int:chapter_id>", methods=["PUT"])
@admin_required
def update_chapter(book_id, chapter_id):
    data = request.get_json() or {}
    conn = get_db()
    row = conn.execute("SELECT id FROM manuscript_chapters WHERE id = ? AND book_id = ?", (chapter_id, book_id)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Chapter not found"}), 404
    conn.execute("UPDATE manuscript_chapters SET chapter_number = ?, title = ?, content = ?, published = ? WHERE id = ? AND book_id = ?", (int(data.get("chapter_number", 0)), str(data.get("title", "Untitled Chapter")).strip() or "Untitled Chapter", str(data.get("content", "")), 1 if data.get("published") else 0, chapter_id, book_id))
    conn.commit()
    conn.close()
    return jsonify({"success": True})


@app.route("/api/manuscripts/<int:book_id>/chapters/<int:chapter_id>", methods=["DELETE"])
@admin_required
def delete_chapter(book_id, chapter_id):
    conn = get_db()
    cur = conn.execute("DELETE FROM manuscript_chapters WHERE id = ? AND book_id = ?", (chapter_id, book_id))
    conn.commit()
    conn.close()
    if cur.rowcount == 0:
        return jsonify({"error": "Chapter not found"}), 404
    return jsonify({"success": True})


@app.route("/api/about", methods=["GET"])
@admin_required
def get_about_content():
    conn = get_db()
    row = conn.execute("SELECT value FROM site_content WHERE key = 'about_content'").fetchone()
    conn.close()
    return jsonify({"content": row["value"] if row else ""})


@app.route("/api/about", methods=["PUT"])
@admin_required
def update_about_content():
    data = request.get_json() or {}
    content = str(data.get("content", ""))
    conn = get_db()
    row = conn.execute("SELECT key FROM site_content WHERE key = 'about_content'").fetchone()
    if row:
        conn.execute("UPDATE site_content SET value = ? WHERE key = 'about_content'", (content,))
    else:
        conn.execute("INSERT INTO site_content(key, value) VALUES ('about_content', ?)", (content,))
    conn.commit()
    conn.close()
    return jsonify({"success": True})


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
