import os
import re
import time
from datetime import datetime
from decimal import Decimal, InvalidOperation
from xml.sax.saxutils import escape as xml_escape

import requests
from flask import Blueprint, jsonify, make_response, redirect, render_template, request, session, url_for, abort

from database import get_db, using_postgres, IntegrityError

store_bp = Blueprint("store", __name__)

# --- Bookstore visibility -------------------------------------------------
# The public storefront is live. Set STORE_VISIBLE to False to hide it again
# (and comment out the nav link in base.html).
# Admin routes (/admin/store, /api/store/admin/*) are intentionally NOT gated
# so inventory can keep being managed while the storefront is hidden.
STORE_VISIBLE = True

ALLOWED_STATUS = {"draft", "active", "archived"}
ALLOWED_CONDITIONS = {"new", "used"}
ALLOWED_SECTIONS = {"Antique", "Vintage", "Used", "New"}


def canonical_section(value):
    """Strict section for a category string: Antique, Vintage, Used, New, or None.

    A book belongs to exactly one section tab. Anything else (legacy
    values like "Books") shows only under All Books.
    """
    text = str(value or "").strip().lower()
    for section in ALLOWED_SECTIONS:
        if text == section.lower():
            return section
    return None

STORE_IMAGE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "store_images")
ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024


def now_string():
    return datetime.now().strftime("%m/%d/%Y %I:%M %p")


def require_admin():
    return bool(
        session.get("admin_logged_in") is True
        and session.get("admin_auth_version") == "2026-08-16-1"
    )


def admin_required():
    if not require_admin():
        return redirect(url_for("admin_login_page"))
    return None


# --- Storefront maintenance curtain -------------------------------------
# Shows a friendly "under maintenance" page in front of the public store
# while the shop is being worked on. Lifts itself Sunday evening; override
# anytime with the STORE_MAINTENANCE env var ("1" = on, "0" = off).
STORE_MAINTENANCE_UNTIL = "2026-10-05T00:00:00+00:00"  # Sun Oct 4, 8pm EDT


def _store_under_maintenance():
    override = (os.environ.get("STORE_MAINTENANCE") or "").strip().lower()
    if override in ("0", "false", "off", "no"):
        return False
    if override in ("1", "true", "on", "yes"):
        return True
    try:
        from datetime import timezone
        until = datetime.fromisoformat(
            (os.environ.get("STORE_MAINTENANCE_UNTIL") or STORE_MAINTENANCE_UNTIL).strip())
        if until.tzinfo is None:
            until = until.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) < until
    except Exception:
        return False


@store_bp.before_request
def _store_maintenance_curtain():
    path = request.path or ""
    is_storefront = path == "/store" or path.startswith(("/store/", "/api/store/paypal", "/api/store/products"))
    if not is_storefront:
        return None
    if require_admin():
        return None  # the admin can peek behind the curtain
    if not _store_under_maintenance():
        return None
    resp = make_response(render_template("store_maintenance.html"), 503)
    resp.headers["Retry-After"] = "172800"
    resp.headers["Cache-Control"] = "no-store"
    return resp


