import glob
import os
import re
import time
import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation

import requests
from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for, abort

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
ALLOWED_SECTIONS = {"Antique", "Vintage"}

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
                "CREATE TABLE IF NOT EXISTS store_orders (id BIGSERIAL PRIMARY KEY, customer_name TEXT NOT NULL DEFAULT '', customer_email TEXT NOT NULL DEFAULT '', total_cents INTEGER NOT NULL DEFAULT 0, payment_status TEXT NOT NULL DEFAULT 'unpaid', order_status TEXT NOT NULL DEFAULT 'pending', provider TEXT NOT NULL DEFAULT '', provider_order_id TEXT NOT NULL DEFAULT '', date_created TEXT NOT NULL, date_updated TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS store_order_items (id BIGSERIAL PRIMARY KEY, order_id BIGINT NOT NULL REFERENCES store_orders(id) ON DELETE CASCADE, product_id BIGINT NOT NULL REFERENCES store_products(id), quantity INTEGER NOT NULL DEFAULT 1, unit_price_cents INTEGER NOT NULL DEFAULT 0)",
                "CREATE TABLE IF NOT EXISTS store_product_images (id BIGSERIAL PRIMARY KEY, product_id BIGINT NOT NULL REFERENCES store_products(id) ON DELETE CASCADE, image_url TEXT NOT NULL, position INTEGER NOT NULL DEFAULT 0, date_created TEXT NOT NULL)",
            ]
        else:
            statements = [
                "CREATE TABLE IF NOT EXISTS store_categories (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL, date_created TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS store_products (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, slug TEXT UNIQUE NOT NULL, author TEXT NOT NULL DEFAULT '', description TEXT NOT NULL DEFAULT '', price_cents INTEGER NOT NULL DEFAULT 0, format TEXT NOT NULL DEFAULT 'Paperback', isbn TEXT NOT NULL DEFAULT '', cover_image_url TEXT NOT NULL DEFAULT '', category TEXT NOT NULL DEFAULT 'Books', language TEXT NOT NULL DEFAULT 'English', fulfillment_source TEXT NOT NULL DEFAULT 'Ingram Content Group', fulfillment_method TEXT NOT NULL DEFAULT 'Direct to Home', stock_quantity INTEGER NOT NULL DEFAULT 0, availability_status TEXT NOT NULL DEFAULT 'automatic', condition TEXT NOT NULL DEFAULT 'new', is_new_release INTEGER NOT NULL DEFAULT 0, is_kw_snyder INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'draft', date_created TEXT NOT NULL, date_updated TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS store_orders (id INTEGER PRIMARY KEY AUTOINCREMENT, customer_name TEXT NOT NULL DEFAULT '', customer_email TEXT NOT NULL DEFAULT '', total_cents INTEGER NOT NULL DEFAULT 0, payment_status TEXT NOT NULL DEFAULT 'unpaid', order_status TEXT NOT NULL DEFAULT 'pending', provider TEXT NOT NULL DEFAULT '', provider_order_id TEXT NOT NULL DEFAULT '', date_created TEXT NOT NULL, date_updated TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS store_order_items (id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL REFERENCES store_orders(id) ON DELETE CASCADE, product_id INTEGER NOT NULL REFERENCES store_products(id), quantity INTEGER NOT NULL DEFAULT 1, unit_price_cents INTEGER NOT NULL DEFAULT 0)",
                "CREATE TABLE IF NOT EXISTS store_product_images (id INTEGER PRIMARY KEY AUTOINCREMENT, product_id INTEGER NOT NULL REFERENCES store_products(id) ON DELETE CASCADE, image_url TEXT NOT NULL, position INTEGER NOT NULL DEFAULT 0, date_created TEXT NOT NULL)",
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
            ]:
                if name not in existing:
                    migrations.append(f"ALTER TABLE store_products ADD COLUMN {name} {definition}")
        for statement in migrations:
            conn.execute(statement)

        for seed_category in ("Books", "Antique", "Vintage"):
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

    section = str(data.get("category", "Antique")).strip()
    if section not in ALLOWED_SECTIONS:
        # Accept legacy multi-category strings by picking the first known section.
        found = next((s for s in ALLOWED_SECTIONS if s in section), None)
        section = found or "Antique"

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


