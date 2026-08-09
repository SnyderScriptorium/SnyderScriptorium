import os
import sqlite3
from datetime import datetime
from functools import wraps

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    jsonify,
)

from werkzeug.security import check_password_hash


# ============================================================
# APPLICATION SETUP
# ============================================================

basedir = os.path.abspath(os.path.dirname(__file__))

DATABASE = os.path.join(basedir, "scriptorium.db")

app = Flask(
    __name__,
    template_folder=os.path.join(basedir, "templates"),
)

# IMPORTANT:
# Set SECRET_KEY in Render Environment Variables for production.
app.secret_key = os.environ.get(
    "SECRET_KEY",
    "snyder-scriptorium-development-key",
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

    # --------------------------------------------------------
    # DRAFTS
    # --------------------------------------------------------
    conn.execute("""
        CREATE TABLE IF NOT EXISTS drafts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            category TEXT NOT NULL,
            content TEXT NOT NULL,
            date_created TEXT NOT NULL
        )
    """)

    # --------------------------------------------------------
    # PUBLISHED POSTS
    # --------------------------------------------------------
    conn.execute("""
        CREATE TABLE IF NOT EXISTS published_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            category TEXT NOT NULL,
            category_name TEXT NOT NULL,
            content TEXT NOT NULL,
            date_published TEXT NOT NULL,
            access_level TEXT NOT NULL DEFAULT 'public'
        )
    """)

    # --------------------------------------------------------
    # MANUSCRIPTS
    # --------------------------------------------------------
    conn.execute("""
        CREATE TABLE IF NOT EXISTS manuscripts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            date_created TEXT NOT NULL
        )
    """)

    # --------------------------------------------------------
    # MEMBERS
    #
    # This is for the future K. W. Snyder membership system.
    #
    # IMPORTANT:
    # subscription_status is NOT automatically made active.
    # A future payment provider will control membership status.
    # --------------------------------------------------------
    conn.execute("""
        CREATE TABLE IF NOT EXISTS members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            subscription_status TEXT NOT NULL DEFAULT 'inactive',
            date_created TEXT NOT NULL
        )
    """)

    # --------------------------------------------------------
    # SUBSCRIPTIONS
    #
    # Prepared for a future payment provider.
    # --------------------------------------------------------
    conn.execute("""
        CREATE TABLE IF NOT EXISTS subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            member_id INTEGER NOT NULL,
            provider TEXT,
            subscription_id TEXT,
            status TEXT NOT NULL DEFAULT 'inactive',
            date_started TEXT,
            date_ends TEXT,
            FOREIGN KEY (member_id) REFERENCES members(id)
        )
    """)

    conn.commit()

    # ========================================================
    # SAFE DATABASE MIGRATIONS
    # ========================================================

    # Check published_posts columns.
    columns = conn.execute(
        "PRAGMA table_info(published_posts)"
    ).fetchall()

    column_names = [column["name"] for column in columns]

    if "access_level" not in column_names:
        conn.execute("""
            ALTER TABLE published_posts
            ADD COLUMN access_level TEXT NOT NULL DEFAULT 'public'
        """)

        conn.commit()

    conn.close()


# ============================================================
# AUTHENTICATION HELPERS
# ============================================================

def require_admin():
    return session.get("admin_logged_in", False)


def require_member():
    return session.get("member_logged_in", False)


def member_has_access():
    """
    A member must have both:
        1. A valid member login session.
        2. An active subscription in the database.

    This prevents simply visiting the private URL from granting
    access.
    """

    if not require_member():
        return False

    member_id = session.get("member_id")

    if not member_id:
        return False

    conn = get_db()

    member = conn.execute(
        """
        SELECT subscription_status
        FROM members
        WHERE id = ?
        """,
        (member_id,),
    ).fetchone()

    conn.close()

    if member is None:
        return False

    return member["subscription_status"] == "active"


def admin_required(view_function):
    @wraps(view_function)
    def wrapped_view(*args, **kwargs):

        if not require_admin():
            return redirect(url_for("admin_dashboard"))

        return view_function(*args, **kwargs)

    return wrapped_view


# ============================================================
# K. W. SNYDER DOMAIN DETECTION
# ============================================================

def is_kw_domain():
    """
    Allows the future K. W. Snyder domain to point directly
    into the private branch.

    The actual domain should eventually be placed in Render
    as:

        KWSNYDER_DOMAIN=your-domain.com

    Until that environment variable exists, the normal
    Snyder Scriptorium domain continues to operate normally.
    """

    configured_domain = os.environ.get(
        "KWSNYDER_DOMAIN",
        ""
    ).strip().lower()

    if not configured_domain:
        return False

    host = request.host.split(":")[0].lower()

    return host == configured_domain or host == f"www.{configured_domain}"


@app.before_request
def route_kw_domain():
    """
    If the future K. W. Snyder domain is being visited directly,
    send the visitor into the K. W. Snyder membership entrance.

    The normal Snyder Scriptorium domain is unaffected.
    """

    if not is_kw_domain():
        return None

    # Allow static files.
    if request.path.startswith("/static/"):
        return None

    # Allow the K. W. Snyder branch itself.
    if request.path.startswith("/kwsnyderwriting"):
        return None

    # Send the domain root to the member entrance.
    if request.path == "/":
        return redirect(url_for("kwsnyderwriting_membership"))

    return None


# ============================================================
# MAIN WEBSITE ROUTES
# ============================================================

@app.route("/")
def the_hearth():
    return render_template("index.html")


@app.route("/about")
def about():
    return render_template("about.html")


# ============================================================
# PUBLIC BLOG
# ============================================================

@app.route("/blog")
def the_blog():
    return render_template(
        "blog_templates/theblog.html"
    )


# ------------------------------------------------------------
# BOOK CURATIONS
# ------------------------------------------------------------

@app.route("/blog/bookcurations")
def book_curations():

    conn = get_db()

    posts = conn.execute(
        """
        SELECT *
        FROM published_posts
        WHERE category = ?
        AND access_level = 'public'
        ORDER BY id DESC
        """,
        ("curations",),
    ).fetchall()

    conn.close()

    return render_template(
        "blog_templates/book_curations.html",
        posts=posts,
    )


# ------------------------------------------------------------
# BOOK REVIEWS
# ------------------------------------------------------------

@app.route("/blog/bookreviews")
def bookreviews():

    conn = get_db()

    posts = conn.execute(
        """
        SELECT *
        FROM published_posts
        WHERE category = ?
        AND access_level = 'public'
        ORDER BY id DESC
        """,
        ("reviews",),
    ).fetchall()

    conn.close()

    return render_template(
        "blog_templates/bookreviews.html",
        posts=posts,
    )


# ------------------------------------------------------------
# CURIOSITY CABINET
# ------------------------------------------------------------

@app.route("/blog/curiosity_cabinet")
def curiosity_cabinet():

    conn = get_db()

    posts = conn.execute(
        """
        SELECT *
        FROM published_posts
        WHERE category = ?
        AND access_level = 'public'
        ORDER BY id DESC
        """,
        ("curiosity",),
    ).fetchall()

    conn.close()

    return render_template(
        "blog_templates/curiosity_cabinet.html",
        posts=posts,
    )


# ============================================================
# K. W. SNYDER WRITING
#
# PRIVATE MEMBER-ONLY BRANCH
# ============================================================

@app.route("/kwsnyderwriting")
def kwsnyderwriting():

    # --------------------------------------------------------
    # STEP 1:
    # Visitor must be logged in as a member.
    # --------------------------------------------------------

    if not require_member():
        return redirect(
            url_for("kwsnyderwriting_membership")
        )

    # --------------------------------------------------------
    # STEP 2:
    # Visitor must have an active subscription.
    # --------------------------------------------------------

    if not member_has_access():
        return redirect(
            url_for("kwsnyderwriting_membership")
        )

    # --------------------------------------------------------
    # STEP 3:
    # Only members-only K.W. Snyder posts are retrieved.
    # --------------------------------------------------------

    conn = get_db()

    posts = conn.execute(
        """
        SELECT *
        FROM published_posts
        WHERE category = ?
        AND access_level = 'members'
        ORDER BY id DESC
        """,
        ("kwsnyderwriting",),
    ).fetchall()

    conn.close()

    return render_template(
        "blog_templates/kwsnyderwriting.html",
        posts=posts,
    )


# ============================================================
# K. W. SNYDER MEMBERSHIP ENTRANCE
# ============================================================

@app.route("/kwsnyderwriting/membership")
def kwsnyderwriting_membership():

    return render_template(
        "blog_templates/kwsnyderwriting_membership.html"
    )


# ============================================================
# K. W. SNYDER MEMBER LOGIN
# ============================================================

@app.route(
    "/kwsnyderwriting/login",
    methods=["GET", "POST"]
)
def member_login():

    if request.method == "POST":

        email = request.form.get(
            "email",
            ""
        ).strip().lower()

        password = request.form.get(
            "password",
            ""
        )

        if not email or not password:
            return redirect(
                url_for(
                    "kwsnyderwriting_membership"
                )
            )

        conn = get_db()

        member = conn.execute(
            """
            SELECT *
            FROM members
            WHERE email = ?
            """,
            (email,),
        ).fetchone()

        conn.close()

        # ----------------------------------------------------
        # Check the stored password hash.
        # ----------------------------------------------------

        if member and check_password_hash(
            member["password_hash"],
            password
        ):

            session["member_logged_in"] = True
            session["member_id"] = member["id"]

            return redirect(
                url_for("kwsnyderwriting")
            )

        return redirect(
            url_for(
                "kwsnyderwriting_membership"
            )
        )

    return render_template(
        "blog_templates/kwsnyderwriting_login.html"
    )


# ============================================================
# K. W. SNYDER MEMBER LOGOUT
# ============================================================

@app.route("/kwsnyderwriting/logout")
def member_logout():

    session.pop(
        "member_logged_in",
        None
    )

    session.pop(
        "member_id",
        None
    )

    return redirect(
        url_for("kwsnyderwriting_membership")
    )


# ============================================================
# STORE
# ============================================================

@app.route("/store")
def the_scriptorium():
    return render_template(
        "store.html"
    )


@app.route("/merch")
def merch_shop():
    return render_template(
        "merch.html"
    )


# ============================================================
# ADMIN AUTHENTICATION
# ============================================================

@app.route("/admin")
def admin_dashboard():

    logged_in = require_admin()

    return render_template(
        "admin.html",
        logged_in=logged_in,
    )


@app.route(
    "/admin/login",
    methods=["POST"]
)
def admin_login():

    password = request.form.get(
        "password",
        ""
    )

    # IMPORTANT:
    # Set ADMIN_PASSWORD in Render Environment Variables.
    admin_password = os.environ.get(
        "ADMIN_PASSWORD",
        "scriptorium123",
    )

    if password == admin_password:

        session["admin_logged_in"] = True

        return redirect(
            url_for("admin_dashboard")
        )

    return redirect(
        url_for("admin_dashboard")
    )


@app.route("/admin/logout")
def admin_logout():

    session.pop(
        "admin_logged_in",
        None
    )

    return redirect(
        url_for("admin_dashboard")
    )


# ============================================================
# BLOG DRAFTS API
# ============================================================

@app.route(
    "/api/drafts",
    methods=["GET"]
)
def get_drafts():

    if not require_admin():
        return jsonify({
            "error": "Unauthorized"
        }), 401

    conn = get_db()

    drafts = conn.execute(
        """
        SELECT *
        FROM drafts
        ORDER BY id DESC
        """
    ).fetchall()

    conn.close()

    return jsonify([
        dict(draft)
        for draft in drafts
    ])


@app.route(
    "/api/drafts",
    methods=["POST"]
)
def create_draft():

    if not require_admin():
        return jsonify({
            "error": "Unauthorized"
        }), 401

    data = request.get_json() or {}

    title = data.get(
        "title",
        "Untitled Draft"
    )

    category = data.get(
        "category",
        ""
    )

    content = data.get(
        "content",
        ""
    )

    date_created = data.get(
        "date",
        ""
    )

    if not date_created:
        date_created = datetime.now().strftime(
            "%m/%d/%Y"
        )

    conn = get_db()

    cursor = conn.execute(
        """
        INSERT INTO drafts
        (
            title,
            category,
            content,
            date_created
        )
        VALUES (?, ?, ?, ?)
        """,
        (
            title,
            category,
            content,
            date_created,
        ),
    )

    conn.commit()

    draft_id = cursor.lastrowid

    conn.close()

    return jsonify({
        "success": True,
        "id": draft_id,
    }), 201


@app.route(
    "/api/drafts/<int:draft_id>",
    methods=["GET"]
)
def get_draft(draft_id):

    if not require_admin():
        return jsonify({
            "error": "Unauthorized"
        }), 401

    conn = get_db()

    draft = conn.execute(
        """
        SELECT *
        FROM drafts
        WHERE id = ?
        """,
        (draft_id,),
    ).fetchone()

    conn.close()

    if draft is None:
        return jsonify({
            "error": "Draft not found"
        }), 404

    return jsonify(
        dict(draft)
    )


@app.route(
    "/api/drafts/<int:draft_id>",
    methods=["DELETE"]
)
def delete_draft(draft_id):

    if not require_admin():
        return jsonify({
            "error": "Unauthorized"
        }), 401

    conn = get_db()

    conn.execute(
        """
        DELETE FROM drafts
        WHERE id = ?
        """,
        (draft_id,),
    )

    conn.commit()
    conn.close()

    return jsonify({
        "success": True
    })


# ============================================================
# PUBLISHED POSTS API
# ============================================================

@app.route(
    "/api/published",
    methods=["GET"]
)
def get_published_posts():

    if not require_admin():
        return jsonify({
            "error": "Unauthorized"
        }), 401

    conn = get_db()

    posts = conn.execute(
        """
        SELECT *
        FROM published_posts
        ORDER BY id DESC
        """
    ).fetchall()

    conn.close()

    return jsonify([
        dict(post)
        for post in posts
    ])


@app.route(
    "/api/published",
    methods=["POST"]
)
def create_published_post():

    if not require_admin():
        return jsonify({
            "error": "Unauthorized"
        }), 401

    data = request.get_json() or {}

    title = data.get(
        "title",
        ""
    )

    category = data.get(
        "category",
        ""
    )

    category_name = data.get(
        "categoryName",
        "Journal"
    )

    content = data.get(
        "content",
        ""
    )

    date_published = data.get(
        "date",
        ""
    )

    access_level = data.get(
        "accessLevel",
        "public"
    )

    if not title:
        return jsonify({
            "error": "Post title is required"
        }), 400

    # --------------------------------------------------------
    # Only these two access levels exist.
    # --------------------------------------------------------

    if access_level not in (
        "public",
        "members"
    ):
        return jsonify({
            "error": "Invalid access level"
        }), 400

    # --------------------------------------------------------
    # K.W. Snyder Writing is ALWAYS members-only.
    #
    # This prevents an admin publishing a K.W. Snyder post
    # accidentally as a public article.
    # --------------------------------------------------------

    if category == "kwsnyderwriting":
        access_level = "members"

    if not date_published:
        date_published = datetime.now().strftime(
            "%m/%d/%Y"
        )

    conn = get_db()

    cursor = conn.execute(
        """
        INSERT INTO published_posts
        (
            title,
            category,
            category_name,
            content,
            date_published,
            access_level
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            title,
            category,
            category_name,
            content,
            date_published,
            access_level,
        ),
    )

    conn.commit()

    post_id = cursor.lastrowid

    conn.close()

    return jsonify({
        "success": True,
        "id": post_id,
        "access_level": access_level,
    }), 201


@app.route(
    "/api/published/<int:post_id>",
    methods=["DELETE"]
)
def delete_published_post(post_id):

    if not require_admin():
        return jsonify({
            "error": "Unauthorized"
        }), 401

    conn = get_db()

    post = conn.execute(
        """
        SELECT *
        FROM published_posts
        WHERE id = ?
        """,
        (post_id,),
    ).fetchone()

    if post is None:

        conn.close()

        return jsonify({
            "error": "Post not found"
        }), 404

    conn.execute(
        """
        DELETE FROM published_posts
        WHERE id = ?
        """,
        (post_id,),
    )

    conn.commit()
    conn.close()

    return jsonify({
        "success": True
    })


# ============================================================
# MANUSCRIPTS API
# ============================================================

@app.route(
    "/api/manuscripts",
    methods=["GET"]
)
def get_manuscripts():

    if not require_admin():
        return jsonify({
            "error": "Unauthorized"
        }), 401

    conn = get_db()

    manuscripts = conn.execute(
        """
        SELECT *
        FROM manuscripts
        ORDER BY id DESC
        """
    ).fetchall()

    conn.close()

    return jsonify([
        dict(book)
        for book in manuscripts
    ])


@app.route(
    "/api/manuscripts",
    methods=["POST"]
)
def create_manuscript():

    if not require_admin():
        return jsonify({
            "error": "Unauthorized"
        }), 401

    data = request.get_json() or {}

    title = data.get(
        "title",
        "Untitled Book or Document"
    )

    content = data.get(
        "content",
        ""
    )

    date_created = data.get(
        "date",
        ""
    )

    if not date_created:
        date_created = datetime.now().strftime(
            "%m/%d/%Y"
        )

    conn = get_db()

    cursor = conn.execute(
        """
        INSERT INTO manuscripts
        (
            title,
            content,
            date_created
        )
        VALUES (?, ?, ?)
        """,
        (
            title,
            content,
            date_created,
        ),
    )

    conn.commit()

    manuscript_id = cursor.lastrowid

    conn.close()

    return jsonify({
        "success": True,
        "id": manuscript_id,
    }), 201


@app.route(
    "/api/manuscripts/<int:manuscript_id>",
    methods=["GET"]
)
def get_manuscript(manuscript_id):

    if not require_admin():
        return jsonify({
            "error": "Unauthorized"
        }), 401

    conn = get_db()

    manuscript = conn.execute(
        """
        SELECT *
        FROM manuscripts
        WHERE id = ?
        """,
        (manuscript_id,),
    ).fetchone()

    conn.close()

    if manuscript is None:
        return jsonify({
            "error": "Manuscript not found"
        }), 404

    return jsonify(
        dict(manuscript)
    )


@app.route(
    "/api/manuscripts/<int:manuscript_id>",
    methods=["DELETE"]
)
def delete_manuscript(manuscript_id):

    if not require_admin():
        return jsonify({
            "error": "Unauthorized"
        }), 401

    conn = get_db()

    conn.execute(
        """
        DELETE FROM manuscripts
        WHERE id = ?
        """,
        (manuscript_id,),
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
    app.run(
        debug=True
    )