def slugify(value):
    value = re.sub(r"[^a-zA-Z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return value or "book"


def ensure_store_tables():
    conn = get_db()
    try:
        if using_postgres():
            statements = [
                "CREATE TABLE IF NOT EXISTS store_categories (id BIGSERIAL PRIMARY KEY, name TEXT UNIQUE NOT NULL, date_created TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS store_products (id BIGSERIAL PRIMARY KEY, title TEXT NOT NULL, slug TEXT UNIQUE NOT NULL, author TEXT NOT NULL DEFAULT '', description TEXT NOT NULL DEFAULT '', price_cents INTEGER NOT NULL DEFAULT 0, format TEXT NOT NULL DEFAULT 'Paperback', isbn TEXT NOT NULL DEFAULT '', cover_image_url TEXT NOT NULL DEFAULT '', category TEXT NOT NULL DEFAULT 'Books', language TEXT NOT NULL DEFAULT 'English', fulfillment_source TEXT NOT NULL DEFAULT 'Ingram Content Group', fulfillment_method TEXT NOT NULL DEFAULT 'Direct to Home', stock_quantity INTEGER NOT NULL DEFAULT 0, availability_status TEXT NOT NULL DEFAULT 'automatic', condition TEXT NOT NULL DEFAULT 'new', is_new_release INTEGER NOT NULL DEFAULT 0, is_kw_snyder INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'draft', date_created TEXT NOT NULL, date_updated TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS store_orders (id BIGSERIAL PRIMARY KEY, customer_name TEXT NOT NULL DEFAULT '', customer_email TEXT NOT NULL DEFAULT '', total_cents INTEGER NOT NULL DEFAULT 0, payment_status TEXT NOT NULL DEFAULT 'unpaid', order_status TEXT NOT NULL DEFAULT 'pending', provider TEXT NOT NULL DEFAULT '', provider_order_id TEXT NOT NULL DEFAULT '', ship_name TEXT NOT NULL DEFAULT '', ship_line1 TEXT NOT NULL DEFAULT '', ship_line2 TEXT NOT NULL DEFAULT '', ship_city TEXT NOT NULL DEFAULT '', ship_state TEXT NOT NULL DEFAULT '', ship_postal TEXT NOT NULL DEFAULT '', ship_country TEXT NOT NULL DEFAULT '', date_created TEXT NOT NULL, date_updated TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS store_order_items (id BIGSERIAL PRIMARY KEY, order_id BIGINT NOT NULL REFERENCES store_orders(id) ON DELETE CASCADE, product_id BIGINT NOT NULL REFERENCES store_products(id), quantity INTEGER NOT NULL DEFAULT 1, unit_price_cents INTEGER NOT NULL DEFAULT 0)",
                "CREATE TABLE IF NOT EXISTS store_product_images (id BIGSERIAL PRIMARY KEY, product_id BIGINT NOT NULL REFERENCES store_products(id) ON DELETE CASCADE, image_url TEXT NOT NULL, position INTEGER NOT NULL DEFAULT 0, date_created TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS store_images (id BIGSERIAL PRIMARY KEY, data BYTEA NOT NULL, mime TEXT NOT NULL DEFAULT 'image/jpeg', date_created TEXT NOT NULL)",
            ]
        else:
            statements = [
                "CREATE TABLE IF NOT EXISTS store_categories (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL, date_created TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS store_products (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, slug TEXT UNIQUE NOT NULL, author TEXT NOT NULL DEFAULT '', description TEXT NOT NULL DEFAULT '', price_cents INTEGER NOT NULL DEFAULT 0, format TEXT NOT NULL DEFAULT 'Paperback', isbn TEXT NOT NULL DEFAULT '', cover_image_url TEXT NOT NULL DEFAULT '', category TEXT NOT NULL DEFAULT 'Books', language TEXT NOT NULL DEFAULT 'English', fulfillment_source TEXT NOT NULL DEFAULT 'Ingram Content Group', fulfillment_method TEXT NOT NULL DEFAULT 'Direct to Home', stock_quantity INTEGER NOT NULL DEFAULT 0, availability_status TEXT NOT NULL DEFAULT 'automatic', condition TEXT NOT NULL DEFAULT 'new', is_new_release INTEGER NOT NULL DEFAULT 0, is_kw_snyder INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'draft', date_created TEXT NOT NULL, date_updated TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS store_orders (id INTEGER PRIMARY KEY AUTOINCREMENT, customer_name TEXT NOT NULL DEFAULT '', customer_email TEXT NOT NULL DEFAULT '', total_cents INTEGER NOT NULL DEFAULT 0, payment_status TEXT NOT NULL DEFAULT 'unpaid', order_status TEXT NOT NULL DEFAULT 'pending', provider TEXT NOT NULL DEFAULT '', provider_order_id TEXT NOT NULL DEFAULT '', ship_name TEXT NOT NULL DEFAULT '', ship_line1 TEXT NOT NULL DEFAULT '', ship_line2 TEXT NOT NULL DEFAULT '', ship_city TEXT NOT NULL DEFAULT '', ship_state TEXT NOT NULL DEFAULT '', ship_postal TEXT NOT NULL DEFAULT '', ship_country TEXT NOT NULL DEFAULT '', date_created TEXT NOT NULL, date_updated TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS store_order_items (id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL REFERENCES store_orders(id) ON DELETE CASCADE, product_id INTEGER NOT NULL REFERENCES store_products(id), quantity INTEGER NOT NULL DEFAULT 1, unit_price_cents INTEGER NOT NULL DEFAULT 0)",
                "CREATE TABLE IF NOT EXISTS store_product_images (id INTEGER PRIMARY KEY AUTOINCREMENT, product_id INTEGER NOT NULL REFERENCES store_products(id) ON DELETE CASCADE, image_url TEXT NOT NULL, position INTEGER NOT NULL DEFAULT 0, date_created TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS store_images (id INTEGER PRIMARY KEY AUTOINCREMENT, data BLOB NOT NULL, mime TEXT NOT NULL DEFAULT 'image/jpeg', date_created TEXT NOT NULL)",
            ]
        for statement in statements:
            conn.execute(statement)

        if using_postgres():
            migrations = [
                "ALTER TABLE store_products ADD COLUMN IF NOT EXISTS language TEXT NOT NULL DEFAULT 'English'",
                "ALTER TABLE store_products ADD COLUMN IF NOT EXISTS fulfillment_source TEXT NOT NULL DEFAULT 'Ingram Content Group'",
                "ALTER TABLE store_products ADD COLUMN IF NOT EXISTS fulfillment_method TEXT NOT NULL DEFAULT 'Direct to Home'",
                "ALTER TABLE store_products ADD COLUMN IF NOT EXISTS availability_status TEXT NOT NULL DEFAULT 'automatic'",
                "ALTER TABLE store_products ADD COLUMN IF NOT EXISTS condition TEXT NOT NULL DEFAULT 'new'",
                "ALTER TABLE store_products ADD COLUMN IF NOT EXISTS is_new_release INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE store_products ADD COLUMN IF NOT EXISTS is_kw_snyder INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE store_products ADD COLUMN IF NOT EXISTS publisher TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE store_products ADD COLUMN IF NOT EXISTS publication_year TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE store_products ADD COLUMN IF NOT EXISTS edition TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE store_products ADD COLUMN IF NOT EXISTS condition_notes TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE store_products ADD COLUMN IF NOT EXISTS notes TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE store_products ADD COLUMN IF NOT EXISTS genre TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE store_orders ADD COLUMN IF NOT EXISTS ship_name TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE store_orders ADD COLUMN IF NOT EXISTS ship_line1 TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE store_orders ADD COLUMN IF NOT EXISTS ship_line2 TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE store_orders ADD COLUMN IF NOT EXISTS ship_city TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE store_orders ADD COLUMN IF NOT EXISTS ship_state TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE store_orders ADD COLUMN IF NOT EXISTS ship_postal TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE store_orders ADD COLUMN IF NOT EXISTS ship_country TEXT NOT NULL DEFAULT ''",
            ]
        else:
            existing = {row["name"] for row in conn.execute("PRAGMA table_info(store_products)").fetchall()}
            migrations = []
            for name, definition in [
                ("language", "TEXT NOT NULL DEFAULT 'English'"),
                ("fulfillment_source", "TEXT NOT NULL DEFAULT 'Ingram Content Group'"),
                ("fulfillment_method", "TEXT NOT NULL DEFAULT 'Direct to Home'"),
                ("availability_status", "TEXT NOT NULL DEFAULT 'automatic'"),
                ("condition", "TEXT NOT NULL DEFAULT 'new'"),
                ("is_new_release", "INTEGER NOT NULL DEFAULT 0"),
                ("is_kw_snyder", "INTEGER NOT NULL DEFAULT 0"),
                ("publisher", "TEXT NOT NULL DEFAULT ''"),
                ("publication_year", "TEXT NOT NULL DEFAULT ''"),
                ("edition", "TEXT NOT NULL DEFAULT ''"),
                ("condition_notes", "TEXT NOT NULL DEFAULT ''"),
                ("notes", "TEXT NOT NULL DEFAULT ''"),
                ("genre", "TEXT NOT NULL DEFAULT ''"),
            ]:
                if name not in existing:
                    migrations.append(f"ALTER TABLE store_products ADD COLUMN {name} {definition}")
            existing_orders = {row["name"] for row in conn.execute("PRAGMA table_info(store_orders)").fetchall()}
            for name in ("ship_name", "ship_line1", "ship_line2", "ship_city",
                         "ship_state", "ship_postal", "ship_country"):
                if name not in existing_orders:
                    migrations.append(f"ALTER TABLE store_orders ADD COLUMN {name} TEXT NOT NULL DEFAULT ''")
        for statement in migrations:
            conn.execute(statement)

        _migrate_local_store_images(conn)

        for seed_category in ("Books", "Antique", "Vintage", "Used", "New"):
            conn.execute(
                "INSERT INTO store_categories(name, date_created) VALUES (?, ?) ON CONFLICT(name) DO NOTHING",
                (seed_category, now_string()),
            )
        conn.commit()
    finally:
        conn.close()


def parse_price(value):
    try:
        amount = Decimal(str(value).strip()).quantize(Decimal("0.01"))
        if amount < 0:
            raise InvalidOperation
        return int(amount * 100)
    except (InvalidOperation, ValueError):
        raise ValueError("Price must be a non-negative dollar amount.")


def product_payload(data):
    """Build a product dict from manually entered form/JSON data.

    Every field is optional except title and price — antique/vintage books
    have no external database to pull from, so everything is typed by hand.
    """
    title = str(data.get("title", "")).strip()
    if not title:
        raise ValueError("A book title is required.")

    raw_price = data.get("price", "")
    if raw_price is None or str(raw_price).strip() == "":
        raise ValueError("A price is required.")
    price_cents = parse_price(raw_price)

    status = str(data.get("status", "draft")).strip().lower()
    if status not in ALLOWED_STATUS:
        raise ValueError("Invalid product status.")

    raw_section = str(data.get("category", "")).strip()
    # Canonicalize known sections (case-insensitive); preserve any other
    # non-empty legacy value untouched; default blanks to Antique.
    section = canonical_section(raw_section) or raw_section or "Antique"

    try:
        stock_quantity = int(str(data.get("stock_quantity", "1") or "1").strip())
    except (TypeError, ValueError):
        raise ValueError("Stock quantity must be a whole number.")
    if stock_quantity < 0:
        raise ValueError("Stock quantity cannot be negative.")

    return {
        "title": title,
        "slug": slugify(data.get("slug") or title),
        "author": str(data.get("author", "")).strip(),
        "description": str(data.get("description", "")).strip(),
        "price_cents": price_cents,
        "format": str(data.get("format", "Hardcover")).strip() or "Hardcover",
        "isbn": str(data.get("isbn", "")).strip(),
        "cover_image_url": str(data.get("cover_image_url", "")).strip(),
        "category": section,
        "genre": str(data.get("genre", "")).strip(),
        "language": str(data.get("language", "English")).strip() or "English",
        "fulfillment_source": str(data.get("fulfillment_source", "In-house")).strip() or "In-house",
        "fulfillment_method": str(data.get("fulfillment_method", "Direct to Home")).strip() or "Direct to Home",
        "availability_status": str(data.get("availability_status", "automatic")).strip() or "automatic",
        "condition": "used",
        "is_new_release": 0,
        "is_kw_snyder": 0,
        "stock_quantity": stock_quantity,
        "status": status,
        "publisher": str(data.get("publisher", "")).strip(),
        "publication_year": str(data.get("publication_year", "")).strip(),
        "edition": str(data.get("edition", "")).strip(),
        "condition_notes": str(data.get("condition_notes", "")).strip(),
        "notes": str(data.get("notes", "")).strip(),
    }


def image_extension_for(data):
    """Detect a real image type from magic bytes. Returns extension or None."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return ".gif"
    if data.startswith(b"RIFF") and len(data) >= 12 and data[8:12] == b"WEBP":
        return ".webp"
    return None


def _validate_upload(storage):
    """Validate an uploaded image. Returns (data, mime). Raises ValueError."""
    filename = (storage.filename or "").strip()
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        raise ValueError("Photo must be a PNG, JPG, GIF, or WebP file.")
    data = storage.read(MAX_IMAGE_BYTES + 1)
    if not data:
        raise ValueError("The uploaded photo was empty.")
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError("Photo must be smaller than 5 MB.")
    real_ext = image_extension_for(data)
    if not real_ext:
        raise ValueError("That file does not look like a real image.")
    mime = "image/" + ("jpeg" if real_ext == ".jpg" else real_ext[1:])
    return data, mime


def store_image_data(conn, data, mime):
    """Persist image bytes in the database (survives redeploys).

    Returns the public /store/image/<id> URL.
    """
    cur = conn.execute(
        "INSERT INTO store_images(data, mime, date_created) VALUES (?, ?, ?)",
        (bytes(data), mime, now_string()),
    )
    return "/store/image/%d" % cur.lastrowid


def save_product_photo(conn, storage):
    """Validate and store an uploaded book photo in the DB. Returns the public URL."""
    data, mime = _validate_upload(storage)
    return store_image_data(conn, data, mime)


MAX_GALLERY_IMAGES = 6


def save_gallery_photo(conn, storage):
    """Validate and store one gallery photo in the DB. Returns the public URL."""
    data, mime = _validate_upload(storage)
    return store_image_data(conn, data, mime)


def _image_id_from_url(url):
    """Extract the DB image id from a /store/image/<id> URL, else None."""
    if not url or not isinstance(url, str):
        return None
    prefix = "/store/image/"
    if not url.startswith(prefix):
        return None
    tail = url[len(prefix):]
    return int(tail) if tail.isdigit() else None


def delete_stored_image(conn, url):
    """Delete a DB-backed image row. Legacy local files are removed from disk."""
    image_id = _image_id_from_url(url)
    if image_id:
        conn.execute("DELETE FROM store_images WHERE id = ?", (image_id,))
    else:
        _delete_local_cover_image(url)


_images_migrated = False


def _migrate_local_store_images(conn, limit=50):
    """One-time, strictly bounded: import surviving local /static/store_images
    files into the database and rewrite their URLs to /store/image/<id>.

    Render wipes the local upload directory on redeploy, so this rescues any
    files still on disk. Runs once per process; never touches remote URLs.
    """
    global _images_migrated
    if _images_migrated:
        return 0
    _images_migrated = True
    if not os.path.isdir(STORE_IMAGE_DIR):
        return 0
    migrated = 0
    try:
        targets = []
        for table, column in (("store_products", "cover_image_url"),
                              ("store_product_images", "image_url")):
            rows = conn.execute(
                "SELECT id, %s AS url FROM %s WHERE %s LIKE '/static/store_images/%%%%'" % (column, table, column)
            ).fetchall()
            targets.extend((table, column, r["id"], r["url"]) for r in rows)
    except Exception:
        return 0
    for table, column, row_id, url in targets:
        if migrated >= limit:
            break
        try:
            filename = url[len("/static/store_images/"):]
            if not filename or "/" in filename or "\\" in filename or filename.startswith("."):
                continue
            path = os.path.join(STORE_IMAGE_DIR, filename)
            if not os.path.isfile(path):
                continue
            with open(path, "rb") as handle:
                data = handle.read(MAX_IMAGE_BYTES + 1)
            if not data or len(data) > MAX_IMAGE_BYTES:
                continue
            real_ext = image_extension_for(data)
            if not real_ext:
                continue
            mime = "image/" + ("jpeg" if real_ext == ".jpg" else real_ext[1:])
            new_url = store_image_data(conn, data, mime)
            conn.execute("UPDATE %s SET %s = ? WHERE id = ?" % (table, column), (new_url, row_id))
            migrated += 1
        except Exception:
            continue
    return migrated


@store_bp.route("/store/image/<int:image_id>")
def serve_store_image(image_id):
    """Serve a database-backed store image with a long immutable cache."""
    conn = get_db()
    try:
        row = conn.execute("SELECT data, mime FROM store_images WHERE id = ?", (image_id,)).fetchone()
    finally:
        conn.close()
    if not row:
        abort(404)
    data = row["data"]
    if isinstance(data, memoryview):
        data = data.tobytes()
    response = make_response(bytes(data))
    response.headers["Content-Type"] = row["mime"] or "image/jpeg"
    response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return response


def get_product_images(conn, product_id):
    """Gallery images for a product, oldest first. Returns [{id, image_url}]."""
    rows = conn.execute(
        "SELECT id, image_url FROM store_product_images WHERE product_id = ? ORDER BY position, id",
        (product_id,),
    ).fetchall()
    return [{"id": row["id"], "image_url": row["image_url"]} for row in rows]


def _request_gallery_photos():
    """Uploaded gallery files from a multipart form (empty list if none)."""
    if request.is_json:
        return []
    photos = request.files.getlist("photos")
    return [p for p in photos if p and (p.filename or "").strip()]


def add_gallery_photos(conn, product_id, slug):
    """Save uploaded gallery photos; returns a list of warning strings."""
    warnings = []
    existing = conn.execute(
        "SELECT COUNT(*) AS c FROM store_product_images WHERE product_id = ?", (product_id,)
    ).fetchone()["c"]
    position = existing
    for storage in _request_gallery_photos():
        if position >= MAX_GALLERY_IMAGES:
            warnings.append(f"Only {MAX_GALLERY_IMAGES} gallery photos per book are kept.")
            break
        try:
            url = save_gallery_photo(conn, storage)
        except ValueError as exc:
            warnings.append(str(exc))
            continue
        conn.execute(
            "INSERT INTO store_product_images(product_id, image_url, position, date_created) VALUES (?, ?, ?, ?)",
            (product_id, url, position, now_string()),
        )
        position += 1
    return warnings


def row_to_dict(row):
    item = dict(row)
    item["price"] = f"{item['price_cents'] / 100:.2f}"
    item["is_new_release"] = bool(item.get("is_new_release"))
    item["is_kw_snyder"] = bool(item.get("is_kw_snyder"))
    item["genre"] = item.get("genre") or ""
    # Strict storefront section: Antique, Vintage, Used, New, or None (All Books only).
    item["section"] = canonical_section(item.get("category"))
    return item


def public_dict(row):
    """Public-facing product dict — never leaks the private admin notes."""
    item = row_to_dict(row)
    item.pop("notes", None)
    return item


@store_bp.before_request
def prepare_store():
    ensure_store_tables()


def active_products(conn):
    return conn.execute(
        """SELECT p.*, COALESCE(v.view_count, 0) AS view_count
           FROM store_products p
           LEFT JOIN (
               SELECT content_id, COUNT(*) AS view_count
               FROM page_views
               WHERE page_type = 'store_book' AND category = 'store'
               GROUP BY content_id
           ) v ON v.content_id = p.id
           WHERE p.status = 'active'
           ORDER BY LOWER(p.title), p.id"""
    ).fetchall()


def _request_data():
    if request.is_json:
        return request.get_json() or {}
    return request.form.to_dict()


def _request_photo():
    if request.is_json:
        return None
    photo = request.files.get("photo")
    if photo and (photo.filename or "").strip():
        return photo
    return None


PRODUCT_COLUMNS = ("title, slug, author, description, price_cents, format, isbn, cover_image_url, category, genre, language, fulfillment_source, fulfillment_method, stock_quantity, availability_status, condition, is_new_release, is_kw_snyder, status, publisher, publication_year, edition, condition_notes, notes, date_created, date_updated")


def _product_values(product):
    return (product["title"], product["slug"], product["author"], product["description"], product["price_cents"], product["format"], product["isbn"], product["cover_image_url"], product["category"], product["genre"], product["language"], product["fulfillment_source"], product["fulfillment_method"], product["stock_quantity"], product["availability_status"], product["condition"], product["is_new_release"], product["is_kw_snyder"], product["status"], product["publisher"], product["publication_year"], product["edition"], product["condition_notes"], product["notes"])


@store_bp.route("/store")
def store_home():
    if not STORE_VISIBLE:
        return redirect(url_for("the_hearth"))
    conn = get_db()
    rows = active_products(conn)
    conn.close()
    return render_template("store.html", products=[public_dict(row) for row in rows])


@store_bp.route("/store/book/<slug>")
def store_book(slug):
    if not STORE_VISIBLE:
        return redirect(url_for("the_hearth"))
    conn = get_db()
    product = conn.execute(
        "SELECT * FROM store_products WHERE slug = ? AND status = 'active'",
        (slug,),
    ).fetchone()
    images = get_product_images(conn, product["id"]) if product else []
    conn.close()
    if not product:
        abort(404)
    item = public_dict(product)
    item["images"] = images
    return render_template("store_book.html", product=item, shipping_cents=shipping_cents(1))


@store_bp.route("/sitemap.xml")
def sitemap():
    """Search-engine sitemap: static pages plus every active book for sale."""
    conn = get_db()
    rows = active_products(conn)
    conn.close()
    urls = []
    for endpoint in ("the_hearth", "about", "contact"):
        urls.append(url_for(endpoint, _external=True))
    urls.append(url_for("store.store_home", _external=True))
    for row in rows:
        item = public_dict(row)
        if item.get("slug"):
            urls.append(url_for("store.store_book", slug=item["slug"], _external=True))
    seen = set()
    unique = [u for u in urls if not (u in seen or seen.add(u))]
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for u in unique:
        lines.append("  <url><loc>%s</loc></url>" % xml_escape(u))
    lines.append("</urlset>")
    resp = make_response("\n".join(lines))
    resp.headers["Content-Type"] = "application/xml"
    return resp


@store_bp.route("/robots.txt")
def robots():
    resp = make_response(
        "User-agent: *\nAllow: /\n\nSitemap: %s\n"
        % url_for("store.sitemap", _external=True)
    )
    resp.headers["Content-Type"] = "text/plain"
    return resp


@store_bp.route("/admin/store/preview")
def admin_store_preview():
    """Admin-only preview of the storefront while STORE_VISIBLE is False."""
    blocked = admin_required()
    if blocked:
        return blocked
    conn = get_db()
    rows = active_products(conn)
    conn.close()
    return render_template("store.html", products=[public_dict(row) for row in rows], preview=True)


@store_bp.route("/admin/store/preview/book/<slug>")
def admin_store_preview_book(slug):
    """Admin-only preview of a product detail page while hidden."""
    blocked = admin_required()
    if blocked:
        return blocked
    conn = get_db()
    product = conn.execute(
        "SELECT * FROM store_products WHERE slug = ? AND status = 'active'",
        (slug,),
    ).fetchone()
    images = get_product_images(conn, product["id"]) if product else []
    conn.close()
    if not product:
        abort(404)
    item = public_dict(product)
    item["images"] = images
    return render_template("store_book.html", product=item, preview=True, shipping_cents=shipping_cents(1))


@store_bp.route("/api/store/products")
def public_products():
    if not STORE_VISIBLE:
        return redirect(url_for("the_hearth"))
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM store_products WHERE status = 'active' ORDER BY LOWER(title), id"
    ).fetchall()
    conn.close()
    return jsonify([public_dict(row) for row in rows])


@store_bp.route("/api/store/products/<int:product_id>")
def public_product(product_id):
    if not STORE_VISIBLE:
        return redirect(url_for("the_hearth"))
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM store_products WHERE id = ? AND status = 'active'",
        (product_id,),
    ).fetchone()
    images = get_product_images(conn, row["id"]) if row else []
    conn.close()
    if not row:
        return jsonify({"error": "Book not found."}), 404
    item = public_dict(row)
    item["images"] = images
    return jsonify(item)


@store_bp.route("/admin/store")
def admin_store():
    blocked = admin_required()
    if blocked:
        return blocked
    return render_template("admin_store.html")


@store_bp.route("/api/store/admin/products", methods=["GET"])
def admin_products():
    blocked = admin_required()
    if blocked:
        return blocked
    conn = get_db()
    rows = conn.execute("SELECT * FROM store_products ORDER BY LOWER(title), id").fetchall()
    conn.close()
    return jsonify([public_dict(row) for row in rows])


@store_bp.route("/api/store/admin/products", methods=["POST"])
def admin_create_product():
    blocked = admin_required()
    if blocked:
        return blocked
    try:
        product = product_payload(_request_data())
    except (ValueError, TypeError) as exc:
        return jsonify({"error": str(exc)}), 400
    conn = get_db()
    try:
        timestamp = now_string()
        cursor = conn.execute(
            f"INSERT INTO store_products({PRODUCT_COLUMNS}) VALUES ({', '.join(['?'] * 26)})",
            _product_values(product) + (timestamp, timestamp),
        )
        new_id = cursor.lastrowid
        photo_warning = None
        photo = _request_photo()
        if photo:
            try:
                product["cover_image_url"] = save_product_photo(conn, photo)
                conn.execute(
                    "UPDATE store_products SET cover_image_url = ?, date_updated = ? WHERE id = ?",
                    (product["cover_image_url"], now_string(), new_id),
                )
            except ValueError as exc:
                photo_warning = str(exc)
        gallery_warnings = add_gallery_photos(conn, new_id, product["slug"])
        if gallery_warnings and not photo_warning:
            photo_warning = "; ".join(gallery_warnings)
        elif gallery_warnings:
            photo_warning = photo_warning + "; " + "; ".join(gallery_warnings)
        conn.commit()
        row = conn.execute("SELECT * FROM store_products WHERE id = ?", (new_id,)).fetchone()
        images = get_product_images(conn, new_id)
    except IntegrityError:
        conn.rollback()
        conn.close()
        return jsonify({"error": "A bookstore product with that slug already exists."}), 409
    conn.close()
    payload = {"success": True, "product": row_to_dict(row)}
    payload["product"]["images"] = images
    if photo_warning:
        payload["photo_warning"] = photo_warning
    return jsonify(payload), 201


@store_bp.route("/api/store/admin/products/<int:product_id>", methods=["GET"])
def admin_get_product(product_id):
    blocked = admin_required()
    if blocked:
        return blocked
    conn = get_db()
    row = conn.execute("SELECT * FROM store_products WHERE id = ?", (product_id,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Book not found."}), 404
    item = row_to_dict(row)
    item["images"] = get_product_images(conn, product_id)
    conn.close()
    return jsonify(item)


@store_bp.route("/api/store/admin/product-images/<int:image_id>", methods=["DELETE"])
def admin_delete_product_image(image_id):
    """Remove one gallery photo (row + local file). The cover photo is separate."""
    blocked = admin_required()
    if blocked:
        return blocked
    conn = get_db()
    row = conn.execute(
        "SELECT id, image_url FROM store_product_images WHERE id = ?", (image_id,)
    ).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Photo not found."}), 404
    delete_stored_image(conn, row["image_url"])
    conn.execute("DELETE FROM store_product_images WHERE id = ?", (image_id,))
    conn.commit()
    conn.close()
    return jsonify({"success": True, "deleted": True})


@store_bp.route("/api/store/admin/products/<int:product_id>", methods=["PUT"])
def admin_update_product(product_id):
    blocked = admin_required()
    if blocked:
        return blocked
    conn = get_db()
    existing = conn.execute("SELECT * FROM store_products WHERE id = ?", (product_id,)).fetchone()
    if not existing:
        conn.close()
        return jsonify({"error": "Book not found."}), 404
    data = _request_data()
    # Keep the current photo unless a new one is uploaded or a URL is typed in.
    if "cover_image_url" not in data:
        data = dict(data)
        data["cover_image_url"] = existing["cover_image_url"]
    try:
        product = product_payload(data)
    except (ValueError, TypeError) as exc:
        conn.close()
        return jsonify({"error": str(exc)}), 400
    try:
        conn.execute(
            "UPDATE store_products SET title = ?, slug = ?, author = ?, description = ?, price_cents = ?, format = ?, isbn = ?, cover_image_url = ?, category = ?, genre = ?, language = ?, fulfillment_source = ?, fulfillment_method = ?, stock_quantity = ?, availability_status = ?, condition = ?, is_new_release = ?, is_kw_snyder = ?, status = ?, publisher = ?, publication_year = ?, edition = ?, condition_notes = ?, notes = ?, date_updated = ? WHERE id = ?",
            _product_values(product)[0:19] + _product_values(product)[19:24] + (now_string(), product_id),
        )
        photo_warning = None
        photo = _request_photo()
        if photo:
            try:
                old_cover = existing["cover_image_url"]
                cover_url = save_product_photo(conn, photo)
                delete_stored_image(conn, old_cover)
                conn.execute(
                    "UPDATE store_products SET cover_image_url = ?, date_updated = ? WHERE id = ?",
                    (cover_url, now_string(), product_id),
                )
            except ValueError as exc:
                photo_warning = str(exc)
        gallery_warnings = add_gallery_photos(conn, product_id, product["slug"])
        if gallery_warnings and not photo_warning:
            photo_warning = "; ".join(gallery_warnings)
        elif gallery_warnings:
            photo_warning = photo_warning + "; " + "; ".join(gallery_warnings)
        conn.commit()
        row = conn.execute("SELECT * FROM store_products WHERE id = ?", (product_id,)).fetchone()
        images = get_product_images(conn, product_id)
    except IntegrityError:
        conn.rollback()
        conn.close()
        return jsonify({"error": "A bookstore product with that slug already exists."}), 409
    conn.close()
    payload = {"success": True, "product": row_to_dict(row)}
    payload["product"]["images"] = images
    if photo_warning:
        payload["photo_warning"] = photo_warning
    return jsonify(payload)


def _delete_local_cover_image(cover_url):
    """Remove a locally uploaded cover image file. Remote URLs are untouched."""
    if not cover_url or not isinstance(cover_url, str):
        return
    prefix = "/static/store_images/"
    if not cover_url.startswith(prefix):
        return
    filename = cover_url[len(prefix):]
    if not filename or "/" in filename or "\\" in filename or filename.startswith("."):
        return
    path = os.path.join(STORE_IMAGE_DIR, filename)
    # Belt and suspenders: never delete outside the store image dir.
    if os.path.abspath(path).startswith(os.path.abspath(STORE_IMAGE_DIR) + os.sep):
        try:
            if os.path.isfile(path):
                os.remove(path)
        except OSError:
            pass


@store_bp.route("/api/store/admin/products/<int:product_id>", methods=["DELETE"])
def admin_delete_product(product_id):
    blocked = admin_required()
    if blocked:
        return blocked
    permanent = request.args.get("permanent") == "1"
    conn = get_db()
    row = conn.execute("SELECT id, cover_image_url FROM store_products WHERE id = ?", (product_id,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Book not found."}), 404
    if permanent:
        gallery_urls = [
            row["image_url"]
            for row in conn.execute(
                "SELECT image_url FROM store_product_images WHERE product_id = ?", (product_id,)
            ).fetchall()
        ]
        try:
            # Order line items reference the product without ON DELETE CASCADE.
            conn.execute("DELETE FROM store_order_items WHERE product_id = ?", (product_id,))
            conn.execute("DELETE FROM store_products WHERE id = ?", (product_id,))
            for url in gallery_urls + [row["cover_image_url"]]:
                image_id = _image_id_from_url(url)
                if image_id:
                    conn.execute("DELETE FROM store_images WHERE id = ?", (image_id,))
            conn.commit()
        except Exception as exc:  # Surface as JSON, never an HTML 500 page.
            try:
                conn.rollback()
            except Exception:
                pass
            conn.close()
            return jsonify({"error": "Could not delete the book. (%s)" % exc}), 500
        conn.close()
        _delete_local_cover_image(row["cover_image_url"])
        for url in gallery_urls:
            _delete_local_cover_image(url)
        return jsonify({"success": True, "deleted": True})
    conn.execute("UPDATE store_products SET status = 'archived', date_updated = ? WHERE id = ?", (now_string(), product_id))
    conn.commit()
    conn.close()
    return jsonify({"success": True})


# Media Mail shipping, in cents: $4.47 for the first book, $0.75 for each
# additional book. Charged by quantity, not weight — one shared helper used
# by both the Buy Now and cart checkout flows.
SHIPPING_FIRST_BOOK_CENTS = 447
SHIPPING_EXTRA_BOOK_CENTS = 75


def shipping_cents(total_qty):
    """Media Mail shipping for an order holding total_qty books."""
    try:
        qty = int(total_qty or 0)
    except (TypeError, ValueError):
        qty = 0
    if qty < 1:
        return 0
    return SHIPPING_FIRST_BOOK_CENTS + SHIPPING_EXTRA_BOOK_CENTS * (qty - 1)


# --- PayPal checkout ------------------------------------------------------
# Single-entry checkout: books are entered once in the store admin. When a
# customer buys, the backend builds the PayPal order from the database row —
# nothing is ever typed into PayPal by hand.
#
# Server env vars (set in Render; never committed):
#   PAYPAL_CLIENT_ID, PAYPAL_CLIENT_SECRET (PAYPAL_SECRET also accepted as a
#   legacy alias), PAYPAL_MODE=sandbox|live
# The client ID is public by design (it ships in the page JS). The secret
# stays server-side and is only used for server-to-server API calls.

PAYPAL_SANDBOX_API = "https://api-m.sandbox.paypal.com"
PAYPAL_LIVE_API = "https://api-m.paypal.com"

_paypal_token_cache = {"token": None, "expires_at": 0.0}


def paypal_mode():
    return (os.environ.get("PAYPAL_MODE", "sandbox") or "sandbox").strip().lower()


def paypal_api_base():
    return PAYPAL_LIVE_API if paypal_mode() == "live" else PAYPAL_SANDBOX_API


def paypal_secret():
    # PAYPAL_CLIENT_SECRET is the canonical name (the membership code uses
    # it); PAYPAL_SECRET is kept as a legacy alias so either one works.
    return (os.environ.get("PAYPAL_CLIENT_SECRET") or os.environ.get("PAYPAL_SECRET") or "").strip()


def paypal_configured():
    return bool(os.environ.get("PAYPAL_CLIENT_ID") and paypal_secret())


def paypal_access_token():
    """Server-to-server OAuth token, cached until near expiry."""
    now = time.time()
    if _paypal_token_cache["token"] and _paypal_token_cache["expires_at"] > now + 60:
        return _paypal_token_cache["token"]
    resp = requests.post(
        paypal_api_base() + "/v1/oauth2/token",
        auth=(os.environ.get("PAYPAL_CLIENT_ID", ""), paypal_secret()),
        data={"grant_type": "client_credentials"},
        headers={"Accept": "application/json"},
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    _paypal_token_cache["token"] = data["access_token"]
    _paypal_token_cache["expires_at"] = now + int(data.get("expires_in", 3000))
    return _paypal_token_cache["token"]


def paypal_request(method, path, payload=None):
    return requests.request(
        method,
        paypal_api_base() + path,
        headers={
            "Authorization": "Bearer " + paypal_access_token(),
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=20,
    )


@store_bp.route("/api/store/paypal/config")
def paypal_config():
    if not STORE_VISIBLE:
        return jsonify({"configured": False})
    return jsonify({
        "configured": paypal_configured(),
        "mode": paypal_mode(),
    })


@store_bp.route("/api/store/paypal/start-checkout", methods=["POST"])
def paypal_start_checkout():
    """Start checkout for a book. Creates the local order and a PayPal order,
    then returns PayPal's approval URL. The buyer approves on PayPal's site and
    is sent back to /store/checkout/return, where we capture. The price is
    always read server-side — the browser never decides what a book costs."""
    if not STORE_VISIBLE:
        return jsonify({"error": "The store is not available."}), 404
    if not paypal_configured():
        return jsonify({"error": "Checkout is not set up yet."}), 503
    data = _request_data()
    try:
        product_id = int(data.get("product_id") or 0)
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid book."}), 400
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM store_products WHERE id = ? AND status = 'active'",
        (product_id,),
    ).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "That book is no longer available."}), 404
    product = row_to_dict(row)
    if int(product.get("stock_quantity") or 0) < 1:
        conn.close()
        return jsonify({"error": "That book is out of stock."}), 409
    price_cents = int(product.get("price_cents") or 0)
    if price_cents < 1:
        conn.close()
        return jsonify({"error": "That book has no price set."}), 409
    ship_cents = shipping_cents(1)
    total_cents = price_cents + ship_cents
    now = now_string()
    cursor = conn.execute(
        "INSERT INTO store_orders (customer_name, customer_email, total_cents, payment_status, order_status, provider, provider_order_id, date_created, date_updated)"
        " VALUES (?, ?, ?, 'unpaid', 'pending', 'paypal', '', ?, ?)",
        ("", "", total_cents, now, now),
    )
    local_order_id = cursor.lastrowid
    conn.execute(
        "INSERT INTO store_order_items (order_id, product_id, quantity, unit_price_cents) VALUES (?, ?, 1, ?)",
        (local_order_id, product_id, price_cents),
    )
    conn.commit()
    base = request.host_url.rstrip("/")
    try:
        resp = paypal_request("POST", "/v2/checkout/orders", {
            "intent": "CAPTURE",
            "purchase_units": [{
                "reference_id": str(local_order_id),
                "description": (product.get("title") or "Book")[:120],
                "amount": {
                    "currency_code": "USD",
                    "value": f"{total_cents / 100:.2f}",
                    "breakdown": {
                        "item_total": {
                            "currency_code": "USD",
                            "value": f"{price_cents / 100:.2f}",
                        },
                        "shipping": {
                            "currency_code": "USD",
                            "value": f"{ship_cents / 100:.2f}",
                        },
                    },
                },
            }],
            "application_context": {
                "brand_name": "Snyder Scriptorium",
                "return_url": base + "/store/checkout/return",
                "cancel_url": base + "/store/checkout/cancel",
                "user_action": "PAY_NOW",
                "shipping_preference": "GET_FROM_FILE",
            },
        })
        body = resp.json()
    except Exception as exc:
        conn.close()
        return jsonify({"error": "Could not start checkout. (%s)" % exc}), 502
    if resp.status_code not in (200, 201):
        detail = ""
        try:
            err = (body.get("details") or body.get("message")) if isinstance(body, dict) else ""
            detail = (" — %s" % err) if err else ""
        except Exception:
            pass
        conn.close()
        return jsonify({"error": "Checkout was declined by PayPal (status %d%s)." % (resp.status_code, detail)}), 502
    paypal_order_id = body.get("id", "") if isinstance(body, dict) else ""
    approval_url = ""
    try:
        for link in body.get("links", []):
            if link.get("rel") == "approve" and link.get("href"):
                approval_url = link["href"]
                break
    except Exception:
        approval_url = ""
    if not paypal_order_id or not approval_url:
        conn.close()
        return jsonify({"error": "PayPal did not return an approval link. Please try again."}), 502
    conn.execute(
        "UPDATE store_orders SET provider_order_id = ?, date_updated = ? WHERE id = ?",
        (paypal_order_id, now_string(), local_order_id),
    )
    conn.commit()
    conn.close()
    return jsonify({"approval_url": approval_url})


def _notify_money(cents):
    return "$%.2f" % (int(cents or 0) / 100)


def _send_order_notification(conn, local_order_id):
    """Email the owner a packing slip the moment an order is captured.

    Never raises: a failed or unconfigured notification must not break
    checkout. Returns True if an email was actually sent.
    """
    try:
        smtp_host = (os.environ.get("SMTP_HOST") or "").strip()
        notify_to = (os.environ.get("NOTIFY_EMAIL_TO") or "").strip()
        if not smtp_host or not notify_to:
            print("[store] order notification skipped: SMTP_HOST/NOTIFY_EMAIL_TO not set", flush=True)
            return False
        try:
            smtp_port = int((os.environ.get("SMTP_PORT") or "587").strip())
        except (TypeError, ValueError):
            smtp_port = 587
        smtp_user = (os.environ.get("SMTP_USER") or "").strip()
        smtp_pass = os.environ.get("SMTP_PASS") or ""
        notify_from = (os.environ.get("NOTIFY_EMAIL_FROM") or "").strip() or smtp_user

        row = conn.execute("SELECT * FROM store_orders WHERE id = ?", (local_order_id,)).fetchone()
        if not row:
            print("[store] order notification skipped: order %s not found" % local_order_id, flush=True)
            return False
        order = dict(row)
        items = conn.execute(
            "SELECT p.title, oi.quantity, oi.unit_price_cents"
            " FROM store_order_items oi JOIN store_products p ON p.id = oi.product_id"
            " WHERE oi.order_id = ? ORDER BY oi.id",
            (local_order_id,),
        ).fetchall()

        item_lines = []
        subtotal = 0
        for item in items:
            item = dict(item)
            qty = int(item.get("quantity") or 1)
            unit = int(item.get("unit_price_cents") or 0)
            subtotal += qty * unit
            item_lines.append("  %s x%d @ %s = %s" % (
                item.get("title") or "Book", qty, _notify_money(unit), _notify_money(qty * unit)))
        total = int(order.get("total_cents") or 0)
        shipping = total - subtotal

        addr_lines = [
            order.get("ship_name") or "",
            order.get("ship_line1") or "",
            order.get("ship_line2") or "",
        ]
        city_state = ", ".join(p for p in [order.get("ship_city") or "", order.get("ship_state") or ""] if p)
        postal = order.get("ship_postal") or ""
        if city_state and postal:
            addr_lines.append("%s %s" % (city_state, postal))
        elif city_state or postal:
            addr_lines.append(city_state or postal)
        if order.get("ship_country"):
            addr_lines.append(order.get("ship_country"))
        addr_lines = [line for line in addr_lines if line.strip()]

        body = "\n".join([
            "New book order #%s — %s" % (local_order_id, _notify_money(total)),
            "Snyder Scriptorium",
            "",
            "Order #%s — %s" % (local_order_id, order.get("date_created") or ""),
            "",
            "Items:",
        ] + item_lines + [
            "",
            "Subtotal: %s" % _notify_money(subtotal),
            "Shipping (US Media Mail): %s" % _notify_money(shipping),
            "Total captured: %s" % _notify_money(total),
            "",
            "Buyer:",
            "  %s" % (order.get("customer_name") or ""),
            "  %s" % (order.get("customer_email") or ""),
            "",
            "Ship to:",
        ] + ["  %s" % line for line in addr_lines])

        import smtplib
        from email.message import EmailMessage
        msg = EmailMessage()
        msg["Subject"] = "New book order #%s — %s" % (local_order_id, _notify_money(total))
        msg["From"] = notify_from
        msg["To"] = notify_to
        msg.set_content(body)
        with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as server:
            server.starttls()
            if smtp_user:
                server.login(smtp_user, smtp_pass)
            server.send_message(msg)
        print("[store] order notification sent for order %s" % local_order_id, flush=True)
        return True
    except Exception as exc:
        print("[store] order notification failed for order %s: %r" % (local_order_id, exc), flush=True)
        return False


def _notify_inbox_order(conn, local_order_id):
    """Drop a 'new order' message into the admin inbox when an order is captured.

    Credential-free companion to the email packing slip: the admin inbox's
    unread badge fires the moment this lands, no SMTP setup needed.
    Never raises: a notification failure must not break checkout.
    """
    try:
        row = conn.execute("SELECT * FROM store_orders WHERE id = ?", (local_order_id,)).fetchone()
        if not row:
            return False
        order = dict(row)
        items = conn.execute(
            "SELECT p.title, oi.quantity, oi.unit_price_cents"
            " FROM store_order_items oi JOIN store_products p ON p.id = oi.product_id"
            " WHERE oi.order_id = ? ORDER BY oi.id",
            (local_order_id,),
        ).fetchall()
        lines = []
        for item in items:
            item = dict(item)
            qty = int(item.get("quantity") or 1)
            lines.append("%s x%d — %s" % (item.get("title") or "Book", qty, _notify_money(item.get("unit_price_cents"))))
        total = _notify_money(order.get("total_cents"))
        ship = " ".join(p for p in [
            order.get("ship_name") or order.get("customer_name") or "",
            order.get("ship_line1") or "",
            order.get("ship_line2") or "",
            order.get("ship_city") or "",
            order.get("ship_state") or "",
            order.get("ship_postal") or "",
        ] if p).strip()
        buyer_name = order.get("customer_name") or "Buyer"
        buyer_email = order.get("customer_email") or ""
        body = "New order #%s\n%s\nTotal: %s\nShip to: %s\nBuyer: %s <%s>" % (
            local_order_id, "\n".join(lines), total, ship or "—", buyer_name, buyer_email)
        conn.execute(
            "INSERT INTO inbox_messages(message_type, name, email, subject, message) VALUES (?, ?, ?, ?, ?)",
            ("order", buyer_name, buyer_email, "New order #%s — %s" % (local_order_id, total), body),
        )
        conn.commit()
        try:
            from push_notifications import send_push
            send_push("New book order — %s" % total,
                      "%s — %s" % (buyer_name, ", ".join(l.split(" — ")[0] for l in lines) or "book order"),
                      url="/admin#tab-inbox", tag="order-%s" % local_order_id)
        except Exception as exc:
            print("[store] order push failed: %r" % (exc,), flush=True)
        return True
    except Exception as exc:
        print("[store] inbox order notification failed: %r" % (exc,), flush=True)
        return False


def _capture_paypal_order(conn, local_order_id, paypal_order_id):
    """Capture an approved PayPal order, verify the amount server-side, then
    record payment and decrement stock. Idempotent: already-paid orders just
    report success. Returns (True, None) or (False, error_message)."""
    row = conn.execute("SELECT * FROM store_orders WHERE id = ?", (local_order_id,)).fetchone()
    if not row:
        return False, "Order not found."
    order = dict(row)
    if order.get("provider_order_id") != paypal_order_id or order.get("provider") != "paypal":
        return False, "Order mismatch."
    if order.get("payment_status") == "paid":
        return True, None
    try:
        resp = paypal_request("POST", "/v2/checkout/orders/%s/capture" % paypal_order_id)
    except Exception as exc:
        return False, "Could not capture payment. (%s)" % exc
    capture = resp.json() or {}
    already_captured = (
        resp.status_code == 422
        and any((d or {}).get("issue") == "ORDER_ALREADY_CAPTURED"
                for d in capture.get("details", []))
    )
    if already_captured:
        # The money already moved (e.g. the buyer reloaded the return page
        # after an earlier crash). Verify via the order itself, then record
        # it locally exactly like a fresh capture.
        try:
            detail = paypal_request("GET", "/v2/checkout/orders/%s" % paypal_order_id)
        except Exception as exc:
            return False, "Could not verify payment. (%s)" % exc
        if detail.status_code != 200:
            return False, "The payment was not completed."
        capture = detail.json() or {}
    elif resp.status_code not in (200, 201):
        return False, "The payment was not completed."
    if capture.get("status") != "COMPLETED":
        return False, "The payment was not completed."
    captured_cents = 0
    for unit in capture.get("purchase_units", []):
        for cap in (unit.get("payments") or {}).get("captures", []):
            amount = cap.get("amount") or {}
            if amount.get("currency_code") == "USD":
                try:
                    captured_cents += int(round(float(amount.get("value", "0")) * 100))
                except (TypeError, ValueError):
                    pass
    if captured_cents != int(order.get("total_cents") or 0):
        return False, "The payment amount did not match the order."
    payer = capture.get("payer") or {}
    payer_name = payer.get("name") or {}
    full_name = (str(payer_name.get("given_name", "")) + " " + str(payer_name.get("surname", ""))).strip()
    # Shipping address comes back on the purchase unit when the order was
    # created with shipping_preference GET_FROM_FILE.
    shipping = {}
    try:
        shipping = (capture.get("purchase_units") or [{}])[0].get("shipping") or {}
    except (IndexError, AttributeError, TypeError):
        shipping = {}
    ship_addr = shipping.get("address") or {}
    ship_name = str((shipping.get("name") or {}).get("full_name", "") or "").strip()
    now = now_string()
    conn.execute(
        "UPDATE store_orders SET payment_status = 'paid', order_status = 'processing',"
        " customer_name = ?, customer_email = ?,"
        " ship_name = ?, ship_line1 = ?, ship_line2 = ?, ship_city = ?,"
        " ship_state = ?, ship_postal = ?, ship_country = ?,"
        " date_updated = ? WHERE id = ?",
        (full_name, payer.get("email_address", ""),
         ship_name,
         str(ship_addr.get("address_line_1", "") or ""),
         str(ship_addr.get("address_line_2", "") or ""),
         str(ship_addr.get("admin_area_2", "") or ""),
         str(ship_addr.get("admin_area_1", "") or ""),
         str(ship_addr.get("postal_code", "") or ""),
         str(ship_addr.get("country_code", "") or ""),
         now, local_order_id),
    )
    items = conn.execute(
        "SELECT product_id, quantity FROM store_order_items WHERE order_id = ?",
        (local_order_id,),
    ).fetchall()
    for item in items:
        item = dict(item)
        quantity = int(item.get("quantity") or 1)
        # CASE WHEN keeps the floor at zero on both SQLite and PostgreSQL.
        conn.execute(
            "UPDATE store_products SET stock_quantity = CASE WHEN stock_quantity - ? < 0 THEN 0 ELSE stock_quantity - ? END,"
            " date_updated = ? WHERE id = ?",
            (quantity, quantity, now, item.get("product_id")),
        )
    conn.execute(
        "UPDATE store_products SET status = 'archived', date_updated = ?"
        " WHERE id IN (SELECT product_id FROM store_order_items WHERE order_id = ?)"
        " AND stock_quantity <= 0 AND status = 'active'",
        (now, local_order_id),
    )
    conn.commit()
    try:
        _send_order_notification(conn, local_order_id)
    except Exception as exc:
        # The sale is already recorded; a notification failure must not
        # undo or break checkout.
        print("[store] order notification failed: %r" % (exc,), flush=True)
    try:
        _notify_inbox_order(conn, local_order_id)
    except Exception as exc:
        print("[store] inbox order notification failed: %r" % (exc,), flush=True)
    return True, None


@store_bp.route("/store/checkout/return")
def paypal_checkout_return():
    """PayPal sends the buyer back here after approval. Capture the payment and
    show the thank-you page."""
    if not STORE_VISIBLE:
        abort(404)
    token = (request.args.get("token") or "").strip()
    conn = get_db()
    order = None
    if token:
        row = conn.execute(
            "SELECT * FROM store_orders WHERE provider_order_id = ? AND provider = 'paypal'",
            (token,),
        ).fetchone()
        order = dict(row) if row else None
    title = "your book"
    status = "error"
    item_count = 0
    message = "We couldn't find that order. If you were charged, contact us and we'll sort it out."
    if order:
        try:
            ok, err = _capture_paypal_order(conn, order["id"], token)
            rows = conn.execute(
                "SELECT p.title FROM store_order_items oi JOIN store_products p ON p.id = oi.product_id"
                " WHERE oi.order_id = ?",
                (order["id"],),
            ).fetchall()
            # NOTE: rows are dicts on PostgreSQL and sqlite3.Row locally --
            # always index by column name, never by position.
            titles = [r["title"] for r in rows if r["title"]]
            item_count = len(rows)
            if len(titles) == 1:
                title = titles[0]
            elif titles:
                title = "%d books" % len(titles)
            if ok:
                status = "success"
                message = ""
            else:
                message = err or "The payment was not completed."
        except Exception as exc:
            print("[store] checkout return failed: %r" % (exc,), flush=True)
            status = "error"
            message = ("Something went wrong while confirming your payment. "
                       "If you were charged, contact us and we'll sort it out.")
    conn.close()
    return render_template("store_checkout_result.html", status=status, title=title, message=message, item_count=item_count)


@store_bp.route("/store/checkout/cancel")
def paypal_checkout_cancel():
    """Buyer cancelled on PayPal's site — no charge was made."""
    if not STORE_VISIBLE:
        abort(404)
    token = (request.args.get("token") or "").strip()
    if token:
        conn = get_db()
        conn.execute(
            "UPDATE store_orders SET order_status = 'cancelled', date_updated = ?"
            " WHERE provider_order_id = ? AND provider = 'paypal' AND payment_status = 'unpaid'",
            (now_string(), token),
        )
        conn.commit()
        conn.close()
    return render_template("store_checkout_result.html", status="cancelled", title="", message="", item_count=0)


# ---------------------------------------------------------------------------
# Shopping cart (session-based). Buy Now stays the instant single-book
# checkout; Add to Cart is the parallel option for buying several books.
# ---------------------------------------------------------------------------

def _get_cart():
    """The cart from the Flask session: {str(product_id): qty}, sanitized."""
    cart = session.get("store_cart")
    if not isinstance(cart, dict):
        return {}
    clean = {}
    for key, value in cart.items():
        try:
            pid = str(int(key))
            qty = int(value)
        except (TypeError, ValueError):
            continue
        if qty > 0:
            clean[pid] = qty
    return clean


def _save_cart(cart):
    session["store_cart"] = cart


def _cart_line_items(conn, cart):
    """Build priced line items for a cart dict.

    Returns (lines, subtotal_cents, usable_cart). Lines are dicts with
    id/title/price_cents/qty/cover_image_url/line_total_cents. Products that
    vanished, went inactive, or hit zero stock are dropped from usable_cart
    (and quantities are capped at stock). Callers re-save usable_cart.
    """
    lines = []
    usable = {}
    subtotal_cents = 0
    for pid, qty in cart.items():
        row = conn.execute(
            "SELECT * FROM store_products WHERE id = ?", (int(pid),)
        ).fetchone()
        if not row:
            continue
        product = row_to_dict(row)
        if product.get("status") != "active":
            continue
        stock = int(product.get("stock_quantity") or 0)
        if stock < 1:
            continue
        qty = min(int(qty), stock)
        usable[pid] = qty
        line_total = int(product.get("price_cents") or 0) * qty
        subtotal_cents += line_total
        lines.append({
            "id": product["id"],
            "title": product.get("title") or "",
            "price_cents": int(product.get("price_cents") or 0),
            "price": product.get("price") or "0.00",
            "qty": qty,
            "line_total_cents": line_total,
            "cover_image_url": product.get("cover_image_url") or "",
        })
    return lines, subtotal_cents, usable


@store_bp.route("/store/cart")
def store_cart_page():
    """The cart page itself; line items load from the cart API."""
    if not STORE_VISIBLE:
        abort(404)
    return render_template("store_cart.html")


@store_bp.route("/api/store/cart")
def api_cart():
    """Current cart: line items, subtotal, shipping, and total item count."""
    if not STORE_VISIBLE:
        return jsonify({"error": "The store is not available."}), 404
    conn = get_db()
    try:
        cart = _get_cart()
        lines, subtotal_cents, usable = _cart_line_items(conn, cart)
        if usable != cart:
            _save_cart(usable)
    finally:
        conn.close()
    count = sum(usable.values())
    ship_cents = shipping_cents(count)
    return jsonify({
        "items": lines,
        "subtotal_cents": subtotal_cents,
        "shipping_cents": ship_cents,
        "total_cents": subtotal_cents + ship_cents,
        "count": count,
    })


@store_bp.route("/api/store/cart/add", methods=["POST"])
def api_cart_add():
    """Add a book to the session cart, capping quantity at stock."""
    if not STORE_VISIBLE:
        return jsonify({"error": "The store is not available."}), 404
    data = _request_data()
    try:
        product_id = int(data.get("product_id") or 0)
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid book."}), 400
    try:
        quantity = int(data.get("quantity") or 1)
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid quantity."}), 400
    if quantity < 1:
        return jsonify({"error": "Quantity must be at least 1."}), 400
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM store_products WHERE id = ? AND status = 'active'",
            (product_id,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return jsonify({"error": "That book is no longer available."}), 404
    product = row_to_dict(row)
    stock = int(product.get("stock_quantity") or 0)
    if stock < 1:
        return jsonify({"error": "That book is out of stock."}), 409
    if int(product.get("price_cents") or 0) < 1:
        return jsonify({"error": "That book has no price set."}), 409
    cart = _get_cart()
    pid = str(product_id)
    requested = cart.get(pid, 0) + quantity
    new_qty = min(requested, stock)
    cart[pid] = new_qty
    _save_cart(cart)
    return jsonify({
        "count": sum(cart.values()),
        "quantity": new_qty,
        "capped": new_qty < requested,
    })


@store_bp.route("/api/store/cart/remove", methods=["POST"])
def api_cart_remove():
    """Remove a book from the session cart entirely."""
    if not STORE_VISIBLE:
        return jsonify({"error": "The store is not available."}), 404
    data = _request_data()
    try:
        pid = str(int(data.get("product_id") or 0))
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid book."}), 400
    cart = _get_cart()
    cart.pop(pid, None)
    _save_cart(cart)
    return jsonify({"count": sum(cart.values())})


@store_bp.route("/api/store/cart/checkout", methods=["POST"])
def api_cart_checkout():
    """Start checkout for the whole cart: one local order, one order-item row
    per line, one PayPal order with an itemized breakdown. The cart is cleared
    only after PayPal returns an order. Prices are always read server-side."""
    if not STORE_VISIBLE:
        return jsonify({"error": "The store is not available."}), 404
    if not paypal_configured():
        return jsonify({"error": "Checkout is not set up yet."}), 503
    cart = _get_cart()
    if not cart:
        return jsonify({"error": "Your cart is empty."}), 400
    conn = get_db()
    lines, subtotal_cents, usable = _cart_line_items(conn, cart)
    if usable != cart:
        # Something changed under the buyer (sold out, archived, removed).
        _save_cart(usable)
        conn.close()
        return jsonify({"error": "A book in your cart is no longer available. Your cart has been updated — please review it."}), 409
    if subtotal_cents < 1:
        conn.close()
        return jsonify({"error": "Your cart has no priced items."}), 409
    total_qty = sum(line["qty"] for line in lines)
    ship_cents = shipping_cents(total_qty)
    total_cents = subtotal_cents + ship_cents
    now = now_string()
    cursor = conn.execute(
        "INSERT INTO store_orders (customer_name, customer_email, total_cents, payment_status, order_status, provider, provider_order_id, date_created, date_updated)"
        " VALUES (?, ?, ?, 'unpaid', 'pending', 'paypal', '', ?, ?)",
        ("", "", total_cents, now, now),
    )
    local_order_id = cursor.lastrowid
    for line in lines:
        conn.execute(
            "INSERT INTO store_order_items (order_id, product_id, quantity, unit_price_cents) VALUES (?, ?, ?, ?)",
            (local_order_id, line["id"], line["qty"], line["price_cents"]),
        )
    conn.commit()
    if len(lines) == 1:
        description = lines[0]["title"]
    else:
        description = "%s +%d more" % (lines[0]["title"], len(lines) - 1)
    base = request.host_url.rstrip("/")
    try:
        resp = paypal_request("POST", "/v2/checkout/orders", {
            "intent": "CAPTURE",
            "purchase_units": [{
                "reference_id": str(local_order_id),
                "description": description[:120],
                "amount": {
                    "currency_code": "USD",
                    "value": f"{total_cents / 100:.2f}",
                    "breakdown": {
                        "item_total": {
                            "currency_code": "USD",
                            "value": f"{subtotal_cents / 100:.2f}",
                        },
                        "shipping": {
                            "currency_code": "USD",
                            "value": f"{ship_cents / 100:.2f}",
                        },
                    },
                },
                "items": [
                    {
                        "name": (line["title"] or "Book")[:127],
                        "unit_amount": {
                            "currency_code": "USD",
                            "value": f"{line['price_cents'] / 100:.2f}",
                        },
                        "quantity": str(line["qty"]),
                    }
                    for line in lines
                ],
            }],
            "application_context": {
                "brand_name": "Snyder Scriptorium",
                "return_url": base + "/store/checkout/return",
                "cancel_url": base + "/store/checkout/cancel",
                "user_action": "PAY_NOW",
                "shipping_preference": "GET_FROM_FILE",
            },
        })
        body = resp.json()
    except Exception as exc:
        conn.close()
        return jsonify({"error": "Could not start checkout. (%s)" % exc}), 502
    if resp.status_code not in (200, 201):
        detail = ""
        try:
            err = (body.get("details") or body.get("message")) if isinstance(body, dict) else ""
            detail = (" — %s" % err) if err else ""
        except Exception:
            pass
        conn.close()
        return jsonify({"error": "Checkout was declined by PayPal (status %d%s)." % (resp.status_code, detail)}), 502
    paypal_order_id = body.get("id", "") if isinstance(body, dict) else ""
    approval_url = ""
    try:
        for link in body.get("links", []):
            if link.get("rel") == "approve" and link.get("href"):
                approval_url = link["href"]
                break
    except Exception:
        approval_url = ""
    if not paypal_order_id or not approval_url:
        conn.close()
        return jsonify({"error": "PayPal did not return an approval link. Please try again."}), 502
    conn.execute(
        "UPDATE store_orders SET provider_order_id = ?, date_updated = ? WHERE id = ?",
        (paypal_order_id, now_string(), local_order_id),
    )
    conn.commit()
    conn.close()
    # Only clear the cart once the PayPal order exists.
    _save_cart({})
    return jsonify({"approval_url": approval_url})