def save_product_photo(product_id, slug, storage):
    """Validate and store an uploaded book photo. Returns the public URL."""
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
    safe_slug = slugify(slug)[:60]
    os.makedirs(STORE_IMAGE_DIR, exist_ok=True)
    for old in glob.glob(os.path.join(STORE_IMAGE_DIR, f"{safe_slug}-{product_id}.*")):
        try:
            os.remove(old)
        except OSError:
            pass
    out_name = f"{safe_slug}-{product_id}{real_ext}"
    with open(os.path.join(STORE_IMAGE_DIR, out_name), "wb") as handle:
        handle.write(data)
    return "/static/store_images/" + out_name


MAX_GALLERY_IMAGES = 6


def save_gallery_photo(product_id, slug, storage):
    """Validate and store one gallery photo. Returns the public URL.

    Unlike the cover photo, gallery files get unique names so several can
    coexist per product.
    """
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
    safe_slug = slugify(slug)[:60]
    os.makedirs(STORE_IMAGE_DIR, exist_ok=True)
    out_name = f"{safe_slug}-{product_id}-{uuid.uuid4().hex[:8]}{real_ext}"
    with open(os.path.join(STORE_IMAGE_DIR, out_name), "wb") as handle:
        handle.write(data)
    return "/static/store_images/" + out_name


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
            url = save_gallery_photo(product_id, slug, storage)
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


PRODUCT_COLUMNS = ("title, slug, author, description, price_cents, format, isbn, cover_image_url, category, language, fulfillment_source, fulfillment_method, stock_quantity, availability_status, condition, is_new_release, is_kw_snyder, status, publisher, publication_year, edition, condition_notes, notes, date_created, date_updated")


def _product_values(product):
    return (product["title"], product["slug"], product["author"], product["description"], product["price_cents"], product["format"], product["isbn"], product["cover_image_url"], product["category"], product["language"], product["fulfillment_source"], product["fulfillment_method"], product["stock_quantity"], product["availability_status"], product["condition"], product["is_new_release"], product["is_kw_snyder"], product["status"], product["publisher"], product["publication_year"], product["edition"], product["condition_notes"], product["notes"])


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
    return render_template("store_book.html", product=item)


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
    return render_template("store_book.html", product=item, preview=True)


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
            f"INSERT INTO store_products({PRODUCT_COLUMNS}) VALUES ({', '.join(['?'] * 25)})",
            _product_values(product) + (timestamp, timestamp),
        )
        new_id = cursor.lastrowid
        photo_warning = None
        photo = _request_photo()
        if photo:
            try:
                product["cover_image_url"] = save_product_photo(new_id, product["slug"], photo)
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
    conn.execute("DELETE FROM store_product_images WHERE id = ?", (image_id,))
    conn.commit()
    conn.close()
    _delete_local_cover_image(row["image_url"])
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
            "UPDATE store_products SET title = ?, slug = ?, author = ?, description = ?, price_cents = ?, format = ?, isbn = ?, cover_image_url = ?, category = ?, language = ?, fulfillment_source = ?, fulfillment_method = ?, stock_quantity = ?, availability_status = ?, condition = ?, is_new_release = ?, is_kw_snyder = ?, status = ?, publisher = ?, publication_year = ?, edition = ?, condition_notes = ?, notes = ?, date_updated = ? WHERE id = ?",
            _product_values(product)[0:18] + _product_values(product)[18:23] + (now_string(), product_id),
        )
        photo_warning = None
        photo = _request_photo()
        if photo:
            try:
                cover_url = save_product_photo(product_id, product["slug"], photo)
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


# --- PayPal checkout ------------------------------------------------------
# Single-entry checkout: books are entered once in the store admin. When a
# customer buys, the backend builds the PayPal order from the database row —
# nothing is ever typed into PayPal by hand.
#
# Server env vars (set in Render; never committed):
#   PAYPAL_CLIENT_ID, PAYPAL_SECRET, PAYPAL_MODE=sandbox|live
# The client ID is public by design (it ships in the page JS). The secret
# stays server-side and is only used for server-to-server API calls.

