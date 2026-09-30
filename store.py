import glob
import os
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

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
            ]
        else:
            statements = [
                "CREATE TABLE IF NOT EXISTS store_categories (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL, date_created TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS store_products (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, slug TEXT UNIQUE NOT NULL, author TEXT NOT NULL DEFAULT '', description TEXT NOT NULL DEFAULT '', price_cents INTEGER NOT NULL DEFAULT 0, format TEXT NOT NULL DEFAULT 'Paperback', isbn TEXT NOT NULL DEFAULT '', cover_image_url TEXT NOT NULL DEFAULT '', category TEXT NOT NULL DEFAULT 'Books', language TEXT NOT NULL DEFAULT 'English', fulfillment_source TEXT NOT NULL DEFAULT 'Ingram Content Group', fulfillment_method TEXT NOT NULL DEFAULT 'Direct to Home', stock_quantity INTEGER NOT NULL DEFAULT 0, availability_status TEXT NOT NULL DEFAULT 'automatic', condition TEXT NOT NULL DEFAULT 'new', is_new_release INTEGER NOT NULL DEFAULT 0, is_kw_snyder INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'draft', date_created TEXT NOT NULL, date_updated TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS store_orders (id INTEGER PRIMARY KEY AUTOINCREMENT, customer_name TEXT NOT NULL DEFAULT '', customer_email TEXT NOT NULL DEFAULT '', total_cents INTEGER NOT NULL DEFAULT 0, payment_status TEXT NOT NULL DEFAULT 'unpaid', order_status TEXT NOT NULL DEFAULT 'pending', provider TEXT NOT NULL DEFAULT '', provider_order_id TEXT NOT NULL DEFAULT '', date_created TEXT NOT NULL, date_updated TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS store_order_items (id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL REFERENCES store_orders(id) ON DELETE CASCADE, product_id INTEGER NOT NULL REFERENCES store_products(id), quantity INTEGER NOT NULL DEFAULT 1, unit_price_cents INTEGER NOT NULL DEFAULT 0)",
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
    conn.close()
    if not product:
        abort(404)
    return render_template("store_book.html", product=public_dict(product))


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
    conn.close()
    if not product:
        abort(404)
    return render_template("store_book.html", product=public_dict(product), preview=True)


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
    conn.close()
    if not row:
        return jsonify({"error": "Book not found."}), 404
    return jsonify(public_dict(row))


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
        conn.commit()
        row = conn.execute("SELECT * FROM store_products WHERE id = ?", (new_id,)).fetchone()
    except IntegrityError:
        conn.rollback()
        conn.close()
        return jsonify({"error": "A bookstore product with that slug already exists."}), 409
    conn.close()
    payload = {"success": True, "product": row_to_dict(row)}
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
    conn.close()
    if not row:
        return jsonify({"error": "Book not found."}), 404
    return jsonify(row_to_dict(row))


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
        conn.commit()
        row = conn.execute("SELECT * FROM store_products WHERE id = ?", (product_id,)).fetchone()
    except IntegrityError:
        conn.rollback()
        conn.close()
        return jsonify({"error": "A bookstore product with that slug already exists."}), 409
    conn.close()
    payload = {"success": True, "product": row_to_dict(row)}
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
        return jsonify({"success": True, "deleted": True})
    conn.execute("UPDATE store_products SET status = 'archived', date_updated = ? WHERE id = ?", (now_string(), product_id))
    conn.commit()
    conn.close()
    return jsonify({"success": True})
