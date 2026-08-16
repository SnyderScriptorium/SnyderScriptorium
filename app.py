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
    if not require_admin():
        return redirect(url_for("admin_login_page"))
    return render_template("admin.html", logged_in=True)


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login_page():
    if request.method == "GET":
        if require_admin():
            return redirect(url_for("admin_dashboard"))
        return render_template("admin_login.html")

    password = request.form.get("password", "")
    configured_password = os.environ.get("ADMIN_PASSWORD", "").strip()
    if not configured_password:
        return render_template("admin_login.html", login_error="Admin password is not configured on the server.")
    if password == configured_password:
        session.clear()
        session.permanent = False
        session["admin_logged_in"] = True
        session["admin_auth_version"] = ADMIN_AUTH_VERSION
        return redirect(url_for("admin_dashboard"))
    return render_template("admin_login.html", login_error="The admin password was not recognized.")


@app.route("/admin/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("admin_login_page"))


@app.route("/admin/inbox")
@admin_required
def admin_inbox():
    return render_template("admin_inbox.html")


@app.route("/api/inbox", methods=["GET"])
@admin_required
def get_inbox():
    status = request.args.get("status", "").strip()
    conn = get_db()
    rows = conn.execute("SELECT * FROM inbox_messages WHERE status = ? ORDER BY id DESC", (status,)).fetchall() if status else conn.execute("SELECT * FROM inbox_messages ORDER BY id DESC").fetchall()
    conn.close()
    return jsonify([dict(row) for row in rows])


@app.route("/api/inbox/<int:message_id>", methods=["PATCH"])
@admin_required
def update_inbox_message(message_id):
    data = request.get_json() or {}
    status = str(data.get("status", "")).strip()
    allowed = {"new", "open", "in_progress", "resolved", "archived"}
    conn = get_db()
    row = conn.execute("SELECT id FROM inbox_messages WHERE id = ?", (message_id,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Inbox message not found."}), 404
    if status and status not in allowed:
        conn.close()
        return jsonify({"error": "Invalid inbox status."}), 400
    if status:
        conn.execute("UPDATE inbox_messages SET status = ?, is_read = 1 WHERE id = ?", (status, message_id))
    else:
        conn.execute("UPDATE inbox_messages SET is_read = 1 WHERE id = ?", (message_id,))
    conn.commit()
    conn.close()
    return jsonify({"success": True})


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
    conn.execute("UPDATE drafts SET title = ?, category = ?, content = ?, date_created = ? WHERE id = ?", (str(data.get("title", "Untitled Draft")).strip() or "Untitled Draft", str(data.get("category", "curations")).strip(), str(data.get("content", "")), str(data.get("date", "")).strip() or now_string(), draft_id))
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
def get_published():
    conn = get_db()
    rows = conn.execute("SELECT id, title, category, category_name, content, date_published AS date, access_level FROM published_posts ORDER BY id DESC").fetchall()
    conn.close()
    return jsonify([dict(row) for row in rows])


@app.route("/api/published", methods=["POST"])
@admin_required
def create_published():
    data = request.get_json() or {}
    title = str(data.get("title", "Untitled Post")).strip() or "Untitled Post"
    category = str(data.get("category", "curations")).strip()
    content = str(data.get("content", ""))
    date_published = str(data.get("date", "")).strip() or now_string()
    access = "members" if category in {"kwsnyderwriting", "kw_short_stories", "kw_poems", "kw_vignettes"} else "public"
    conn = get_db()
    cur = conn.execute("INSERT INTO published_posts(title, category, category_name, content, date_published, access_level) VALUES (?, ?, ?, ?, ?, ?)", (title, category, category_label(category), content, date_published, access))
    conn.commit()
    post_id = cur.lastrowid
    conn.close()
    return jsonify({"success": True, "id": post_id}), 201


@app.route("/api/published/<int:post_id>", methods=["GET"])
@admin_required
def get_published_post(post_id):
    conn = get_db()
    row = conn.execute("SELECT id, title, category, category_name, content, date_published AS date, access_level FROM published_posts WHERE id = ?", (post_id,)).fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "Published post not found"}), 404
    return jsonify(dict(row))


@app.route("/api/published/<int:post_id>", methods=["PUT"])
@admin_required
def update_published_post(post_id):
    data = request.get_json() or {}
    title = str(data.get("title", "Untitled Post")).strip() or "Untitled Post"
    category = str(data.get("category", "curations")).strip()
    content = str(data.get("content", ""))
    access = "members" if category in {"kwsnyderwriting", "kw_short_stories", "kw_poems", "kw_vignettes"} else "public"
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
    books = conn.execute("SELECT b.id, b.title, b.description, COUNT(c.id) AS chapter_count, SUM(CASE WHEN c.published = 1 THEN 1 ELSE 0 END) AS published_chapter_count FROM manuscript_books b LEFT JOIN manuscript_chapters c ON c.book_id = b.id GROUP BY b.id ORDER BY b.id DESC").fetchall()
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
    cur = conn.execute("INSERT INTO manuscript_books(title, description, date_created, updated_at) VALUES (?, ?, ?, ?)", (title, description, now_string(), now_string()))
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
    conn.execute("UPDATE manuscript_books SET title = ?, description = ?, updated_at = ? WHERE id = ?", (str(data.get("title", "")).strip(), str(data.get("description", "")), now_string(), book_id))
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
    cur = conn.execute("INSERT INTO manuscript_chapters(book_id, chapter_number, title, content, published, date_created, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)", (book_id, chapter_number, title, content, published, now_string(), now_string()))
    conn.commit()
    chapter_id = cur.lastrowid
    conn.close()
    return jsonify({"success": True, "id": chapter_id}), 201


@app.route("/api/manuscripts/<int:book_id>/chapters/<int:chapter_id>")
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
    conn.execute("UPDATE manuscript_chapters SET chapter_number = ?, title = ?, content = ?, published = ?, updated_at = ? WHERE id = ? AND book_id = ?", (int(data.get("chapter_number", 0)), str(data.get("title", "Untitled Chapter")).strip() or "Untitled Chapter", str(data.get("content", "")), 1 if data.get("published") else 0, now_string(), chapter_id, book_id))
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
        conn.execute("INSERT INTO site_content(key, value, updated_at) VALUES ('about_content', ?, ?)", (content, now_string()))
    conn.commit()
    conn.close()
    return jsonify({"success": True})


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