PAYPAL_SANDBOX_API = "https://api-m.sandbox.paypal.com"
PAYPAL_LIVE_API = "https://api-m.paypal.com"

_paypal_token_cache = {"token": None, "expires_at": 0.0}


def paypal_mode():
    return (os.environ.get("PAYPAL_MODE", "sandbox") or "sandbox").strip().lower()


def paypal_api_base():
    return PAYPAL_LIVE_API if paypal_mode() == "live" else PAYPAL_SANDBOX_API


def paypal_configured():
    return bool(os.environ.get("PAYPAL_CLIENT_ID") and os.environ.get("PAYPAL_SECRET"))


def paypal_access_token():
    """Server-to-server OAuth token, cached until near expiry."""
    now = time.time()
    if _paypal_token_cache["token"] and _paypal_token_cache["expires_at"] > now + 60:
        return _paypal_token_cache["token"]
    resp = requests.post(
        paypal_api_base() + "/v1/oauth2/token",
        auth=(os.environ.get("PAYPAL_CLIENT_ID", ""), os.environ.get("PAYPAL_SECRET", "")),
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
    total_cents = int(product.get("price_cents") or 0)
    if total_cents < 1:
        conn.close()
        return jsonify({"error": "That book has no price set."}), 409
    now = now_string()
    cursor = conn.execute(
        "INSERT INTO store_orders (customer_name, customer_email, total_cents, payment_status, order_status, provider, provider_order_id, date_created, date_updated)"
        " VALUES (?, ?, ?, 'unpaid', 'pending', 'paypal', '', ?, ?)",
        ("", "", total_cents, now, now),
    )
    local_order_id = cursor.lastrowid
    conn.execute(
        "INSERT INTO store_order_items (order_id, product_id, quantity, unit_price_cents) VALUES (?, ?, 1, ?)",
        (local_order_id, product_id, total_cents),
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
                },
            }],
            "application_context": {
                "brand_name": "Snyder Scriptorium",
                "return_url": base + "/store/checkout/return",
                "cancel_url": base + "/store/checkout/cancel",
                "user_action": "PAY_NOW",
            },
        })
    except Exception as exc:
        conn.close()
        return jsonify({"error": "Could not start checkout. (%s)" % exc}), 502
    if resp.status_code not in (200, 201):
        conn.close()
        return jsonify({"error": "Could not start checkout."}), 502
    body = resp.json() or {}
    paypal_order_id = body.get("id", "")
    approval_url = ""
    for link in body.get("links", []):
        if link.get("rel") == "approve":
            approval_url = link.get("href", "")
            break
    if not paypal_order_id or not approval_url:
        conn.close()
        return jsonify({"error": "Could not start checkout."}), 502
    conn.execute(
        "UPDATE store_orders SET provider_order_id = ?, date_updated = ? WHERE id = ?",
        (paypal_order_id, now_string(), local_order_id),
    )
    conn.commit()
    conn.close()
    return jsonify({"approval_url": approval_url})


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
    if resp.status_code not in (200, 201):
        return False, "The payment was not completed."
    capture = resp.json() or {}
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
    now = now_string()
    conn.execute(
        "UPDATE store_orders SET payment_status = 'paid', order_status = 'processing',"
        " customer_name = ?, customer_email = ?, date_updated = ? WHERE id = ?",
        (full_name, payer.get("email_address", ""), now, local_order_id),
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
    message = "We couldn't find that order. If you were charged, contact us and we'll sort it out."
    if order:
        ok, err = _capture_paypal_order(conn, order["id"], token)
        item = conn.execute(
            "SELECT p.title FROM store_order_items oi JOIN store_products p ON p.id = oi.product_id"
            " WHERE oi.order_id = ? LIMIT 1",
            (order["id"],),
        ).fetchone()
        if item:
            title = item[0]
        if ok:
            status = "success"
            message = ""
        else:
            message = err or "The payment was not completed."
    conn.close()
    return render_template("store_checkout_result.html", status=status, title=title, message=message)


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
    return render_template("store_checkout_result.html", status="cancelled", title="", message="")
