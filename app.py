import os
import sqlite3
from flask import Flask, render_template, request, redirect, url_for, session, jsonify

# Find the exact folder where app.py lives
basedir = os.path.abspath(os.path.dirname(__file__))

# Database location
DATABASE = os.path.join(basedir, "scriptorium.db")

# Explicitly point Flask to your templates folder
app = Flask(
    __name__,
    template_folder=os.path.join(basedir, "templates")
)

app.secret_key = os.environ.get(
    "SECRET_KEY",
    "snyder-scriptorium-development-key"
)


# ============================================================
# DATABASE HELPERS
# ============================================================

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS drafts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            category TEXT NOT NULL,
            content TEXT NOT NULL,
            date_created TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS published_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            category TEXT NOT NULL,
            category_name TEXT NOT NULL,
            content TEXT NOT NULL,
            date_published TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS manuscripts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            date_created TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()


# ============================================================
# MAIN WEBSITE ROUTES
# ============================================================

@app.route("/")
def the_hearth():
    return render_template("index.html")


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/blog")
def the_blog():
    return render_template("blog_templates/theblog.html")


@app.route("/blog/bookcurations")
def book_curations():
    return render_template("blog_templates/book_curations.html")


@app.route("/blog/bookreviews")
def bookreviews():
    return render_template("blog_templates/bookreviews.html")


@app.route("/blog/curiosity_cabinet")
def curiosity_cabinet():
    return render_template("blog_templates/curiosity_cabinet.html")


@app.route("/kwsnyderwriting")
def kwsnyderwriting():
    return render_template("kwsnyderwriting.html")


@app.route("/store")
def the_scriptorium():
    return render_template("store.html")


@app.route("/merch")
def merch_shop():
    return render_template("merch.html")


# ============================================================
# ADMIN AUTHENTICATION
# ============================================================

@app.route("/admin")
def admin_dashboard():
    logged_in = session.get("admin_logged_in", False)
    return render_template("admin.html", logged_in=logged_in)


@app.route("/admin/login", methods=["POST"])
def admin_login():
    password = request.form.get("password", "")

    if password == "scriptorium123":
        session["admin_logged_in"] = True
        return redirect(url_for("admin_dashboard"))

    return redirect(url_for("admin_dashboard"))


@app.route("/admin/logout")
def admin_logout():
    session.pop("admin_logged_in", None)
    return redirect(url_for("admin_dashboard"))


# ============================================================
# BACKEND STORAGE API
# ============================================================

def require_admin():
    return session.get("admin_logged_in", False)


# ----------------------------
# BLOG DRAFTS
# ----------------------------

@app.route("/api/drafts", methods=["GET"])
def get_drafts():
    if not require_admin():
        return jsonify({"error": "Unauthorized"}), 401

    conn = get_db()
    drafts = conn.execute(
        "SELECT * FROM drafts ORDER BY id DESC"
    ).fetchall()
    conn.close()

    return jsonify([dict(draft) for draft in drafts])


@app.route("/api/drafts", methods=["POST"])
def create_draft():
    if not require_admin():
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json() or {}

    title = data.get("title", "Untitled Draft")
    category = data.get("category", "")
    content = data.get("content", "")
    date_created = data.get("date", "")

    if not date_created:
        from datetime import datetime
        date_created = datetime.now().strftime("%m/%d/%Y")

    conn = get_db()

    cursor = conn.execute(
        """
        INSERT INTO drafts
        (title, category, content, date_created)
        VALUES (?, ?, ?, ?)
        """,
        (title, category, content, date_created)
    )

    conn.commit()

    draft_id = cursor.lastrowid
    conn.close()

    return jsonify({
        "success": True,
        "id": draft_id
    }), 201


@app.route("/api/drafts/<int:draft_id>", methods=["GET"])
def get_draft(draft_id):
    if not require_admin():
        return jsonify({"error": "Unauthorized"}), 401

    conn = get_db()

    draft = conn.execute(
        "SELECT * FROM drafts WHERE id = ?",
        (draft_id,)
    ).fetchone()

    conn.close()

    if draft is None:
        return jsonify({"error": "Draft not found"}), 404

    return jsonify(dict(draft))


@app.route("/api/drafts/<int:draft_id>", methods=["DELETE"])
def delete_draft(draft_id):
    if not require_admin():
        return jsonify({"error": "Unauthorized"}), 401

    conn = get_db()

    conn.execute(
        "DELETE FROM drafts WHERE id = ?",
        (draft_id,)
    )

    conn.commit()
    conn.close()

    return jsonify({"success": True})


# ----------------------------
# PUBLISHED POSTS
# ----------------------------

@app.route("/api/published", methods=["GET"])
def get_published_posts():
    if not require_admin():
        return jsonify({"error": "Unauthorized"}), 401

    conn = get_db()

    posts = conn.execute(
        "SELECT * FROM published_posts ORDER BY id DESC"
    ).fetchall()

    conn.close()

    return jsonify([dict(post) for post in posts])


@app.route("/api/published", methods=["POST"])
def create_published_post():
    if not require_admin():
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json() or {}

    title = data.get("title", "")
    category = data.get("category", "")
    category_name = data.get("categoryName", "Journal")
    content = data.get("content", "")
    date_published = data.get("date", "")

    if not title:
        return jsonify({"error": "Post title is required"}), 400

    if not date_published:
        from datetime import datetime
        date_published = datetime.now().strftime("%m/%d/%Y")

    conn = get_db()

    cursor = conn.execute(
        """
        INSERT INTO published_posts
        (title, category, category_name, content, date_published)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            title,
            category,
            category_name,
            content,
            date_published
        )
    )

    conn.commit()

    post_id = cursor.lastrowid
    conn.close()

    return jsonify({
        "success": True,
        "id": post_id
    }), 201


@app.route("/api/published/<int:post_id>", methods=["DELETE"])
def delete_published_post(post_id):
    if not require_admin():
        return jsonify({"error": "Unauthorized"}), 401

    conn = get_db()

    post = conn.execute(
        "SELECT * FROM published_posts WHERE id = ?",
        (post_id,)
    ).fetchone()

    if post is None:
        conn.close()
        return jsonify({"error": "Post not found"}), 404

    conn.execute(
        "DELETE FROM published_posts WHERE id = ?",
        (post_id,)
    )

    conn.commit()
    conn.close()

    return jsonify({
        "success": True
    })


# ----------------------------
# MANUSCRIPTS
# ----------------------------

@app.route("/api/manuscripts", methods=["GET"])
def get_manuscripts():
    if not require_admin():
        return jsonify({"error": "Unauthorized"}), 401

    conn = get_db()

    manuscripts = conn.execute(
        "SELECT * FROM manuscripts ORDER BY id DESC"
    ).fetchall()

    conn.close()

    return jsonify([dict(book) for book in manuscripts])


@app.route("/api/manuscripts", methods=["POST"])
def create_manuscript():
    if not require_admin():
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json() or {}

    title = data.get(
        "title",
        "Untitled Book or Document"
    )

    content = data.get("content", "")
    date_created = data.get("date", "")

    if not date_created:
        from datetime import datetime
        date_created = datetime.now().strftime("%m/%d/%Y")

    conn = get_db()

    cursor = conn.execute(
        """
        INSERT INTO manuscripts
        (title, content, date_created)
        VALUES (?, ?, ?)
        """,
        (
            title,
            content,
            date_created
        )
    )

    conn.commit()

    manuscript_id = cursor.lastrowid
    conn.close()

    return jsonify({
        "success": True,
        "id": manuscript_id
    }), 201


@app.route("/api/manuscripts/<int:manuscript_id>", methods=["GET"])
def get_manuscript(manuscript_id):
    if not require_admin():
        return jsonify({"error": "Unauthorized"}), 401

    conn = get_db()

    manuscript = conn.execute(
        "SELECT * FROM manuscripts WHERE id = ?",
        (manuscript_id,)
    ).fetchone()

    conn.close()

    if manuscript is None:
        return jsonify({
            "error": "Manuscript not found"
        }), 404

    return jsonify(dict(manuscript))


@app.route("/api/manuscripts/<int:manuscript_id>", methods=["DELETE"])
def delete_manuscript(manuscript_id):
    if not require_admin():
        return jsonify({"error": "Unauthorized"}), 401

    conn = get_db()

    conn.execute(
        "DELETE FROM manuscripts WHERE id = ?",
        (manuscript_id,)
    )

    conn.commit()
    conn.close()

    return jsonify({
        "success": True
    })


# ============================================================
# STARTUP
# ============================================================

init_db()


if __name__ == "__main__":
    app.run(debug=True)
